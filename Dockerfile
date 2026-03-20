# Stage 1: Build Frontend
FROM node:20-alpine as frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Setup Backend & Runtime
FROM python:3.11-slim

# Install system dependencies (ffmpeg)
# We also need to be careful about permissions if running as non-root, but Cloud Run handles root nicely by default or we specify USER.
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Backend requirements
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy Backend Code
COPY backend/ ./backend/

# Copy Frontend Build Artifacts
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Env vars default for Cloud Run
ENV PORT=8080
ENV ALLOWED_BUCKETS=""
ENV GOOGLE_CLIENT_ID=""
ENV ALLOWED_USERS=""
ENV GOOGLE_CLOUD_PROJECT=""
ENV THUMBNAIL_BUCKET="bucket-viewer-thumbnails"

# We need to serve the frontend static files from FastAPI or use a separate server?
# For a "Combined Service", FastAPI should serve schema *and* static files.
# We need to update main.py to serve static.

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
