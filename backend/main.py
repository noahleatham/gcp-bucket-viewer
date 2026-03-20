from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from typing import List, Optional
import logging
import io
import os
import zipfile
from dotenv import load_dotenv

from datetime import datetime, timezone, time
# Load env vars
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# Local imports
from .auth import verify_google_token
from .gcs_utils import list_files, check_thumbnail_exists, get_bucket, upload_thumbnail, get_allowed_buckets, get_blob_stream, get_thumbnail_bucket
from .permissions import check_user_access, get_user_buckets

# Thumbnail generation imports
from PIL import Image, ImageOps
import tempfile
import subprocess
import shutil

app = FastAPI()
logger = logging.getLogger("uvicorn")

origins = [
    "http://localhost:5173",
    "http://localhost:8080",
    "*", 
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}

@app.get("/api/config")
async def get_config():
    return {
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
    }

@app.get("/api/buckets")
async def get_buckets(user: dict = Depends(verify_google_token)):
    return {"buckets": get_user_buckets(user["email"])}

@app.get("/api/media")
async def get_media(
    bucket_name: str,
    page_token: Optional[str] = None, 
    limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    prefix: str = "",
    user: dict = Depends(verify_google_token)
):
    if not check_user_access(user["email"], bucket_name, prefix):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        s_dt = None
        e_dt = None
        if start_date:
            s_dt = datetime.fromisoformat(start_date)
            if s_dt.tzinfo is None:
                s_dt = s_dt.replace(tzinfo=timezone.utc)

        if end_date:
            # Parse and set to the very end of the day (23:59:59)
            e_dt = datetime.fromisoformat(end_date)
            e_dt = datetime.combine(e_dt.date(), time.max).replace(tzinfo=timezone.utc)


        items, next_token, subdirs = list_files(
            bucket_name, 
            prefix=prefix,
            limit=limit, 
            page_token=page_token,
            start_date=s_dt,
            end_date=e_dt
        )
        return {
            "items": items, 
            "nextPageToken": next_token,
            "subdirectories": subdirs
        }
    except ValueError as e:
         raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error listing media: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate-all-thumbnails")
async def generate_all_thumbnails(
    background_tasks: BackgroundTasks,
    bucket_name: str = Query(..., description="Bucket name"),
    user: dict = Depends(verify_google_token)
):
    if not check_user_access(user["email"], bucket_name):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        bucket = get_bucket(bucket_name)
        thumb_bucket = get_thumbnail_bucket()

        # Get all existing thumbnails from dedicated thumbnail bucket
        print(f"Scanning thumbnail bucket for {bucket_name}...")
        thumbnail_blobs = thumb_bucket.list_blobs(prefix=f"{bucket_name}/")
        thumb_set = {b.name for b in thumbnail_blobs}

        all_blobs = bucket.list_blobs()
        queued_count = 0
        total_media = 0

        for blob in all_blobs:
            if blob.name.endswith("/"):
                continue

            # Simple filtered check for common media types
            content_type = blob.content_type or ""
            is_media = (
                content_type.startswith("image/") or
                content_type.startswith("video/") or
                blob.name.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'))
            )

            if not is_media:
                continue

            total_media += 1
            if f"{bucket_name}/{blob.name}" not in thumb_set:
                background_tasks.add_task(generate_thumbnail_task, bucket_name, blob.name)
                queued_count += 1

        return {
            "status": "queued",
            "total_media_found": total_media,
            "thumbnails_queued": queued_count,
            "message": f"Queued {queued_count} thumbnails for generation."
        }
    except Exception as e:
        logger.error(f"Error in bulk generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download-batch")
async def download_batch(
    files: List[str],
    bucket_name: str = Query(..., description="Bucket name"),
    user: dict = Depends(verify_google_token)
):
    if not files:
        raise HTTPException(status_code=400, detail="No files specified")

    if any(not check_user_access(user["email"], bucket_name, f) for f in files):
        raise HTTPException(status_code=403, detail="Access denied")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Too many files for batch download (max 50)")

    try:
        bucket = get_bucket(bucket_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Single file case: download original directly
    if len(files) == 1:
        file_path = files[0]
        try:
            stream, content_type, size = get_blob_stream(bucket_name, file_path)
            filename = file_path.split("/")[-1]
            
            def iterfile():
                with stream as f:
                    while True:
                        chunk = f.read(1024*1024)
                        if not chunk:
                            break
                        yield chunk
                        
            headers = {
                "Content-Disposition": f'attachment; filename="{filename}"',
            }
            if size is not None:
                headers["Content-Length"] = str(size)

            return StreamingResponse(
                iterfile(), 
                media_type=content_type or "application/octet-stream",
                headers=headers
            )
        except Exception as e:
            logger.error(f"Error streaming single file {file_path}: {e}")
            raise HTTPException(status_code=500, detail=f"Single file download failed: {str(e)}")

    # Multi-file case: create ZIP
    def zip_generator():
        # Use a temporary file to build the ZIP to avoid memory issues and corruptions
        with tempfile.NamedTemporaryFile(delete=False) as tmp_zip:
            tmp_zip_path = tmp_zip.name
            
        try:
            with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in files:
                    try:
                        blob = bucket.blob(file_path)
                        blob.reload()
                        
                        # Limit individual file size in ZIP to 500MB
                        if blob.size > 500 * 1024 * 1024:
                            zf.writestr(f"{file_path.split('/')[-1]}.skipped.txt", "File too large (>500MB).")
                            continue
                        
                        # Use a temp file for the blob to save memory
                        # delete=False ensures we can close it and then read it back safely
                        tmp_blob = tempfile.NamedTemporaryFile(delete=False)
                        try:
                            blob.download_to_file(tmp_blob)
                            tmp_blob.close() # Close to ensure all data is written and visible
                            zf.write(tmp_blob.name, arcname=file_path.split("/")[-1])
                        finally:
                            if os.path.exists(tmp_blob.name):
                                os.remove(tmp_blob.name)
                            
                    except Exception as e:
                        logger.error(f"Error zipping {file_path}: {e}")
                        zf.writestr(f"{file_path.split('/')[-1]}.error.txt", f"Error zipping this file: {str(e)}")
            
            # Stream the completed ZIP back to the client
            with open(tmp_zip_path, "rb") as f:
                while True:
                    chunk = f.read(1024*1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            if os.path.exists(tmp_zip_path):
                try:
                    os.remove(tmp_zip_path)
                except:
                    pass

    return StreamingResponse(
        zip_generator(), 
        media_type="application/zip", 
        headers={"Content-Disposition": "attachment; filename=download.zip"}
    )


import sys

def generate_thumbnail_task(bucket_name: str, blob_name: str):
    try:
        bucket = get_bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        content_type = blob.content_type or ""
        lower_name = blob_name.lower()
        is_video = content_type.startswith("video/") or lower_name.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
        is_image = content_type.startswith("image/") or lower_name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.tiff'))
        
        if not (is_video or is_image):
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, "source")
            blob.download_to_filename(local_path)
            thumb_path = os.path.join(tmpdir, "thumb.jpg")
            
            if is_video:
                cmd = [
                    "ffmpeg", "-i", local_path, 
                    "-ss", "00:00:01.000", 
                    "-vframes", "1", 
                    "-vf", "scale=-1:360",
                    thumb_path
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                with Image.open(local_path) as img:
                    img = ImageOps.exif_transpose(img)
                    img.thumbnail((360, 360))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(thumb_path, "JPEG", quality=85)
            
            if os.path.exists(thumb_path):
                with open(thumb_path, "rb") as f:
                    upload_thumbnail(bucket_name, blob_name, f.read())
    except Exception as e:
        logger.error(f"Error generating thumbnail for {blob_name}: {e}")

@app.get("/api/thumbnail/{path:path}")
async def get_thumbnail(
    path: str, 
    background_tasks: BackgroundTasks,
    bucket_name: str = Query(..., description="Bucket name"),
    user: dict = Depends(verify_google_token)
):
    if not check_user_access(user["email"], bucket_name, path):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
         get_bucket(bucket_name)
    except ValueError:
         raise HTTPException(status_code=400, detail="Invalid bucket")

    thumb_bucket = get_thumbnail_bucket()
    thumb_blob_path = f"{bucket_name}/{path}"

    def stream_thumbnail():
        blob = thumb_bucket.blob(thumb_blob_path)
        stream = blob.open("rb", chunk_size=64*1024)
        def iterfile():
            with stream as f:
                while True:
                    chunk = f.read(64*1024)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(iterfile(), media_type="image/jpeg")

    # If exists, stream it
    if check_thumbnail_exists(bucket_name, path):
        return stream_thumbnail()

    # Check if it's even media before attempting to generate
    lower_name = path.lower()
    if not lower_name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp4', '.mov', '.avi', '.mkv', '.webm')):
        raise HTTPException(status_code=404, detail="Thumbnails not available for non-media files")

    # Otherwise generate synchronously (Option B for Cloud Run)
    generate_thumbnail_task(bucket_name, path)

    if check_thumbnail_exists(bucket_name, path):
        return stream_thumbnail()

    raise HTTPException(status_code=500, detail="Thumbnail generation failed")

# Endpoint to Proxy Full Media (Video/Image)
@app.get("/api/stream/{path:path}")
async def stream_media(
    path: str,
    range: Optional[str] = Header(None),
    bucket_name: str = Query(..., description="Bucket name"),
    user: dict = Depends(verify_google_token)
):
    """
    Proxies the full file from GCS for viewer/streaming with Range support (HTTP 206).
    """
    if not check_user_access(user["email"], bucket_name, path):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        stream, content_type, size = get_blob_stream(bucket_name, path)
        
        start = 0
        end = size - 1 if size else None
        status_code = 200

        if range and size:
            # Simple Range header parser: "bytes=0-100" or "bytes=0-"
            try:
                parts = range.replace("bytes=", "").split("-")
                start = int(parts[0]) if parts[0] else 0
                if parts[1]:
                    end = int(parts[1])
                status_code = 206
            except Exception:
                pass

        if start > 0:
            stream.seek(start)

        def iterfile():
             bytes_to_read = (end - start + 1) if end is not None else None
             read_so_far = 0
             with stream as f:
                 while True:
                     to_read = 1024*1024 # 1MB chunks
                     if bytes_to_read is not None:
                         to_read = min(to_read, bytes_to_read - read_so_far)
                     
                     if to_read <= 0:
                         break
                         
                     chunk = f.read(to_read)
                     if not chunk:
                         break
                     yield chunk
                     read_so_far += len(chunk)
        
        headers = {
            "Accept-Ranges": "bytes"
        }
        if size is not None:
            if status_code == 206:
                content_end = end if end is not None else size - 1
                headers["Content-Range"] = f"bytes {start}-{content_end}/{size}"
                headers["Content-Length"] = str(content_end - start + 1)
            else:
                headers["Content-Length"] = str(size)

        return StreamingResponse(
            iterfile(), 
            status_code=status_code,
            media_type=content_type or "application/octet-stream",
            headers=headers
        )
    except Exception as e:
        logger.error(f"Stream error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if os.path.exists("frontend/dist"):
    app.mount("/assets", StaticFiles(directory="frontend/dist/assets"), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404, detail="Not Found")
            
        dist_path = os.path.join("frontend/dist", full_path)
        if os.path.exists(dist_path) and os.path.isfile(dist_path):
            return FileResponse(dist_path)
            
        return FileResponse("frontend/dist/index.html")
