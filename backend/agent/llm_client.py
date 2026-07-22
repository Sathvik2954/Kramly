"""
llm_client.py
-------------
Provider-agnostic LLM client for Kramly's agentic reasoning layer.

Design decisions
~~~~~~~~~~~~~~~~
1. **Groq primary, Mistral fallback — raw HTTPS, no vendor SDKs.**
   Both providers expose OpenAI-compatible chat-completion REST endpoints
   (`POST /v1/chat/completions`, Bearer auth, `choices[0].message.content`).
   Calling them directly via `httpx` avoids depending on two separate SDKs
   with different import paths/versions, and keeps this file the single
   place that knows how to talk to an LLM.

   Verified against provider docs (as of 2026-07):
   - Groq:    https://console.groq.com/docs/api-reference
              endpoint: https://api.groq.com/openai/v1/chat/completions
   - Mistral: https://docs.mistral.ai/api/endpoint/chat
              endpoint: https://api.mistral.ai/v1/chat/completions

2. **Decisions are the point, not chat.**
   This client exists to let the agent layer make real judgment calls
   (replan or not, how to sequence a path, whether a path is pedagogically
   sound) instead of only narrating decisions made elsewhere. Every public
   method returns something the caller can act on programmatically —
   `complete_json` parses and validates a JSON object, it does not hand
   back raw prose for the caller to regex.

3. **Fail loud to the caller, not to the user.**
   `LLMUnavailableError` is raised when both providers are unreachable or
   unconfigured. Callers in `engine.py` / `reasoning.py` decide whether to
   fall back to deterministic logic — this module never silently
   swallows failures, so the fallback path is always a visible, logged
   decision rather than an accident.

4. **No fine-tuning, no local inference.**
   Per project constraints, this only calls hosted Groq/Mistral APIs.

5. **Timeout and JSON-retry temperature default from Settings**
   (`llm_request_timeout_seconds`, `llm_json_retry_temperature`), not
   module constants — see app/config.py.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"


class LLMUnavailableError(RuntimeError):
    """Raised when no configured LLM provider could produce a response.

    Callers should catch this specifically (not a bare `Exception`) so
    that a provider outage is handled the same deliberate way everywhere:
    log a warning and drop to the module's deterministic fallback.
    """


class LLMClient:
    """Thin client that tries Groq first, then Mistral, for chat completions.

    Parameters
    ----------
    groq_api_key, mistral_api_key : str, optional
        Provider API keys. Either or both may be ``None`` — a provider
        with no key is skipped rather than attempted and failed.
    groq_model, mistral_model : str
        Model IDs to request from each provider.
    timeout : float, optional
        Per-request timeout in seconds, applied to both providers.
        Defaults to Settings.llm_request_timeout_seconds.
    """

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        mistral_api_key: Optional[str] = None,
        groq_model: str = "llama-3.3-70b-versatile",
        mistral_model: str = "mistral-small-latest",
        timeout: Optional[float] = None,
    ) -> None:
        self.groq_api_key = groq_api_key
        self.mistral_api_key = mistral_api_key
        self.groq_model = groq_model
        self.mistral_model = mistral_model
        if timeout is None:
            from app.config import settings
            timeout = settings.llm_request_timeout_seconds
        self.timeout = timeout

    @property
    def has_any_provider(self) -> bool:
        """True if at least one provider is configured with an API key."""
        return bool(self.groq_api_key or self.mistral_api_key)

    # ------------------------------------------------------------------
    # Provider calls
    # ------------------------------------------------------------------
    def _call_groq(self, messages: list[dict], *, json_mode: bool, temperature: float, max_tokens: int) -> str:
        if not self.groq_api_key:
            raise LLMUnavailableError("Groq API key not configured.")

        payload: dict = {
            "model": self.groq_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = httpx.post(
            GROQ_ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def _call_mistral(self, messages: list[dict], *, json_mode: bool, temperature: float, max_tokens: int) -> str:
        if not self.mistral_api_key:
            raise LLMUnavailableError("Mistral API key not configured.")

        payload: dict = {
            "model": self.mistral_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        response = httpx.post(
            MISTRAL_ENDPOINT,
            headers={
                "Authorization": f"Bearer {self.mistral_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def complete(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 700,
    ) -> str:
        """Return the raw text content of a chat completion.

        Tries Groq first, then Mistral. Raises `LLMUnavailableError` if
        neither provider is configured or both requests fail.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        errors: list[str] = []

        if self.groq_api_key:
            try:
                return self._call_groq(messages, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens)
            except Exception as exc:  # noqa: BLE001 - provider fallback boundary
                logger.warning("Groq completion failed, falling back to Mistral: %s", exc)
                errors.append(f"groq: {exc}")

        if self.mistral_api_key:
            try:
                return self._call_mistral(messages, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens)
            except Exception as exc:  # noqa: BLE001 - final provider, no further fallback
                logger.warning("Mistral completion failed: %s", exc)
                errors.append(f"mistral: {exc}")

        raise LLMUnavailableError(
            "No LLM provider available. " + ("; ".join(errors) if errors else "No API keys configured.")
        )

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.1,
        max_tokens: int = 700,
    ) -> dict:
        """Return a parsed JSON object from the model.

        The caller's `system`/`user` prompts must instruct the model to
        respond with JSON matching a specific shape — this method only
        handles requesting JSON mode and parsing the result. One retry is
        attempted with a stricter instruction if the first response isn't
        valid JSON; after that, `LLMUnavailableError` is raised so the
        caller can fall back to deterministic logic. The retry temperature
        defaults to Settings.llm_json_retry_temperature.
        """
        raw = self.complete(system, user, json_mode=True, temperature=temperature, max_tokens=max_tokens)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("LLM returned non-JSON content on first attempt, retrying once.")

        from app.config import settings

        retry_user = (
            user
            + "\n\nIMPORTANT: Respond with ONLY a single valid JSON object. "
            "No markdown, no code fences, no commentary before or after it."
        )
        raw_retry = self.complete(
            system, retry_user, json_mode=True,
            temperature=settings.llm_json_retry_temperature,
            max_tokens=max_tokens,
        )
        try:
            return json.loads(raw_retry)
        except (json.JSONDecodeError, TypeError) as exc:
            raise LLMUnavailableError(f"LLM did not return valid JSON after retry: {exc}") from exc


def build_default_client() -> LLMClient:
    """Construct an `LLMClient` from `app.config.settings`.

    Kept as a separate factory (rather than a module-level singleton
    constructed at import time) so tests can freely construct clients with
    mock keys without needing `app.config` to be importable/configured.
    """
    from app.config import settings

    return LLMClient(
        groq_api_key=settings.groq_api_key,
        mistral_api_key=settings.mistral_api_key,
        groq_model=settings.groq_model,
        mistral_model=settings.mistral_model,
        timeout=settings.llm_request_timeout_seconds,
    )
