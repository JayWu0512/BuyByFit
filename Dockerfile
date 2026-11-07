# Backend image for the Cloud Run trigger that builds from the repository root
# (cloudrun-buybyfit-git-*, service buybyfit-git). Same as backend/Dockerfile, with paths relative to the root.
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
