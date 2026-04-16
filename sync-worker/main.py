"""
Sync Worker entrypoint. Runs immediately on startup, then every SYNC_INTERVAL_SECONDS.
"""
import schedule
import time
import structlog
import logging
from config import Config
from registry_client import MCPRegistryClient
from gateway_client import GatewayClient
from syncer import run_sync

config = Config.from_env()
logging.basicConfig(level=getattr(logging, config.log_level.upper(), logging.INFO))
structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, config.log_level.upper(), logging.INFO)
    )
)
log = structlog.get_logger()


def sync_job():
    rc = MCPRegistryClient(config)
    gc = GatewayClient(config)
    if not gc.health_check():
        log.warning("sync_skipped_gateway_unavailable")
        return
    run_sync(rc, gc, config.sync_state_file)


if __name__ == "__main__":
    log.info("sync_worker_starting", interval_seconds=config.sync_interval_seconds)
    sync_job()
    schedule.every(config.sync_interval_seconds).seconds.do(sync_job)
    while True:
        schedule.run_pending()
        time.sleep(30)
