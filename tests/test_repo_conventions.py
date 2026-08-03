"""Repository conventions: naming guard and package hygiene.

Extends the original single-file rename guard to every source file of the
package, the launcher and the GUI smoke script.
"""
import glob
import os

from fakes import ROOT, check

# Directories a whole-repository walk must not descend into. The first group is
# generated or vendored; the second is the maintainer's own, kept OUT of git.
#
# The second group matters more than it looks. `internal_tools/`, `.claude/`,
# `crashes/` and the private notes exist on the owner's machine and in NO public
# checkout, so a guard that scans them measures a different set here than in CI:
# an em dash typed into PROJECT_NOTES.md would redden the suite locally while CI
# stayed green, which teaches that a red guard is local noise. Measured 2026-08-02:
# the dash scan covered 183 files, 12 of them git-ignored - including
# `crashes/latest-crash.txt`, whose contents are arbitrary text from OS exceptions.
# The notes keep their own dash check in `.claude/hooks/check_notes.py`, which runs
# exactly where they exist.
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", "licenses", "build", "dist",
             ".hypothesis", "internal_tools", ".claude", "crashes"}
SKIP_FILES = {"PROJECT_NOTES.md", "HISTORY_NOTES.md", "CLAUDE.md",
              "CHANGELOG-INTERNAL.md"}
# Same reason, by prefix: HANDOFF-*.md are maintainer briefs kept out of git.
SKIP_PREFIXES = ("HANDOFF-",)


def repo_text_files(exts):
    """Every text file that is actually IN the repository, with the given suffixes.

    Returns a list so a caller can assert it is not empty: a scanner whose walk
    yields nothing passes every check it makes, and looks exactly like a scanner
    that works. See test_the_repository_scanners_actually_read_files.
    """
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if (name.endswith(exts) and name not in SKIP_FILES
                    and not name.startswith(SKIP_PREFIXES)):
                out.append(os.path.join(dirpath, name))
    return out


def _source_files():
    files = [os.path.join(ROOT, "bean_network_tester.py"),
             os.path.join(ROOT, "smoke_gui.py")]
    files += glob.glob(os.path.join(ROOT, "beantester", "**", "*.py"), recursive=True)
    return files


def test_no_old_name_references():
    """Rename regression guard: the code must not contain the old name."""
    for path in _source_files():
        src = open(path, encoding="utf-8").read()
        for bad in ("netshaper", "NetShaper", "ShaperCore", "netsharper"):
            check(f"no reference to '{bad}' in {os.path.basename(path)}", bad not in src)


def test_gui_not_imported_by_core_package():
    """``import beantester`` must not pull in tkinter (CLI works without it)."""
    import importlib
    import subprocess
    import sys
    code = ("import sys; sys.path.insert(0, r'%s'); import beantester; "
            "sys.exit(1 if 'tkinter' in sys.modules else 0)" % ROOT)
    proc = subprocess.run([sys.executable, "-c", code])
    check("core package import does not require tkinter", proc.returncode == 0)
    importlib.import_module("beantester")


def _gui_files():
    return glob.glob(os.path.join(ROOT, "beantester", "gui", "**", "*.py"), recursive=True)


def test_no_hardcoded_window_geometry():
    """Window size must come from ``scaling.initial_geometry``, not a literal.

    ``root.geometry("680x900")`` did not fit on a 1366x768 laptop: the bottom bar
    and the log ended up under the taskbar.
    """
    import re
    pattern = re.compile(r"""geometry\(\s*["']\d+x\d+""")
    offenders = [os.path.basename(p) for p in _gui_files()
                 if pattern.search(open(p, encoding="utf-8").read())]
    check("no hard-coded window geometry in the GUI", not offenders, f"({offenders})")


def test_single_mouse_wheel_dispatcher():
    """Exactly one place may bind the wheel globally.

    The old per-container ``bind_all``/``unbind_all`` pairs fought each other and
    were torn down by the ``<Leave>`` Tk sends when the pointer enters a child.
    """
    offenders = [os.path.basename(p) for p in _gui_files()
                 if "bind_all" in open(p, encoding="utf-8").read()
                 and os.path.basename(p) != "scrollable.py"]
    check("only scrollable.py binds the mouse wheel globally", not offenders,
          f"({offenders})")


def test_treeviews_never_live_inside_a_scrollable_frame():
    """Scroll-inside-scroll would make the wheel dispatcher ambiguous."""
    for page in ("control.py",):
        src = open(os.path.join(ROOT, "beantester", "gui", "pages", page),
                   encoding="utf-8").read()
        check(f"{page}: no Treeview inside the scrollable body",
              "Treeview(" not in src and "SortableTree(" not in src)


def test_no_silent_exception_swallowing_outside_the_crash_logger():
    """`except: pass` hides failures. In a codebase heading towards a million lines
    and "an enormous variety of bugs" (the owner's words), a swallowed exception is
    a bug nobody will ever see. The replacement is `crashlog.quiet(...)` / .note /
    .once, which swallow for the USER but record for US.

    The one place allowed to `except: pass` is the crash logger itself: it cannot
    call itself to report a failure while reporting a failure - that is a recursion,
    not a safety net. Its own I/O (writing the file, rotating it, installing a hook)
    is the exception.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "beantester"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "crashlog.py":
            continue                    # the logger may not call itself
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = [n for n in node.body if not isinstance(n, ast.Pass)]
            # `except ...: pass` with nothing else is the silent swallow
            only_pass = all(isinstance(n, ast.Pass) for n in node.body)
            if only_pass:
                offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")

    check("no bare `except: pass` outside the crash logger "
          "(use crashlog.quiet / note / once instead)",
          not offenders, f"({offenders})")


def test_no_em_or_en_dashes_in_repo_text():
    """Project convention: the repository uses the plain hyphen '-' only.

    Em dashes and en dashes are banned everywhere in the project's own text and
    code (owner's decision, July 2026). The only exception is verbatim third-party
    licence text under licenses/, which must not be altered.
    """
    banned = {"\u2014": "em dash", "\u2013": "en dash", "\u2012": "figure dash",
              "\u2212": "minus sign", "\u2015": "horizontal bar"}
    exts = (".py", ".md", ".json", ".toml", ".spec", ".yml", ".yaml", ".txt",
            ".cfg", ".ini")
    offenders = []
    for path in repo_text_files(exts):
        text = open(path, encoding="utf-8", errors="replace").read()
        for ch, label in banned.items():
            if ch in text:
                offenders.append(f"{os.path.relpath(path, ROOT)}: {label}")
    check("no em/en dashes outside licenses/ (use '-')", not offenders,
          f"({offenders[:8]}{'...' if len(offenders) > 8 else ''})")


# -- prose with an expiry date -------------------------------------------------- #
# Convention 5 guards claims that are FALSE. This guards the OTHER failure mode,
# which cost four stale sites in a single transition: a claim that was TRUE when it
# was written and was supposed to die when a stage landed. Chunks 2a->2d wired the
# SocketWatcher into the engine and targeting, but comments went on saying "NOT read
# by targeting yet - that is 2c" long after it was read, because nothing enforced
# the expiry: check_notes.py deliberately does not check prose, and a comment cannot
# fail a build by itself.
#
# So prose that is only true UNTIL a stage lands carries a marker naming that stage,
# and the ids still open live here, in exactly one place. Closing a stage means
# deleting its id from this set - which turns this test red on every marker still
# pointing at it, so the prose is corrected in the same commit as the code that
# outdated it.
#
# This set is NOT a roadmap. It is the set of stage ids that PROSE currently points
# at, which is why an id nothing references is a failure too: it means the marker is
# gone and the entry was left behind.
# Empty is the HEALTHY state: it means no prose in the repo is currently waiting on a
# stage. Add an id the moment you write a sentence with an expiry date, and delete it
# when the stage lands - the second check below then points at whatever prose is left.
OPEN_PENDING = set()

PENDING_EXTS = (".py", ".md")


def test_no_stale_pending_markers():
    """Every expiry-dated marker names an open stage, and every open stage is marked.

    Both directions were MUTATION-CHECKED (2026-07-25) rather than assumed, because
    a guard nobody has deliberately broken is a guard whose shape nobody knows: a
    marker naming an id that is not in ``OPEN_PENDING`` fails, and deleting the last
    marker for a listed id fails. Confirmed red for each.

    The scan skips THIS file, which holds the ids rather than pointing at them, so a
    future example in the text above cannot break the guard. Note that the
    placeholder form used in prose and changelogs does not match the pattern (``<``
    is not a valid id character), so documentation can name the token freely.
    """
    import re

    marker = re.compile(r"PENDING\(([a-z0-9][a-z0-9-]*)\)")
    seen = {}
    for path in repo_text_files(PENDING_EXTS):
        name = os.path.basename(path)
        if name == os.path.basename(__file__):
            continue                     # the registry does not scan itself
        if name.startswith("CHANGELOG"):
            # A changelog records what HAPPENED and is dated by its nature: an
            # entry saying "added a marker named X" stays TRUE after X closes, so
            # it is history, not drift. Found the hard way - the first real
            # closing (socket-event-fields) tripped over the very entry that
            # announced the marker.
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        for lineno, line in enumerate(text.splitlines(), 1):
            for found in marker.findall(line):
                seen.setdefault(found, []).append(
                    f"{os.path.relpath(path, ROOT)}:{lineno}")

    stale = sorted(f"{key} ({', '.join(where)})"
                   for key, where in seen.items() if key not in OPEN_PENDING)
    check("every PENDING marker names a stage still open in OPEN_PENDING "
          "(a closed stage means the prose beside the marker is now a lie)",
          not stale, f"({stale})")

    unmarked = sorted(OPEN_PENDING - set(seen))
    check("every id in OPEN_PENDING is still referenced by a marker "
          "(an id nothing points at is a leftover entry, not an open stage)",
          not unmarked, f"({unmarked})")


# -- the canary: a scanner that reads nothing passes everything ----------------- #
def test_the_repository_scanners_actually_read_files():
    """Every whole-tree scanner proves it saw a file it must have seen.

    A guard built on a glob or a walk has a failure mode that looks identical to
    success: the collection comes back EMPTY and every assertion over it holds
    vacuously. Nothing here would notice - `not offenders` is true when there are
    no files, a rename of `beantester/` would silence four separate guards at once,
    and the suite would stay green while guarding nothing.

    This is the cheapest possible answer: name one file each collector MUST return,
    plus a floor on the count. Both halves matter - the anchor catches a collector
    pointed at the wrong root, the floor catches one that quietly narrowed.

    Mutation-checked 2026-08-02: emptying any collector, and pointing the walk at a
    non-existent root, each turn this red.
    """
    import test_code_hygiene
    import test_layering
    import test_readme_guards

    def names(paths):
        return {os.path.basename(p) for p in paths}

    for label, paths, anchor, floor in (
            ("_source_files", _source_files(), "core.py", 20),
            ("_gui_files", _gui_files(), "app.py", 10),
            ("repo_text_files(.py)", repo_text_files((".py",)), "engine.py", 60),
            ("repo_text_files(.md)", repo_text_files((".md",)), "README.md", 4),
            ("code_hygiene._pkg_files", test_code_hygiene._pkg_files(), "core.py", 20),
            ("layering._top_level_modules",
             test_layering._top_level_modules(), "engine.py", 15),
            ("readme_guards._top_level_modules",
             test_readme_guards._top_level_modules(), "engine.py", 15),
    ):
        check(f"{label} returned files at all (an empty scan passes every check "
              f"it makes and looks exactly like a working guard)", paths, "(empty)")
        check(f"{label} still reaches {anchor}", anchor in names(paths),
              f"({sorted(names(paths))[:6]}...)")
        check(f"{label} did not quietly narrow (expected at least {floor})",
              len(paths) >= floor, f"(got {len(paths)})")


def test_the_repository_scanners_stay_out_of_what_is_not_in_the_repository():
    """The dash and PENDING scans must measure the REPOSITORY, not this machine.

    `internal_tools/`, `.claude/`, `crashes/` and the private notes live here and in
    no public checkout, so scanning them makes the guard mean one thing locally and
    another in CI - and a red that CI cannot reproduce teaches that red is noise.
    Measured before the fix (2026-08-02): 12 of the 183 files scanned were
    git-ignored, `crashes/latest-crash.txt` among them, whose text comes from OS
    exceptions and is nobody's convention to keep.
    """
    scanned = {os.path.relpath(p, ROOT).replace(os.sep, "/")
               for p in repo_text_files((".py", ".md", ".json", ".txt"))}
    for stray in ("PROJECT_NOTES.md", "CLAUDE.md", "HISTORY_NOTES.md",
                  "CHANGELOG-INTERNAL.md", "HANDOFF-UI-CLI.md"):
        check(f"{stray} is not scanned (it is not in the repository)",
              stray not in scanned, f"({stray})")
    for prefix in ("internal_tools/", ".claude/", "crashes/"):
        leaked = sorted(p for p in scanned if p.startswith(prefix))
        check(f"nothing under {prefix} is scanned (git-ignored, absent in CI)",
              not leaked, f"({leaked[:4]})")
