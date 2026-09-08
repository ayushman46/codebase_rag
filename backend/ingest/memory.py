"""Small RSS guard used by the single-process Render ingestion worker."""

import asyncio
import gc
import logging
import os
import resource
import subprocess
import sys

from config import settings

logger = logging.getLogger(__name__)


def rss_mb() -> float:
    """Return current process RSS in MB without an optional dependency.

    ``ru_maxrss`` is a lifetime high-water mark, not current memory. Using it
    for back-pressure makes a worker fail permanently after one transient
    allocation, which is especially harmful on a 512 MB Render service. Use
    the live Linux proc value or macOS ``ps`` output and retain the resource
    fallback only for platforms without either interface.
    """
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status", encoding="utf-8") as status_file:
                for line in status_file:
                    if line.startswith("VmRSS:"):
                        return float(line.split()[1]) / 1024
        except (OSError, ValueError, IndexError):
            pass
    elif sys.platform == "darwin":
        try:
            output = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            return float(output.strip()) / 1024
        except (OSError, ValueError, subprocess.SubprocessError):
            pass

    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # Linux reports KB; macOS reports bytes. This is only a last-resort
    # fallback because it reports the high-water mark on both platforms.
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
