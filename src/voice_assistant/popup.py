"""An on-screen card showing a Snapchat message while it's being sent.

The window is drawn with GTK by Ubuntu's own Python (/usr/bin/python3, which has
GTK built in) in a separate process, so it keeps drawing while the assistant is
busy listening or driving the browser. The assistant sends it JSON lines on stdin
to change what it shows. This file only uses the standard library plus GTK, so it
can run as a plain script.
"""

import json
import subprocess
import sys
import threading
from pathlib import Path

SYSTEM_PYTHON = "/usr/bin/python3"
WIDTH = 440

# Old green-screen terminal: phosphor green text that glows, amber highlights,
# and faint CRT scanlines over a near-black background.
GREEN = "#33ff66"
CSS = b"""
* { font-family: "Ubuntu Mono", "DejaVu Sans Mono", monospace; }
label { text-shadow: 0 0 6px rgba(51, 255, 102, 0.55); }
.card {
    background-color: #050a06;
    background-image: repeating-linear-gradient(to bottom, rgba(0, 0, 0, 0) 0px, rgba(0, 0, 0, 0) 2px,
                                                rgba(0, 0, 0, 0.45) 2px, rgba(0, 0, 0, 0.45) 4px);
    border: 2px solid #33ff66;
    box-shadow: inset 0 0 18px rgba(51, 255, 102, 0.18);
    padding: 12px 18px 14px 18px;
}
.heading { color: #1f9e3f; font-size: 11pt; }
.to-label { color: #1f9e3f; font-size: 13pt; }
.to { color: #ffb000; font-weight: 700; font-size: 14pt; text-shadow: 0 0 6px rgba(255, 176, 0, 0.6); }
.message { color: #33ff66; font-size: 14pt; }
.status { font-weight: 700; font-size: 13pt; }
.waiting { color: #ffb000; text-shadow: 0 0 6px rgba(255, 176, 0, 0.6); }
.working { color: #1f9e3f; }
.done { color: #33ff66; }
.failed { color: #ff4040; text-shadow: 0 0 6px rgba(255, 64, 64, 0.6); }
"""


class SendPopup:
    """Used by the assistant. Each method updates the card; it closes by itself after
    `finish`, or straight away if the assistant goes away."""

    def __init__(self, to: str, message: str):
        self.proc = subprocess.Popen([SYSTEM_PYTHON, str(Path(__file__))], stdin=subprocess.PIPE, text=True)
        self._send({"to": to, "message": message, "status": "Finding chat…", "state": "working"})

    def update(self, status: str, state: str = "working", to: str | None = None):
        self._send({"status": status, "state": state, **({"to": to} if to else {})})

    def finish(self, status: str, state: str, close_after: float = 2.5):
        self._send({"status": status, "state": state, "close_after": int(close_after * 1000)})
        try:
            self.proc.stdin.close()
        except OSError:
            pass

    def _send(self, update: dict):
        try:
            self.proc.stdin.write(json.dumps(update) + "\n")
            self.proc.stdin.flush()
        except OSError:
            pass  # the window failed to open; sending carries on without it


def _run_window():
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    style = Gtk.CssProvider()
    style.load_from_data(CSS)

    # A POPUP window has no title bar and doesn't take keyboard focus.
    window = Gtk.Window(type=Gtk.WindowType.POPUP)
    window.set_keep_above(True)
    window.set_default_size(WIDTH, -1)
    screen = window.get_screen()
    Gtk.StyleContext.add_provider_for_screen(screen, style, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def label(css_class: str, **kwargs) -> Gtk.Label:
        widget = Gtk.Label(xalign=0, **kwargs)
        widget.get_style_context().add_class(css_class)
        return widget

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    card.get_style_context().add_class("card")
    card.set_size_request(WIDTH, -1)
    card.pack_start(label("heading", label="C:\\> SNAPCHAT.EXE /SEND"), False, False, 0)
    to_row = Gtk.Box(spacing=8)
    to_row.pack_start(label("to-label", label="TO:"), False, False, 0)
    to_label = label("to", wrap=True, max_width_chars=30)
    to_row.pack_start(to_label, False, False, 0)
    card.pack_start(to_row, False, False, 0)
    message_label = label("message", wrap=True, max_width_chars=40)
    message_label.set_line_wrap_mode(2)  # wrap long words too
    card.pack_start(message_label, False, False, 0)
    status_label = label("status")
    card.pack_start(status_label, False, False, 0)
    window.add(card)

    close_after = {"ms": 0}
    status = {"text": "", "cursor": True}

    def show_status():
        status_label.set_text(f"[ {status['text']} ]" + (" █" if status["cursor"] else ""))

    def blink():
        status["cursor"] = not status["cursor"]
        show_status()
        return True

    GLib.timeout_add(500, blink)

    def apply(update: dict):
        if "to" in update:
            to_label.set_text(update["to"].upper())
        if "message" in update:
            message_label.set_text(f"> {update['message']}")
        if "status" in update:
            status["text"] = update["status"].upper().replace("…", "...")
            show_status()
            context = status_label.get_style_context()
            for state in ("waiting", "working", "done", "failed"):
                context.remove_class(state)
            context.add_class(update.get("state", "working"))
        if "close_after" in update:
            close_after["ms"] = update["close_after"]
        if update.get("stdin_closed"):
            GLib.timeout_add(close_after["ms"], Gtk.main_quit)
            return False
        window.resize(WIDTH, 1)  # shrink to fit the new text
        if not window.get_visible():
            window.show_all()
            display = window.get_screen().get_display()
            geometry = (display.get_primary_monitor() or display.get_monitor(0)).get_geometry()
            window.move(geometry.x + (geometry.width - WIDTH) // 2, geometry.y + 48)
        return False

    def read_stdin():
        for line in sys.stdin:
            GLib.idle_add(apply, json.loads(line))
        GLib.idle_add(apply, {"stdin_closed": True})

    threading.Thread(target=read_stdin, daemon=True).start()
    Gtk.main()


if __name__ == "__main__":
    _run_window()
