FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu

WORKDIR /build

COPY requirements.txt ./requirements.txt

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    OLLAMA_MODEL=llama3.2 \
    OLLAMA_BASE_URL=http://ollama:11434 \
    CHROMA_DB_DIR=/app/chroma_db \
    AGROMIND_DB_PATH=/app/runtime/agromind.db \
    AGROMIND_DATA_DIR=/app/data/agri \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /app --shell /usr/sbin/nologin appuser

COPY --from=builder /opt/venv /opt/venv

COPY app.py ./app.py
COPY answer_generation.py ./answer_generation.py
COPY chunker.py ./chunker.py
COPY document_processor.py ./document_processor.py
COPY ingest.py ./ingest.py
COPY query_translation.py ./query_translation.py
COPY rag_pipeline.py ./rag_pipeline.py
COPY retrieval.py ./retrieval.py
COPY vector_store.py ./vector_store.py
COPY start.sh ./start.sh
COPY templates ./templates
COPY data/agri ./data/agri

RUN chmod +x /app/start.sh \
    && mkdir -p /app/runtime /app/chroma_db \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health').read()"

CMD ["/app/start.sh"]
