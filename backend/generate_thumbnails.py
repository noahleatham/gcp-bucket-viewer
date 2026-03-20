"""
Manual thumbnail generation script.

Scans buckets for media files missing thumbnails and generates them.
Uses range reads for videos to avoid downloading entire files from
archival storage (only fetches first N MB needed for frame extraction).

For MP4/MOV videos, checks the moov atom position first (64KB header read).
If the moov atom is at the end of the file (common for camera recordings),
the script downloads moov from the tail + first N MB of video data, then
reassembles them into a fast-start layout that ffmpeg can parse — avoiding
a full file download. If reassembly fails, files are skipped by default.
Use --allow-full-download to fall back to full file downloads.

Usage:
    python -m backend.generate_thumbnails                          # All allowed buckets
    python -m backend.generate_thumbnails fujifilm-photos          # Specific bucket
    python -m backend.generate_thumbnails fujifilm-photos --dry-run  # Preview only
    python -m backend.generate_thumbnails --range-mb 20            # Use 20MB range reads for videos
    python -m backend.generate_thumbnails --allow-full-download    # Fall back to full download on failure
"""

import os
import sys
import tempfile
import subprocess
import argparse

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from PIL import Image, ImageOps

from .gcs_utils import get_allowed_buckets, get_bucket, get_thumbnail_bucket, upload_thumbnail, check_thumbnail_exists

# Track bytes downloaded for cost reporting
_bytes_downloaded = 0
_bytes_saved = 0

RANGE_MB_DEFAULT = 20


def _download_video_partial(blob, local_path, range_bytes):
    """Download only the first range_bytes of a video file."""
    global _bytes_downloaded, _bytes_saved
    blob.reload()
    file_size = blob.size or 0

    if file_size <= range_bytes:
        # File is smaller than range — just download the whole thing
        blob.download_to_filename(local_path)
        _bytes_downloaded += file_size
        return file_size

    blob.download_to_filename(local_path, start=0, end=range_bytes - 1)
    _bytes_downloaded += range_bytes
    _bytes_saved += file_size - range_bytes
    return range_bytes


def _try_ffmpeg_thumbnail(input_path, thumb_path):
    """Try to extract a thumbnail frame with ffmpeg. Returns True on success."""
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ss", "00:00:01.000",
        "-vframes", "1",
        "-vf", "scale=-1:360",
        thumb_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0 and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0


def _scan_mp4_atoms(header_bytes: bytes) -> dict:
    """Scan MP4/MOV atom headers to determine layout.

    MP4/MOV files are structured as a sequence of atoms (boxes), each with a
    4-byte size and 4-byte type. If the 'mdat' atom (media data) appears before
    'moov' (metadata/index), ffmpeg cannot parse a partial download from the
    start of the file because it needs the moov atom to locate keyframes.

    Returns dict with:
        'layout':      'moov_first', 'mdat_first', or 'unknown'
        'mdat_offset': byte offset where mdat atom starts (if found)
        'mdat_size':   declared size of mdat atom (if found)
    """
    result = {'layout': 'unknown'}
    pos = 0
    while pos + 8 <= len(header_bytes):
        size = int.from_bytes(header_bytes[pos:pos + 4], 'big')
        atom_type = header_bytes[pos + 4:pos + 8]
        try:
            atom_name = atom_type.decode('ascii')
        except (UnicodeDecodeError, ValueError):
            return result
        actual_size = size
        # Extended size: size==1 means the real size is in the next 8 bytes
        if size == 1:
            if pos + 16 > len(header_bytes):
                return result
            actual_size = int.from_bytes(header_bytes[pos + 8:pos + 16], 'big')
        elif size == 0:
            return result  # atom extends to EOF
        if actual_size < 8:
            return result
        if atom_name == 'moov':
            result['layout'] = 'moov_first'
            return result
        if atom_name == 'mdat':
            result['layout'] = 'mdat_first'
            result['mdat_offset'] = pos
            result['mdat_size'] = actual_size
            return result
        pos += actual_size
    return result


def _find_atom_in_data(data: bytes, target: bytes):
    """Find a top-level atom by type in raw MP4 data. Returns (offset, size) or None."""
    pos = 0
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos:pos + 4], 'big')
        atom_type = data[pos + 4:pos + 8]
        actual_size = size
        if size == 1:
            if pos + 16 > len(data):
                return None
            actual_size = int.from_bytes(data[pos + 8:pos + 16], 'big')
        elif size == 0:
            actual_size = len(data) - pos
        if actual_size < 8:
            return None
        if atom_type == target:
            return (pos, actual_size)
        pos += actual_size
    return None


def _patch_stco_offsets(moov_data: bytearray, delta: int):
    """Adjust stco (32-bit) and co64 (64-bit) chunk offset tables in moov.

    When moov is moved from after mdat to before it, every absolute chunk
    offset must increase by the size of the moov atom (since mdat shifted).
    """
    # Patch stco (32-bit offsets)
    pos = 0
    while True:
        idx = moov_data.find(b'stco', pos)
        if idx == -1:
            break
        # stco layout: [4:size][4:'stco'][1:version][3:flags][4:entry_count][4*N:offsets]
        # idx points to 'stco'; version starts at idx+4
        entry_count = int.from_bytes(moov_data[idx + 8:idx + 12], 'big')
        for i in range(entry_count):
            off_pos = idx + 12 + i * 4
            if off_pos + 4 > len(moov_data):
                break
            old = int.from_bytes(moov_data[off_pos:off_pos + 4], 'big')
            moov_data[off_pos:off_pos + 4] = (old + delta).to_bytes(4, 'big')
        pos = idx + 4

    # Patch co64 (64-bit offsets)
    pos = 0
    while True:
        idx = moov_data.find(b'co64', pos)
        if idx == -1:
            break
        entry_count = int.from_bytes(moov_data[idx + 8:idx + 12], 'big')
        for i in range(entry_count):
            off_pos = idx + 12 + i * 8
            if off_pos + 8 > len(moov_data):
                break
            old = int.from_bytes(moov_data[off_pos:off_pos + 8], 'big')
            moov_data[off_pos:off_pos + 8] = (old + delta).to_bytes(8, 'big')
        pos = idx + 4


def _assemble_partial_faststart(pre_mdat: bytes, moov_data: bytes,
                                head_path: str, mdat_offset: int,
                                output_path: str):
    """Build a partial fast-start MP4: [pre-mdat atoms] [patched moov] [truncated mdat].

    The moov atom's stco/co64 offsets are adjusted so that chunk positions
    remain correct after moov is inserted before mdat.
    """
    patched = bytearray(moov_data)
    # Inserting moov (len(moov_data) bytes) before mdat shifts all mdat
    # content forward by that amount. stco/co64 offsets are absolute file
    # positions, so each must increase by len(moov_data).
    _patch_stco_offsets(patched, len(moov_data))

    with open(output_path, 'wb') as out:
        # Everything before mdat (ftyp, free, wide, etc.)
        out.write(pre_mdat)
        # Patched moov (now before mdat)
        out.write(bytes(patched))
        # Truncated mdat from the head download
        with open(head_path, 'rb') as head:
            head.seek(mdat_offset)
            out.write(head.read())


def _try_video_partial_download(blob, tmpdir, ext, range_bytes, allow_full_download, thumb_path):
    """Try partial download → ffmpeg. Falls back to full download if allowed.

    Returns: 'ok', 'skipped_partial_failed', 'failed', or None if thumb generated.
    """
    global _bytes_downloaded
    partial_path = os.path.join(tmpdir, f"source_partial{ext}")
    downloaded = _download_video_partial(blob, partial_path, range_bytes)

    if _try_ffmpeg_thumbnail(partial_path, thumb_path):
        return None  # success, thumb_path exists

    if not allow_full_download:
        return 'skipped_partial_failed'

    blob.reload()
    file_size = blob.size or 0
    if downloaded >= file_size:
        return 'failed'

    print(f"partial failed, downloading full file ({file_size / 1024 / 1024:.0f}MB)...", end=" ", flush=True)
    full_path = os.path.join(tmpdir, f"source_full{ext}")
    blob.download_to_filename(full_path)
    _bytes_downloaded += file_size
    if _try_ffmpeg_thumbnail(full_path, thumb_path):
        return None  # success
    return 'failed'


def generate_thumbnail(bucket_name: str, blob_name: str, range_bytes: int = RANGE_MB_DEFAULT * 1024 * 1024,
                       allow_full_download: bool = False) -> str:
    """Generate a thumbnail for a single media file.

    Returns: 'ok', 'skipped', 'skipped_moov_at_end', 'skipped_partial_failed', 'failed'
    """
    global _bytes_downloaded, _bytes_saved
    bucket = get_bucket(bucket_name)
    blob = bucket.blob(blob_name)

    content_type = blob.content_type or ""
    lower_name = blob_name.lower()
    ext = os.path.splitext(blob_name)[1].lower()
    is_video = content_type.startswith("video/") or lower_name.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
    is_image = content_type.startswith("image/") or lower_name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.tiff'))

    if not (is_video or is_image):
        return 'skipped'

    with tempfile.TemporaryDirectory() as tmpdir:
        thumb_path = os.path.join(tmpdir, "thumb.jpg")

        if is_video:
            is_mp4_mov = lower_name.endswith(('.mp4', '.mov', '.m4v'))

            if is_mp4_mov:
                # Check moov atom position with a small 64KB header read
                blob.reload()
                file_size = blob.size or 0
                header_size = min(65536, file_size)
                header_path = os.path.join(tmpdir, f"header{ext}")
                blob.download_to_filename(header_path, start=0, end=header_size - 1)
                _bytes_downloaded += header_size

                with open(header_path, 'rb') as f:
                    header_data = f.read()

                info = _scan_mp4_atoms(header_data)

                if info['layout'] == 'mdat_first':
                    # Moov is at the end — try partial reassembly:
                    # download moov from the tail + first N MB of mdat,
                    # then stitch into a fast-start layout ffmpeg can parse.
                    mdat_offset = info['mdat_offset']
                    mdat_size = info['mdat_size']
                    moov_start = mdat_offset + mdat_size
                    moov_size = file_size - moov_start

                    reassembly_ok = False
                    if 0 < moov_size <= 50 * 1024 * 1024:
                        print(f"moov at end, reassembling (~{_format_bytes(moov_size + range_bytes)})...", end=" ", flush=True)

                        # Download the tail (moov + any small atoms after mdat)
                        tail_path = os.path.join(tmpdir, "tail_data")
                        blob.download_to_filename(tail_path, start=moov_start, end=file_size - 1)
                        _bytes_downloaded += moov_size

                        with open(tail_path, 'rb') as f:
                            tail_data = f.read()

                        # Find the actual moov atom (there may be small atoms
                        # like 'free' between mdat and moov)
                        moov_loc = _find_atom_in_data(tail_data, b'moov')
                        if moov_loc:
                            moov_off, moov_len = moov_loc
                            moov_bytes = tail_data[moov_off:moov_off + moov_len]

                            # Download first range_bytes for mdat video data
                            head_size = min(range_bytes, file_size)
                            head_path = os.path.join(tmpdir, f"head{ext}")
                            blob.download_to_filename(head_path, start=0, end=head_size - 1)
                            _bytes_downloaded += head_size
                            _bytes_saved += max(0, file_size - moov_size - head_size)

                            # Assemble: [pre-mdat atoms][patched moov][truncated mdat]
                            pre_mdat = header_data[:mdat_offset]
                            assembled_path = os.path.join(tmpdir, f"assembled{ext}")
                            _assemble_partial_faststart(pre_mdat, moov_bytes,
                                                        head_path, mdat_offset,
                                                        assembled_path)

                            if _try_ffmpeg_thumbnail(assembled_path, thumb_path):
                                reassembly_ok = True

                    if not reassembly_ok:
                        if not allow_full_download:
                            return 'skipped_moov_at_end'
                        print(f"reassembly failed, full download ({file_size / 1024 / 1024:.0f}MB)...", end=" ", flush=True)
                        full_path = os.path.join(tmpdir, f"source_full{ext}")
                        blob.download_to_filename(full_path)
                        _bytes_downloaded += file_size
                        if not _try_ffmpeg_thumbnail(full_path, thumb_path):
                            return 'failed'
                else:
                    # moov_first or unknown — standard partial download
                    result = _try_video_partial_download(blob, tmpdir, ext, range_bytes,
                                                        allow_full_download, thumb_path)
                    if result is not None:
                        return result
            else:
                # Non-MP4 video (AVI, MKV, WebM) — partial download directly
                result = _try_video_partial_download(blob, tmpdir, ext, range_bytes,
                                                    allow_full_download, thumb_path)
                if result is not None:
                    return result
        else:
            local_path = os.path.join(tmpdir, f"source{ext}")
            blob.download_to_filename(local_path)
            blob.reload()
            _bytes_downloaded += blob.size or 0

            with Image.open(local_path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((360, 360))
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=85)

        if os.path.exists(thumb_path):
            with open(thumb_path, "rb") as f:
                upload_thumbnail(bucket_name, blob_name, f.read())
            return 'ok'
    return 'failed'


def _format_bytes(n):
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} bytes"


def main():
    global _bytes_downloaded, _bytes_saved

    parser = argparse.ArgumentParser(description="Generate missing thumbnails for GCS media files")
    parser.add_argument("bucket", nargs="?", help="Specific bucket to process (default: all allowed buckets)")
    parser.add_argument("--prefix", help="Only process files under this prefix/subdirectory")
    parser.add_argument("--dry-run", action="store_true", help="List missing thumbnails without generating")
    parser.add_argument("--range-mb", type=int, default=RANGE_MB_DEFAULT,
                        help=f"MB to download for video range reads (default: {RANGE_MB_DEFAULT})")
    parser.add_argument("--allow-full-download", action="store_true",
                        help="Allow full file downloads when partial/range reads fail (default: skip those files)")
    args = parser.parse_args()

    range_bytes = args.range_mb * 1024 * 1024

    if args.bucket:
        bucket_names = [args.bucket]
    else:
        bucket_names = get_allowed_buckets()

    if not bucket_names:
        print("No buckets configured. Set ALLOWED_BUCKETS env var.")
        sys.exit(1)

    print(f"Video range read size: {args.range_mb} MB (use --range-mb to adjust)")
    if not args.allow_full_download:
        print("Full downloads disabled (use --allow-full-download to enable)")

    skipped_moov = 0
    skipped_partial = 0

    for bucket_name in bucket_names:
        print(f"\nProcessing bucket: {bucket_name}")
        bucket = get_bucket(bucket_name)
        thumb_bucket = get_thumbnail_bucket()

        # Build set of existing thumbnails
        print("  Scanning existing thumbnails...")
        thumb_set = {b.name for b in thumb_bucket.list_blobs(prefix=f"{bucket_name}/")}
        print(f"  Found {len(thumb_set)} existing thumbnails")

        # Scan source bucket
        missing = []
        total_media = 0
        for blob in bucket.list_blobs(prefix=args.prefix or ""):
            if blob.name.endswith("/"):
                continue
            content_type = blob.content_type or ""
            lower_name = blob.name.lower()
            is_media = (
                content_type.startswith("image/") or
                content_type.startswith("video/") or
                lower_name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'))
            )
            if not is_media:
                continue
            total_media += 1
            if f"{bucket_name}/{blob.name}" not in thumb_set:
                missing.append(blob.name)

        print(f"  Total media: {total_media}, Missing thumbnails: {len(missing)}")

        if args.dry_run:
            for name in missing[:20]:
                print(f"    - {name}")
            if len(missing) > 20:
                print(f"    ... and {len(missing) - 20} more")
            continue

        for i, blob_name in enumerate(missing, 1):
            try:
                print(f"  [{i}/{len(missing)}] {blob_name}...", end=" ", flush=True)
                result = generate_thumbnail(bucket_name, blob_name, range_bytes=range_bytes,
                                            allow_full_download=args.allow_full_download)
                if result == 'ok':
                    print("OK")
                elif result == 'skipped_moov_at_end':
                    print("SKIPPED (moov at end, reassembly failed)")
                    skipped_moov += 1
                elif result == 'skipped_partial_failed':
                    print("SKIPPED (partial download not enough)")
                    skipped_partial += 1
                elif result == 'skipped':
                    print("skipped (not media)")
                else:
                    print("FAILED")
            except Exception as e:
                print(f"FAILED: {e}")

    # Print skip summary
    if skipped_moov + skipped_partial > 0:
        print(f"\n--- Skipped Videos ---")
        if skipped_moov:
            print(f"  Moov at end (reassembly failed): {skipped_moov}")
        if skipped_partial:
            print(f"  Partial download failed:  {skipped_partial}")
        print(f"  Re-run with --allow-full-download to process these files")

    # Print cost summary
    if _bytes_downloaded > 0 or _bytes_saved > 0:
        total_would_have = _bytes_downloaded + _bytes_saved
        print(f"\n--- Transfer Summary ---")
        print(f"  Downloaded:    {_format_bytes(_bytes_downloaded)}")
        print(f"  Avoided:       {_format_bytes(_bytes_saved)}")
        print(f"  Without range: {_format_bytes(total_would_have)}")
        if total_would_have > 0:
            pct = (_bytes_saved / total_would_have) * 100
            print(f"  Savings:       {pct:.1f}%")
        # Estimate archival retrieval costs
        dl_gb = _bytes_downloaded / 1024**3
        saved_gb = _bytes_saved / 1024**3
        print(f"\n  Est. archive retrieval cost:  ${dl_gb * 0.05:.2f} (at $0.05/GB)")
        print(f"  Est. cost without range reads: ${(dl_gb + saved_gb) * 0.05:.2f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
