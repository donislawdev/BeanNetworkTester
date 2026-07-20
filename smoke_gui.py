# GUI smoke test with a fake tkinter (CI containers have no real Tk).
# Verifies: the App builds in PL and EN, a language switch rebuilds the UI while
# keeping settings AND the session state, the tick loop runs, no raw translation
# keys leak into widget texts, profiles behave, CSV export rotates a stale header.
import os
import re
import sys

# This script prints Polish text (a validation message contains "musi byc liczba"
# with diacritics). On Windows the console defaults to cp1252, which cannot encode
# 'c-acute', and the whole smoke run died with UnicodeEncodeError *while printing a
# PASS line*. Force UTF-8 so the output can carry any language it tests.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):     # very old Python / already-wrapped stream
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

import fake_tk                                    # noqa: E402

tk = fake_tk.install()

import bean_network_tester as n                   # noqa: E402  (after the fakes)

fails = []


def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}]  {name} {detail}")
    if not cond:
        fails.append(name)


RAW_KEY = re.compile(r"^(app|buttons|chart|conns|dialogs|errors|events|fields|"
                     r"filters|frames|log|menu|presets|profiles|session|stats|"
                     r"summary|tips)\.[a-z0-9_]+$")


def leaked_keys(root):
    return [t for t in fake_tk.texts(root) if RAW_KEY.match(t.strip())]


# -- build in Polish ---------------------------------------------------------
n.set_language("pl")
root = tk.Tk()
app = n.App(root)
check("GUI: App builds with the fake tkinter (PL)", True)
check("GUI: language selector lists discovered languages",
      set(app._lang_name2code.values()) == {"en", "pl"}, f"({app._lang_name2code})")

# -- no raw translation keys in widget texts (regression: missing T()) -------
check("GUI: widget texts are translated (no raw i18n keys)", not leaked_keys(root),
      f"({sorted(set(leaked_keys(root)))[:8]})")

# -- tick loop + widget refreshers -------------------------------------------
app._tick()
for page in ("statistics", "connections", "control"):
    app.select_page(page)
    app._tick()
check("GUI: _tick() runs on every page (stats, chart, tables, summary)", True)

# -- worker-thread logging goes through the queue, never straight to widgets --
import threading as _threading                    # noqa: E402
_t = _threading.Thread(target=lambda: app.log("worker-thread line"))
_t.start(); _t.join()
check("GUI: worker-thread log is queued, not applied immediately",
      not any("worker-thread line" in l for l in app._log_lines))
app._tick()
check("GUI: queued worker-thread log appears after a main-thread tick",
      any("worker-thread line" in l for l in app._log_lines))

# -- settings round-trip through the widgets ---------------------------------
# the form starts on "Perfect network": nothing is impaired until the user says so
s = app._settings_from_widgets()
check("GUI: the form starts on a perfect link",
      s["latency"] == 0.0 and s["jitter"] == 0.0 and s["loss"] == 0.0
      and s["filter"] == "both",
      f"(lat={s['latency']}, loss={s['loss']}, filter={s['filter']})")
app.vars["latency"].set("100")
s = app._settings_from_widgets()
check("GUI: settings read from widgets", s["latency"] == 100.0, f"(lat={s['latency']})")
app.vars["latency"].set("0")

# -- translated exception from a widget field --------------------------------
app.loss_var.set("abc")
try:
    app._settings_from_widgets()
    check("GUI: invalid field raises", False)
except ValueError as e:
    check("GUI: invalid field raises a translated (PL) message",
          "musi być liczbą" in str(e) and "Utrata" in str(e), f"({e})")
app.loss_var.set("250")
try:
    app._settings_from_widgets()
    check("GUI: out-of-range field raises", False)
except ValueError as e:
    check("GUI: out-of-range field raises a translated range error",
          "zakresie" in str(e), f"({e})")
app.loss_var.set("1")

# -- language switch (PL -> EN) keeps settings and rebuilds ------------------
app.down_var.set("512")
app.lang_var.set("English")
app._switch_language()
check("GUI: language switch rebuilds into English", app._lang == "en")
check("GUI: settings survive the language switch", float(app.down_var.get()) == 512.0,
      f"(down={app.down_var.get()})")
check("GUI: no raw i18n keys after the language switch", not leaked_keys(root),
      f"({sorted(set(leaked_keys(root)))[:8]})")
try:
    app.loss_var.set("abc")
    app._settings_from_widgets()
except ValueError as e:
    check("GUI: exception now in English", "must be a number" in str(e), f"({e})")
app.loss_var.set("1")

# -- switch back to Polish ----------------------------------------------------
app.lang_var.set("Polski")
app._switch_language()
check("GUI: switch back to Polish", app._lang == "pl")

# -- profiles: scope warning, reserved names ----------------------------------
# (the app uses its own themed dialogs, not the native white message boxes)
import beantester.gui.dialogs as _dlg             # noqa: E402
warnings, errors = [], []
_dlg.show_warning = lambda parent, title, msg: warnings.append((title, msg))
_dlg.show_error = lambda parent, title, msg: errors.append((title, msg))
app.profiles.persist = lambda: None               # no file writes from the smoke run

app.rst_var.set("5")                              # active setting outside profile scope
_dlg.ask_string = lambda *a, **k: None            # user cancels the name dialog
app._save_profile()
check("GUI: profile save warns about out-of-scope settings",
      len(warnings) == 1 and app._short_label("fields.rst") in warnings[0][1],
      f"({warnings})")
check("GUI: cancelled name dialog saves nothing", not app.profiles.names())

app.rst_var.set("0")
warnings.clear()
_dlg.ask_string = lambda *a, **k: n.T("presets.terrible")  # preset name (PL)
app._save_profile()
check("GUI: no scope warning when only profile fields are set", not warnings)
check("GUI: preset name is rejected for a user profile",
      len(errors) == 1 and not app.profiles.names(), f"({errors})")

_dlg.ask_string = lambda *a, **k: "Moje VPN"
app._save_profile()
check("GUI: valid profile name is saved", app.profiles.names() == ["Moje VPN"])

check("GUI: the picker offers presets then own profiles, nothing else",
      app._profile_names() == [n.T(k) for k in n.PRESETS] + ["Moje VPN"],
      f"({app._profile_names()[-3:]})")

# -- preset only fills the form; it never applies by itself -------------------
app.profile_var.set(n.T("presets.terrible"))
app._load_selected_profile()
check("GUI: picking a preset fills the form",
      float(app.loss_var.get()) == 10.0 and float(app.lat_var.get()) == 300.0,
      f"(loss={app.loss_var.get()}, lat={app.lat_var.get()})")

# -- CSV export: stale header rotates the old file, never misaligns rows ------
import csv as _csv                                # noqa: E402
import tempfile as _tempfile                      # noqa: E402
import beantester.gui.app as _appmod              # noqa: E402
_tmpdir = _tempfile.mkdtemp()
_appmod.CSV_FILE = os.path.join(_tmpdir, "stats.csv")
app._export_csv()
app._export_csv()                                 # same header -> plain append
with open(_appmod.CSV_FILE, newline="", encoding="utf-8") as _f:
    _rows = list(_csv.reader(_f))
check("GUI: CSV append keeps a single current header",
      len(_rows) == 3 and _rows[0][:2] == ["time", "packets_seen"], f"({_rows[:1]})")
with open(_appmod.CSV_FILE, "w", encoding="utf-8") as _f:
    _f.write("time,old_col\n1,2\n")               # legacy column layout
app._export_csv()
_rotated = [x for x in os.listdir(_tmpdir) if x != "stats.csv"]
with open(_appmod.CSV_FILE, newline="", encoding="utf-8") as _f:
    _first = next(_csv.reader(_f), [])
check("GUI: CSV with a stale header is rotated aside and restarted",
      len(_rotated) == 1 and _first[:2] == ["time", "packets_seen"], f"(rotated={_rotated})")

# -- no raw translation keys or ASCII-Polish leaking into the log -------------
joined = "\n".join(app._log_lines)
leaks = [w for w in ("tips.", "frames.", "buttons.", "zaklocen", "Jezyk") if w in joined]
check("GUI: log has no raw keys / legacy ASCII-Polish", not leaks, f"({leaks})")

print()
print(f"GUI smoke: {'OK' if not fails else f'{len(fails)} FAIL'}")
sys.exit(1 if fails else 0)
