"""LLM access for the orchestrator, behind a small provider abstraction.

Every model call in the app funnels through `generate()` / `generate_from_file()`.
Those dispatch to one of three backends, chosen by environment:

  • "gemini" — Google Gemini (the original cloud path).
  • "openai" — ANY OpenAI-compatible /chat/completions endpoint. This single
               provider covers a LOCAL open-source model (Ollama, llama.cpp
               server, LM Studio, vLLM, SGLang) AND cost-effective hosted
               endpoints (Together, Fireworks, Groq, DeepInfra, OpenRouter…),
               since they all speak the same wire format. No SDK needed —
               we POST with the standard library, so there are zero new deps.
  • "stub"   — offline keyword templates (no network, no cost).

Selection (see `_resolve_provider`): explicit TRUS_LLM_PROVIDER wins; otherwise
a configured TRUS_LLM_BASE_URL → openai, a real GEMINI_API_KEY → gemini, else stub.

Env for the openai provider:
  TRUS_LLM_BASE_URL  e.g. http://localhost:11434/v1   (Ollama)
                     e.g. http://localhost:8000/v1     (vLLM / llama.cpp server)
                     e.g. https://api.together.xyz/v1  (hosted)
  TRUS_LLM_MODEL     e.g. qwen2.5:7b-instruct  /  meta-llama/Llama-3.1-8B-Instruct
  TRUS_LLM_API_KEY   optional; local servers ignore it, hosted ones need it
  TRUS_LLM_JSON_MODE object (default) | schema | off
  TRUS_LLM_TIMEOUT   request timeout seconds (default 60)
"""
import base64
import json
import os
import urllib.error
import urllib.request
from typing import Optional

from dotenv import load_dotenv

from src.schema import LLMError

load_dotenv()

_client = None

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TEMPERATURE = 0.4


def _timeout() -> float:
    try:
        return float(os.environ.get("TRUS_LLM_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _cascade_enabled() -> bool:
    """When a local/hosted endpoint is unreachable, fall back to Gemini (if a key
    is set) and then to offline templates instead of failing the request."""
    return os.environ.get("TRUS_LLM_CASCADE", "on").strip().lower() not in ("off", "0", "false", "no")


def _max_output_tokens() -> int | None:
    raw = os.environ.get("TRUS_LLM_MAX_OUTPUT_TOKENS", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_stub_key(key: str | None) -> bool:
    return not key or key.startswith("stub-") or key == "your_key_here"


def _resolve_provider() -> str:
    """Active backend: explicit override, else auto-detect."""
    p = os.environ.get("TRUS_LLM_PROVIDER", "").strip().lower()
    if p in ("gemini", "openai", "stub"):
        return p
    if os.environ.get("TRUS_LLM_BASE_URL", "").strip():
        return "openai"
    if not _is_stub_key(os.environ.get("GEMINI_API_KEY")):
        return "gemini"
    return "stub"


def is_stub_mode() -> bool:
    """True when no real model is wired — the orchestrator then serves templates."""
    return _resolve_provider() == "stub"


def provider_info() -> dict:
    """Non-secret diagnostics for a status endpoint."""
    p = _resolve_provider()
    info: dict[str, str] = {"provider": p}
    if p == "gemini":
        info["model"] = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    elif p == "openai":
        info["model"] = os.environ.get("TRUS_LLM_MODEL", "")
        info["base_url"] = os.environ.get("TRUS_LLM_BASE_URL", "")
    return info


# ---------------------------------------------------------------- stub -------

def _stub_module_for(prompt: str) -> str:
    """Canned ModuleConfig for offline/dev use (see stub_templates.py)."""
    from src.stub_templates import pick_template

    return json.dumps(pick_template(prompt))


# -------------------------------------------------------------- gemini -------

def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _gemini_config(system: Optional[str]):
    from google.genai import types

    # Static system_instruction + variable text at the tail → Gemini's implicit
    # context caching (automatic on 2.5/3.x) discounts the repeated prefix for free.
    kwargs: dict = {
        "system_instruction": system,
        "response_mime_type": "application/json",
        "temperature": DEFAULT_TEMPERATURE,
    }
    mot = _max_output_tokens()
    if mot:
        kwargs["max_output_tokens"] = mot
    return types.GenerateContentConfig(**kwargs)


def _gemini_generate(prompt: str, system: Optional[str]) -> str:
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        response = _get_client().models.generate_content(
            model=model, contents=prompt, config=_gemini_config(system),
        )
    except Exception as e:  # network, quota (429), auth — surfaced cleanly upstream
        raise LLMError(str(e)) from e
    text = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text


def _gemini_generate_file(user_message: str, system: Optional[str], data: bytes, mime: str) -> str:
    from google.genai import types

    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=data, mime_type=mime), user_message],
            config=_gemini_config(system),
        )
    except Exception as e:
        raise LLMError(str(e)) from e
    text = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text


# ----------------------------------------------- openai-compatible -----------

def _openai_chat(messages: list[dict], schema: Optional[dict] = None, expect_array: bool = False) -> str:
    base = os.environ.get("TRUS_LLM_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("TRUS_LLM_MODEL", "").strip()
    if not base or not model:
        raise LLMError("Set TRUS_LLM_BASE_URL and TRUS_LLM_MODEL to use the openai provider.")
    api_key = os.environ.get("TRUS_LLM_API_KEY", "").strip()

    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": DEFAULT_TEMPERATURE,
        "stream": False,
    }
    mode = os.environ.get("TRUS_LLM_JSON_MODE", "object").strip().lower()
    # json_object forces an object root, which is incompatible with the
    # array-returning decompose path — skip the constraint there and rely on the
    # prompt + validate/retry. Schema-guided decoding is opt-in (servers that
    # support it: vLLM, llama.cpp, recent Ollama).
    if mode == "schema" and schema is not None and not expect_array:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "module_config", "schema": schema, "strict": False},
        }
    elif mode in ("object", "schema") and not expect_array:
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400] if hasattr(e, "read") else ""
        raise LLMError(f"LLM endpoint returned HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"Could not reach the LLM endpoint at {base}: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM endpoint returned non-JSON: {e}") from e

    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected LLM response shape: {str(payload)[:300]}") from e
    if not text or not text.strip():
        raise LLMError("The model returned an empty response.")
    return text


# ------------------------------------------------------------- public --------

def generate(prompt: str, system: Optional[str] = None, *, schema: Optional[dict] = None,
             expect_array: bool = False) -> str:
    provider = _resolve_provider()
    if provider == "stub":
        return _stub_module_for(prompt)
    if provider == "openai":
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            return _openai_chat(messages, schema=schema, expect_array=expect_array)
        except LLMError:
            # Local/hosted endpoint unreachable → degrade gracefully.
            if not _cascade_enabled():
                raise
            if not _is_stub_key(os.environ.get("GEMINI_API_KEY")):
                return _gemini_generate(prompt, system)
            return _stub_module_for(prompt)
    return _gemini_generate(prompt, system)


def generate_from_file(user_message: str, system: Optional[str], data: bytes, mime: str) -> str:
    """Multimodal generation. Gemini handles any file; the openai provider handles
    images (data URL); unsupported inputs return "{}" so callers fall back to templates."""
    provider = _resolve_provider()
    if provider == "stub":
        return "{}"
    if provider == "openai":
        if mime.startswith("image/"):
            b64 = base64.b64encode(data).decode("ascii")
            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": [
                {"type": "text", "text": user_message},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]})
            return _openai_chat(messages, expect_array=True)
        return "{}"  # non-image documents aren't portable across openai-compat servers
    return _gemini_generate_file(user_message, system, data, mime)


# ------------------------------------------------- vision (image → text) -----
# A SEPARATE vision model (the text model may be text-only, e.g. Qwen3-4B). Used
# by the Layout Studio screenshot importer. Config:
#   TRUS_VISION_MODEL     e.g. qwen2.5vl:7b   (required to enable)
#   TRUS_VISION_BASE_URL  defaults to TRUS_LLM_BASE_URL
#   TRUS_VISION_API_KEY   defaults to TRUS_LLM_API_KEY
#   TRUS_VISION_TIMEOUT   seconds (default 180 — image inference is slower)

def vision_available() -> bool:
    return bool(os.environ.get("TRUS_VISION_MODEL", "").strip())


def vision_info() -> dict:
    if not vision_available():
        return {"available": False}
    return {
        "available": True,
        "model": os.environ.get("TRUS_VISION_MODEL", "").strip(),
        "base_url": (os.environ.get("TRUS_VISION_BASE_URL") or os.environ.get("TRUS_LLM_BASE_URL", "")).strip(),
    }


def vision_describe(system: Optional[str], user_text: str, data: bytes, mime: str) -> str:
    """Send an image + instruction to the configured vision model; return its text."""
    model = os.environ.get("TRUS_VISION_MODEL", "").strip()
    base = (os.environ.get("TRUS_VISION_BASE_URL") or os.environ.get("TRUS_LLM_BASE_URL", "")).strip().rstrip("/")
    if not model or not base:
        raise LLMError(
            "No vision model configured. Run a vision model (e.g. `make ollama-vision`) "
            "and set TRUS_VISION_MODEL."
        )
    api_key = (os.environ.get("TRUS_VISION_API_KEY") or os.environ.get("TRUS_LLM_API_KEY", "")).strip()
    try:
        timeout = float(os.environ.get("TRUS_VISION_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0

    b64 = base64.b64encode(data).decode("ascii")
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]})
    body = json.dumps({"model": model, "messages": messages, "temperature": DEFAULT_TEMPERATURE,
                       "stream": False}).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400] if hasattr(e, "read") else ""
        raise LLMError(f"Vision endpoint returned HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"Could not reach the vision endpoint at {base}: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"Vision endpoint returned non-JSON: {e}") from e
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected vision response shape: {str(payload)[:300]}") from e
    if not text or not text.strip():
        raise LLMError("The vision model returned an empty response.")
    return text


def vision_capture(system: Optional[str], user_text: str, data: bytes, mime: str) -> str:
    """Image → text for the capture engine, choosing the right backend:
      1. a dedicated LOCAL vision endpoint (TRUS_VISION_MODEL) if configured, else
      2. Gemini multimodal (when a real GEMINI_API_KEY is set).
    On hardware where the local vision path is unreliable (e.g. AMD RDNA2 on bare
    Windows) leave TRUS_VISION_MODEL unset so capture uses Gemini. Raises LLMError
    when no vision backend is available."""
    if vision_available():
        return vision_describe(system, user_text, data, mime)
    if not _is_stub_key(os.environ.get("GEMINI_API_KEY")):
        return _gemini_generate_file(user_text, system, data, mime)
    raise LLMError(
        "No vision backend available. Set TRUS_VISION_MODEL (local vision endpoint) "
        "or GEMINI_API_KEY (cloud) to capture screenshots."
    )
