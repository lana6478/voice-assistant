"""Sends Snapchat chats by driving Snapchat for Web (https://www.snapchat.com/web)
in a real browser with Playwright. Snapchat has no public messaging API, so this is
the only option. You log in once with `voice-assistant snapchat-login`; the browser
profile is saved so later sends are already logged in.

Snapchat changes its website from time to time. If sending stops working, the
selectors below are the place to look.
"""

import re

from .config import DATA_DIR

SNAPCHAT_URL = "https://www.snapchat.com/web"
PROFILE_DIR = DATA_DIR / "snapchat-profile"

# Tried in order until one is found.
SEARCH_BOX_SELECTORS = [
    "input[placeholder*='Search' i]",
    "[role='searchbox']",
    "input[type='search']",
]
MESSAGE_BOX_SELECTORS = [
    "[placeholder*='Send a chat' i]",
    "[aria-label*='Send a chat' i]",
    "div[contenteditable='true']",
    "textarea",
]


class SnapchatError(Exception):
    """An error with a message that's fine to read out to the user."""


class Snapchat:
    def __init__(self, config: dict):
        self.config = config["snapchat"]
        self._playwright = None
        self._context = None

    def _browser(self):
        if self._context is not None:
            try:
                self._context.pages  # raises if the window was closed
                return self._context
            except Exception:
                self.close()
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        options = {"headless": self.config["headless"], "viewport": {"width": 1200, "height": 800}}
        if self.config["browser_channel"]:
            options["channel"] = self.config["browser_channel"]
        self._context = self._playwright.chromium.launch_persistent_context(str(PROFILE_DIR), **options)
        return self._context

    def _page(self):
        context = self._browser()
        page = context.pages[0] if context.pages else context.new_page()
        if not page.url.startswith(SNAPCHAT_URL):
            page.goto(SNAPCHAT_URL)
        page.wait_for_load_state("domcontentloaded")
        return page

    def login(self):
        """Opens Snapchat Web so you can log in. Close the window when you're done."""
        page = self._page()
        print("Log in to Snapchat in the browser window, then close the window.")
        page.wait_for_event("close", timeout=0)
        self.close()

    def resolve_name(self, spoken: str) -> str:
        spoken = re.sub(r"^my ", "", spoken.strip().lower())
        contacts = {k.lower(): v for k, v in self.config["contacts"].items()}
        return contacts.get(spoken, spoken)

    def send(self, who: str, message: str) -> str:
        name = self.resolve_name(who)
        page = self._page()
        if "accounts.snapchat.com" in page.url:
            raise SnapchatError("You're not logged in to Snapchat. Run voice assistant snapchat login.")

        self._open_chat(page, name)
        box = _first_visible(page, MESSAGE_BOX_SELECTORS, timeout=8000)
        if box is None:
            raise SnapchatError(f"I opened the chat with {name} but couldn't find the message box.")
        box.click()
        page.keyboard.type(message, delay=15)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        return f"Sent to {name}."

    def _open_chat(self, page, name: str):
        name_pattern = re.compile(rf"^\s*{re.escape(name)}\s*$", re.I)

        # Recent chats are listed on the left; try clicking the name directly first.
        entry = page.get_by_text(name_pattern).first
        try:
            entry.wait_for(state="visible", timeout=6000)
            entry.click()
            return
        except Exception:
            pass

        # Otherwise search for them.
        search = _first_visible(page, SEARCH_BOX_SELECTORS, timeout=3000)
        if search is None:
            raise SnapchatError(f"I couldn't find {name} in your chats. Are you logged in to Snapchat?")
        search.click()
        search.fill(name)
        result = page.get_by_text(re.compile(re.escape(name), re.I)).first
        try:
            result.wait_for(state="visible", timeout=6000)
        except Exception:
            raise SnapchatError(f"I couldn't find anyone called {name} on Snapchat.")
        result.click()

    def close(self):
        try:
            if self._context is not None:
                self._context.close()
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._context = self._playwright = None


def _first_visible(page, selectors: list[str], timeout: int):
    """Returns the first visible element matching any of the selectors, or None."""
    combined = page.locator(", ".join(selectors)).filter(visible=True).first
    try:
        combined.wait_for(state="visible", timeout=timeout)
    except Exception:
        return None
    for selector in selectors:
        locator = page.locator(selector).filter(visible=True)
        if locator.count():
            return locator.first
    return combined
