from typing import Tuple
from langchain_ollama import OllamaLLM
import os

class QueryTranslator:
    def __init__(self):
        print("QueryTranslator initialized with Step Back technique")
        self.llm = OllamaLLM(
            model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            temperature=0.3,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        )

    def step_back_translate(self, query: str) -> Tuple[str, str]:
        query_translation_prompt = f"""You are an expert agricultural consultant with decades of experience 
                     in crop science, soil management, pest control, and sustainable farming practices.

                            I am going to ask you a specific farming question. Your task is to:
                            1. STEP BACK from the specific question
                            2. Identify the broader agricultural principle or concept behind it
                            3. Reframe it aOllamaLLM(model="llama3.2", temperature=0.3)OllamaLLM(model="llama3.2", temperature=0.3)s a general KNOWLEDGE-BASED principle question

                            IMPORTANT: 
                            - Do NOT ask the farmer a question back
                            - Respond with ONLY the reframed question, no labels, no prefixes
                            - Do NOT include words like "Specific:" or "Step-Back:"

                            Original Question: {query}

                            Example Input: "Why are my tomato leaves turning yellow in sandy soil?"
                            Example Output: "What are the fundamental nutrient deficiency and soil composition principles that affect plant health?"

                            Your reframed question:"""
        step_back_query = self.llm.invoke(query_translation_prompt)
        return query, step_back_query

    def get_both_queries(self, query: str) -> dict:  # ← added self
        original_query, step_back_query = self.step_back_translate(query)  # ← unpack
        return {
            "original_query": original_query,
            "step_back_query": step_back_query,
            "retrieval_instructions": (
                f"First Retrieve general agricultural principles using the step-back query: '{step_back_query}'. "
                f"Then Retrieve specific case studies and solutions using the original query: '{original_query}'. "
                f"Combine and rank results based on relevance to both queries."
            )
        }

if __name__ == "__main__":
    test_query = "Why are my crops not growing well?"
    translator = QueryTranslator()
    result = translator.get_both_queries(test_query)
    print(f"Original Query: {result['original_query']}")
    print(f"Step-Back Query: {result['step_back_query']}")
    print(f"Retrieval Instructions: {result['retrieval_instructions']}")
