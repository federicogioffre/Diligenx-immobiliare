"""
Rate limiter — slowapi backed by in-memory storage (single instance).

Usage in a route module:
    from fastapi import Request
    from app.core.limiter import limiter

    @router.post("/login")
    @limiter.limit("10/minute")
    def login(request: Request, ...):
        ...

The limiter instance and the exception handler are both registered in main.py.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
