"""Sends Snapchat chats by driving Snapchat for Web (https://www.snapchat.com/web)
in a real browser with Playwright. Snapchat has no public messaging API, so this is
the only option. You log in once with `voice-assistant snapchat-login`; the browser
profile is saved so later sends are already logged in.

Snapchat changes its website from time to time. If sending stops working, the
selectors below are the place to look.
"""

import re
from difflib import SequenceMatcher

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
# How closely a spoken name must match a Snapchat name (0 to 1).
MIN_NAME_SIMILARITY = 0.75


class SnapchatError(Exception):
    """An error with a message that's fine to read out to the user."""


class Snapchat:
    def __init__(self, config: dict):
        self.config = config["snapchat"]
        self._playwright = None
        self._context = None
        self._context_closed = False
        self._open_name = None

    def _browser(self, minimized: bool = True):
        """The assistant's Chrome window. It's opened once and then kept running in the
        background, so later messages reuse it. If you close it, it reopens next time."""
        if self._context is not None:
            if not self._context_closed:
                return self._context
            self.close()
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        options = {"headless": self.config["headless"], "viewport": {"width": 1200, "height": 800}}
        if self.config["browser_channel"]:
            options["channel"] = self.config["browser_channel"]
        if minimized:
            # Keep working normally while minimised; Chrome otherwise slows hidden windows down.
            options["args"] = [
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
            ]
        self._context = self._playwright.chromium.launch_persistent_context(str(PROFILE_DIR), **options)
        self._context_closed = False
        self._context.on("close", lambda _: setattr(self, "_context_closed", True))
        if minimized:
            _minimize(self._context)
        return self._context

    def _page(self, minimized: bool = True):
        context = self._browser(minimized)
        # Use one Snapchat tab and close any others.
        page = context.pages[0] if context.pages else context.new_page()
        for extra in context.pages[1:]:
            extra.close()
        if not page.url.startswith(SNAPCHAT_URL):
            page.goto(SNAPCHAT_URL)
        page.wait_for_load_state("domcontentloaded")
        return page

    def login(self):
        """Opens Snapchat Web so you can log in. Close the window when you're done."""
        page = self._page(minimized=False)
        print("Log in to Snapchat in the browser window, then close the window.")
        page.wait_for_event("close", timeout=0)
        self.close()

    def resolve_name(self, spoken: str) -> str:
        spoken = re.sub(r"^my ", "", spoken.strip().lower())
        contacts = {k.lower(): v for k, v in self.config["contacts"].items()}
        return contacts.get(spoken, spoken)

    def open_chat(self, who: str) -> str:
        """Opens the chat with `who` and returns their name as shown on Snapchat."""
        page = self._page()
        if "accounts.snapchat.com" in page.url:
            raise SnapchatError("You're not logged in to Snapchat. Run voice assistant snapchat login.")
        self._open_name = self._open_chat(page, self.resolve_name(who))
        return self._open_name

    def send_to_open_chat(self, message: str) -> str:
        """Sends `message` to the chat opened by `open_chat`."""
        page = self._page()
        name = self._open_name
        if not _chat_title_is(page, name):
            raise SnapchatError(f"The chat with {name} isn't open any more, so I didn't send it.")
        box = _first_visible(page, MESSAGE_BOX_SELECTORS, timeout=8000)
        if box is None:
            raise SnapchatError(f"I opened the chat with {name} but couldn't find the message box.")
        box.focus()  # focus rather than click, so the window stays minimised
        page.keyboard.type(message, delay=15)
        page.keyboard.press("Enter")
        page.wait_for_timeout(1000)
        return f"Sent to {name}."

    def _open_chat(self, page, wanted: str) -> str:
        """Opens the chat whose name best matches `wanted` and returns its real name.
        Speech recognition often misspells names ("Ruben" for "Reuben"), so names are
        matched loosely, then the open chat's title is checked before anything is typed."""
        search = _first_visible(page, SEARCH_BOX_SELECTORS, timeout=8000)
        if search is None:
            raise SnapchatError("I couldn't find the Snapchat search box. Are you logged in?")

        # Recent chats first, then search by the full name and by each word in it
        # (searching "marshall" finds "Reuben Marshall" even if "Ruben" doesn't).
        words = sorted({w for w in wanted.split() if len(w) >= 3}, key=len, reverse=True)
        for query in ["", wanted, *words]:
            search.fill(query)
            page.wait_for_timeout(2500)
            match = _best_match(page, wanted)
            if match is None:
                continue
            item, name = match
            if not _chat_title_is(page, name, timeout=0):  # clicking an open chat closes it
                _press(item.get_by_text(name, exact=True).first)
                if not _chat_title_is(page, name, timeout=3000):
                    # Snapchat ignored the simulated click; a real one un-minimises the window.
                    item.click()
                    _minimize(self._context)
            if not _chat_title_is(page, name):
                raise SnapchatError(f"I tried to open the chat with {name} but a different chat opened, so I didn't send it.")
            return name
        raise SnapchatError(f"I couldn't find {wanted} in your Snapchat friends.")

    def close(self):
        try:
            if self._context is not None:
                self._context.close()
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:
            pass
        self._context = self._playwright = None


def _minimize(context):
    """Minimises the browser window (Chrome ignores --start-minimized on Linux)."""
    page = context.pages[0] if context.pages else context.new_page()
    cdp = context.new_cdp_session(page)
    window = cdp.send("Browser.getWindowForTarget")["windowId"]
    cdp.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "minimized"}})
    cdp.detach()


def _press(locator):
    """Clicks an element with simulated mouse events. A real click would bring the
    minimised window back up."""
    for event in ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]:
        locator.dispatch_event(event, {"bubbles": True, "button": 0})


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


def _simplify(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())


def _similarity(wanted: str, name: str) -> float:
    """How well a spoken name matches a Snapchat name, 0 to 1. Saying only some of
    the name counts, so "reuben" and "reuben marshall" both match
    "Reuben Louis Harrison Marshall"."""
    wanted, name = _simplify(wanted), _simplify(name)
    if not wanted or not name:
        return 0.0
    whole = SequenceMatcher(None, wanted, name).ratio()
    # Each spoken word against its closest word in the name.
    name_words = name.split()
    by_word = sum(
        max(SequenceMatcher(None, word, other).ratio() for other in name_words) for word in wanted.split()
    ) / len(wanted.split())
    return max(whole, by_word)


def _best_match(page, wanted: str):
    """The chat list entry that best matches `wanted`, as (locator, name), or None.
    Only real chat entries are considered, never the "Ask My AI" suggestion."""
    items = page.locator("nav [role='listitem']").filter(visible=True)
    best = None
    for i in range(items.count()):
        item = items.nth(i)
        try:
            lines = [line.strip() for line in item.inner_text(timeout=1000).split("\n")]
        except Exception:
            continue
        # Each entry has a display name and maybe a username. Group chats list their
        # members separated by commas, which we skip so a group isn't mistaken for a person.
        names = [line for line in lines if re.search(r"[A-Za-z]", line) and "," not in line][:2]
        for name in names:
            score = _similarity(wanted, name)
            if score >= MIN_NAME_SIMILARITY and (best is None or score > best[0]):
                best = (score, item, names[0])
    return None if best is None else best[1:]


def _chat_title_is(page, name: str, timeout: int = 5000) -> bool:
    """Whether the open chat's title (top of the right-hand side) is `name`,
    waiting up to `timeout` ms for it to appear."""
    for _ in range(max(1, timeout // 250)):
        if page.evaluate(
            """(name) => [...document.querySelectorAll('body *')].some(e =>
                e.children.length === 0 && e.textContent.trim() === name && !e.closest('nav')
                && e.getBoundingClientRect().top < 120 && e.offsetParent !== null)""",
            name,
        ):
            return True
        page.wait_for_timeout(250)
    return False
