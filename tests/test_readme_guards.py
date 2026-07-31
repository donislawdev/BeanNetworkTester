"""Docs guards for the two README parts that are NOT generated and drifted.

``test_cli_docs`` already pins the CLI flag tables to the parser. These two guard
the other hand-maintained mirrors of the code:

  1. the "Project layout" tree - every top-level module must be listed, in both
     READMEs. It fell behind reality (a whole ``gui/panels/`` subpackage plus
     ``model_worker.py`` / ``windows.py`` / ``crashlog.py`` and others existed
     but were unlisted) because nothing checked it.
  2. the "How it works" pipeline - prose that restates the numbered order in
     ``BeanCore.decide()``. It lost the LAN-mode and blocking steps once; this
     ties the English wording back to the docstring so a reorder goes red.
  3. the ``--preset`` id list - a hand-typed mirror of ``PRESETS``. Five presets
     were added in one sitting and the only thing standing between the docs and
     a stale list was remembering to edit two files.
"""
import ast
import glob
import os
import re

from fakes import ROOT, check

READMES = ("README.md", "README.pl.md")


def _read(name):
    return open(os.path.join(ROOT, name), encoding="utf-8").read()


def _top_level_modules():
    """Basenames of the modules the layout lists individually (dunders and the
    ``pages``/``panels``/``widgets`` subpackages, shown by directory, excluded)."""
    paths = glob.glob(os.path.join(ROOT, "beantester", "*.py"))
    paths += glob.glob(os.path.join(ROOT, "beantester", "gui", "*.py"))
    return sorted(os.path.basename(p) for p in paths
                  if os.path.basename(p) not in ("__init__.py", "__main__.py"))


def test_project_layout_lists_every_module():
    mods = _top_level_modules()
    for readme in READMES:
        text = _read(readme)
        missing = [m for m in mods if m not in text]
        check(f"{readme} 'Project layout' lists every top-level module",
              not missing, f"(missing: {missing})")


# Mechanism keywords that appear verbatim in BOTH the core docstring and the
# README prose, in pipeline order. Latency and bandwidth are paraphrased
# differently on each side (latency/delay, bandwidth/throughput), so they are not
# pinned by name - their neighbours bracket them.
PIPELINE = ("targeting", "LAN", "blocking", "NAT", "RST", "flapping", "MTU",
            "SYN", "loss", "corruption", "duplication")


def _keyword_order(text):
    """The PIPELINE keywords present in ``text``, in first-occurrence order."""
    seen = [(text.find(w), w) for w in PIPELINE if text.find(w) >= 0]
    return [w for _, w in sorted(seen)]


def _section(text, heading):
    """The body of a ``## heading ...`` section, up to the next ``## ``."""
    m = re.search(r"(?m)^## " + re.escape(heading) + r".*$", text)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"(?m)^## ", rest)
    return rest[:nxt.start()] if nxt else rest


def _core_pipeline_order():
    doc = ast.get_docstring(ast.parse(
        _read(os.path.join("beantester", "core.py"))))
    return _keyword_order(doc or "")


def test_english_readme_pipeline_matches_core_decide():
    core = _core_pipeline_order()
    readme = _keyword_order(_section(_read("README.md"), "How it works"))
    check("README.md 'How it works' order matches BeanCore.decide()",
          core == readme, f"(core={core} readme={readme})")


def test_both_readmes_list_every_preset_id():
    """The ``--preset`` id list is typed by hand in both READMEs.

    It is the same failure shape as the project layout above: a registry with a
    prose mirror and nothing tying the two together. A missing id is worse than
    a cosmetic gap, because the list is what a reader copies into a script -
    a preset absent from it effectively does not exist.

    Extras are checked too: an id that was renamed away leaves a line pointing
    at a ``--preset`` value the CLI now rejects.
    """
    from beantester.presets import PRESETS
    ids = set(PRESETS)
    for readme in READMES:
        found = set(re.findall(r"`(presets\.[a-z0-9_]+)`", _read(readme)))
        check(f"{readme} lists every preset id", not (ids - found),
              f"(missing: {sorted(ids - found)})")
        check(f"{readme} lists no preset id that no longer exists",
              not (found - ids), f"(stale: {sorted(found - ids)})")


def test_both_readmes_document_every_csv_column():
    """The two CSV headers are registries with a hand-typed mirror in the docs.

    A CSV column nobody documented is worse than an undocumented GUI column: the
    GUI has a tooltip on every header, a CSV has nothing but the word itself, and
    the connections export deliberately does NOT reuse the table's labels
    (``impaired`` for "impaired?", ``delivered_down_bytes`` for "down[KB]").
    """
    from beantester.gui.app import App
    names = set(App.CONN_CSV_HEADER)
    names |= {App.CSV_COLUMNS.get(k, k) for k in App.CSV_COLUMNS}
    for readme in READMES:
        text = _read(readme)
        missing = sorted(n for n in names if n not in text)
        check(f"{readme} documents every CSV column", not missing,
              f"(missing: {missing})")


def test_both_readmes_document_every_connections_column():
    """Same rule for the table itself: 17 columns, all sortable, all explained.

    The check is on the i18n LABEL rather than the internal key, because the
    label is what the reader sees in the app and has to find in the docs.
    """
    import json
    import os as _os
    from beantester.gui.pages.conns import COLUMNS
    for readme, lang in zip(READMES, ("en", "pl")):
        with open(_os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as f:
            names = json.load(f)
        text = _read(readme)
        missing = sorted(names[key] for key in COLUMNS.values()
                         if names[key] not in text)
        check(f"{readme} documents every Connections column", not missing,
              f"(missing: {missing})")


def test_both_readmes_list_every_scenario_action_and_shipped_file():
    """The action list is two entries and the shipped set is seven files; both are
    exactly the kind of thing that grows once and is never written down."""
    import glob
    import os as _os
    from beantester.scenario import ACTIONS, FILE_KEYS, STEP_KEYS
    files = sorted(_os.path.basename(p)
                   for p in glob.glob(_os.path.join(ROOT, "scenarios", "*.json")))
    for readme in READMES:
        text = _read(readme)
        for name, items in (("action", ACTIONS), ("step key", STEP_KEYS),
                            ("file key", FILE_KEYS)):
            missing = [i for i in items if f"`{i}`" not in text]
            check(f"{readme} documents every scenario {name}", not missing,
                  f"(missing: {missing})")
        missing_files = [f for f in files if f not in text]
        check(f"{readme} describes every shipped scenario", not missing_files,
              f"(missing: {missing_files})")


def test_polish_readme_pipeline_keeps_lan_and_blocking():
    """The regression that happened: the PL brief skipped LAN mode and blocking."""
    sec = _section(_read("README.pl.md"), "Jak to działa")
    order = [w for _, w in sorted((sec.find(w), w) for w in
             ("celowanie", "tryb LAN", "blokada", "NAT") if sec.find(w) >= 0)]
    check("README.pl.md 'Jak to działa' keeps celowanie -> tryb LAN -> blokada -> NAT",
          order == ["celowanie", "tryb LAN", "blokada", "NAT"], f"(got {order})")
