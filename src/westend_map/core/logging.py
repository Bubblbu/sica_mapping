"""Logging helpers shared across the application."""

from __future__ import annotations

import logging
import sys
from typing import Any

try:  # Optional dependency that provides richer progress bars.
    from tqdm.auto import tqdm  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tqdm = None  # type: ignore


class ProgressReporter:
    """Wrapper around tqdm with graceful fallback to standard logging."""

    def __init__(self, total_steps: int, label: str = "Progress") -> None:
        self.total_steps = max(int(total_steps) if total_steps else 1, 1)
        self.label = label
        self._tqdm = None
        self._current = 0
        self._finished = False

    def __enter__(self) -> "ProgressReporter":
        if tqdm is not None:
            self._tqdm = tqdm(total=self.total_steps, desc=self.label, unit="step", leave=False, dynamic_ncols=True)
        else:
            logger.info("%s started", self.label)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self._emit("Failed", error=True)
            if self._tqdm is not None:
                self._tqdm.close()
            return False
        if not self._finished:
            self.finish()
        return False

    def step(self, message: str) -> None:
        self._current = min(self.total_steps, self._current + 1)
        self._emit(message)

    def finish(self, message: str = "Done") -> None:
        if self._finished:
            return
        if self._tqdm is not None:
            remaining = self.total_steps - self._tqdm.n
            if remaining > 0:
                self._tqdm.update(remaining)
            if message:
                self._tqdm.set_postfix_str(message, refresh=False)
            self._tqdm.close()
        else:
            logger.info("%s complete", self.label)
        self._finished = True

    def _emit(self, message: str, *, error: bool = False) -> None:
        if self._tqdm is not None:
            self._tqdm.update(1)
            if message:
                self._tqdm.set_postfix_str(message, refresh=False)
        else:
            log = logger.error if error else logger.info
            log("%s (%d/%d) %s", self.label, self._current, self.total_steps, message)


try:
    from loguru import logger as _loguru_logger  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    _loguru_logger = None  # type: ignore[assignment]

logger = logging.getLogger("westend_map")

_configured = False


def configure_logging(verbose: bool = False) -> None:
    """Configure project-wide logging with loguru if available."""
    global _configured
    if _configured:
        if _loguru_logger is not None:
            _loguru_logger.remove()
            _loguru_logger.add(
                sys.stderr,
                level="DEBUG" if verbose else "INFO",
                format=(
                    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                    "<level>{level: <8}</level> | "
                    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                    "<level>{message}</level>"
                ),
                colorize=sys.stderr.isatty(),
            )
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        return

    if _loguru_logger is None:
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(format="%(levelname)s: %(message)s", level=level)
        logger.setLevel(level)
        _configured = True
        return

    _loguru_logger.remove()
    _loguru_logger.add(
        sys.stderr,
        level="DEBUG" if verbose else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=sys.stderr.isatty(),
    )

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if _loguru_logger is None:  # pragma: no cover - defensive
                return
            try:
                level = _loguru_logger.level(record.levelname).name
            except ValueError:
                level = record.levelno
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
            _loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=logging.DEBUG)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    _configured = True


def get_logger(*_, **__) -> Any:
    """Backwards compatible accessor."""
    return logger
