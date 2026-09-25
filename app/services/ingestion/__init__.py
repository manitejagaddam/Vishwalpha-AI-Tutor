"""
app/services/ingestion/__init__.py
──────────────────────────────────
Public surface of the ingestion package.

Import IngestionPipeline from here — do not import directly from sub-modules.
"""
from app.services.ingestion.pipeline import IngestionPipeline

__all__ = ["IngestionPipeline"]
