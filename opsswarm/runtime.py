import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ReadinessManager:
    def __init__(self):
        self._is_ready = False
        self._is_draining = False
        self._lock = asyncio.Lock()

    async def startup_complete(self):
        async with self._lock:
            self._is_ready = True
            logger.info("Startup complete - Readiness: READY")

    async def initiate_drain(self):
        async with self._lock:
            self._is_draining = True
            self._is_ready = False
            logger.info("Draining initiated - Readiness: UNAVAILABLE")

    @property
    def ready(self) -> bool:
        return self._is_ready

    @property
    def draining(self) -> bool:
        return self._is_draining

# Singleton manager
readiness = ReadinessManager()

# Decorator to block non-ready mutations (Issue #73)
from fastapi import HTTPException
from functools import wraps

def check_draining(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if readiness.draining:
            raise HTTPException(503, "Service is draining")
        return await func(*args, **kwargs)
    return wrapper

