#!/usr/bin/env python3
"""Headed GUI render check on real Tk (CI, under a virtual display).

The fake-tk smoke (smoke_gui.py) cannot see truncation or DPI/layout breakage: it
records geometry calls but never lays anything out with real font metrics. This
script builds the REAL App at the minimum supported resolution (1366x768) in every
shipped language, visits every page and opens the About window, and fails if any
BUTTON is clipped (rendered narrower than it asks for). That is the "Wesprzyj
projekt" -> "Wesp" class of regression: it only appears with real fonts and the
longer Polish strings, so example-based tests stay green while the UI is broken.

Truncated wrapping labels (long About-box prose) are reported for the human but do
NOT fail the run - they legitimately wrap when given less width.

Usage:
    python tools/ci_gui_render.py            # all discovered languages
    python tools/ci_gui_render.py --lang pl  # one language

Needs a display. In CI:
    xvfb-run -a --server-args="-screen 0 1366x768x24" python tools/ci_gui_render.py

Set BEAN_NO_ELEVATE=1 so the app never tries to elevate.
"""
import os
import sys

os.environ.setdefault("BEAN_NO_ELEVATE", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import tkinter as tk                                 # noqa: E402

import bean_network_tester as n                      # noqa: E402

GEOMETRY = "1366x768"
BUTTON_CLASSES = ("TButton", "Button")
LABEL_CLASSES = ("TLabel", "Label")
TOL = 1                                               # px slack against rounding


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _text(widget):
    try:
        return str(widget.cget("text")) if "text" in widget.keys() else ""
    except tk.TclError:
        return ""


def _clip(widget):
    """Return (req, got) when the widget is rendered narrower than it asks for."""
    try:
        got, req = widget.winfo_width(), widget.winfo_reqwidth()
    except tk.TclError:
        return None
    if got <= 1 or got >= req - TOL:
        return None
    return req, got


def _scan(root):
    buttons, labels = [], []
    for widget in _walk(root):
        try:
            if not widget.winfo_ismapped():
                continue
            cls = widget.winfo_class()
        except tk.TclError:
            continue
        is_button = cls in BUTTON_CLASSES
        if not is_button and cls not in LABEL_CLASSES:
            continue
        text = _text(widget).strip()
        if not text or "\n" in text:            # multi-line text wraps by design
            continue
        clip = _clip(widget)
        if not clip:
            continue
        req, got = clip
        (buttons if is_button else labels).append((text, req, got))
    return buttons, labels


def _cancel_afters(root):
    """Drop pending after() callbacks so teardown does not spew Tcl errors."""
    try:
        for aid in root.tk.eval("after info").split():
            try:
                root.after_cancel(aid)
            except tk.TclError:
                pass
    except tk.TclError:
        pass


def check_language(code):
    n.set_language(code)
    root = tk.Tk()
    root.geometry(GEOMETRY)
    app = n.App(root)
    root.update_idletasks()
    root.update()

    buttons, labels = [], []
    for page in ("control", "statistics", "connections"):
        app.select_page(page)
        root.update_idletasks()
        root.update()
        b, l = _scan(root)
        buttons += b
        labels += l
    try:
        app.open_window("about")
        root.update_idletasks()
        root.update()
        b, l = _scan(root)
        buttons += b
        labels += l
    except Exception as exc:                     # noqa: BLE001 - report, keep going
        print(f"  [{code}] could not open the About window: {exc}")

    buttons = sorted(set(buttons))
    labels = sorted(set(labels))
    for text, req, got in labels:
        print(f"  [{code}] note: label narrower than requested "
              f"(req={req} got={got}): {text!r}")
    for text, req, got in buttons:
        print(f"  [{code}] CLIPPED BUTTON (req={req} got={got}): {text!r}")
    ok = not buttons
    print(f"  [{code}] {'OK' if ok else f'{len(buttons)} clipped button(s)'}")

    # Teardown is best-effort: the result above is already computed, and a noisy
    # Tk destroy (registered windows, scheduled callbacks) must never fail the run.
    _cancel_afters(root)
    try:
        root.destroy()
    except tk.TclError:
        pass
    return ok


def main(argv):
    if "--lang" in argv:
        i = argv.index("--lang")
        code = argv[i + 1] if i + 1 < len(argv) else "en"
        return 0 if check_language(code) else 1

    # Discover languages and run each in its own process, so a fragile Tk teardown
    # in one language cannot leak into the next.
    import subprocess
    langs = [code for code, _name in n.available_languages()]
    print(f"GUI render check on real Tk at {GEOMETRY} for: {', '.join(langs)}")
    ok = True
    for code in langs:
        rc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--lang", code]
        ).returncode
        ok = (rc == 0) and ok
    print(f"GUI render: {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
