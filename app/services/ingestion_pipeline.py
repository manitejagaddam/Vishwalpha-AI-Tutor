"""
app/services/ingestion_pipeline.py
────────────────────────────────────
COMPATIBILITY SHIM — do not add logic here.

The ingestion pipeline has been split into a modular package:
  app/services/ingestion/
    __init__.py          → re-exports IngestionPipeline
    pipeline.py          → orchestrator (17 stages)
    pdf_extractor.py     → stages 0-6: MIME / validation / page analysis
    text_processor.py    → stages 7-10: strip / stitch / sanitise
    structure_detector.py → stage 11: structure detection + quality gate
    db_writer.py         → stages 13-15: upsert helpers + DB write loop
    ocr_helpers.py       → paddlex / Tesseract helpers
    models.py            → shared dataclasses and constants

This shim re-exports IngestionPipeline so existing callers
(admin.py, scripts/ingest.py) continue to work without modification.

Update your imports when convenient:
  BEFORE:  from app.services.ingestion_pipeline import IngestionPipeline
  AFTER:   from app.services.ingestion import IngestionPipeline
"""
from app.services.ingestion import IngestionPipeline  # noqa: F401

__all__ = ["IngestionPipeline"]
