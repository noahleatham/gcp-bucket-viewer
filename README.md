# GCP Bucket Viewer

A personal media archive viewer for Google Cloud Storage. Browse, preview, and download photos and videos from GCS buckets through a clean web interface. Deployed as a single container to Google Cloud Run.

## Features

- Google OAuth authentication with email allowlist
- Browse GCS buckets and folders
- Infinite scroll media grid with thumbnail previews
- Photo and video preview modal
- Batch download
- On-demand thumbnail generation (images via Pillow, videos via ffmpeg)

## Stack

- **Backend**: Python 3.11 / FastAPI
- **Frontend**: React 19 / Vite 7
- **Storage**: Google Cloud Storage
- **Auth**: Google OAuth 2.0
- **Deployment**: Docker / Google Cloud Run

## Local Development

### Backend

```bash
pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # Dev server on :5173
```

Create a `backend/.env` file:

```env
GOOGLE_CLOUD_PROJECT=your-project-id
ALLOWED_BUCKETS=bucket-one,bucket-two
GOOGLE_CLIENT_ID=your-oauth-client-id
ALLOWED_USERS=you@example.com
```

## Docker

```bash
docker build -t gcp-bucket-viewer .
docker run -p 8080:8080 \
  -e GOOGLE_CLOUD_PROJECT=... \
  -e ALLOWED_BUCKETS=... \
  -e GOOGLE_CLIENT_ID=... \
  -e ALLOWED_USERS=... \
  gcp-bucket-viewer
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `ALLOWED_BUCKETS` | Comma-separated bucket allowlist |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (unset = auth bypassed) |
| `ALLOWED_USERS` | Comma-separated email allowlist |
| `VITE_API_BASE` | Frontend API base URL (default: `http://localhost:8000`) |

## Permissions

Per-user access is controlled via `backend/permissions.json`. Each entry maps an email address to a list of rules that determine which buckets and paths they can access.

```json
{
  "user@example.com": ["*"],
  "friend@example.com": ["my-bucket"],
  "limited@example.com": ["my-bucket/photos/trip/"]
}
```

**Rule types:**

| Rule | Access granted |
|------|----------------|
| `"*"` | Full access to all buckets in `ALLOWED_BUCKETS` |
| `"bucket-name"` | Full access to that bucket |
| `"bucket-name/prefix/"` | Access restricted to that prefix and sub-paths |

Multiple rules can be combined — e.g. `["bucket-a", "bucket-b/photos/"]`.

The file is watched at runtime and reloaded automatically when changed, so permissions updates take effect without restarting the server.

## Deployment

The multi-stage Dockerfile builds the React frontend and packages it with the Python backend. In production, FastAPI serves the SPA from `frontend/dist/` and proxies non-API routes to `index.html`.

Deploy to Cloud Run with [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) for GCS access.

### Build & Deploy to Cloud Run

**1. Build the image using Cloud Build:**

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/gcp-bucket-viewer
```

**2. Deploy to Cloud Run:**

```bash
gcloud run deploy gcp-bucket-viewer \
  --image gcr.io/YOUR_PROJECT_ID/gcp-bucket-viewer \
  --region us-central1 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,ALLOWED_BUCKETS=bucket-one,GOOGLE_CLIENT_ID=YOUR_CLIENT_ID,ALLOWED_USERS=you@example.com
```

**3. Re-deploy after changes (build + deploy):**

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/gcp-bucket-viewer && \
gcloud run deploy gcp-bucket-viewer \
  --image gcr.io/YOUR_PROJECT_ID/gcp-bucket-viewer \
  --region us-central1
```

The service will use the existing Cloud Run environment variables on re-deploy, so `--set-env-vars` is only needed on first deploy.
