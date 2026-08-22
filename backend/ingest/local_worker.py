"""Local and self-hosted runner for the durable Supabase ingestion queue."""

import asyncio
import logging

from config import settings
from database import assert_supabase_schema, get_supabase_client
from ingest.pipeline import process_one_queued_ingestion

logger = logging.getLogger(__name__)


async def process_queue_forever():
    """Claim one queued job at a time without blocking FastAPI request handling."""
    logger.info("Local ingestion worker started; polling every %s seconds", settings.local_ingestion_poll_seconds)

    while True:
        try:
            # The schema check is cached after its first success. Run the first
            # network-bound call in a worker thread so it cannot block the API.
            await asyncio.to_thread(assert_supabase_schema)
            result = await process_one_queued_ingestion(get_supabase_client())
            # Continue immediately while work is available; otherwise avoid
            # repeatedly querying Supabase when the queue is empty.
            delay = 0 if result.get("processed") else settings.local_ingestion_poll_seconds
        except asyncio.CancelledError:
            logger.info("Local ingestion worker stopped")
            raise
        except Exception:
            logger.exception("Local ingestion worker could not process the queue; retrying")
            delay = max(settings.local_ingestion_poll_seconds, 3.0)

        await asyncio.sleep(delay)
