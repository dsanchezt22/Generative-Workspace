import json
import os
from typing import Optional

from dotenv import load_dotenv

from src.schema import LLMError

load_dotenv()

_client = None

DEFAULT_MODEL = "gemini-flash-latest"


def _is_stub_key(key: str | None) -> bool:
    return not key or key.startswith("stub-") or key == "your_key_here"


def is_stub_mode() -> bool:
    return _is_stub_key(os.environ.get("GEMINI_API_KEY"))


def _stub_module_for(prompt: str) -> str:
    """Canned ModuleConfig for dev when no real Gemini key is set.

    Lets the full pipeline (frontend → backend → orchestrator → renderer) be
    exercised locally without burning real LLM credits or needing an API key.
    Routes the prompt to an intent-appropriate template so different prompts
    produce genuinely different modules (see stub_templates.py).
    """
    from src.stub_templates import pick_template

    return json.dumps(pick_template(prompt))


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def generate(prompt: str, system: Optional[str] = None) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if _is_stub_key(key):
        return _stub_module_for(prompt)

    from google.genai import types

    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
    except Exception as e:  # network, quota (429), auth — surfaced cleanly upstream
        raise LLMError(str(e)) from e

    text = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text


def generate_from_file(user_message: str, system: Optional[str], data: bytes, mime: str) -> str:
    """Multimodal generation: send a document/image plus instructions to Gemini."""
    key = os.environ.get("GEMINI_API_KEY")
    if _is_stub_key(key):
        # Offline: callers fall back to keyword templates; signal with empty JSON object.
        return "{}"

    from google.genai import types

    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                user_message,
            ],
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
    except Exception as e:
        raise LLMError(str(e)) from e

    text = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text
