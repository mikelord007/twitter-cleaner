from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import BrowserContext, Page, async_playwright

from twitter_cleaner.config import Config


class TwitterSession:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def start(self) -> Page:
        self._playwright = await async_playwright().start()

        # Use a persistent profile directory so the browser accumulates real
        # cookies and state — much harder for Twitter to flag as a bot.
        profile_dir = str(self._config.state_dir / "chrome_profile")

        self.context = await self._playwright.chromium.launch_persistent_context(
            profile_dir,
            channel="chrome",        # use the user's real installed Chrome
            headless=False,          # must be visible for manual login
            viewport={"width": 1280, "height": 800},
            args=["--disable-blink-features=AutomationControlled"],
        )

        # Hide the webdriver flag.
        await self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Reuse the first tab Playwright opens automatically; close any extras.
        pages = self.context.pages
        if pages:
            self.page = pages[0]
            for p in pages[1:]:
                await p.close()
        else:
            self.page = await self.context.new_page()
        await self._ensure_logged_in()
        return self.page

    async def _ensure_logged_in(self) -> None:
        page = self.page
        await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)

        if "login" in page.url or "i/flow/login" in page.url:
            await self._manual_login()

    async def _manual_login(self) -> None:
        page = self.page
        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30000)

        print("\n" + "-" * 60)
        print("  Log in to Twitter/X in the browser window that just opened.")
        print("  Complete any 2FA or verification steps as usual.")
        print("  This window will close automatically once you're logged in.")
        print("-" * 60 + "\n")

        # Poll until the URL leaves the login flow (up to 5 minutes).
        for _ in range(300):
            await asyncio.sleep(1)
            url = page.url
            if "login" not in url and "i/flow" not in url and "x.com" in url:
                break
        else:
            raise RuntimeError("Login timed out after 5 minutes.")

        await asyncio.sleep(2)

        if "login" in page.url or "i/flow" in page.url:
            raise RuntimeError("Login did not complete -- please try again.")

        print("Logged in. Session will persist in the Chrome profile.\n")

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self._playwright:
            await self._playwright.stop()
