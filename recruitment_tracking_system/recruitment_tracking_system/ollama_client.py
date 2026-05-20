from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class OllamaChatResult:
    ok: bool
    message: str
    raw: Optional[Dict[str, Any]] = None
    error: str = ""


def _friendly_connection_error(base_url: str, exc: Exception) -> str:
    base_url = (base_url or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    detail = str(exc) or exc.__class__.__name__
    if "WinError 10061" in detail or "Connection refused" in detail or "actively refused" in detail:
        return (
            f"Ollama is not reachable at {base_url} (connection refused). "
            f"Start Ollama (e.g. `ollama serve`) and verify it is listening on {host}:{port}, "
            "or set `OLLAMA_ENABLED=0` / `ASSESSMENT_LLM_PROVIDER=gemini`."
        )

    if "Name or service not known" in detail or "getaddrinfo failed" in detail:
        return (
            f"Ollama host could not be resolved for {base_url}. "
            "Check `OLLAMA_BASE_URL` (host/port) or set `OLLAMA_ENABLED=0`."
        )

    return f"Ollama request error calling {base_url}/api/chat: {detail}"


def ollama_chat(
    *,
    base_url: str,
    model: str,
    user_message: str,
    system_message: str = "",
    timeout_seconds: int = 300,
) -> OllamaChatResult:
    """
    Calls Ollama's local Chat API: POST {base_url}/api/chat
    """
    base_url = (base_url or "").strip().rstrip("/")
    model = (model or "").strip()
    user_message = (user_message or "").strip()
    system_message = (system_message or "").strip()

    if not base_url:
        return OllamaChatResult(ok=False, message="", error="OLLAMA_BASE_URL is missing.")
    if not model:
        return OllamaChatResult(ok=False, message="", error="OLLAMA_MODEL is missing.")
    if not user_message:
        return OllamaChatResult(ok=False, message="", error="Message is empty.")

    messages: List[Dict[str, str]] = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": user_message})

    url = f"{base_url}/api/chat"
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}

    try:
        import requests  # type: ignore
    except Exception as exc:
        return OllamaChatResult(
            ok=False,
            message="",
            error=f"Python dependency error importing requests: {exc}. Install dependencies (e.g. certifi).",
        )

    try:
        resp = requests.post(url, json=payload, timeout=max(1, int(timeout_seconds)))
    except requests.RequestException as exc:
        return OllamaChatResult(ok=False, message="", error=_friendly_connection_error(base_url, exc))

    if resp.status_code >= 400:
        body = ""
        try:
            body = resp.text or ""
        except Exception:
            body = ""
        return OllamaChatResult(ok=False, message="", error=f"Ollama error {resp.status_code}: {body[:500]}")

    try:
        data = resp.json()
    except Exception:
        return OllamaChatResult(ok=False, message="", error="Invalid JSON from Ollama.")

    content = ""
    try:
        content = (data.get("message") or {}).get("content") or ""
    except Exception:
        content = ""

    content = (content or "").strip()
    if not content:
        return OllamaChatResult(ok=False, message="", raw=data, error="Empty response from model.")

    return OllamaChatResult(ok=True, message=content, raw=data)
