"""Small NVIDIA NIM client boundary used by all model-backed query work."""

import asyncio
import re
import threading
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from config import ModelConfigurationError, nvidia_rate_limiter, require_nvidia_api_key, settings


class LLMProviderError(RuntimeError):
    """A safe, user-facing failure from the configured model provider."""


_THINKING_BLOCK = re.compile(r"<(?:think|analysis|reasoning)>.*?</(?:think|analysis|reasoning)>", re.IGNORECASE | re.DOTALL)
_CODE_EDIT_BLOCK = re.compile(r"<code_edit>\s*.*?</code_edit>", re.IGNORECASE | re.DOTALL)
_FINAL_LABEL = re.compile(
    r"(?ims)^\s*(?:final(?:\s+(?:answer|response))?|assistant\s+response)\s*:\s*(.+)\Z"
)
_INTERNAL_PLANNING_PREFIX = re.compile(
    r"^\s*(?:analysis\s*:|reasoning\s*:|the user (?:said|asked|is asking)|"
    r"i (?:should|need to|will)|we (?:should|need to|will)|no need to)\b",
    re.IGNORECASE,
)

_async_client: AsyncOpenAI | None = None
_async_client_loop: asyncio.AbstractEventLoop | None = None
_async_client_lock = threading.Lock()


def get_async_client() -> AsyncOpenAI:
    """Reuse one HTTP client per event loop so keep-alive connections survive requests."""
    global _async_client, _async_client_loop
    loop = asyncio.get_running_loop()
    with _async_client_lock:
        if _async_client is None or _async_client_loop is not loop:
            _async_client = AsyncOpenAI(
                base_url=settings.nvidia_base_url,
                api_key=require_nvidia_api_key(),
                timeout=settings.nvidia_timeout_seconds,
                max_retries=0,
            )
            _async_client_loop = loop
        return _async_client


async def close_async_client() -> None:
    """Close the process-scoped provider client during application shutdown."""
    global _async_client, _async_client_loop
    with _async_client_lock:
        client = _async_client
        _async_client = None
        _async_client_loop = None
    if client is not None:
        await client.close()


def user_facing_content(content: str) -> str:
    """Reject provider planning text instead of displaying it in the chat UI.

    Some hosted model templates can emit a planning trace in ``content`` even
    when thinking is disabled. It is not an answer and must never be saved to
    a user's conversation history.
    """
    cleaned = _THINKING_BLOCK.sub("", content).strip()
    final_match = _FINAL_LABEL.search(cleaned)
    if final_match:
        cleaned = final_match.group(1).strip()
    if not cleaned or _INTERNAL_PLANNING_PREFIX.match(cleaned):
        raise LLMProviderError("NVIDIA returned internal planning instead of a user-facing answer.")
    return cleaned


def is_transient_provider_error(error: Exception) -> bool:
    return isinstance(error, (APITimeoutError, APIConnectionError)) or (
        isinstance(error, APIStatusError) and error.status_code in {429, 500, 502, 503, 504}
    )


def retry_delay(error: Exception, attempt: int) -> float:
    response = getattr(error, "response", None)
    retry_after = response.headers.get("retry-after") if response is not None else None
    try:
        if retry_after is not None:
            return min(60.0, max(0.1, float(retry_after)))
    except (TypeError, ValueError):
        pass
    return min(30.0, settings.embedding_retry_base_seconds * (2 ** attempt))


def _can_try_fallback(error: Exception) -> bool:
    """Allow a configured fallback for outages and retired model IDs only."""
    if is_transient_provider_error(error):
        return True
    return isinstance(error, APIStatusError) and error.status_code in {404, 410}


async def complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    enable_thinking: bool | None = None,
    max_tokens: int | None = None,
    fallback_models: list[str] | None = None,
    retry_attempts: int | None = None,
    structured_output: bool = False,
) -> str:
    """Return final answer content while intentionally discarding private reasoning.

    ``fallback_models`` is intentionally opt-in. The normal answer path keeps
    one deterministic model, while code editing can fail over to another
    allow-listed NVIDIA catalog model when a free endpoint is busy, retired, or
    temporarily unavailable.
    """
    api_key = require_nvidia_api_key()
    # Validate configuration before entering the retry loop, then reuse the
    # process-scoped client to avoid a DNS/TLS connection setup on every query.
    if not api_key:
        raise ModelConfigurationError("NVIDIA is not configured.")
    client = get_async_client()
    last_error: Exception | None = None
    model_names = list(dict.fromkeys([model or settings.nemotron_model, *(fallback_models or [])]))
    attempts = max(1, int(retry_attempts or settings.answer_retry_attempts))
    try:
        for model_index, model_name in enumerate(model_names):
            for attempt in range(attempts):
                try:
                    await nvidia_rate_limiter.acquire()
                    response = await client.chat.completions.create(
                        model=model_name,
                        messages=messages,
                        temperature=0.1,
                        top_p=0.95,
                        max_tokens=max_tokens or settings.answer_max_tokens,
                        extra_body={
                            "chat_template_kwargs": {
                                "enable_thinking": (
                                    settings.nvidia_enable_thinking if enable_thinking is None else enable_thinking
                                ),
                                "force_nonempty_content": True,
                            },
                        },
                    )
                    if not response.choices:
                        raise LLMProviderError("NVIDIA returned an empty completion.")
                    content = response.choices[0].message.content
                    if not isinstance(content, str) or not content.strip():
                        raise LLMProviderError("NVIDIA returned a completion without answer content.")
                    if structured_output:
                        structured = _CODE_EDIT_BLOCK.search(content)
                        if structured:
                            # Code editing consumes only the machine-readable
                            # patch. Any model reasoning or wrapper prose is
                            # discarded before exact-source validation.
                            return structured.group(0).strip()
                    return user_facing_content(content)
                except LLMProviderError:
                    raise
                except Exception as error:
                    last_error = error
                    # A retired or invalid model will never recover by
                    # retrying. Switch to the configured fallback immediately.
                    if isinstance(error, APIStatusError) and error.status_code in {404, 410}:
                        break
                    if not _can_try_fallback(error) or attempt == attempts - 1:
                        break
                    await asyncio.sleep(retry_delay(error, attempt))
            # A fallback is useful only after the primary has exhausted its
            # retries. Never fall back after auth, validation, or content errors.
            if model_index < len(model_names) - 1 and not _can_try_fallback(last_error or Exception()):
                break

        if isinstance(last_error, APITimeoutError):
            raise LLMProviderError("NVIDIA timed out while generating the answer after retries.") from last_error
        if isinstance(last_error, APIConnectionError):
            raise LLMProviderError("Could not connect to NVIDIA while generating the answer after retries.") from last_error
        if isinstance(last_error, APIStatusError):
            raise LLMProviderError(
                f"NVIDIA could not generate the answer after retries (HTTP {last_error.status_code})."
            ) from last_error
        raise LLMProviderError("NVIDIA returned an invalid response.") from last_error
    except LLMProviderError:
        raise
    except Exception as error:
        raise LLMProviderError("NVIDIA returned an invalid response.") from error
