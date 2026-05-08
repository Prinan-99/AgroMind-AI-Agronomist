# Farmer RAG Pipeline

A Retrieval-Augmented Generation (RAG) system designed to answer diverse agricultural questions from farmers using Step Back query translation and hybrid retrieval.

## 📋 Architecture

/rag-chatbot/
├── document_processor.py      ← Load & chunk PDFs
├── vector_store.py            ← Chroma DB management
├── ingest.py                  ← Orchestrate ingestion
├── query_translation.py       ← Step Back prompting (refactor from template)
├── retrieval.py               ← Hybrid search (refactor from template)
├── answer_generation.py       ← NEW: LLM response synthesis
├── rag_pipeline.py            ← Connect all 4 pieces
└── data/agri/                 ← Documents

Here's the complete AgroMind RAG flow:

```
                        🌾 AGROMIND RAG PIPELINE
                        
┌─────────────────────────────────────────────────────┐
│                   INGESTION (run once)               │
│                                                     │
│  document_processor.py                             │
│  └── Loads 33 PDFs from 5 folders                 │
│      crops/irrigation/pest/pest_harvest/soil        │
│              ↓                                      │
│  chunker.py                                        │
│  └── Splits pages into 500-word chunks             │
│      with 50-word overlap                          │
│              ↓                                      │
│  vector_store.py                                   │
│  └── Embeds chunks → stores in ChromaDB            │
└─────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────┐
│                 QUERY (every question)               │
│                                                     │
│  👨‍🌾 Farmer asks: "Why are my crops not growing?"   │
│              ↓                                      │
│  query_translation.py (Step-Back Prompting)        │
│  └── Original  → "Why are my crops not growing?"  │
│  └── Step-back → "What principles affect crop     │
│                    growth and soil health?"        │
│              ↓                                      │
│  retrieval.py (HybridRetriever)                    │
│  └── Vector search  (60%) → semantic meaning      │
│  └── Keyword search (40%) → exact terms           │
│  └── Merge & rank → top 5 chunks                  │
│              ↓                                      │
│  answer_generation.py                              │
│  └── LLM (Ollama) reads chunks + query            │
│  └── Generates practical farming advice           │
│              ↓                                      │
│  💡 "Your crops need nitrogen. Apply fertilizer   │
│      at pH 6.0-7.0 and ensure proper irrigation"  │
└─────────────────────────────────────────────────────┘
```

---

### In one line per file:

| File | Job |
|---|---|
| `document_processor.py` | Load PDFs → extract text |
| `chunker.py` | Split text → 500-word chunks |
| `vector_store.py` | Store chunks → ChromaDB |
| `ingest.py` | Run above 3 together once |
| `query_translation.py` | One query → two queries |
| `retrieval.py` | Search ChromaDB → top 5 chunks |
| `answer_generation.py` | Chunks + query → LLM answer |
| `rag_pipeline.py` | Ties query side end-to-end |

## Google Login Setup

The login page supports Google sign-in through OAuth.

### 1. Create OAuth credentials in Google Cloud

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Select or create a project for AgroMind.
3. Go to **APIs & Services** → **OAuth consent screen** and finish the basic app setup.
4. Go to **APIs & Services** → **Credentials**.
5. Click **Create Credentials** → **OAuth client ID**.
6. Choose **Web application**.
7. Add this authorized redirect URI:

```text
http://localhost:5000/login/google/callback
```

8. Copy the generated **Client ID** and **Client Secret**.

### 2. Add a local `.env`

Create a `.env` file in the project root with:

```env
FLASK_SECRET_KEY=change-me
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

For local development, Flask will load `.env` automatically when `python-dotenv` is available.

### 3. Run the app

```bash
source source/bin/activate
python app.py
```

If Google blocks local HTTP sign-in in your browser, set this once in your terminal before starting the app:

```bash
export AUTHLIB_INSECURE_TRANSPORT=1
```