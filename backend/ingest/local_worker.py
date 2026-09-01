"""Local and self-hosted runner for the durable Turso ingestion queue."""

import asyncio
import logging

from config import settings
from database import assert_turso_schema, get_turso_store
from ingest.pipeline import process_one_queued_ingestion, recover_stuck_repos

logger = logging.getLogger(__name__)

# Run the recovery sweep every N poll cycles to catch any repos that were
# left in an intermediate state by a prior crash. One sweep per ~30 seconds
# is sufficient; the condition is rare and cheap.
_RECOVERY_SWEEP_INTERVAL = 10


async def process_queue_forever():
    """Claim one queued job at a time without blocking FastAPI request handling."""
    logger.info("Local ingestion worker started; polling every %s seconds", settings.local_ingestion_poll_seconds)
    poll_count = 0
    failure_streak = 0

    while True:
        try:
            # The schema check is cached after its first successful Turso call.
            await assert_turso_schema()
            # Periodically sweep for repos stuck in an intermediate status whose
            # ingestion job was already marked completed by a crashed worker.
            poll_count += 1
            if poll_count == 1 or poll_count % _RECOVERY_SWEEP_INTERVAL == 0:
                recovered = await recover_stuck_repos(get_turso_store())
                if recovered:
                    logger.info("Recovery sweep restored %d stuck repository(ies)", recovered)
            result = await process_one_queued_ingestion(get_turso_store())
            failure_streak = 0
            # Continue immediately while work is available; otherwise avoid
            # repeatedly querying Turso when the queue is empty.
            delay = 0 if result.get("processed") else settings.local_ingestion_poll_seconds
        except asyncio.CancelledError:
            logger.info("Local ingestion worker stopped")
            raise
        except Exception:
            logger.exception("Local ingestion worker could not process the queue; retrying")
            failure_streak += 1
            # A provider/database outage should not fill logs every few
            # seconds. The delay resets as soon as one poll succeeds.
            delay = max(
                settings.local_ingestion_poll_seconds,
                min(30.0, 3.0 * (2 ** min(failure_streak - 1, 3))),
            )

        await asyncio.sleep(delay)
