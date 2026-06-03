# Farmer RAG Pipeline

A Retrieval-Augmented Generation (RAG) system designed to answer diverse agricultural questions from farmers using Step Back query translation and hybrid retrieval.

## Main Architecture

/rag-chatbot/
├── document_processor.py      ← Load & chunk PDFs
├── vector_store.py            ← Chroma DB management
├── ingest.py                  ← Orchestrate ingestion
├── query_translation.py       ← Step Back prompting (refactor from template)
├── retrieval.py               ← Hybrid search (refactor from template)
├── answer_generation.py       ← NEW: LLM response synthesis
├── rag_pipeline.py            ← Connect all 4 pieces
└── data/agri/                 ← Documents

## Home Page
<img width="1915" height="1123" alt="image" src="https://github.com/user-attachments/assets/a4d16be6-64d8-458c-afa6-751020d9db2f" />


