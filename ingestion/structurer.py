import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

# Regex for NCERT section numbering: "1.1", "1.2.1", "1.2.5", etc.
SECTION_NUMBER_RE = re.compile(r'^(\d+\.\d+(?:\.\d+)?)\s+(.+)$')

class TextStructurer:
    """
    Deterministic section detection for NCERT textbook chapters.
    
    Uses two signals to detect topic boundaries:
    1. Section numbering patterns (1.1, 1.2.1, etc.) — most reliable
    2. Font size / bold metadata from the parser — supplementary
    
    Does NOT depend on LLM repair for topic detection.
    """
    
    def __init__(self, max_chunk_chars: int = 800):
        self.max_chunk_chars = max_chunk_chars
    
    def structure(self, parsed_pages: list[dict], repaired_structure: dict = None) -> List[Dict]:
        """
        Walks through all parsed elements and segments them into topics.
        
        Returns a list of:
          {"title": "Topic Name", "section_number": "1.2.1", "chunks": ["...", "..."]}
        """
        # Flatten all elements across pages
        all_elements = []
        for page in parsed_pages:
            all_elements.extend(page.get("elements", []))
        
        if not all_elements:
            logger.warning("No elements found in parsed pages!")
            return []
        
        # Pass 1: Detect section boundaries
        sections = self._detect_sections(all_elements)
        
        logger.info(f"Detected {len(sections)} sections: {[s['title'] for s in sections]}")
        
        # Pass 2: Chunk each section
        result = []
        for section in sections:
            chunks = self._chunk_text(section["content"])
            if chunks:
                result.append({
                    "title": section["title"],
                    "section_number": section.get("section_number", ""),
                    "chunks": chunks
                })
        
        return result
    
    def _detect_sections(self, elements: list[dict]) -> List[Dict]:
        """
        Walks through elements and splits them into sections based on:
        1. Section numbering (1.1, 1.2.1, etc.) in Headers
        2. Large/bold headers that indicate new topics
        """
        sections = []
        current_section = {
            "title": "Introduction",
            "section_number": "",
            "content_parts": []
        }
        
        for el in elements:
            el_type = el.get("type", "")
            el_text = el.get("text", "").strip()
            font_size = el.get("font_size", 10.0)
            is_bold = el.get("is_bold", False)
            
            if not el_text:
                continue
            
            # Check if this element starts a new section
            new_section = self._check_section_boundary(el_text, el_type, font_size, is_bold)
            
            if new_section:
                # Save previous section
                if current_section["content_parts"]:
                    sections.append({
                        "title": current_section["title"],
                        "section_number": current_section["section_number"],
                        "content": "\n\n".join(current_section["content_parts"])
                    })
                
                # Start new section
                current_section = {
                    "title": new_section["title"],
                    "section_number": new_section["section_number"],
                    "content_parts": []
                }
            else:
                # Append to current section content
                current_section["content_parts"].append(el_text)
        
        # Don't forget the last section
        if current_section["content_parts"]:
            sections.append({
                "title": current_section["title"],
                "section_number": current_section["section_number"],
                "content": "\n\n".join(current_section["content_parts"])
            })
        
        # Filter out empty or noise-only sections
        sections = [s for s in sections if len(s["content"].strip()) > 50]
        
        return sections
    
    def _check_section_boundary(self, text: str, el_type: str, font_size: float, is_bold: bool) -> dict | None:
        """
        Determines if a text element represents a new section heading.
        Returns {"title": "...", "section_number": "..."} or None.
        """
        # Strategy 1: Look for NCERT section numbering (most reliable)
        # Match patterns like "1.1 Chemical Equations" or "1.2.1 Combination Reaction"
        match = SECTION_NUMBER_RE.match(text)
        if match:
            section_num = match.group(1)
            section_title = match.group(2).strip()
            # Validate: section title should be reasonably short and look like a heading
            if len(section_title) < 150 and not section_title[0].islower():
                # Clean garbled overlay artifacts from title
                clean_title = self._clean_section_title(section_title)
                return {
                    "title": f"{section_num} {clean_title}",
                    "section_number": section_num
                }
        
        # Strategy 2: Large bold headers that contain "Types of" or other key phrases
        # But ONLY if they are classified as headers by the parser
        if el_type == "Header" and is_bold and font_size > 12.0:
            # Skip known non-section headers
            skip_patterns = [
                r'^Q\s*U\s*E\s*S\s*T\s*I\s*O\s*N',  # "Q U E S T I O N S"
                r'^EXERCISES?$',
                r'^QUESTIONS?$',
                r'^Do\s+You\s+Know',
                r'^Activity\s+\d',
                r'^Figure\s+\d',
                r'^What\s+you\s+have\s+learnt',
                r'^Group\s+Activity',
            ]
            if not any(re.match(p, text, re.IGNORECASE) for p in skip_patterns):
                # Only treat as section if it's short enough to be a heading
                if len(text) < 100:
                    return {
                        "title": text,
                        "section_number": ""
                    }
        
        return None
    
    def _chunk_text(self, content: str) -> List[str]:
        """
        Splits section content into chunks of roughly max_chunk_chars.
        Splits on paragraph boundaries (double newline) first.
        """
        if not content.strip():
            return []
        
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        
        chunks = []
        current_chunk = ""
        
        for para in paragraphs:
            # If adding this paragraph would exceed the limit, save current chunk
            if current_chunk and (len(current_chunk) + len(para) + 2) > self.max_chunk_chars:
                chunks.append(current_chunk.strip())
                current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para
        
        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks
    
    def _clean_section_title(self, title: str) -> str:
        """
        Clean garbled section titles from NCERT PDF overlay rendering.
        
        Example: 'CHEMICAL EQUA AL EQUA AL EQUATIONS TIONS TIONS'
        → 'Chemical Equations'
        
        Strategy: Remove words that are uppercase fragments (<=5 chars, all caps)
        appearing after the first occurrence of a complete word, when they look
        like broken suffixes.
        """
        words = title.split()
        if len(words) <= 2:
            return title.title()  # Short titles are fine, just normalize case
        
        # Detect if this title has fragmented overlay text
        # Indicator: multiple short uppercase words that look like word fragments
        short_upper_count = sum(1 for w in words if w.isupper() and len(w) <= 5)
        
        if short_upper_count >= 2:
            # Build clean title by removing duplicate/fragment words
            cleaned = []
            seen = set()
            for word in words:
                word_lower = word.lower()
                # Skip if it's a short fragment we've already seen or a suffix fragment
                if word.isupper() and len(word) <= 5 and word_lower in seen:
                    continue
                # Skip words that are pure suffixes of words already in cleaned
                is_suffix = False
                for existing in cleaned:
                    if existing.lower().endswith(word_lower) and len(word) < len(existing):
                        is_suffix = True
                        break
                if is_suffix:
                    continue
                    
                seen.add(word_lower)
                cleaned.append(word)
            
            title = ' '.join(cleaned)
        
        # Normalize to title case for consistency
        return title.title()
