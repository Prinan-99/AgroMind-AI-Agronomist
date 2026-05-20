FROM ollama/ollama:latest

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    OLLAMA_MODEL=llama3.2 \
    OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    CHROMA_DB_DIR=/app/chroma_db \
    AGROMIND_DB_PATH=/app/runtime/agromind.db \
    AGROMIND_DATA_DIR=/app/data/agri

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libglib2.0-0 \
        libgl1 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install -r requirements.txt

ENV PATH="/opt/venv/bin:${PATH}"

COPY . .

RUN chmod +x /app/start.sh \
    && mkdir -p /app/runtime /app/chroma_db /root/.ollama

EXPOSE 5000 11434

CMD ["/app/start.sh"]
