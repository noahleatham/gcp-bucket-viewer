# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GCP Bucket Viewer is a personal media archive viewer for Google Cloud Storage. Authenticated users can browse, preview, and download photos/videos from GCS buckets. Deployed to Google Cloud Run as a single container.

## Commands

### Backend (Python/FastAPI)

```bash
# Run from repo root (required for relative imports)
python -m uvicorn backend.main:app --reload --port 8000

# Install dependencies
pip install -r backend/requirements.txt
```

### Frontend (React/Vite)

```bash
cd frontend
npm install
npm run dev       # Dev server on :5173
npm run build     # Production build → frontend/dist/
npm run lint      # ESLint
```

### Docker

```bash
docker build -t gcp-bucket-viewer .
docker run -p 8080:8080 \
  -e GOOGLE_CLOUD_PROJECT=... \
  -e ALLOWED_BUCKETS=... \
  -e GOOGLE_CLIENT_ID=... \
  -e ALLOWED_USERS=... \
  gcp-bucket-viewer
```

## Architecture

**Backend** (`backend/`): Python FastAPI app. All routes defined in `main.py` under `/api/`. Auth logic in `auth.py` (Google OAuth ID token verification + email allowlist). GCS operations in `gcs_utils.py`. In production, serves the frontend SPA from `frontend/dist/` and falls through non-API routes to `index.html`.

**Frontend** (`frontend/`): React 19 + Vite 7 SPA. No client-side routing — navigation is state-driven. `AuthContext.jsx` handles Google OAuth, token storage (localStorage), and axios interceptors. `Gallery.jsx` is the main UI (~900 lines) containing the media grid, infinite scroll, thumbnail loading with retry logic, preview modal, folder navigation, and batch download.

**Thumbnails**: Generated on-demand or in bulk. Images use Pillow; videos use ffmpeg (subprocess). Stored back to GCS under `thumbnails/` prefix. The thumbnail endpoint returns 202 while generating, and the frontend retries up to 10 times.

**Deployment**: Multi-stage Dockerfile — Node for frontend build, Python 3.11-slim runtime with ffmpeg. Target is Cloud Run with ADC for GCS credentials.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GOOGLE_CLOUD_PROJECT` | GCP project ID |
| `ALLOWED_BUCKETS` | Comma-separated bucket allowlist |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (unset = auth bypassed) |
| `ALLOWED_USERS` | Comma-separated email allowlist |
| `VITE_API_BASE` | Frontend API base URL (default: `http://localhost:8000`) |

## Key Patterns

- Backend must be run as a module from the repo root (`python -m uvicorn backend.main:app`) due to relative imports
- CORS is permissive (`*`) for local development
- Auth token passed via `Authorization: Bearer` header, or `?token=` query param for streaming endpoints
- No tests or CI/CD exist currently
- No Python linter configured
- `react-router-dom` and `tailwind-merge` are installed but unused
