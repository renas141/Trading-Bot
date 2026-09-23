"""Console and rotating local file logging; never dump environment/settings."""

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(directory: Path, level: str = "INFO") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s")
    formatter.converter = time.gmtime
    console = logging.StreamHandler()
    file_handler = RotatingFileHandler(directory / "bot.log", maxBytes=2_000_000,
                                      backupCount=3, encoding="utf-8")
    for handler in (console, file_handler):
        handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console, file_handler], force=True)
