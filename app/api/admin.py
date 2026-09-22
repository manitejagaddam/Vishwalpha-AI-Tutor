"""
app/api/admin.py
────────────────
Admin routes (e.g. data ingestion).
Protected by a static ADMIN_API_KEY from environment variables.
"""
from fastapi import APIRouter, HTTPException, Depends

from app.schemas import IngestRequest, IngestResponse
from app.services.ingestion_pipeline import IngestionPipeline
from app.api.deps import verify_admin_key

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/ingest", response_model=IngestResponse)
def ingest_pdf(request: IngestRequest, _=Depends(verify_admin_key)):
    """
    Ingests a textbook PDF chapter into the curriculum database.
    Requires X-Admin-Key header.
    """
    pipeline = IngestionPipeline()
    try:
        result = pipeline.process_pdf(
            pdf_path=request.pdf_path,
            board_name=request.board_name,
            class_num=request.class_num,
            subject_name=request.subject_name,
            book_title=request.book_title,
            book_natural_key=request.book_natural_key,
            chapter_title=request.chapter_title,
            chapter_number=request.chapter_number,
        )
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
