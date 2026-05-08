"""
RAG Pipeline
Final end-to-end orchestrator for AgroMind
"""

from query_translation import QueryTranslator
from vector_store import VectorStore
from retrieval import HybridRetriever, RetrievalResult
from answer_generation import AnswerGenerator
from typing import List


class RAGPipeline:
    def __init__(self):
        print("🚀 Initializing AgroMind RAG Pipeline...\n")
        self.translator = QueryTranslator()
        self.store = VectorStore()
        self.retriever = HybridRetriever(vector_weight=0.6, keyword_weight=0.4, top_k=3)
        self.generator = AnswerGenerator(top_docs=3)
        self.chat_history = []
        print("\n✅ Pipeline ready!\n")

    def run(self, query: str) -> str:
        """Run full RAG pipeline on a farmer query"""

        print(f"🌾 Query: {query}\n")

        if self.chat_history:
            last_q = self.chat_history[-1]["query"]
            contextual_query = f"Previous: {last_q} | Current: {query}"
        else:
            contextual_query = query

        # Step 1: Translate query
        print("🔄 Step 1: Translating query...")
        both_queries = self.translator.get_both_queries(contextual_query)
        original = both_queries["original_query"]
        step_back = both_queries["step_back_query"]
        print(f"   Original: {original[:80]}")
        print(f"   Step-back: {step_back[:80]}...\n")

        # Step 2: ChromaDB vector search on both queries (fast ANN)
        print("🔍 Step 2: Retrieving relevant documents...")
        vector_docs = self.store.query(step_back, n_results=5)
        keyword_docs = self.store.query(original, n_results=5)

        # Merge + deduplicate into ~6-8 candidates
        all_docs = {doc["doc_id"]: doc for doc in vector_docs + keyword_docs}
        candidates = list(all_docs.values())

        # Step 3: BM25 re-rank on small candidate set only
        self.retriever.documents = candidates
        ranked_results = self.retriever.retrieve(original, step_back)
        print(f"   Retrieved {len(ranked_results)} ranked chunks\n")

        # Convert RetrievalResult → dict for AnswerGenerator
        retrieved = [
            {
                "doc_id": r.doc_id,
                "content": r.content,
                "source": r.source,
                "category": r.category,
                "combined_score": r.combined_score
            }
            for r in ranked_results
        ]

        # Step 4: Generate answer
        print("🤖 Step 3-4: Generating answer...")
        answer = self.generator.generate(query, retrieved)
        self.chat_history.append({"query": query, "answer": answer})
        return answer


if __name__ == "__main__":
    pipeline = RAGPipeline()

    while True:
        query = input("\n🌾 Ask AgroMind (or 'quit'): ")
        if query.lower() == "quit":
            break
        answer = pipeline.run(query)
        print(f"\n💡 Answer:\n{answer}")