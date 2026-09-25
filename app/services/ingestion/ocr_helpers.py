"""
app/services/ingestion/ocr_helpers.py
───────────────────────────────────────
Stage 6 (partial): OCR and paddlex image analysis helpers.

Responsibilities:
  - Lazy-load the paddlex layout pipeline (singleton).
  - Convert PDF pages to PIL images (PyMuPDF → pdf2image fallback).
  - Run Tesseract OCR with per-word confidence scoring.
  - Run Tesseract in math-PSM mode for equation regions.
  - Run Tesseract in table mode → markdown table.
  - Run paddlex layout detection on a page image.

Nothing in this module touches the database.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile

from app.services.ingestion.models import PageBlock

logger = logging.getLogger(__name__)

# ── paddlex singleton ─────────────────────────────────────────────────────────

_LAYOUT_PIPELINE = None
_PADDLEX_OK: bool | None = None


def get_layout_pipeline():
    """Lazy-loads the paddlex layout_parsing pipeline (one per process)."""
    global _LAYOUT_PIPELINE, _PADDLEX_OK
    if _PADDLEX_OK is not None:
        return _LAYOUT_PIPELINE
    try:
        from paddlex import create_pipeline  # type: ignore
        _LAYOUT_PIPELINE = create_pipeline(pipeline="layout_parsing")
        _PADDLEX_OK = True
        logger.info("[Ingestion] paddlex layout_parsing loaded.")
    except Exception as exc:
        logger.warning(f"[Ingestion] paddlex unavailable ({exc}); using heuristic mode.")
        _PADDLEX_OK = False
    return _LAYOUT_PIPELINE


# ── Label normalisation ───────────────────────────────────────────────────────

_LABEL_MAP = {
    "title": "heading", "heading": "heading", "section_heading": "heading",
    "text": "text", "paragraph": "text",
    "table": "table", "table_caption": "text",
    "figure": "figure_ref", "figure_caption": "text",
    "formula": "equation", "equation": "equation",
    "header": "header_footer", "footer": "header_footer",
    "page_number": "header_footer",
}


def map_label(label: str) -> str:
    return _LABEL_MAP.get(label.lower(), "text")


# ── Image helpers ─────────────────────────────────────────────────────────────

def page_to_image(pdf_path: str, page_number: int):
    """
    Converts one PDF page to a PIL Image at 300 DPI.
    Tries PyMuPDF first, falls back to pdf2image.
    Returns None on failure.
    """
    try:
        import fitz  # type: ignore
        import io
        from PIL import Image
        doc = fitz.open(pdf_path)
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=300)
        return Image.open(io.BytesIO(pix.tobytes("png")))
    except ImportError:
        pass
    except Exception as exc:
        logger.debug(f"[Ingestion] PyMuPDF page_to_image p{page_number} failed: {exc}")

    try:
        from pdf2image import convert_from_path  # type: ignore
        imgs = convert_from_path(
            pdf_path, first_page=page_number, last_page=page_number, dpi=300
        )
        return imgs[0] if imgs else None
    except ImportError:
        logger.warning("[Ingestion] pdf2image missing. Run: uv add pdf2image Pillow")
    except Exception as exc:
        logger.warning(f"[Ingestion] page_to_image p{page_number}: {exc}")
    return None


def crop(img, coords: list):
    """Crops a PIL image to the bounding box described by coords."""
    if not coords or len(coords) < 4:
        return None
    try:
        if isinstance(coords[0], list):
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            box = (min(xs), min(ys), max(xs), max(ys))
        else:
            box = tuple(coords[:4])
        return img.crop(box)
    except Exception:
        return None


# ── OCR helpers ───────────────────────────────────────────────────────────────

def ocr_with_confidence(img) -> tuple[str, float | None]:
    """
    Runs Tesseract OCR and returns (text, avg_confidence).
    Returns ("", None) when pytesseract is unavailable or errors.
    """
    try:
        import pytesseract  # type: ignore
        data  = pytesseract.image_to_data(img, lang="eng",
                                          output_type=pytesseract.Output.DICT)
        confs = [int(c) for c in data["conf"] if int(c) >= 0]
        text  = pytesseract.image_to_string(img, lang="eng")
        avg   = round(sum(confs) / len(confs), 1) if confs else None
        return text, avg
    except ImportError:
        logger.warning("[Ingestion] pytesseract missing. Run: uv add pytesseract")
    except Exception as exc:
        logger.debug(f"[Ingestion] OCR error: {exc}")
    return "", None


def ocr_math(img) -> tuple[str, float | None]:
    """OCR optimised for equation regions — PSM 6 + common character fixes."""
    try:
        import pytesseract  # type: ignore
        text = pytesseract.image_to_string(img, lang="eng", config="--psm 6 --oem 3")
        _, conf = ocr_with_confidence(img)
        # Common math OCR corrections
        text = re.sub(r"\bl\b", "1", text)
        text = re.sub(r"\bO\b(?=\d)", "0", text)
        text = re.sub(r"(\d)\s*x\s*(\d)", r"\1x\2", text)
        return text.strip(), conf
    except Exception:
        return "", None


def ocr_table(img) -> str:
    """OCR a table region and format as a markdown table."""
    try:
        import pytesseract  # type: ignore
        data  = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT, config="--psm 6"
        )
        lines: dict[int, list[str]] = {}
        for j, word in enumerate(data["text"]):
            if word.strip() and int(data["conf"][j]) > 30:
                lines.setdefault(data["line_num"][j], []).append(word)
        if not lines:
            return ""
        rows = [" | ".join(ws) for ws in lines.values()]
        if len(rows) > 1:
            rows.insert(
                1,
                " | ".join(["---"] * max(len(r.split(" | ")) for r in rows[:1]))
            )
        return "\n".join(rows)
    except Exception:
        return ""


def looks_like_equation(text: str) -> bool:
    """Heuristic: true if the string looks like a math/chemistry equation."""
    math_chars = set("=+\u2212-*/^\u222b\u2211\u220f\u221a\u221e"
                     "\u03b1\u03b2\u03b3\u03c0\u00d7\u00f7\u2264\u2265\u2260\u00b1")
    return len(set(text) & math_chars) >= 2 and len(text) < 200


# ── paddlex image analysis ────────────────────────────────────────────────────

def paddlex_analyse_image(
    img, page_num: int, pipeline
) -> tuple[list[PageBlock], float | None]:
    """
    Runs paddlex layout detection on a PIL image, then OCRs each detected region.
    Returns (blocks, avg_confidence).
    """
    blocks: list[PageBlock] = []
    confs:  list[float]     = []

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        img.save(tmp.name, "JPEG", quality=95)
        tmp_path = tmp.name

    try:
        for res in pipeline.predict(tmp_path, batch_size=1):
            res_dict = res.to_json() if hasattr(res, "to_json") else {}
            for box in res_dict.get("boxes", []):
                label  = box.get("label", "text").lower()
                btype  = map_label(label)
                if btype == "header_footer":
                    continue
                coords = box.get("coordinate", [])
                region = crop(img, coords)
                if region is None:
                    continue
                if btype == "table":
                    text = ocr_table(region)
                    conf = None
                elif btype == "equation":
                    text, conf = ocr_math(region)
                else:
                    text, conf = ocr_with_confidence(region)

                if conf is not None:
                    confs.append(conf)
                if text.strip():
                    blocks.append(PageBlock(btype, text, page_num, conf))
    finally:
        os.unlink(tmp_path)

    avg = round(sum(confs) / len(confs), 1) if confs else None
    return blocks, avg
