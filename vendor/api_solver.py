"""Minimal TurnstileAPIServer stub for integration.

This lightweight implementation provides the small surface used by the
refactored registrar: construction, an async `_initialize_browser` method and
an asyncio.Queue `browser_pool`. It intentionally avoids heavy dependencies
and real browser startup so the package can be imported safely.
"""
import asyncio
from typing import Optional


class TurnstileAPIServer:
    def __init__(self, headless: bool, useragent: Optional[str], debug: bool, browser_type: str, thread: int, proxy_support: bool, use_random_config: bool = False, browser_name: Optional[str] = None, browser_version: Optional[str] = None, manual: bool = False):
        self.debug = debug
        self.browser_type = browser_type
        self.headless = headless
        self.thread_count = thread or 1
        self.proxy_support = proxy_support
        self.browser_pool: asyncio.Queue = asyncio.Queue()
        self.use_random_config = use_random_config
        self.browser_name = browser_name
        self.browser_version = browser_version

    async def _initialize_browser(self) -> None:
        # Put zero or placeholder entries into the pool; real implementation
        # would start browsers. We leave the pool empty so registrar falls back
        # to local browser creation when needed.
        return

