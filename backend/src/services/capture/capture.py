"""Stage 1 — CAPTURE: screenshot bytes → full-fidelity IR.

Steps 0-3 of the pipeline: preprocess (downscale), optional OCR ground-truth text,
then a vision-model read into a CaptureIR. The vision call goes through
`llm.vision_capture` (local vision endpoint if configured, else Gemini multimodal).
"""

from __future__ import annotations

from src import llm
from src.schema import RefusalError

from . import ocr
from .ir import CaptureIR, IRParseError, parse_ir
from .prompts import CAPTURE_SYSTEM

_MAX_SIDE = 1280


def preprocess(data: bytes, mime: str) -> tuple[bytes, str, dict]:
    """Downscale the longest side to 1280px and normalize to PNG (latency/cost).
    Degrades to the original bytes if Pillow isn't installed."""
    try:  # Pillow is optional — guard so default installs/tests don't require it.
        import io

        from PIL import Image

        img: Image.Image = Image.open(io.BytesIO(data))
        img.load()
        w, h = img.size
        scale = min(1.0, _MAX_SIDE / float(max(w, h))) if max(w, h) else 1.0
        if scale < 1.0:
            new_size: tuple[int, int] = (max(1, int(w * scale)), max(1, int(h * scale)))
            img = img.resize(new_size)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue(), "image/png", {"w": img.size[0], "h": img.size[1]}
    except Exception:
        return data, mime, {}


_RETRY_NOTE = (
    "\n\nYour previous output was not valid JSON. Return ONLY the JSON object, nothing else."
)


def capture_ir(data: bytes, mime: str, use_case_hint: str | None = None) -> CaptureIR:
    """Read the screenshot into a CaptureIR. Raises LLMError (model unavailable) or
    RefusalError (couldn't read a usable layout)."""
    png, png_mime, viewport = preprocess(data, mime)
    ocr_block = ""
    text = ocr.ocr_text(png)
    if text:
        ocr_block = (
            f"\n\nExact on-screen text (OCR, use these strings verbatim for labels):\n{text[:2000]}"
        )

    user = (
        "Capture this screenshot as the IR JSON."
        + (f" It is a {use_case_hint} interface." if use_case_hint else "")
        + ocr_block
    )

    last: Exception | None = None
    for attempt in range(2):  # one retry — VLMs occasionally slip on strict JSON
        raw = llm.vision_capture(
            CAPTURE_SYSTEM, user if attempt == 0 else user + _RETRY_NOTE, png, png_mime
        )
        try:
            ir = parse_ir(raw)
            if viewport and not ir.viewport:
                ir.viewport = viewport
            return ir
        except IRParseError as e:
            last = e
    raise RefusalError(f"Couldn't read a usable layout from that image ({last}).")
