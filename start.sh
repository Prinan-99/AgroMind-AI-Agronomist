#!/usr/bin/env bash
set -euo pipefail

export PORT="${PORT:-5000}"
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2}"
export CHROMA_DB_DIR="${CHROMA_DB_DIR:-/app/chroma_db}"
export AGROMIND_DB_PATH="${AGROMIND_DB_PATH:-/app/runtime/agromind.db}"
export AGROMIND_DATA_DIR="${AGROMIND_DATA_DIR:-/app/data/agri}"

mkdir -p "$(dirname "$AGROMIND_DB_PATH")" "$CHROMA_DB_DIR"

echo "[AgroMind] Waiting for Ollama..."
check_ollama() {
    python - "$OLLAMA_BASE_URL" <<'PY'
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
try:
    urllib.request.urlopen(base_url + "/api/tags", timeout=2).read()
except Exception:
    raise SystemExit(1)
raise SystemExit(0)
PY
}

for _ in $(seq 1 90); do
    if check_ollama; then
        break
    fi
    sleep 1
done

if ! check_ollama; then
    echo "[AgroMind] Ollama did not become ready." >&2
    exit 1
fi

if [ "${RUN_INGEST_ON_START:-auto}" = "1" ] || [ "${RUN_INGEST_ON_START:-auto}" = "true" ]; then
    echo "[AgroMind] RUN_INGEST_ON_START enabled; rebuilding ChromaDB."
    python ingest.py
elif [ "${RUN_INGEST_ON_START:-auto}" = "auto" ]; then
    echo "[AgroMind] Checking ChromaDB collection..."
    if python - <<'PY'
from vector_store import VectorStore
store = VectorStore()
raise SystemExit(0 if store.count() > 0 else 2)
PY
    then
        echo "[AgroMind] Existing ChromaDB collection found."
    else
        echo "[AgroMind] ChromaDB is empty; running ingestion."
        python ingest.py
    fi
fi

echo "[AgroMind] Starting Flask app on port ${PORT}..."
exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --threads "${GUNICORN_THREADS:-4}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    app:app
