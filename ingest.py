"""
Ingest
Ties document_processor → chunker → vector_store together
Run this ONCE to build your knowledge base
"""

from document_processor import DocumentProcessor
from chunker import Chunker
from vector_store import VectorStore


def ingest():
    print("🚀 Starting ingestion pipeline...\n")

    # Step 1: Load PDFs
    print("📂 Step 1: Loading documents...")
    processor = DocumentProcessor()
    docs = processor.load_all_docs()
    print(f"✅ Loaded {len(docs)} pages\n")

    # Step 2: Chunk
    print("✂️  Step 2: Chunking documents...")
    chunker = Chunker(chunk_size=500, overlap=50)
    chunks = chunker.chunk_documents(docs)
    print(f"✅ Created {len(chunks)} chunks\n")

    # Step 3: Store in ChromaDB
    print("💾 Step 3: Storing in ChromaDB...")
    store = VectorStore()
    store.add_chunks(chunks)
    print(f"\n🎉 Ingestion complete! {store.count()} chunks ready for retrieval")


if __name__ == "__main__":
    ingest()