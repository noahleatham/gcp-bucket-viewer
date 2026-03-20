from google.cloud import storage
import logging
from typing import List, Optional, Tuple
import os
import io
from datetime import datetime

# Initialize Client
try:
    storage_client = storage.Client()
except Exception as e:
    logging.warning(f"Could not initialize storage client: {e}")
    storage_client = None

logger = logging.getLogger("uvicorn")

def get_allowed_buckets() -> List[str]:
    buckets_str = os.environ.get("ALLOWED_BUCKETS", "")
    if not buckets_str:
        return []
    return [b.strip() for b in buckets_str.split(",") if b.strip()]

def get_thumbnail_bucket_name() -> str:
    return os.environ.get("THUMBNAIL_BUCKET", "bucket-viewer-thumbnails")

def get_bucket(bucket_name: str):
    allowed = get_allowed_buckets()
    if bucket_name not in allowed:
        raise ValueError(f"Bucket {bucket_name} is not allowed")

    return storage_client.bucket(bucket_name)

def get_thumbnail_bucket():
    return storage_client.bucket(get_thumbnail_bucket_name())

def list_files(
    bucket_name: str, 
    prefix: str = "", 
    limit: int = 100, 
    page_token: str = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Tuple[List[dict], str, List[str]]:
    """
    Lists files and common prefixes (subdirectories).
    """
    bucket = get_bucket(bucket_name)
    # Using delimiter='/' allows us to discover "subdirectories" via blobs.prefixes
    blobs = bucket.list_blobs(prefix=prefix, max_results=limit, page_token=page_token, delimiter='/')

    results = []
    for blob in blobs:
        if blob.name.endswith("/") or blob.name == prefix:
            continue
        
        # Date filtering
        if start_date and blob.updated and blob.updated < start_date:
            continue
        if end_date and blob.updated and blob.updated > end_date:
            continue

        # Refined media detection
        content_type = blob.content_type or ""
        lower_name = blob.name.lower()
        
        is_video = content_type.startswith("video/") or lower_name.endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm'))
        is_image = content_type.startswith("image/") or lower_name.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif', '.heic', '.tiff'))

        results.append({
            "name": blob.name,
            "size": blob.size,
            "content_type": content_type,
            "updated": blob.updated.isoformat() if blob.updated else None,
            "is_video": is_video,
            "is_image": is_image
        })
    
    # Extract subdirectories from the common prefixes
    subdirectories = list(blobs.prefixes) if blobs.prefixes else []
    
    return results, blobs.next_page_token, subdirectories

def check_thumbnail_exists(bucket_name: str, blob_name: str) -> bool:
    thumbnail_path = f"{bucket_name}/{blob_name}"
    bucket = get_thumbnail_bucket()
    blob = bucket.blob(thumbnail_path)
    return blob.exists()

def upload_thumbnail(bucket_name: str, original_blob_name: str, thumbnail_data: bytes):
    thumbnail_path = f"{bucket_name}/{original_blob_name}"
    bucket = get_thumbnail_bucket()
    blob = bucket.blob(thumbnail_path)
    blob.upload_from_string(thumbnail_data, content_type="image/jpeg")
    
def get_blob_stream(bucket_name: str, blob_name: str, start_byte: Optional[int] = None, end_byte: Optional[int] = None):
    """
    Returns a file-like object for the blob, optionally for a specific range.
    """
    bucket = get_bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.reload()
    
    # Open for reading as binary. GCS open() supports start/end offsets.
    return blob.open("rb", chunk_size=1024*1024), blob.content_type, blob.size
