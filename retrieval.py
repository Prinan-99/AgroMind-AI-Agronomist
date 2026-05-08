"""
Hybrid Retrieval
BM25 keyword re-ranker on ChromaDB candidates
"""

from typing import List, Dict
from dataclasses import dataclass
import math
from collections import Counter


@dataclass
class RetrievalResult:
    """Single retrieved document result"""
    doc_id: str
    content: str
    source: str
    category: str = "general"
    vector_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0


class HybridRetriever:
    def __init__(self, vector_weight: float = 0.6, keyword_weight: float = 0.4, top_k: int = 3):
        assert abs(vector_weight + keyword_weight - 1.0) < 1e-6, "Weights must sum to 1"
        self.vector_weight = vector_weight
        self.keyword_weight = keyword_weight
        self.top_k = top_k
        self.documents: List[Dict] = []

    def retrieve(self, original_query: str, step_back_query: str) -> List[RetrievalResult]:
        """Re-rank candidates using BM25 on original query."""
        keyword_results = self._keyword_search(original_query)
        return self._merge_and_rank(keyword_results)

    def _keyword_search(self, query: str) -> List[RetrievalResult]:
        """BM25 keyword search on candidate documents"""
        if not self.documents:
            return []

        k1, b = 1.5, 0.75
        query_terms = query.lower().split()
        doc_contents = [doc["content"].lower() for doc in self.documents]
        avg_dl = sum(len(doc.split()) for doc in doc_contents) / len(doc_contents)
        tf_list = [Counter(doc.split()) for doc in doc_contents]

        N = len(self.documents)
        idf = {}
        for term in query_terms:
            df = sum(1 for doc in doc_contents if term in doc)
            idf[term] = math.log((N - df + 0.5) / (df + 0.5) + 1)

        results = []
        for i, doc in enumerate(self.documents):
            dl = len(doc_contents[i].split())
            score = 0.0
            for term in query_terms:
                tf = tf_list[i].get(term, 0)
                score += idf.get(term, 0) * (tf * (k1 + 1)) / (
                    tf + k1 * (1 - b + b * dl / avg_dl)
                )
            results.append(RetrievalResult(
                doc_id=doc["doc_id"],
                content=doc["content"],
                source=doc.get("source", "unknown"),
                category=doc.get("category", "general"),
                vector_score=doc.get("vector_score", 0.0),
                keyword_score=float(score)
            ))

        return sorted(results, key=lambda x: x.keyword_score, reverse=True)

    def _merge_and_rank(self, keyword_results: List[RetrievalResult]) -> List[RetrievalResult]:
        """Combine ChromaDB vector score + BM25 score into final ranking"""
        if not keyword_results:
            return []

        v_scores = [r.vector_score for r in keyword_results]
        k_scores = [r.keyword_score for r in keyword_results]
        v_max = max(v_scores, default=1)
        k_max = max(k_scores, default=1)

        for result in keyword_results:
            norm_v = result.vector_score / (v_max + 1e-9)
            norm_k = result.keyword_score / (k_max + 1e-9)
            result.combined_score = (
                self.vector_weight * norm_v + self.keyword_weight * norm_k
            )

        return sorted(keyword_results, key=lambda x: x.combined_score, reverse=True)[:self.top_k]


if __name__ == "__main__":
    retriever = HybridRetriever(vector_weight=0.6, keyword_weight=0.4, top_k=3)
    retriever.documents = [
        {"doc_id": "1", "content": "Tomato leaves turn yellow due to nitrogen deficiency.", "source": "agro_db", "category": "crops", "vector_score": 0.85},
        {"doc_id": "2", "content": "Soil pH affects nutrient availability. Optimal pH is 6.0-7.0.", "source": "agro_db", "category": "soil", "vector_score": 0.60},
        {"doc_id": "3", "content": "Yellowing leaves can indicate iron deficiency in alkaline soils.", "source": "agro_db", "category": "soil", "vector_score": 0.75},
    ]
    results = retriever.retrieve("Why are my tomato leaves yellow?", "What causes leaf yellowing?")
    for r in results:
        print(f"[{r.doc_id}] Combined: {r.combined_score:.3f} | {r.content[:60]}...")