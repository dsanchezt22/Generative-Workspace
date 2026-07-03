"""R-211: server-side text extraction so document uploads ground generation on
EVERY provider (not just Gemini's native multimodal path)."""

import os

from src.services import extract

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_txt_decodes_utf8():
    assert extract.text_from_file(b"hello world", "text/plain") == "hello world"


def test_csv_decodes():
    assert extract.text_from_file(b"a,b\n1,2", "text/csv") == "a,b\n1,2"


def test_markdown_decodes():
    assert extract.text_from_file(b"# Title\nbody", "text/markdown") == "# Title\nbody"


def test_invalid_utf8_is_replaced_not_raised():
    """errors="replace" — a byte that isn't valid UTF-8 must not raise; the rest
    of the content is still usable."""
    data = b"caf" + b"\xe9" + b" latte"
    result = extract.text_from_file(data, "text/plain")
    assert result is not None
    assert "caf" in result
    assert "latte" in result


def test_unsupported_mime_returns_none():
    assert extract.text_from_file(b"binary junk", "application/octet-stream") is None


def test_empty_after_strip_returns_none():
    assert extract.text_from_file(b"   \n\t  ", "text/plain") is None


def test_truly_empty_returns_none():
    assert extract.text_from_file(b"", "text/plain") is None


def test_oversized_text_is_capped_at_20000_chars():
    big = ("x" * 25_000).encode("utf-8")
    result = extract.text_from_file(big, "text/plain")
    assert result is not None
    assert len(result) <= 20_000


def test_pdf_extracts_text_from_fixture():
    """backend/tests/fixtures/tiny.pdf is a hand-built one-page PDF whose content
    stream draws the literal text "Trus fixture" (see scratch generator in the
    Task 5 report — pypdf's writer can't easily embed text, so the fixture is a
    checked-in binary built from raw PDF object syntax)."""
    with open(os.path.join(_FIXTURE_DIR, "tiny.pdf"), "rb") as f:
        data = f.read()
    result = extract.text_from_file(data, "application/pdf")
    assert result is not None
    assert "Trus fixture" in result


def test_pdf_garbage_bytes_returns_none():
    assert extract.text_from_file(b"not actually a pdf", "application/pdf") is None


def test_filename_argument_is_accepted_and_ignored_for_decoding():
    # filename is informational only; decoding is driven by mime.
    assert extract.text_from_file(b"hi", "text/plain", filename="notes.txt") == "hi"
