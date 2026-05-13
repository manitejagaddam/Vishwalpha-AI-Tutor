import re
import logging

logger = logging.getLogger(__name__)

class TextCleaner:
    """
    Deterministic text cleaning for NCERT textbook PDFs.
    Handles 90%+ of noise without needing any LLM calls.
    """
    
    # Common NCERT page footer patterns (chapter title + page number)
    FOOTER_PATTERNS = [
        r'(?m)^\s*(?:Reprint\s+\d{4}[-–]\d{2,4})\s*$',           # "Reprint 2026-27"
        r'(?m)^\s*Science\s+\d+\s*$',                              # "Science 2", "Science 14"
        r'(?m)^\s*[A-Z][a-z]+(?:\s+[A-Za-z]+)*\s+\d{1,3}\s*$',   # "Chemical Reactions and Equations 7"
        r'(?m)^\s*\d{1,3}\s*$',                                    # Standalone page numbers
        r'(?m)^\s*CHAPTER\s*$',                                    # Standalone "CHAPTER"
    ]
    
    def __init__(self):
        self._footer_re = [re.compile(p) for p in self.FOOTER_PATTERNS]
    
    def clean(self, text: str) -> str:
        """Full cleaning pipeline for raw extracted text."""
        text = self._remove_footers(text)
        text = self._fix_broken_hyphens(text)
        text = self._normalize_whitespace(text)
        return text.strip()
    
    def clean_element(self, text: str) -> str:
        """Light cleaning for individual layout elements (preserves structure)."""
        text = self._dedup_repeated_text(text)
        text = self._remove_footers(text)
        text = self._fix_broken_hyphens(text)
        text = self._normalize_whitespace(text)
        return text.strip()
    
    def _dedup_repeated_text(self, text: str) -> str:
        """
        Fix NCERT PDF overlay issue where text is repeated/fragmented.
        E.g. '1.1 CHEMICAL EQUA AL EQUA AL EQUATIONS TIONS TIONS'
        → '1.1 CHEMICAL EQUATIONS'
        """
        import re
        
        # Check for repeated section number patterns like "1.1 ... 1.1 ... 1.1 ..."
        section_match = re.match(r'^(\d+\.\d+(?:\.\d+)?)\s', text)
        if section_match:
            section_num = section_match.group(1)
            escaped = re.escape(section_num)
            occurrences = list(re.finditer(escaped, text))
            if len(occurrences) > 1:
                # Take text from the LAST occurrence onwards
                last_start = occurrences[-1].start()
                text = text[last_start:]
            
            # Now clean up fragmented suffixes in the remaining text
            # Pattern: "CHEMICAL EQUA AL EQUA AL EQUATIONS TIONS TIONS"
            # Strategy: remove words that are just fragments (uppercase, <5 chars)
            # followed by repeated copies of the same fragment
            words = text.split()
            if len(words) > 2:
                cleaned_words = [words[0]]  # keep section number
                i = 1
                seen_fragments = set()
                while i < len(words):
                    word = words[i]
                    # Skip if this word is a short uppercase fragment that repeats
                    if (word.isupper() and len(word) <= 5 and 
                        i + 1 < len(words) and 
                        word in seen_fragments):
                        i += 1
                        continue
                    seen_fragments.add(word)
                    cleaned_words.append(word)
                    i += 1
                text = ' '.join(cleaned_words)
        
        # Handle repeated Activity labels like "Activity 1.1 Activity 1.1 Activity 1.1"
        activity_match = re.match(r'^(Activity\s+\d+\.\d+)\s+\1', text)
        if activity_match:
            text = activity_match.group(1)
        
        # Handle repeated generic header text like "HA HA HA HAVE YOU..."
        # Remove stuttering at start
        text = re.sub(r'^(?:(\w{2,5})\s+)+(\1\w+)', r'\2', text)
        
        return text
    
    def _remove_footers(self, text: str) -> str:
        """Remove page footers, reprint notices, standalone page numbers."""
        for pattern in self._footer_re:
            text = pattern.sub('', text)
        return text
    
    def _fix_broken_hyphens(self, text: str) -> str:
        """Fix words broken across lines: 'photo-\\nsynthesis' → 'photosynthesis'."""
        # Pattern: word ending with hyphen, followed by newline and continuation
        text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
        # Also fix mid-line broken hyphens: "photo- synthesis" → "photosynthesis"
        text = re.sub(r'(\w)-\s{2,}(\w)', r'\1\2', text)
        return text
    
    def _normalize_whitespace(self, text: str) -> str:
        """Collapse excessive whitespace while preserving paragraph breaks."""
        # Multiple spaces/tabs → single space
        text = re.sub(r'[ \t]+', ' ', text)
        # 3+ newlines → double newline (paragraph break)
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Remove leading/trailing whitespace on each line
        lines = [line.strip() for line in text.split('\n')]
        return '\n'.join(lines)
    
    def _remove_figure_references(self, text: str) -> str:
        """Remove standalone figure reference lines that add no educational value."""
        # "Figure 1.1 ..." on its own line - keep inline refs, remove standalone
        # Actually, keep figure references as they provide context
        return text
    
    def is_noise(self, text: str) -> bool:
        """Check if a text block is pure noise (should be discarded entirely)."""
        text = text.strip()
        if not text:
            return True
        # Pure page numbers
        if text.isdigit():
            return True
        # Very short fragments that are just noise
        if len(text) < 5 and not any(c.isalpha() for c in text):
            return True
        # Reprint notices
        if re.match(r'^Reprint\s+\d{4}', text):
            return True
        return False
