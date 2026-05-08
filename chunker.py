"""
Chunker
Splits extracted PDF pages into smaller overlapping chunks
for better RAG retrieval
"""

from typing import List, Dict


class Chunker:
    def __init__(self, chunk_size: int = 500, overlap: int = 50):
        """
        Args:
            chunk_size: Max words per chunk
            overlap: Overlapping words between chunks
                     (preserves context at boundaries)
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_documents(self, docs: List[Dict]) -> List[Dict]:
        """Chunk all documents"""
        all_chunks = []
        for doc in docs:
            chunks = self.chunk_text(doc)
            all_chunks.extend(chunks)
        print(f"✅ Total chunks created: {len(all_chunks)}")
        return all_chunks

    def chunk_text(self, doc: Dict) -> List[Dict]:
        """Split a single document into overlapping chunks"""
        words = doc["content"].split()
        chunks = []
        chunk_index = 0
        start = 0

        while start < len(words):
            end = start + self.chunk_size
            chunk_words = words[start:end]
            chunk_content = " ".join(chunk_words)

            chunks.append({
                "doc_id": f"{doc['doc_id']}_chunk{chunk_index}",
                "content": chunk_content,
                "source": doc["source"],
                "category": doc["category"],
                "page": doc["page"],
                "chunk_index": chunk_index
            })

            chunk_index += 1
            start += self.chunk_size - self.overlap  # slide with overlap

        return chunks


if __name__ == "__main__":
    from document_processor import DocumentProcessor

    # Step 1: Load all docs
    processor = DocumentProcessor()
    docs = processor.load_all_docs()

    # Step 2: Chunk them
    chunker = Chunker(chunk_size=500, overlap=50)
    chunks = chunker.chunk_documents(docs)

    # Step 3: Preview
    print(f"\n📄 Sample chunk:")
    print(f"ID      : {chunks[0]['doc_id']}")
    print(f"Category: {chunks[0]['category']}")
    print(f"Page    : {chunks[0]['page']}")
    print(f"Words   : {len(chunks[0]['content'].split())}")
    print(f"Preview : {chunks[0]['content'][:150]}...")