"""Optional OCR ground-truth text (Phase 2). Lazy + env-gated: returns "" unless
TRUS_CAPTURE_OCR=on and RapidOCR is installed, so the default install/tests never
need the extra dependency."""
from __future__ import annotations

import os


def ocr_enabled() -> bool:
    return os.environ.get("TRUS_CAPTURE_OCR", "off").strip().lower() in ("on", "1", "true", "yes")


def ocr_text(png_bytes: bytes) -> str:
    """Exact on-screen text (joined) so the VLM doesn't invent labels. Best-effort:
    any failure (dependency missing, runtime error) degrades to ""."""
    if not ocr_enabled():
        return ""
    try:  # pragma: no cover - exercised only when RapidOCR is installed
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        engine = RapidOCR()
        result, _ = engine(png_bytes)
        if not result:
            return ""
        return " ".join(line[1] for line in result if len(line) > 1)
    except Exception:  # pragma: no cover
        return ""
