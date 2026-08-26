"""Small NVIDIA NIM client boundary used by all model-backed query work."""

import asyncio
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from config import nvidia_rate_limiter, require_nvidia_api_key, settings


class LLMProviderError(RuntimeError):
    """A safe, user-facing failure from the configured model provider."""


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


async def complete(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    enable_thinking: bool | None = None,
    max_tokens: int | None = None,
) -> str:
    """Return final answer content while intentionally discarding private reasoning."""
    api_key = require_nvidia_api_key()
    client = AsyncOpenAI(
        base_url=settings.nvidia_base_url,
        api_key=api_key,
        timeout=settings.nvidia_timeout_seconds,
        max_retries=0,
    )
    last_error: Exception | None = None
    try:
        for attempt in range(max(1, settings.embedding_retry_attempts)):
            try:
                await nvidia_rate_limiter.acquire()
                response = await client.chat.completions.create(
                    model=model or settings.nemotron_model,
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
                return content.strip()
            except LLMProviderError:
                raise
            except Exception as error:
                last_error = error
                if not is_transient_provider_error(error) or attempt == max(1, settings.embedding_retry_attempts) - 1:
                    break
                await asyncio.sleep(retry_delay(error, attempt))

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
    finally:
        await client.close()
