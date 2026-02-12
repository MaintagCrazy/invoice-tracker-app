"""
Simple in-memory rate limiter — 20 requests/minute per IP
"""
import time
from collections import defaultdict
from typing import List

from fastapi import Request, HTTPException


# Store timestamps per IP
_request_timestamps: dict[str, List[float]] = defaultdict(list)

MAX_REQUESTS = 20
WINDOW_SECONDS = 60


def _clean_old_entries(ip: str, now: float):
    """Remove timestamps older than the window"""
    cutoff = now - WINDOW_SECONDS
    _request_timestamps[ip] = [t for t in _request_timestamps[ip] if t > cutoff]


async def rate_limit_dependency(request: Request):
    """FastAPI dependency that enforces rate limiting on chat endpoints"""
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    _clean_old_entries(ip, now)

    if len(_request_timestamps[ip]) >= MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please wait before sending more messages. Limit: {MAX_REQUESTS} per minute."
        )

    _request_timestamps[ip].append(now)
