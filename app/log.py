"""Terminal logging: one timed line per graph node, plus decision lines from the nodes."""
import functools
import logging
import time

log = logging.getLogger("review")


def setup_logging(level: str = "INFO") -> None:
    """Idempotent. Call once at program start (CLI / API)."""
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", "%H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(level.upper())
    log.propagate = False
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def logged(name: str, fn):
    """Wrap a graph node so every run logs its name and duration."""

    @functools.wraps(fn)
    def wrapper(state):
        log.info("-> %s", name)
        start = time.perf_counter()
        try:
            return fn(state)
        except Exception as e:
            log.error("!! %s failed: %s: %s", name, type(e).__name__, e)
            raise
        finally:
            log.debug("   %s took %.2fs", name, time.perf_counter() - start)

    return wrapper
