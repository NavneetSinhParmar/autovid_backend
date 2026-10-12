"""Application console logs for Uvicorn, local render threads and Celery."""
import logging
import os
import sys


def configure_logging():
    logger = logging.getLogger("app")
    level = os.getenv("BACKEND_LOG_LEVEL", "INFO").upper()
    logger.setLevel(getattr(logging, level, logging.INFO))
    if not any(getattr(handler, "autovid_console", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.autovid_console = True
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s | %(message)s", datefmt="%H:%M:%S"))
        logger.addHandler(handler)
    logger.propagate = False
