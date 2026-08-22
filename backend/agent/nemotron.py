"""Small NVIDIA NIM client boundary used by all model-backed query work."""

from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from config import nvidia_rate_limiter, require_nvidia_api_key, settings


class LLMProviderError(RuntimeError):
    """A safe, user-facing failure from the configured model provider."""


async def complete(messages: list[dict[str, Any]], *, max_tokens: int = 4096) -> str:
    """Return final answer content while intentionally discarding private reasoning."""
    api_key = require_nvidia_api_key()
    await nvidia_rate_limiter.acquire()
    client = AsyncOpenAI(
        base_url=settings.nvidia_base_url,
        api_key=api_key,
        timeout=settings.nvidia_timeout_seconds,
        max_retries=0,
    )
    try:
        response = await client.chat.completions.create(
            model=settings.nemotron_model,
            messages=messages,
            temperature=0.1,
            top_p=0.95,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}},
        )
        if not response.choices:
            raise LLMProviderError("NVIDIA returned an empty completion.")
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("NVIDIA returned a completion without answer content.")
        return content.strip()
    except LLMProviderError:
        raise
    except APITimeoutError as error:
        raise LLMProviderError("NVIDIA timed out while generating the answer. Please retry.") from error
    except APIConnectionError as error:
        raise LLMProviderError("Could not connect to NVIDIA while generating the answer. Please retry.") from error
    except APIStatusError as error:
        raise LLMProviderError(
            f"NVIDIA could not generate the answer (HTTP {error.status_code}). Please retry."
        ) from error
    except Exception as error:
        raise LLMProviderError("NVIDIA returned an invalid response. Please retry.") from error
    finally:
        await client.close()
