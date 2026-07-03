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
import contextvars
import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from dotenv import load_dotenv

from src.schema import LLMError

load_dotenv()

_client = None

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TEMPERATURE = 0.4


@dataclass
class GenResult:
    text: str
    provider: str
    model: str
    degraded: bool = False
    tokens_in: int | None = None
    tokens_out: int | None = None


last_call: contextvars.ContextVar[GenResult | None] = contextvars.ContextVar(
    "llm_last_call", default=None
)


def _gemini_model() -> str:
    """The configured Gemini model, read fresh per call (single source — was
    duplicated as `os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)` at every
    gemini call site)."""
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def _timeout() -> float:
    try:
        return float(os.environ.get("TRUS_LLM_TIMEOUT", "60"))
    except ValueError:
        return 60.0


def _cascade_enabled() -> bool:
    """When a local/hosted endpoint is unreachable, fall back to Gemini (if a key
    is set) and then to offline templates instead of failing the request."""
    return os.environ.get("TRUS_LLM_CASCADE", "on").strip().lower() not in (
        "off",
        "0",
        "false",
        "no",
    )


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
        info["model"] = _gemini_model()
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


def _gemini_config(system: str | None):
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


def _gemini_generate(prompt: str, system: str | None) -> str:
    model = _gemini_model()
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=prompt,
            config=_gemini_config(system),
        )
    except Exception as e:  # network, quota (429), auth — surfaced cleanly upstream
        raise LLMError(str(e)) from e
    text: str | None = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text


def _gemini_generate_file_raw(
    user_message: str, system: str | None, data: bytes, mime: str
) -> tuple[str, object]:
    """Same call as `_gemini_generate_file`, but also returns the raw SDK
    response object so `generate_from_file` can read `usage_metadata` for
    telemetry (R-1201/R-1202) without re-issuing the request."""
    from google.genai import types

    model = _gemini_model()
    try:
        response = _get_client().models.generate_content(
            model=model,
            contents=[types.Part.from_bytes(data=data, mime_type=mime), user_message],
            config=_gemini_config(system),
        )
    except Exception as e:
        raise LLMError(str(e)) from e
    text: str | None = response.text
    if not text:
        raise LLMError("The model returned an empty response.")
    return text, response


def _gemini_generate_file(user_message: str, system: str | None, data: bytes, mime: str) -> str:
    text, _response = _gemini_generate_file_raw(user_message, system, data, mime)
    return text


def _gemini_usage(response: object) -> tuple[int | None, int | None]:
    """Best-effort (tokens_in, tokens_out) from a Gemini response's
    `usage_metadata`. The google-genai SDK's response shape isn't guaranteed
    across versions (and test doubles may omit it entirely), so every
    attribute access here is optional rather than assumed."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None, None
    return (
        getattr(meta, "prompt_token_count", None),
        getattr(meta, "candidates_token_count", None),
    )


# ----------------------------------------------- openai-compatible -----------


def _openai_chat(
    messages: list[dict], schema: dict | None = None, expect_array: bool = False
) -> tuple[str, dict]:
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
        # base is operator-configured (TRUS_LLM_BASE_URL), never end-user input.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
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
        text: str | None = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected LLM response shape: {str(payload)[:300]}") from e
    if not text or not text.strip():
        raise LLMError("The model returned an empty response.")
    return text, payload.get("usage", {})


# ------------------------------------------------------------- public --------


def generate(
    prompt: str,
    system: str | None = None,
    *,
    schema: dict | None = None,
    expect_array: bool = False,
) -> GenResult:
    # Reset provenance up front so an exception path leaves last_call = None
    # (unknown provenance), never a stale previous-call value (R-403).
    last_call.set(None)
    provider = _resolve_provider()

    def _done(r: GenResult) -> GenResult:
        last_call.set(r)
        return r

    def _stub_text() -> str:
        if expect_array:
            from src.stub_templates import pick_system

            return json.dumps(pick_system(prompt))
        return _stub_module_for(prompt)

    if provider == "stub":
        return _done(GenResult(_stub_text(), "stub", "stub"))
    if provider == "openai":
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        try:
            text, usage = _openai_chat(messages, schema=schema, expect_array=expect_array)
            return _done(
                GenResult(
                    text,
                    "openai",
                    os.environ.get("TRUS_LLM_MODEL", ""),
                    tokens_in=usage.get("prompt_tokens"),
                    tokens_out=usage.get("completion_tokens"),
                )
            )
        except LLMError:
            # Local/hosted endpoint unreachable → degrade gracefully. The fallback
            # result must carry the model that actually answered, not the failed one.
            if not _cascade_enabled():
                raise
            if not _is_stub_key(os.environ.get("GEMINI_API_KEY")):
                return _done(
                    GenResult(
                        _gemini_generate(prompt, system), "gemini", _gemini_model(), degraded=True
                    )
                )
            return _done(GenResult(_stub_text(), "stub", "stub", degraded=True))
    return _done(GenResult(_gemini_generate(prompt, system), "gemini", _gemini_model()))


def generate_from_file(user_message: str, system: str | None, data: bytes, mime: str) -> str:
    """Multimodal generation. Gemini handles any file; the openai provider handles
    images (data URL); unsupported inputs return "{}" so callers can refuse honestly
    instead of silently degrading to a template.

    On success, sets `last_call` to a real GenResult (provider/model per the same
    per-branch resolution `generate()` uses, tokens where the payload offers them)
    so file-path generations carry provenance too (R-1201/R-1202). This path never
    cascades, so degraded is always False. The "{}" sentinel returns are refusals,
    not successes — they leave last_call at None."""
    # Clear stale provenance: a raising path (and the "{}" sentinel paths below)
    # must not leave a prior call's result live.
    last_call.set(None)
    provider = _resolve_provider()
    if provider == "stub":
        return "{}"
    if provider == "openai":
        if mime.startswith("image/"):
            b64 = base64.b64encode(data).decode("ascii")
            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            )
            text, usage = _openai_chat(messages, expect_array=True)
            last_call.set(
                GenResult(
                    text,
                    "openai",
                    os.environ.get("TRUS_LLM_MODEL", ""),
                    tokens_in=usage.get("prompt_tokens"),
                    tokens_out=usage.get("completion_tokens"),
                )
            )
            return text
        return "{}"  # non-image documents aren't portable across openai-compat servers
    text, response = _gemini_generate_file_raw(user_message, system, data, mime)
    tokens_in, tokens_out = _gemini_usage(response)
    last_call.set(
        GenResult(
            text,
            "gemini",
            _gemini_model(),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
    )
    return text


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
        "base_url": (
            os.getenv("TRUS_VISION_BASE_URL") or os.getenv("TRUS_LLM_BASE_URL") or ""
        ).strip(),
    }


def vision_describe(system: str | None, user_text: str, data: bytes, mime: str) -> str:
    """Send an image + instruction to the configured vision model; return its text."""
    model = os.environ.get("TRUS_VISION_MODEL", "").strip()
    base = (
        (os.getenv("TRUS_VISION_BASE_URL") or os.getenv("TRUS_LLM_BASE_URL") or "")
        .strip()
        .rstrip("/")
    )
    if not model or not base:
        raise LLMError(
            "No vision model configured. Run a vision model (e.g. `make ollama-vision`) "
            "and set TRUS_VISION_MODEL."
        )
    api_key = (os.getenv("TRUS_VISION_API_KEY") or os.getenv("TRUS_LLM_API_KEY") or "").strip()
    try:
        timeout = float(os.environ.get("TRUS_VISION_TIMEOUT", "180"))
    except ValueError:
        timeout = 180.0

    b64 = base64.b64encode(data).decode("ascii")
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }
    )
    body = json.dumps(
        {"model": model, "messages": messages, "temperature": DEFAULT_TEMPERATURE, "stream": False}
    ).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    try:
        # base is operator-configured (TRUS_VISION_BASE_URL/TRUS_LLM_BASE_URL), never end-user input.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
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
        text: str | None = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Unexpected vision response shape: {str(payload)[:300]}") from e
    if not text or not text.strip():
        raise LLMError("The vision model returned an empty response.")
    return text


def vision_capture(system: str | None, user_text: str, data: bytes, mime: str) -> str:
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


# ------------------------------------------------ speech-to-text (voice → text) -----
# Voice rambling → text (R-201/R-204 half). A SEPARATE pluggable endpoint — most
# local/hosted LLM servers don't also serve speech-to-text, so this mirrors the
# vision section above rather than reusing TRUS_LLM_*. Config:
#   TRUS_STT_BASE_URL  e.g. http://localhost:8000/v1  (any OpenAI-compatible
#                      /audio/transcriptions server — whisper.cpp server,
#                      faster-whisper server, or a hosted Whisper-compatible endpoint)
#   TRUS_STT_MODEL     e.g. whisper-1                  (required to enable)
#   TRUS_STT_API_KEY   optional; local servers ignore it
#   TRUS_STT_TIMEOUT   seconds (default 120 — audio can run long)
# BOTH TRUS_STT_BASE_URL and TRUS_STT_MODEL must be set — unlike vision, there's
# no plausible "the text-model server also happens to serve STT" default, so no
# fallback to TRUS_LLM_BASE_URL. Unset → the route refuses honestly (422).


def _stt_timeout() -> float:
    try:
        return float(os.environ.get("TRUS_STT_TIMEOUT", "120"))
    except ValueError:
        return 120.0


def _sanitize_header_value(v: str) -> str:
    """Strip CR/LF (and quotes) from a value before it's spliced into a manually
    built multipart header line. python-multipart passes a client's raw filename
    and content_type through unmodified — a bare `\\n` in either would smuggle a
    fully-formed extra form field into the body we POST to the operator's STT
    server (header injection). No legitimate filename or MIME type contains these,
    so removing them is loss-free."""
    return v.replace("\r", "").replace("\n", "").replace('"', "")


def stt_available() -> bool:
    return bool(os.environ.get("TRUS_STT_BASE_URL", "").strip()) and bool(
        os.environ.get("TRUS_STT_MODEL", "").strip()
    )


def transcribe(data: bytes, mime: str, filename: str | None) -> str:
    """Voice → text via an OpenAI-compatible POST {base}/audio/transcriptions.
    The only MULTIPART (not JSON) call in this module — the body is built by
    hand with urllib, mirroring `_openai_chat`'s zero-dep ethos (no `requests`).

    Transcription is NOT a "generation" (no ModuleConfig, no semantic cache, no
    cascade) — this never touches `last_call`; the route records its own
    telemetry instead of the shared `_track` contextmanager in routes/modules.py,
    which reads `last_call` for provider/model/tokens that don't apply here."""
    base = os.environ.get("TRUS_STT_BASE_URL", "").strip().rstrip("/")
    model = os.environ.get("TRUS_STT_MODEL", "").strip()
    if not base or not model:
        raise LLMError("Set TRUS_STT_BASE_URL and TRUS_STT_MODEL to use voice transcription.")
    api_key = os.environ.get("TRUS_STT_API_KEY", "").strip()

    boundary = uuid.uuid4().hex
    # Both filename and mime are client-supplied and spliced raw into header lines
    # below — sanitize CR/LF/quotes out of each to close multipart header injection.
    name = _sanitize_header_value(filename or "audio") or "audio"
    safe_mime = _sanitize_header_value(mime)
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="model"\r\n\r\n',
            model.encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'.encode(),
            f"Content-Type: {safe_mime}\r\n\r\n".encode(),
            data,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(base + "/audio/transcriptions", data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")

    try:
        # base is operator-configured (TRUS_STT_BASE_URL), never end-user input.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(req, timeout=_stt_timeout()) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:400] if hasattr(e, "read") else ""
        raise LLMError(f"STT endpoint returned HTTP {e.code}: {detail}") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"Could not reach the STT endpoint at {base}: {e}") from e
    except json.JSONDecodeError as e:
        raise LLMError(f"STT endpoint returned non-JSON: {e}") from e

    text = payload.get("text")
    if text is None:
        raise LLMError(f"Unexpected STT response shape: {str(payload)[:300]}")
    return str(text)
