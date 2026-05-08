"""
Vector Store
ChromaDB management for AgroMind RAG
"""

import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict


class VectorStore:
    def __init__(self, persist_dir: str = "./chroma_db"):
        """Initialize ChromaDB with local persistence"""
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-mpnet-base-v2"
        )
        self.collection = self.client.get_or_create_collection(
            name="agrimind",
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )
        print(f"✅ ChromaDB connected | Collection: agrimind")

    def add_chunks(self, chunks: List[Dict]):
        """Add chunks to ChromaDB"""
        ids = [chunk["doc_id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        metadatas = [
            {
                "source": chunk["source"],
                "category": chunk["category"],
                "page": chunk["page"],
                "chunk_index": chunk["chunk_index"]
            }
            for chunk in chunks
        ]

        batch_size = 100
        for i in range(0, len(chunks), batch_size):
            self.collection.add(
                ids=ids[i:i+batch_size],
                documents=documents[i:i+batch_size],
                metadatas=metadatas[i:i+batch_size]
            )
            print(f"📥 Ingested batch {i//batch_size + 1} | {min(i+batch_size, len(chunks))}/{len(chunks)} chunks")

        print(f"✅ Total chunks in ChromaDB: {self.collection.count()}")

    def query(self, query_text: str, n_results: int = 5) -> List[Dict]:
        """Query ChromaDB for similar chunks"""
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )

        docs = []
        for i in range(len(results["ids"][0])):
            docs.append({
                "doc_id": results["ids"][0][i],
                "content": results["documents"][0][i],
                "source": results["metadatas"][0][i]["source"],
                "category": results["metadatas"][0][i]["category"],
                "vector_score": 1 - results["distances"][0][i],  # ← distance → similarity
            })
        return docs

    def count(self) -> int:
        """Return total chunks stored"""
        return self.collection.count()


if __name__ == "__main__":
    store = VectorStore()
    print(f"📊 Chunks in store: {store.count()}")