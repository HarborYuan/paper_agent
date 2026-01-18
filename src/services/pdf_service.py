import httpx
import io
from typing import Optional
from pypdf import PdfReader

class PDFService:
    def __init__(self):
        self.headers = {
            "User-Agent": "PaperAgent/0.1.0 (mailto:your-email@example.com)"
        }

    async def extract_text_from_url(self, pdf_url: str) -> Optional[str]:
        """
        Download PDF from URL and extract text.
        """
        # arXiv PDF URLs usually work directly, but sometimes need to change /abs/ to /pdf/
        # stored URL in Paper model usually comes from `link.href` which for application/pdf type is correct.
        
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                print(f"Downloading PDF: {pdf_url}")
                response = await client.get(pdf_url, headers=self.headers, timeout=30.0)
                response.raise_for_status()
                pdf_bytes = response.content
                
                reader = PdfReader(io.BytesIO(pdf_bytes))
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
                
                return text.strip()
        except Exception as e:
            print(f"Error extracting PDF text from {pdf_url}: {e}")
            return None

pdf_service = PDFService()
