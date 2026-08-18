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

# The website sources under site/ are public text like any other, and until they
# existed every scanner below stopped at the extensions a Python project has. The
# conventions do not stop there: a dash, a machine path or an address in a page
# template is published to a browser instead of to a reader of the repository,
# which is worse, not better. Kept as its own tuple so the addition is visible
# rather than buried in three separate literals.
WEB_EXTS = (".html", ".css", ".js", ".xml", ".svg")


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
            ".cfg", ".ini") + WEB_EXTS
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
            # The website sources: without this line the three scans above would
            # keep passing if site/ vanished or moved, which is the exact failure
            # this test exists for - an empty collection satisfies every check.
            ("repo_text_files(web)", repo_text_files(WEB_EXTS), "style.css", 4),
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

    🔴 **The HANDOFF half of this was an ASSERTION THAT COULD NOT FAIL, and only a
    mutation run said so.** It named `HANDOFF-UI-CLI.md`, a brief deleted on
    2026-08-10, so `repo_text_files` could never return it whatever
    `SKIP_PREFIXES` held - emptying that tuple changed nothing and the guard still
    read as proof (`internal_tools/mutate.py`, 2026-08-17: SURVIVED). It now PLANTS
    a brief for the length of the scan, so the skip has something to skip. The
    other names above are files that DO exist here, so they were never in doubt.
    """
    # A brief that really exists, because a guard against scanning one cannot be
    # tested by naming a file that is absent. `HANDOFF-*.md` is git-ignored, so this
    # never dirties the tree, and it is removed before the assertions run.
    probe = os.path.join(ROOT, "HANDOFF-scanner-probe.md")
    check("the planted brief is not overwriting a real one",
          not os.path.exists(probe), f"({probe})")
    # An em-dash: what the dash scan would object to if it ever read this file.
    # Built with chr() rather than written out, because THIS file is repository text
    # and is scanned by the very rule it defines - a literal one fails the suite.
    with open(probe, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("planted by the suite " + chr(0x2014) + " removed immediately\n")
    try:
        scanned = {os.path.relpath(p, ROOT).replace(os.sep, "/")
                   for p in repo_text_files((".py", ".md", ".json", ".txt"))}
    finally:
        os.remove(probe)
    for stray in ("PROJECT_NOTES.md", "CLAUDE.md", "HISTORY_NOTES.md",
                  "CHANGELOG-INTERNAL.md", os.path.basename(probe)):
        check(f"{stray} is not scanned (it is not in the repository)",
              stray not in scanned, f"({stray})")
    for prefix in ("internal_tools/", ".claude/", "crashes/"):
        leaked = sorted(p for p in scanned if p.startswith(prefix))
        check(f"nothing under {prefix} is scanned (git-ignored, absent in CI)",
              not leaked, f"({leaked[:4]})")


# Things that must never reach a public repository. Only the mechanical half of
# the rule lives here - see the note next to the test about the other half.
PRIVATE_PATTERNS = (
    # The backslash spelling is the one that actually leaks - it is what cmd,
    # PowerShell and a Python traceback print - and until 2026-08-11 this pattern did
    # not match it. Inside a character class, an escaped forward slash is just a
    # forward slash, so the class held ONE character and the guard only ever caught
    # the URL-style spelling. Found by mutation while extending these scans to the
    # website sources: a probe file carrying a profile path in backslash form passed
    # this test. After the fix both spellings match and the tracked tree has no hit.
    # No example is written out here on purpose: this file is repository text, so it
    # is scanned by the rule it defines, and a literal one would fail the suite.
    (r"[A-Za-z]:[\\/]{1,2}Users[\\/]", "a Windows user-profile path"),
    (r"/home/[a-z][\w.-]*/", "a Linux home path"),
    (r"/Users/[A-Za-z][\w.-]*/", "a macOS home path"),
    (r"\bgh[pousr]_[A-Za-z0-9]{16,}", "a GitHub token"),
    (r"\bAKIA[0-9A-Z]{12,}", "an AWS access key id"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "a private key"),
)

# The WinDivert copyright line has to carry its author's address: it is part of
# the notice we are obliged to reproduce. Nothing else may hold an address.
EMAIL_ALLOWED_IN = {"THIRD-PARTY-NOTICES.md"}


def test_nothing_private_to_this_machine_reaches_the_public_repository():
    """This repository is public, and so is its history.

    A path, a machine name or a token committed once stays readable after it is
    deleted, because the commit that added it does not go away. That makes this
    cheaper to enforce than to clean up, which is the whole argument for a test.

    What this canNOT check is the other half of the rule (convention 45): that a
    comment explains ITSELF rather than pointing at a document only the
    maintainers can open. Four comments doing exactly that were found by reading,
    2026-08-03, and reading is the only thing that finds them. Said out loud so
    the presence of this test is not mistaken for full coverage.
    """
    import re
    files = repo_text_files((".py", ".md", ".json", ".txt", ".toml", ".spec", ".yml")
                            + WEB_EXTS)
    check("the privacy scan actually read the repository", len(files) >= 30,
          f"({len(files)} files)")
    for pattern, what in PRIVATE_PATTERNS:
        rx = re.compile(pattern)
        offenders = []
        for path in files:
            with open(path, encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if rx.search(line):
                        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                        offenders.append(f"{rel}:{number}")
        check(f"nothing in the repository looks like {what}", not offenders,
              f"({offenders[:4]})")


def test_no_stray_email_addresses_in_the_public_tree():
    """An address in a public repository is an address that gets scraped.

    The one exception is deliberate and required: the WinDivert notice reproduces
    its author's copyright line, address included, because that is the notice we
    are obliged to pass on.
    """
    import re
    rx = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")
    offenders = []
    for path in repo_text_files((".py", ".md", ".json", ".txt", ".toml", ".spec", ".yml")
                                + WEB_EXTS):
        name = os.path.basename(path)
        if name in EMAIL_ALLOWED_IN:
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            for number, line in enumerate(handle, 1):
                for hit in rx.findall(line):
                    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                    offenders.append(f"{rel}:{number} {hit}")
    check("no email addresses outside the notices that must carry one",
          not offenders, f"({offenders[:4]})")


def test_every_script_the_workflows_run_is_actually_in_the_repository():
    """A CI dependency that git does not carry works here and nowhere else.

    ``internal_tools/`` is deliberately outside git: measurement rigs and probes
    that never ship and that the owner backs up separately. ``tools/`` is the
    opposite - it IS carried, because the workflows run it. Put a workflow
    dependency in the wrong one and nothing fails locally, where the file exists;
    it fails on a fresh clone, which is to say on somebody else's machine, and
    the error is a missing file rather than the reason for it.

    So the rule "when a script becomes a CI dependency it moves to ``tools/``"
    gets a guard instead of a memory: every ``python <path>`` a workflow runs has
    to exist AND be tracked.
    """
    import re
    import subprocess
    workflows = glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml"))
    check("there are workflows to read", bool(workflows), f"({workflows})")

    referenced = set()
    for path in workflows:
        with open(path, encoding="utf-8") as handle:
            for match in re.finditer(r"python\s+([\w./-]+\.py)", handle.read()):
                referenced.add(match.group(1))
    check("the workflow scan found the scripts it runs", len(referenced) >= 3,
          f"({sorted(referenced)})")

    for script in sorted(referenced):
        full = os.path.join(ROOT, script)
        check(f"{script} exists", os.path.exists(full))
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", script],
                                 cwd=ROOT, capture_output=True, text=True)
        check(f"{script} is tracked by git (a fresh clone must have it)",
              tracked.returncode == 0,
              "(it is ignored or untracked - internal_tools/ cannot hold a CI dependency)")


def _script_lines(text):
    """``(line number, text)`` for every line inside a ``run:`` block.

    Hand-rolled rather than PyYAML, because the suite carries no YAML dependency
    and the question is lexical anyway: is this text part of a script a runner
    will execute. A ``run:`` opens the block, and the block ends at the first
    non-empty line indented no further than the key itself.
    """
    import re
    out, block = [], None
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if block is not None:
            if stripped and indent <= block:
                block = None
            else:
                out.append((number, line))
                continue
        match = re.match(r"-?\s*run:(.*)$", stripped)
        if match:
            out.append((number, match.group(1)))
            block = indent
    return out


def test_no_workflow_puts_a_github_expression_inside_a_shell_script():
    """``${{ }}`` in a ``run:`` block is TEXT SUBSTITUTION, not a variable.

    GitHub expands the expression into the script before any shell exists, so a
    value carrying a shell metacharacter stops being an argument and becomes a
    command. The safe form is an intermediate ``env:`` entry, quoted where it is
    used - which is what GitHub's own hardening guide says, and what the
    ``check the pull-request description`` step in ``ci.yml`` has always done.

    The repository had exactly one exception, four lines above that very step:
    ``--commits origin/${{ github.base_ref }}..${{ ... .head.sha }}``. Narrow
    rather than harmless (``base_ref`` must name a branch that already exists
    here, and the job holds no secrets), and three lines to close - which is
    exactly the kind of thing that survives on a memory and dies on a guard.
    """
    workflows = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
    check("there are workflows to read", bool(workflows), f"({workflows})")
    offenders = []
    scripts = 0
    for path in workflows:
        with open(path, encoding="utf-8") as handle:
            lines = _script_lines(handle.read())
        scripts += len(lines)
        for number, line in lines:
            if "${{" in line:
                offenders.append(f"{os.path.basename(path)}:{number} {line.strip()[:60]}")
    # A parser that stopped finding script lines would pass this silently, which
    # is the failure mode of every hand-written scanner.
    check("the scan actually read some script lines", scripts > 20, f"({scripts})")
    check("no workflow interpolates a GitHub expression into a script",
          not offenders, f"({offenders})")


def test_every_action_a_workflow_uses_is_pinned_to_a_commit():
    """A tag is a movable reference, and that movement IS the attack.

    ``actions/checkout@v7`` names whichever commit that tag points at today, and
    the owner of the tag may repoint it at any time - which is what the
    tj-actions and trivy-action compromises did. GitHub's hardening guide is
    blunt about the remedy: a full-length commit SHA is the only way to use an
    action as an immutable release.

    Immutable releases (generally available since October 2025) do not retire
    this rule, and it is worth writing down why, because they sound like they
    should. They lock the release tag - ``v7.0.1`` - while the floating major
    ``v7`` is DESIGNED to move and GitHub's own documentation tells action
    authors to move it. One reference in this repository was not even a tag:
    ``actions/dependency-review-action@v5`` resolved to a BRANCH of that name.

    The comment after the SHA is part of the rule rather than decoration. It is
    what tells a reader which version the digest is, and it is exactly the format
    Dependabot writes and rewrites when it bumps a pin - so pinning costs no
    upkeep, it only moves the decision to update from the action's owner to us.
    """
    import re
    workflows = sorted(glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
    check("there are workflows to read", bool(workflows), f"({workflows})")
    seen, unpinned, uncommented = 0, [], []
    for path in workflows:
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                match = re.search(r"uses:\s*([\w.-]+/[\w.-]+)@(\S+)(.*)$", line)
                if not match:
                    continue
                seen += 1
                action, ref, rest = match.group(1), match.group(2), match.group(3)
                where = f"{os.path.basename(path)}:{number} {action}@{ref[:12]}"
                if not re.fullmatch(r"[0-9a-f]{40}", ref):
                    unpinned.append(where)
                elif not re.search(r"#\s*v?\d", rest):
                    uncommented.append(where)
    # A regex that stopped matching would report a clean sweep of nothing.
    check("the scan found the actions the workflows use", seen >= 15, f"({seen})")
    check("every action is pinned to a full commit SHA", not unpinned, f"({unpinned})")
    check("every pin says which version it is", not uncommented, f"({uncommented})")
