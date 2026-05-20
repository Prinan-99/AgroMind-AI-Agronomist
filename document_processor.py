import os
from pathlib import Path
from typing import List, Dict

import pdfplumber

class DocumentProcessor:
    def __init__(self, data_dir:str=None):
        data_dir = data_dir or os.getenv("AGROMIND_DATA_DIR", "data/agri/")
        self.data_dir=Path(data_dir)
        self.categories=["crops","irrigation","pest","pest_harvest","soil"]

    def fix_reversed_text(self, text: str) -> str:
        """Detect and fix mirror-reversed text chunks."""
        words = text.split()
        if not words:
            return text
        
        sample = words[:10]
        reversed_count = sum(1 for w in sample if w[::-1].lower() in 
                            {'the', 'of', 'and', 'to', 'a', 'in', 'is', 'it'})
        
        if reversed_count >= 2:
            return ' '.join(w[::-1] for w in words)
        return text

    def load_all_docs(self) -> List[Dict]:
        all_docs = []
        for category in self.categories:
            category_path = self.data_dir / category
            pdfs = list(category_path.glob("*.pdf"))
            print(f"Found {len(pdfs)} PDFs in category '{category}'")

            for pdf_path in pdfs:
                docs = self.load_pdf(pdf_path, category)
                all_docs.extend(docs)
            
            print(f"Total documents loaded from '{category}': {len(docs)}")
        
        print(f"\nTotal ALL categories: {len(all_docs)}")
        return all_docs  
    
    def load_pdf(self, pdf_path:Path, category:str)->List[Dict]:
        docs=[]
        try:
             with pdfplumber.open(pdf_path) as pdf:
                  for page_num, page in enumerate(pdf.pages):
                      text = page.extract_text()
                      if text and text.strip():
                          text = self.fix_reversed_text(text)
                          docs.append({
                                "doc_id": f"{category}_{pdf_path.stem}_p{page_num + 1}",
                                "content": text.strip(),
                                "source": str(pdf_path.name),
                                "category": category,
                                "page": page_num + 1
                          })
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {e}")
        return docs
    
if __name__ == "__main__":
    processor = DocumentProcessor()
    docs = processor.load_all_docs()
