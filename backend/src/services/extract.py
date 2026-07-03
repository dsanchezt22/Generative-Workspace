"""Server-side text extraction for document grounding (R-211).

Gemini's native multimodal path can read any file directly, but the stub
provider and openai-compat endpoints (non-image mimes) cannot — without this,
those paths either fabricate a keyword-template result or refuse every upload.
`text_from_file` turns a document's bytes into plain text so the orchestrator
can ground generation in the document's ACTUAL content on every provider by
routing it through the normal text-generation path instead.
"""

from __future__ import annotations

import io

_MAX_PAGES = 30
_MAX_CHARS = 20_000

# text/csv and text/markdown already match the text/* prefix below; some
# clients/browsers send these non-text/* aliases for the same file types.
_EXTRA_TEXT_MIMES = {"application/csv", "application/x-csv"}


def text_from_file(data: bytes, mime: str, filename: str | None = None) -> str | None:
    """Best-effort plain-text extraction. Returns None when the mime is
    unsupported or the extracted text is empty after stripping — callers treat
    None as "could not ground; fall through to the existing behavior"."""
    normalized_mime = (mime or "").split(";")[0].strip().lower()

    text: str | None
    if normalized_mime.startswith("text/") or normalized_mime in _EXTRA_TEXT_MIMES:
        text = data.decode("utf-8", errors="replace")
    elif normalized_mime == "application/pdf":
        text = _pdf_text(data)
        if text is None:
            return None
    else:
        return None

    text = text.strip()
    if not text:
        return None
    return text[:_MAX_CHARS]


def _pdf_text(data: bytes) -> str | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return None

    parts: list[str] = []
    total = 0
    for page in reader.pages[:_MAX_PAGES]:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        if page_text:
            parts.append(page_text)
            total += len(page_text)
        if total >= _MAX_CHARS:
            break
    return "\n".join(parts)
