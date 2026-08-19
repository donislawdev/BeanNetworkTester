"""Run the mutation registry: break a guarded behaviour, prove the named test reddens.

What question this closes
-------------------------
"Is this test actually guarding what its name says?" A green suite proves nothing
about a behaviour whose guard never fails. The only proof is the sentence "this test
would be red if I broke this" - executed, not asserted.

The registry lives in `tests/test_mutation_registry.py`, because it must ship and
must be checked by the normal suite. This runner used to live outside git as a rig
(PROJECT_NOTES rule 3) - it moved here on 2026-08-19, and the reason is the gap
that move closes: what ships is a registry whose entries are only checked for
POINTING at code that exists. Nothing in the repository ever ran one. "116 caught,
0 survived" was true on the day somebody typed it and unverifiable every day
after, which is the same class of claim this whole registry exists to refuse.

Traps this already fell into, all paid for elsewhere and worth keeping
----------------------------------------------------------------------
1. **A pattern that went stale reports a false "caught".** If the search string no
   longer occurs, the file is unchanged, the test passes for the ordinary reason and
   the entry looks proven. So a hit count != 1 is `SKIP`, never a result. The normal
   suite catches this too (the registry test counts occurrences), which is why that
   check is in both places.
2. **Restore by BYTES, never by rewriting text.** Opening a file in text mode on
   Windows turns LF into CRLF, `.gitattributes` says the repo is LF, and the tree
   ends up dirty in a way `git diff` does not show. Never `git checkout --` either:
   for a file with uncommitted work that destroys the very fix being tested.
3. **Aim at ONE test.** Naming two tests with `or` and seeing red proves only that
   one of them fell. The entry that names the other would then report "not caught"
   in a full run and look like a hole in the product.
4. **The canary.** One entry is deliberately broken syntax and MUST come back as
   BROKEN. Without it, a runner whose subprocess call is misconfigured reports
   "everything caught" and the whole run is a lie.

Usage
-----
    python tools/mutate.py                     # every entry, plus the canary
    python tools/mutate.py gui                 # entries whose label contains "gui"
    python tools/mutate.py --changed origin/master
                                               # only entries whose FILE changed
                                               # against that ref - what a pull
                                               # request runs, usually seconds

`--changed` exists because the full run is minutes (~13 on the developer machine,
117 entries) and a pull request touches a handful of files. It compares with
`git diff --name-only <ref>...HEAD`, the three-dot form, so a change on the base
branch does not drag unrelated entries in. With no entry matching, it says so and
exits 0 - a pull request that touches nothing guarded is not a failure.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_mutation_registry import CANARY, MUTATIONS          # noqa: E402


def run_test(test_name):
    """Return True when the named test FAILS - i.e. the mutation was caught."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-k", test_name, "-q",
         "-p", "no:randomly"],
        cwd=ROOT, capture_output=True, text=True)
    # "Did pytest actually run this test?" has to be read from pytest's own exit
    # code, not from scanning its output for the word ERROR.
    #
    # 🔴 The substring check was WRONG in the one direction that matters: it turned
    # a genuine `caught` into a SKIP whenever the failing test's traceback happened
    # to print an upper-case ERROR - and a test about Win32 error constants prints
    # `_ERROR_SERVICE_MARKED_FOR_DELETE` in its own source line. A rig that reports
    # "unproven" for a guard that works is the same lie as one that reports
    # "caught" for a guard that does not, only quieter.
    #
    # Pytest's codes: 0 passed, 1 failed, 2 interrupted, 3 internal, 4 usage,
    # 5 nothing collected. Only 0 and 1 are answers to the question.
    if proc.returncode == 5 or "no tests ran" in proc.stdout:
        return None                       # the name matched nothing: not a result
    if proc.returncode not in (0, 1) or "errors during collection" in proc.stdout:
        return None                       # the tree did not run: also not a result
    return proc.returncode != 0


def apply_one(entry):
    path = os.path.join(ROOT, entry["file"])
    with open(path, "rb") as handle:
        original = handle.read()
    # Newlines are NORMALISED before matching, and put back before writing.
    #
    # 🔴 Without this, every entry aiming at one of the files that still carry CRLF
    # in this tree reported SKIP - and the registry test in `tests/` did not notice,
    # because it reads in TEXT mode, where universal newlines turn `\r\n` into `\n`
    # and the pattern matches. So the suite said the entry was healthy while the
    # runner quietly refused to run it, which is the exact shape of a guard that
    # proves nothing while looking fine. Found on `sortable_tree.py` (600 CRLF).
    crlf = b"\r\n" in original
    text = original.decode("utf-8").replace("\r\n", "\n")
    if text.count(entry["old"]) != 1:
        return "SKIP", "pattern occurs %d times, not 1" % text.count(entry["old"])
    try:
        mutated = text.replace(entry["old"], entry["new"], 1)
        if crlf:
            mutated = mutated.replace("\n", "\r\n")
        with open(path, "wb") as handle:
            handle.write(mutated.encode("utf-8"))
        compiled = subprocess.run([sys.executable, "-m", "compileall", "-q", path],
                                  cwd=ROOT, capture_output=True, text=True)
        if compiled.returncode != 0:
            return "BROKEN", "the mutated tree does not compile"
        caught = run_test(entry["test"])
        if caught is None:
            return "SKIP", "no test matched %r" % entry["test"]
        return ("caught" if caught else "SURVIVED"), entry["test"]
    finally:
        with open(path, "wb") as handle:   # bytes, so line endings survive
            handle.write(original)


def changed_files(ref):
    """Repository-relative paths that differ from ``ref``, in the three-dot sense."""
    proc = subprocess.run(["git", "diff", "--name-only", "%s...HEAD" % ref],
                          cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        # Not a result: a runner that cannot read the diff must not report that
        # nothing changed, because that reads exactly like a clean run.
        print("mutate: git diff against %r failed: %s"
              % (ref, proc.stderr.strip()[:200]), file=sys.stderr)
        raise SystemExit(2)
    return {line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()}


def main(argv):
    argv = list(argv[1:])
    ref = None
    if "--changed" in argv:
        position = argv.index("--changed")
        try:
            ref = argv[position + 1]
        except IndexError:
            print("mutate: --changed needs a ref", file=sys.stderr)
            return 2
        del argv[position:position + 2]
    needle = argv[0] if argv else ""

    entries = [m for m in MUTATIONS if needle in m["label"]]
    if ref is not None:
        touched = changed_files(ref)
        entries = [m for m in entries if m["file"].replace("\\", "/") in touched]
        print("changed against %s: %d file(s), %d matching registry entr(ies)"
              % (ref, len(touched), len(entries)))
        if not entries:
            print("nothing guarded by the registry was touched")
            return 0
    elif not needle:
        entries = entries + [CANARY]
    width = max(len(m["label"]) for m in entries)
    counts = {}
    for entry in entries:
        state, detail = apply_one(entry)
        counts[state] = counts.get(state, 0) + 1
        print("%-*s  %-9s %s" % (width, entry["label"], state, detail))
    print("\n" + "  ".join("%s: %d" % kv for kv in sorted(counts.items())))
    # The canary only rides along on a FULL run. A filtered run (a label, or
    # --changed) has none, and demanding one there would make every pull request
    # fail for the shape of the run rather than for its result.
    canary_ok = needle or ref is not None or counts.get("BROKEN") == 1
    if not canary_ok:
        print("CANARY DID NOT FIRE - this whole run proves nothing")
    return 0 if counts.get("SURVIVED", 0) == 0 and canary_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
