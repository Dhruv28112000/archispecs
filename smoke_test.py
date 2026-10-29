"""Smoke test: call the configured LLM provider once and print the reply.

LLM_PROVIDER=gemini (default) uses GEMINI_API_KEY + LLM_MODEL; LLM_PROVIDER=ollama uses
OLLAMA_HOST + OLLAMA_MODEL (+ optional OLLAMA_API_KEY). Never prints secret values.
"""
import os
import sys

import ollama
from dotenv import load_dotenv
from google import genai
from google.genai import types

PROMPT = "Reply with one short sentence confirming you are working."


def gemini() -> int:
    """Send one prompt to Gemini and print the reply text."""
    missing = [name for name in ("GEMINI_API_KEY", "LLM_MODEL") if not os.getenv(name)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)} (see .env.example)")
        return 1
    model = os.environ["LLM_MODEL"]
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(
        model=model, contents=PROMPT,
        config=types.GenerateContentConfig(temperature=float(os.getenv("LLM_TEMPERATURE", "0.2"))),
    )
    print(f"Provider: gemini · Model: {model}")
    print(f"Reply: {response.text}")
    return 0


def local_ollama() -> int:
    """Send one prompt to Ollama and print the reply text."""
    host, model = os.getenv("OLLAMA_HOST", "http://localhost:11434"), os.getenv("OLLAMA_MODEL", "qwen3:8b")
    api_key = os.getenv("OLLAMA_API_KEY")
    client = ollama.Client(host=host, headers={"Authorization": f"Bearer {api_key}"} if api_key else None)
    response = client.chat(model=model, messages=[{"role": "user", "content": PROMPT}], think=False)
    print(f"Provider: ollama · Model: {model} · Host: {host}")
    print(f"Reply: {response.message.content}")
    return 0


def main() -> int:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    try:
        return local_ollama() if provider == "ollama" else gemini()
    except Exception as exc:  # surface the error type/message, never the key
        print(f"{provider} call failed ({type(exc).__name__}): {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
