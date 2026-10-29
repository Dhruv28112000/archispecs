"""Single LLM entry point: generate_json(system, user, schema).

LLM_PROVIDER=gemini (default): Gemini (google-genai structured output) first; retries
429/5xx with exponential backoff, then falls back to Ollama on any remaining Gemini error.
LLM_PROVIDER=ollama: Ollama only (no Gemini key needed). Responses are
validated with Pydantic (one repair retry) and cached in CACHE_DIR.
"""
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Callable, TypeVar

import ollama
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

MAX_RETRIES = 3
MAX_RETRY_DELAY_S = 60
log = logging.getLogger("archispecs.llm")

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when no provider produced a valid response."""


def _cache_path(system: str, user: str, schema: type[BaseModel]) -> Path:
    digest = hashlib.sha256((system + user + schema.__name__).encode("utf-8")).hexdigest()
    cache_dir = ROOT / os.getenv("CACHE_DIR", ".cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{digest}.json"


def _temperature() -> float:
    return float(os.getenv("LLM_TEMPERATURE", "0.2"))


def _retry_delay_s(exc: errors.APIError) -> float:
    """Server-suggested retry delay in seconds from a 429's RetryInfo (0 if absent)."""
    match = re.search(r"'retryDelay': '([\d.]+)s'", str(exc))
    return float(match.group(1)) if match else 0.0


def _call_gemini(system: str, user: str, schema: type[BaseModel]) -> str:
    """Return raw JSON text from Gemini, retrying 429/5xx with exponential backoff."""
    api_key, model = os.getenv("GEMINI_API_KEY"), os.getenv("LLM_MODEL")
    if not api_key or not model:
        raise LLMError("GEMINI_API_KEY or LLM_MODEL not set (see .env.example)")
    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=_temperature(),
    )
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(model=model, contents=user, config=config)
            if not response.text:
                raise LLMError("Gemini returned an empty response")
            return response.text
        except errors.APIError as exc:
            retryable = exc.code == 429 or (exc.code or 0) >= 500
            if exc.code == 429 and _retry_delay_s(exc) > MAX_RETRY_DELAY_S:
                retryable = False  # e.g. daily quota exhausted — backoff cannot help, fall back now
            if not retryable or attempt == MAX_RETRIES:
                raise
            delay = 2**attempt
            log.warning("Gemini %s, retry %d/%d in %ds", exc.code, attempt + 1, MAX_RETRIES, delay)
            time.sleep(delay)
    raise LLMError("unreachable")


def _call_ollama(system: str, user: str, schema: type[BaseModel]) -> str:
    """Return raw JSON text from Ollama constrained by the schema's JSON Schema."""
    api_key = os.getenv("OLLAMA_API_KEY")  # only for remote/cloud hosts; local Ollama needs none
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"), headers=headers)
    response = client.chat(
        model=os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        format=schema.model_json_schema(),
        # Ollama's default context is too small for BRD + memory + gaps; it would truncate silently.
        options={"temperature": _temperature(), "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "16384"))},
        think=False,  # qwen3 "thinking" text would break JSON output
    )
    return response.message.content or ""


def _generate_validated(call: Callable[[str, str, type[T]], str], system: str, user: str,
                        schema: type[T]) -> T:
    """Call a provider and validate; on ValidationError retry once with the error appended."""
    raw = call(system, user, schema)
    try:
        return schema.model_validate_json(raw)
    except ValidationError as exc:
        log.warning("Validation failed, sending one repair request: %s", exc.error_count())
        repair = (f"{user}\n\nYour previous answer did not match the required JSON schema.\n"
                  f"Previous answer:\n{raw}\n\nValidation errors:\n{exc}\n\n"
                  "Return corrected JSON only.")
        return schema.model_validate_json(call(system, repair, schema))


def _providers() -> list[tuple[str, Callable[[str, str, type[T]], str]]]:
    """Provider chain from LLM_PROVIDER: "gemini" (default, Ollama fallback) or "ollama" (Ollama only)."""
    choice = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    if choice == "gemini":
        return [("gemini", _call_gemini), ("ollama", _call_ollama)]
    if choice == "ollama":
        return [("ollama", _call_ollama)]
    raise LLMError(f"Unknown LLM_PROVIDER '{choice}' (use 'gemini' or 'ollama')")


def generate_json(system: str, user: str, schema: type[T]) -> T:
    """Generate a validated `schema` instance from the LLM (cache → provider chain).

    Raises LLMError if every provider fails.
    """
    cache_file = _cache_path(system, user, schema)
    if cache_file.exists():
        log.info("LLM provider: cache (%s, %s)", schema.__name__, cache_file.name[:12])
        return schema.model_validate_json(cache_file.read_text(encoding="utf-8"))

    failures = []
    for name, call in _providers():
        try:
            result = _generate_validated(call, system, user, schema)
        except Exception as exc:  # noqa: BLE001 — every failure moves to the next provider
            log.warning("LLM provider %s failed (%s): %s", name, type(exc).__name__, exc)
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        log.info("LLM provider: %s (%s)", name, schema.__name__)
        cache_file.write_text(result.model_dump_json(), encoding="utf-8")
        return result

    raise LLMError("All LLM providers failed — " + " | ".join(failures))
