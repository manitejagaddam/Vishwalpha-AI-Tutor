"""
app/api/admin.py
────────────────
Admin routes (e.g. data ingestion).
Protected by a static ADMIN_API_KEY from environment variables.
"""
import os
import tempfile
import shutil
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form

from app.schemas import IngestRequest, IngestResponse, IngestLogResponse
from app.api.deps import verify_admin_key
from app.data.database import managed_session
from app.data.models.content import BookIngestionLog, Book

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_pdf(
    file: UploadFile = File(...),
    board_name: str = Form(...),
    class_num: int = Form(...),
    subject_name: str = Form(...),
    book_title: str = Form(...),
    book_natural_key: str = Form(...),
    chapter_title: str = Form(...),
    chapter_number: int = Form(...),
    _=Depends(verify_admin_key),
):
    """
    Ingests a textbook PDF chapter into the curriculum database.
    Requires X-Admin-Key header.
    """
    from app.services.ingestion_pipeline import IngestionPipeline
    pipeline = IngestionPipeline()
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        result = pipeline.process_pdf(
            pdf_path=temp_path,
            board_name=board_name,
            class_num=class_num,
            subject_name=subject_name,
            book_title=book_title,
            book_natural_key=book_natural_key,
            chapter_title=chapter_title,
            chapter_number=chapter_number,
        )
        return IngestResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/ingestion-log", response_model=list[IngestLogResponse])
def get_ingestion_log(
    book_natural_key: str | None = None,
    status: str | None = None,
    limit: int = 50,
    _=Depends(verify_admin_key),
):
    """
    Returns recent ingestion log entries.
    Filter by book_natural_key and/or status.
    Newest first, max 50 by default.
    """
    with managed_session() as db:
        q = db.query(
            BookIngestionLog.id,
            BookIngestionLog.book_id,
            Book.natural_key.label("book_natural_key"),
            BookIngestionLog.chapter_number,
            BookIngestionLog.pdf_hash,
            BookIngestionLog.status,
            BookIngestionLog.ingestion_confidence,
            BookIngestionLog.coverage,
            BookIngestionLog.error,
            BookIngestionLog.ingested_at,
            BookIngestionLog.finished_at,
        ).join(Book, BookIngestionLog.book_id == Book.id)

        if book_natural_key:
            q = q.filter(Book.natural_key == book_natural_key)
        if status:
            q = q.filter(BookIngestionLog.status == status)
            
        rows = q.order_by(BookIngestionLog.ingested_at.desc()).limit(limit).all()
        
        return [
            IngestLogResponse(
                id=r.id,
                book_id=r.book_id,
                book_natural_key=r.book_natural_key,
                chapter_number=r.chapter_number,
                pdf_hash=r.pdf_hash,
                status=r.status,
                ingestion_confidence=r.ingestion_confidence,
                coverage=r.coverage,
                error=r.error,
                ingested_at=r.ingested_at,
                finished_at=r.finished_at,
            )
            for r in rows
        ]

