# Kachra Mitra — API + app image.
#
# Runtime deps only: no torch, no training data. Inference is ONNX Runtime.
# Build:  docker build -t kachra-mitra .
# Run:    docker run --rm -p 8000:8000 -e FACILITY_PROVIDER=fixture kachra-mitra
#
# The model is optional. If artifacts/ does not exist the API still boots and
# /health reports classifier.ready=false; /classify returns 503 with the fix command.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# libgomp is required by onnxruntime's CPU provider
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY . .

RUN mkdir -p /data \
    && useradd --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app /data

USER app

ENV ONNX_PATH=artifacts_pretrained/mobilenet_v3_large_imagenet.onnx \
    LABELS_PATH=artifacts_pretrained/labels.json \
    DB_PATH=/data/app.db \
    LLM_PROVIDER=fake \
    FACILITY_PROVIDER=fixture

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()" || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
