"""Small RSS guard used by the single-process Render ingestion worker."""

import asyncio
import gc
import logging
import os
import resource

from config import settings

logger = logging.getLogger(__name__)


def rss_mb() -> float:
    """Return process RSS in MB on Linux and macOS without optional packages."""
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KB; macOS reports bytes.
    if value > 1024 * 1024 * 2:
        return value / (1024 * 1024)
    return value / 1024


def pressure_level(value: float | None = None) -> str:
    current = rss_mb() if value is None else value
    if current >= settings.memory_critical_mb:
        return "critical"
    if current >= settings.memory_warning_mb:
        return "warning"
    if current >= settings.memory_target_mb:
        return "elevated"
    return "normal"


async def wait_for_memory_headroom() -> float:
    """Pause new embedding work briefly while pressure is critical.

    A bounded wait avoids an infinite retry loop. If memory does not fall,
    raising MemoryError lets the durable job lease recover instead of allowing
    Render's 512 MB process limit to terminate the service.
    """
    current = rss_mb()
    if current < settings.memory_critical_mb:
        return current
    for _ in range(10):
        gc.collect()
        await asyncio.sleep(0.25)
        current = rss_mb()
        if current < settings.memory_critical_mb:
            logger.warning("Memory pressure eased to %.1f MB", current)
            return current
    raise MemoryError(
        f"Ingestion paused at {current:.1f} MB RSS to protect the 512 MB service. Retry will resume safely."
    )
