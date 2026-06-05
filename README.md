# Farmer RAG Pipeline

A Retrieval-Augmented Generation (RAG) system designed to answer diverse agricultural questions from farmers using Step Back query translation and hybrid retrieval.

## Architecture

A RAG pipeline built on 4 modular components:

1. **Document Processor** — Loads and chunks agricultural PDFs
2. **Vector Store** — Manages ChromaDB embeddings for semantic search
3. **Query Translation** — Applies Step Back prompting to 
   reframe farmer queries for better retrieval
4. **Retrieval** — Hybrid search combining semantic + 
   keyword matching
5. **Answer Generation** — Synthesizes context-aware 
   responses via LLM

> Flow: Query → Step Back Translation → 
> Hybrid Retrieval → LLM Synthesis → Answer

## Home Page
https://github.com/user-attachments/assets/d13c8c97-991d-4248-a884-6081afae1327



