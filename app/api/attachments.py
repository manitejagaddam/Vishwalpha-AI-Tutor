"""
app/api/attachments.py
───────────────────────
Endpoints for uploading student attachments (diagrams, math homework, textbook photos, PDFs).
Performs vision analysis on images and returns rich metadata for inclusion in chat turns.
"""
import logging
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_current_user
from app.data.models.platform import User
from app.services.attachment_service import save_and_analyze_attachment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/attachments", tags=["Attachments"])


class AttachmentResponse(BaseModel):
    attachment_id: str
    filename: str
    content_type: str
    url: str
    extracted_text: Optional[str] = ""
    description: Optional[str] = ""
    topic_hint: Optional[str] = ""
    base64_thumbnail: Optional[str] = None


@router.post("/upload", response_model=AttachmentResponse)
async def upload_attachment(
    file: UploadFile = File(...),
    student: User = Depends(get_current_user),
):
    """
    Upload an attachment (image or PDF) for curriculum inquiry.
    Processes images with Multimodal Vision (transcribing text, math, and diagrams)
    and returns metadata ready to attach to ChatRequest.
    """
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        metadata = save_and_analyze_attachment(
            file_bytes=file_bytes,
            filename=file.filename or "attachment",
            content_type=file.content_type or "application/octet-stream",
            user_id=str(student.id),
        )

        return AttachmentResponse(**metadata)

    except ValueError as val_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(val_err),
        )
    except Exception as exc:
        logger.error(f"Attachment upload failed: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process and analyze attachment.",
        )
