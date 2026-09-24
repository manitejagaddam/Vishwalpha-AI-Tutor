"""
app/services/attachment_service.py
───────────────────────────────────
Handles student attachment uploads (images, homework photos, diagrams, PDFs).
Performs Multimodal Vision analysis via Azure OpenAI GPT-4.1-mini to transcribe
math equations, question text, diagram labels, and extract visual descriptions.
"""
import os
import uuid
import base64
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from app.config import settings
from app.infra.azure_openai_client import get_openai

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("uploads/attachments")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

ALLOWED_DOC_TYPES = {
    "application/pdf": ".pdf",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


def save_and_analyze_attachment(
    file_bytes: bytes,
    filename: str,
    content_type: str,
    user_id: str,
) -> Dict[str, Any]:
    """
    Saves an uploaded file to uploads/attachments/ and analyzes it.
    If image: calls Azure OpenAI Vision to extract text and describe diagrams.
    If PDF: extracts text content.
    Returns metadata dict for insertion into ChatRequest and MessageContentBlock.
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError("File exceeds maximum allowed size of 10MB.")

    ext = ALLOWED_IMAGE_TYPES.get(content_type) or ALLOWED_DOC_TYPES.get(content_type)
    if not ext:
        # Fallback to extension from filename
        suffix = Path(filename).suffix.lower()
        if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = suffix
            content_type = f"image/{suffix.lstrip('.')}"
        elif suffix == ".pdf":
            ext = ".pdf"
            content_type = "application/pdf"
        else:
            raise ValueError(f"Unsupported file type: {content_type}. Please upload an image (PNG, JPG, WEBP) or PDF.")

    attachment_id = str(uuid.uuid4())
    safe_filename = f"{attachment_id}{ext}"
    dest_path = UPLOAD_DIR / safe_filename

    # Write file to disk
    with open(dest_path, "wb") as f:
        f.write(file_bytes)

    extracted_text = ""
    description = ""
    topic_hint = ""
    base64_thumbnail = None

    if content_type.startswith("image/"):
        b64_encoded = base64.b64encode(file_bytes).decode("utf-8")
        data_url = f"data:{content_type};base64,{b64_encoded}"
        base64_thumbnail = data_url if len(b64_encoded) < 200_000 else None

        try:
            client = get_openai()
            system_prompt = (
                "You are an expert NCERT Indian curriculum tutor analyzing an image uploaded by a student (Classes 6-12).\n"
                "Extract all learning information thoroughly:\n"
                "1. Transcribe any question text, math problems, equations, textbook paragraphs, or question numbers verbatim.\n"
                "2. Provide a clear, precise visual description of any diagrams, charts, circuit diagrams, geometric shapes, or biological drawings.\n"
                "3. Provide a brief subject/topic hint (e.g. 'Class 10 Science - Chemical Reactions' or 'Class 9 Math - Triangles').\n"
                "Respond ONLY with a valid JSON object formatted as:\n"
                "{\n"
                '  "extracted_text": "<transcribed questions/equations/text>",\n'
                '  "description": "<visual description of diagram/labels>",\n'
                '  "topic_hint": "<detected subject or topic>"\n'
                "}"
            )

            res = client.chat.completions.create(
                model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Analyze this student image attachment."},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                max_tokens=800,
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            content = res.choices[0].message.content or "{}"
            parsed = json.loads(content)
            extracted_text = parsed.get("extracted_text", "")
            description = parsed.get("description", "")
            topic_hint = parsed.get("topic_hint", "")

        except Exception as exc:
            logger.warning(f"Multimodal vision analysis failed: {exc}", exc_info=True)
            description = f"Image attachment ({filename})"

    elif content_type == "application/pdf":
        try:
            import pypdf
            import io
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text_pages = [page.extract_text() or "" for page in reader.pages[:5]]
            extracted_text = "\n".join(text_pages).strip()
            description = f"PDF document ({len(reader.pages)} pages)"
            topic_hint = "Document analysis"
        except Exception as exc:
            logger.warning(f"PDF text extraction failed: {exc}")
            description = f"PDF attachment ({filename})"

    url_path = f"/uploads/attachments/{safe_filename}"

    return {
        "attachment_id": attachment_id,
        "filename": filename,
        "content_type": content_type,
        "url": url_path,
        "extracted_text": extracted_text,
        "description": description,
        "topic_hint": topic_hint,
        "base64_thumbnail": base64_thumbnail,
    }
