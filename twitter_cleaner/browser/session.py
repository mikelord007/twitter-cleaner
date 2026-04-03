from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from twitter_cleaner.config import Config


class TwitterSession:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright = None
        self._browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        self._playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": self._config.headless}

        session_file = self._config.session_file
        context_kwargs: dict = {}
        if session_file.exists():
            context_kwargs["storage_state"] = str(session_file)

        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self.context = await self._browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()

        await self._ensure_logged_in()
        return self.page

    async def _ensure_logged_in(self) -> None:
        page = self.page
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        if "login" in page.url or "i/flow/login" in page.url:
            await self._login()

    async def _login(self) -> None:
        cfg = self._config
        page = self.page

        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        # Username
        username_input = page.get_by_label("Phone, email, or username")
        await username_input.fill(cfg.username)
        await page.get_by_role("button", name="Next").click()
        await asyncio.sleep(2)

        # Possible "enter your phone/username" confirmation step
        unusual_input = page.locator('input[data-testid="ocfEnterTextTextInput"]')
        if await unusual_input.count() > 0:
            await unusual_input.fill(cfg.username)
            await page.get_by_role("button", name="Next").click()
            await asyncio.sleep(2)

        # Password
        password_input = page.get_by_label("Password", exact=True)
        await password_input.fill(cfg.password)
        await page.get_by_role("button", name="Log in").click()
        await asyncio.sleep(3)

        # TOTP 2FA
        if cfg.totp_secret:
            totp_input = page.locator('input[data-testid="ocfEnterTextTextInput"]')
            if await totp_input.count() > 0:
                import pyotp
                code = pyotp.TOTP(cfg.totp_secret).now()
                await totp_input.fill(code)
                await page.get_by_role("button", name="Next").click()
                await asyncio.sleep(3)

        # Verify we're logged in
        if "login" in page.url or "i/flow/login" in page.url:
            raise RuntimeError("Login failed — check your credentials in .env")

        # Save session cookies
        await self.context.storage_state(path=str(self._config.session_file))

    async def close(self) -> None:
        if self.context:
            await self.context.storage_state(path=str(self._config.session_file))
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
