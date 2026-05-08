"""
Answer Generation
Synthesizes final answer from retrieved chunks using LLM
Low latency: uses only top 3 ranked docs
"""

from typing import List, Dict
from langchain_ollama import OllamaLLM


class AnswerGenerator:
    def __init__(self, model: str = "llama3.2", top_docs: int = 3):
        """
        Args:
            model: Ollama model to use
            top_docs: Number of top ranked docs to use
        """
        self.llm = OllamaLLM(model=model, temperature=0.3)
        self.top_docs = top_docs
        print(f"✅ LLM loaded: {model} | Using top {top_docs} docs for generation")

    def generate(self, query: str, retrieved_docs: List[Dict]) -> str:
        """Generate answer from query + top ranked retrieved docs"""

        top_docs = retrieved_docs[:self.top_docs]

        context = "\n\n".join([
            f"[Source: {doc['source']} | Category: {doc.get('category', 'general')}]\n{doc['content']}"
            for doc in top_docs
        ])

        prompt = f"""You are AgroMind, an expert agricultural consultant AI.

Use ONLY the context below to answer the farmer's question.
Only use information that is directly relevant to the question.
Be concise, practical, and actionable. 2-4 sentences max.
If the answer is not in the context, say "I don't have specific information on this."

CONTEXT:
{context}

FARMER'S QUESTION:
{query}

ANSWER:"""

        response = self.llm.invoke(prompt)
        return response


if __name__ == "__main__":
    generator = AnswerGenerator(top_docs=3)
    sample_docs = [
        {"source": "wheat.pdf", "category": "crops",
         "content": "Wheat requires well-drained soil with pH 6.0-7.0. Apply nitrogen fertilizer at sowing."},
        {"source": "soil.pdf", "category": "soil",
         "content": "Soil fertility depends on organic matter, pH, and nutrient balance."},
        {"source": "irrigation.pdf", "category": "irrigation",
         "content": "Irrigation scheduling depends on soil moisture and crop growth stage."},
    ]
    answer = generator.generate("How do I grow wheat properly?", sample_docs)
    print(f"\n🌾 Answer:\n{answer}")