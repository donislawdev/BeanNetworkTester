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


def test_polish_readme_pipeline_keeps_lan_and_blocking():
    """The regression that happened: the PL brief skipped LAN mode and blocking."""
    sec = _section(_read("README.pl.md"), "Jak to działa")
    order = [w for _, w in sorted((sec.find(w), w) for w in
             ("celowanie", "tryb LAN", "blokada", "NAT") if sec.find(w) >= 0)]
    check("README.pl.md 'Jak to działa' keeps celowanie -> tryb LAN -> blokada -> NAT",
          order == ["celowanie", "tryb LAN", "blokada", "NAT"], f"(got {order})")
