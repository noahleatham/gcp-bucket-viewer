"""
One-off migration script to move thumbnails from source buckets to a dedicated thumbnail bucket.

Old layout:  {source_bucket}:thumbnails/{blob_name}.jpg
New layout:  bucket-viewer-thumbnails:{source_bucket}/{blob_name}

Run with: python -m backend.migrate_thumbnails
"""

import os
import logging
from dotenv import load_dotenv
from google.cloud import storage

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SOURCE_BUCKETS = [b.strip() for b in os.environ.get("ALLOWED_BUCKETS", "").split(",") if b.strip()]
THUMBNAIL_BUCKET = os.environ.get("THUMBNAIL_BUCKET", "bucket-viewer-thumbnails")


def migrate():
    client = storage.Client()
    dest_bucket = client.bucket(THUMBNAIL_BUCKET)

    for source_bucket_name in SOURCE_BUCKETS:
        logger.info(f"Processing bucket: {source_bucket_name}")
        source_bucket = client.bucket(source_bucket_name)

        blobs = list(source_bucket.list_blobs(prefix="thumbnails/"))
        logger.info(f"  Found {len(blobs)} thumbnail blobs")

        copied = 0
        deleted = 0
        errors = 0

        for blob in blobs:
            # Old path: thumbnails/{original_blob_name}.jpg
            # Strip "thumbnails/" prefix and trailing ".jpg" suffix
            relative = blob.name[len("thumbnails/"):]
            if relative.endswith(".jpg"):
                relative = relative[:-4]

            if not relative:
                logger.warning(f"  Skipping blob with empty relative path: {blob.name}")
                errors += 1
                continue

            new_path = f"{source_bucket_name}/{relative}"

            try:
                # Copy to destination bucket
                source_bucket.copy_blob(blob, dest_bucket, new_name=new_path)
                copied += 1

                # Delete original
                blob.delete()
                deleted += 1

                if copied % 50 == 0:
                    logger.info(f"  Progress: {copied}/{len(blobs)} copied")
            except Exception as e:
                logger.error(f"  Error migrating {blob.name} -> {new_path}: {e}")
                errors += 1

        logger.info(
            f"  Done with {source_bucket_name}: "
            f"{copied} copied, {deleted} deleted, {errors} errors"
        )

    logger.info("Migration complete.")


if __name__ == "__main__":
    if not SOURCE_BUCKETS:
        logger.error("ALLOWED_BUCKETS env var is empty, nothing to migrate")
    else:
        migrate()
