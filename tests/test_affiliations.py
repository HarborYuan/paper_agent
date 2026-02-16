import asyncio
import pytest
from src.services.llm import LLMService, AffiliationResponse
from src.services.pdf_service import pdf_service
from src.models import Paper
from datetime import datetime

# Papers to test
PAPERS = [
    {
        "id": "1512.03385", # ResNet
        "title": "Deep Residual Learning for Image Recognition",
        "url": "https://arxiv.org/pdf/1512.03385"
    },
    {
        "id": "2010.11929", # ViT
        "title": "An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        "url": "https://arxiv.org/pdf/2010.11929"
    },
    {
        "id": "2103.00020", # CLIP
        "title": "Learning Transferable Visual Models From Natural Language Supervision",
        "url": "https://arxiv.org/pdf/2103.00020"
    },
    {
        "id": "2601.07372", # Specific paper request
        "title": "Test Paper",
        "url": "https://arxiv.org/pdf/2601.07372"
    }
]

async def _run_affiliation_extraction():
    llm = LLMService()
    
    print("Starting Affiliation Extraction Test...")
    
    for p_info in PAPERS:
        print(f"\nProcessing {p_info['title']} ({p_info['id']})...")
        
        # 1. Download Text
        full_text = await pdf_service.extract_text_from_url(p_info["url"])
        
        if not full_text:
            print("FAILED to download/extract text.")
            continue
            
        print(f"Extracted {len(full_text)} chars.")
        
        # 2. Extract Affiliations
        # Create dummy paper object
        paper = Paper(
            id=p_info["id"],
            title=p_info["title"],
            authors="[]",
            summary_generic="",
            published_at=datetime.now(),
            category_primary="cs.CV",
            all_categories="[]",
            pdf_url=p_info["url"]
        )
        
        aff_data = await llm.extract_affiliations(paper, full_text)
        
        if aff_data:
            print("--- Extraction Result ---")
            print(f"Main Affiliation: {aff_data.main_affiliation}")
            print(f"Main Company: {aff_data.main_company}")
            print(f"Main University: {aff_data.main_university}")
            print(f"All: {aff_data.affiliations}")
        else:
            print("FAILED to extract affiliations.")

@pytest.mark.skip(reason="Integration test: requires network access and OpenAI API key. Run manually via __main__.")
def test_affiliation_extraction():
    asyncio.run(_run_affiliation_extraction())

if __name__ == "__main__":
    asyncio.run(_run_affiliation_extraction())

