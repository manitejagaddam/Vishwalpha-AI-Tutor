"""
app/api/admin.py
────────────────
Admin routes (e.g. data ingestion).
Protected by a static ADMIN_API_KEY from environment variables.
"""
from fastapi import APIRouter, HTTPException, Depends

from app.config import settings
from app.schemas import IngestRequest, IngestResponse
from app.services.ingestion_pipeline import IngestionPipeline
from app.api.deps import verify_admin_key

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/ingest", response_model=IngestResponse)
def ingest_pdf(request: IngestRequest, _=Depends(verify_admin_key)):
    """
    Ingests a textbook PDF into the curriculum database.
    Requires X-Admin-Key header.
    """
    pipeline = IngestionPipeline()
    try:
        result = pipeline.process_pdf(
            pdf_path=request.pdf_path,
            class_num=request.class_num,
            subject=request.subject,
            chapter=request.chapter,
        )
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
