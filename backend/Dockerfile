FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image at build time, from our own GCS mirror -- not Hugging Face Hub.
# HF rate-limits unauthenticated requests, and repeated builds/cold starts were hitting that limit (one
# build's download took 7 minutes; some failed outright). This bucket holds an exact copy of fastembed's
# own cache layout for BAAI/bge-small-en-v1.5 (a fully open, public model; mirroring its weights carries
# no sensitivity), so fastembed finds the model pre-cached and never calls HF at all, at build or runtime.
# No fallback to HF here deliberately: if the mirror is missing, fail the build loudly, don't silently
# fall back to the flaky path this replaces.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed_cache
# python:3.12-slim has no curl; urllib is already there, so use that instead of adding an apt package.
RUN mkdir -p "$FASTEMBED_CACHE_PATH" \
    && python -c "import urllib.request; urllib.request.urlretrieve('https://storage.googleapis.com/buybyfit-ml-models/bge-small-en-v1.5-fastembed-cache.tar.gz', '/tmp/model-cache.tar.gz')" \
    && tar -xzf /tmp/model-cache.tar.gz -C "$FASTEMBED_CACHE_PATH" \
    && rm /tmp/model-cache.tar.gz \
    && python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"

COPY . .

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
