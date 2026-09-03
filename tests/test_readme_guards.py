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

# One README since 2026-09-03 (owner's decision): the Polish translation is gone
# and the Polish documentation lives on the project website instead. The tuple
# stays a tuple rather than collapsing into the literal - every guard below is
# written to walk a SET of READMEs, and a second language would otherwise have to
# reintroduce the loop into each of them.
READMES = ("README.md",)


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
    from beantester.gui import csv_export
    names = set(csv_export.CONN_CSV_HEADER)
    names |= {csv_export.CSV_COLUMNS.get(k, k) for k in csv_export.CSV_COLUMNS}
    # Session columns are part of the same header and just as undocumentable by
    # inspection - `capture_narrowed` decides what `packets_seen` next to it even
    # counted.
    names |= set(csv_export.CSV_SESSION_COLUMNS.values())
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
    for readme, lang in zip(READMES, ("en",), strict=True):
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


def test_no_semicolons_in_readme_prose():
    """Same rule as the UI text (PROJECT_NOTES convention 1b): a full stop or a
    comma, because that is what people write.

    Code is exempt and has to be, since a semicolon is syntax there - bash,
    JSON, PowerShell, filter expressions. So fenced blocks and inline `code
    spans` are cut out before looking, which is what keeps this check free of
    false positives.

    It used to skip any line INDENTED by four spaces as well, on the theory that
    those are indented code blocks. In markdown they are also how a nested list
    continues, and that is what the exemption actually hid: a semicolon lived in
    a nested bullet of README.md while this guard reported the file clean.
    MEASURED before removing it - of the indented lines outside fences, 16 in
    README.md and 8 in the Polish README that then existed, EVERY one was list
    text and none was code. The file fences all its code, so the exemption
    protected nothing and blinded the check. Should an indented code block ever
    arrive, this test will say so and the answer is to fence it, which is better
    markdown regardless.
    """
    for readme in READMES:
        offenders, fenced = [], False
        for number, line in enumerate(_read(readme).splitlines(), 1):
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            prose = re.sub(r"`[^`]*`", "", line)
            if ";" in prose:
                offenders.append(f"{number}: {prose.strip()[:60]}")
        check(f"{readme}: no semicolons in prose", not offenders,
              f"({offenders[:4]})")


def test_both_readmes_list_every_job_the_ci_workflow_runs():
    """Prose about CI is the first thing to go stale, and nothing was watching it.

    The workflow gained four jobs in two days. A reader deciding whether to trust
    this project reads the README, not the YAML - so the table there has to be the
    set of jobs, exactly: a new job that nobody documented reddens this, and so
    does a documented job that no longer exists.

    Parsed by hand rather than with PyYAML, which is deliberately not a test
    dependency (see the same choice in test_site.py).
    """
    import re
    with open(os.path.join(ROOT, ".github", "workflows", "ci.yml"), encoding="utf-8") as f:
        lines = f.read().splitlines()
    inside, jobs = False, []
    for line in lines:
        if re.match(r"^jobs:\s*$", line):
            inside = True
            continue
        if inside:
            if line and not line.startswith((" ", "\t", "#")):
                break                                   # a new top-level key
            match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if match:
                jobs.append(match.group(1))
    check("the workflow scan found its jobs", len(jobs) >= 5, f"({jobs})")

    for readme in READMES:
        text = _read(readme)
        # Only the marked table: both READMEs are full of tables whose first
        # column is a backticked lowercase name (CLI flags, CSV columns), and a
        # guard that reads all of them measures the wrong thing.
        block = re.search(r"<!-- ci-jobs:start -->(.*?)<!-- ci-jobs:end -->", text, re.S)
        check(f"{readme} carries the marked CI table", block is not None)
        documented = set(re.findall(r"^\| `([a-z0-9_-]+)` \|", block.group(1) if block else "",
                                    re.MULTILINE))
        missing = sorted(set(jobs) - documented)
        extra = sorted(documented - set(jobs))
        check(f"{readme} documents every CI job", not missing, f"(missing: {missing})")
        check(f"{readme} documents no job that no longer exists", not extra,
              f"(stale: {extra})")
