import fitz
import os
import logging
from ingestion.cleaner import TextCleaner

logger = logging.getLogger(__name__)

class PDFParser:
    """
    Layout-aware PDF parser using PyMuPDF's dictionary API.
    Extracts text blocks with font metadata (size, boldness) for 
    downstream section detection.
    """
    
    def __init__(self, use_ocr: bool = False):
        self.use_ocr = use_ocr
        self.cleaner = TextCleaner()
        if self.use_ocr:
            try:
                from paddleocr import PaddleOCR
                self.ocr = PaddleOCR(use_angle_cls=True, lang='en')
            except ImportError:
                logger.warning("PaddleOCR not available. OCR fallback disabled.")
                self.use_ocr = False

    def parse(self, pdf_path: str) -> list[dict]:
        """
        Parses a PDF and returns a list of pages, each containing layout elements
        with font metadata for section detection.
        
        Each element has:
          - type: "Header" or "NarrativeText"
          - text: cleaned text content
          - font_size: dominant font size of the block
          - is_bold: whether the block uses a bold font
        """
        parsed_pages = []
        doc = fitz.open(pdf_path)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            fitz_text = page.get_text()
            
            # Heuristic: if very little text, page might be scanned
            is_scanned = len(fitz_text.strip()) < 50
            
            if is_scanned and self.use_ocr:
                logger.info(f"Page {page_num+1}: scanned page detected, running OCR...")
                ocr_text = self._ocr_page(page)
                paragraphs = [p.strip() for p in ocr_text.split("\n\n") if p.strip()]
                elements = []
                for p in paragraphs:
                    cleaned = self.cleaner.clean_element(p)
                    if cleaned and not self.cleaner.is_noise(cleaned):
                        elements.append({
                            "type": "NarrativeText",
                            "text": cleaned,
                            "font_size": 10.0,  # default for OCR
                            "is_bold": False
                        })
                parsed_pages.append({
                    "page_num": page_num + 1,
                    "elements": elements,
                    "raw_text": ocr_text
                })
            else:
                elements = self._extract_elements_with_fonts(page)
                parsed_pages.append({
                    "page_num": page_num + 1,
                    "elements": elements,
                    "raw_text": fitz_text
                })
        
        doc.close()
        logger.info(f"Parsed {len(parsed_pages)} pages from {os.path.basename(pdf_path)}")
        return parsed_pages

    def _extract_elements_with_fonts(self, page) -> list[dict]:
        """
        Extracts text blocks from a page using PyMuPDF dict API.
        Returns elements with font metadata for section detection.
        """
        page_dict = page.get_text("dict")
        elements = []
        
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            
            # Collect all spans in this block to determine dominant font properties
            spans_data = []
            full_text_parts = []
            
            for line in block.get("lines", []):
                line_text_parts = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    if span_text.strip():
                        spans_data.append({
                            "text": span_text,
                            "size": span.get("size", 10.0),
                            "font": span.get("font", ""),
                            "char_count": len(span_text.strip())
                        })
                        line_text_parts.append(span_text)
                if line_text_parts:
                    full_text_parts.append("".join(line_text_parts))
            
            text = " ".join(full_text_parts).strip()
            
            if not text:
                continue
            
            # Clean the text
            cleaned = self.cleaner.clean_element(text)
            if not cleaned or self.cleaner.is_noise(cleaned):
                continue
            
            # Determine dominant font size (weighted by character count)
            if spans_data:
                total_chars = sum(s["char_count"] for s in spans_data)
                if total_chars > 0:
                    weighted_size = sum(s["size"] * s["char_count"] for s in spans_data) / total_chars
                else:
                    weighted_size = 10.0
                
                # Check if any significant portion is bold
                bold_chars = sum(
                    s["char_count"] for s in spans_data 
                    if "bold" in s["font"].lower() or "black" in s["font"].lower()
                )
                is_bold = bold_chars > (total_chars * 0.5)  # >50% bold
            else:
                weighted_size = 10.0
                is_bold = False
            
            # Classify element type based on font properties
            is_header = (
                (weighted_size > 11.5 or is_bold) and 
                len(cleaned) < 200 and
                len(cleaned.split('\n')) <= 3  # headers are short
            )
            
            elements.append({
                "type": "Header" if is_header else "NarrativeText",
                "text": cleaned,
                "font_size": round(weighted_size, 1),
                "is_bold": is_bold
            })
        
        return elements

    def _ocr_page(self, page) -> str:
        """OCR fallback for scanned pages."""
        pix = page.get_pixmap()
        temp_img_path = f"temp_ocr_page_{page.number}.png"
        pix.save(temp_img_path)
        
        result = self.ocr.ocr(temp_img_path, cls=True)
        page_text = ""
        if result and result[0]:
            for line in result[0]:
                text = line[1][0]
                page_text += text + "\n"
        
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)
        
        return page_text.strip()
