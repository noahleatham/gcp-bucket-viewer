import os
import logging
import sys
from dotenv import load_dotenv

# Setup logging to stdout
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# Load env (so it picks up credentials)
load_dotenv("backend/.env")

# Mock Uvicorn logger
logger = logging.getLogger("uvicorn")
logger.setLevel(logging.INFO)

# Import the task function
# We need to make sure backend is in path
sys.path.append(os.getcwd())

try:
    from backend.main import generate_thumbnail_task
except ImportError:
    # If direct import fails due to relative imports in main.py, we might need to adjust
    # But main.py uses `.auth` which implies it expects to be run as module.
    # Let's try running this script as a module or adjusting imports.
    # actually main.py uses `from .auth` which fails if run directly.
    # We will just copy the logic effectively or try `python -m`
    pass

if __name__ == "__main__":
    print("Starting manual generation test...")
    # Pick a file we saw in the verification step: '05012025_dump/DSCF0001.JPG' in 'fujifilm-photos'
    bucket_name = "fujifilm-photos"
    blob_name = "05012025_dump/DSCF0001.JPG"
    
    # We need to hack the module import issue if we just run this file.
    # Better: Run `python -m backend.debug_thumb`
    
    from backend.main import generate_thumbnail_task
    generate_thumbnail_task(bucket_name, blob_name)
    print("Done.")
