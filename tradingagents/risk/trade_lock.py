"""
CooperCorp PRJ-002 — Trade Lock
File-based mutex to prevent concurrent order submissions.
"""
import fcntl
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

LOCK_FILE = "/tmp/coopercorp_trade.lock"


class TradeLock:
    def __init__(self, lock_file: str = LOCK_FILE):
        self.lock_file = lock_file
        self._fd = None

    def acquire(self, timeout: float = 10) -> bool:
        """Try to acquire file lock. Returns False if already locked after timeout."""
        deadline = time.monotonic() + timeout
        self._fd = open(self.lock_file, "w")
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.debug("TradeLock acquired")
                return True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    logger.warning("TradeLock: could not acquire lock within timeout")
                    self._fd.close()
                    self._fd = None
                    return False
                time.sleep(0.1)

    def release(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
                logger.debug("TradeLock released")
            except Exception:
                pass
            self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
