"""
app/api/admin.py
────────────────
Admin routes (e.g. data ingestion).
Protected by a static ADMIN_API_KEY from environment variables.
"""
from fastapi import APIRouter, HTTPException, Depends, Security
from fastapi.security import APIKeyHeader

from app.config import settings
from app.schemas import IngestRequest, IngestResponse
from app.services.ingestion_pipeline import IngestionPipeline

router = APIRouter(prefix="/admin", tags=["Admin"])
api_key_header = APIKeyHeader(name="X-Admin-Key", auto_error=False)


def verify_admin_key(api_key: str = Security(api_key_header)):
    if not settings.ADMIN_API_KEY:
        # If no key is configured in .env, lock the endpoint entirely
        raise HTTPException(
            status_code=403, detail="Admin API key not configured on server."
        )
    if api_key != settings.ADMIN_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Admin API Key")
    return api_key


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
