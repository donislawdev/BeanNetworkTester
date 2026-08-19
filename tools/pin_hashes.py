#!/usr/bin/env python3
"""Write the artefact hashes for a pinned requirements file.

    python tools/pin_hashes.py requirements.txt          # rewrite it in place
    python tools/pin_hashes.py --print requirements.txt  # show, change nothing

Why the file needs them
-----------------------
`pydivert==3.1.3` pins a NUMBER. It does not pin the bytes: an attacker who
reaches the index - or the account that publishes there - can serve a different
artefact under the same version, and every build afterwards is theirs. That is
not a hypothetical for this project, because the wheel it names carries the
WinDivert kernel driver we install on a user's machine.

With hashes present pip switches to hash-checking mode and refuses anything that
does not match, so a swapped artefact fails the build instead of shipping.

What this does
--------------
Reads every `name==version` line, asks the PyPI JSON API for EVERY artefact of
that exact version, and writes them all as `--hash=sha256:` continuation lines.
All of them, not just the one this machine would pick: the same file installs on
Windows and Linux runners, and each picks a different wheel.

Two things it deliberately does not do:

* it never invents a version. The version is the pin, and the pin is a decision
  made by a person - this only records what that decision resolves to;
* it does not touch a requirement without `==`. A file that is meant to track
  latest (`requirements-dev.txt`) cannot be hash-pinned, and quietly freezing it
  would break the weekly run that exists to watch that drift.
"""
import argparse
import io
import json
import re
import sys
import urllib.request
from urllib.parse import quote

API = "https://pypi.org/pypi/%s/%s/json"
PINNED = re.compile(r"^(?P<name>[A-Za-z0-9._-]+)==(?P<version>[^\s;\\]+)(?P<rest>.*)$")


def _url(name, version):
    """The PyPI JSON endpoint for one exact version, with both parts escaped.

    🔴 The escaping is not about the scheme. A scanner flags `urlopen` on a value it
    cannot see the shape of, and the risk it names - a `file://` URL reading a local
    file - is not reachable here: `API` is a literal `https://` and both parts land in
    the PATH, after the authority. Measured across `../../etc/passwd`, `x@evil.com`
    and a literal `file:///c:/windows` as the version: the scheme stays `https` and
    the host stays `pypi.org` in every case.

    What IS reachable is quieter and worth closing anyway. `version` is only barred
    from whitespace and semicolons, so `1.0?x=y` or `1.0#frag` used to truncate the
    path into a query or a fragment - a DIFFERENT endpoint, answering about something
    else, and this file writes the hashes that gate the supply chain. Escaped, such a
    version asks about a release that does not exist and fails loudly instead.
    """
    return API % (quote(name, safe=""), quote(version, safe=""))


def artefact_hashes(name, version, timeout=30):
    """Every sha256 on PyPI for that exact version, newest artefact last."""
    with urllib.request.urlopen(_url(name, version), timeout=timeout) as response:
        payload = json.load(response)
    digests = [f["digests"]["sha256"] for f in payload.get("urls", [])]
    if not digests:
        raise SystemExit(f"pin_hashes: {name}=={version} has no artefacts on PyPI")
    return sorted(set(digests))


def rewrite(text, fetch=artefact_hashes):
    """The file with a fresh hash block under every pinned requirement."""
    out, skipped = [], []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        match = PINNED.match(line.strip())
        if not match or line.startswith((" ", "\t", "#")):
            # Not a pinned requirement: a comment, a blank, an `-r` include, or a
            # continuation line from a previous run (dropped and rebuilt below).
            if line.strip().startswith("--hash="):
                continue
            out.append(line)
            continue
        # Drop a stale hash block that followed this requirement.
        while index < len(lines) and lines[index].strip().startswith("--hash="):
            index += 1
        name, version = match.group("name"), match.group("version")
        rest = match.group("rest").rstrip().rstrip("\\").rstrip()
        digests = fetch(name, version)
        skipped.append((name, version, len(digests)))
        head = f"{name}=={version}{rest}"
        out.append(head + " \\")
        for position, digest in enumerate(digests):
            tail = " \\" if position < len(digests) - 1 else ""
            out.append(f"    --hash=sha256:{digest}{tail}")
    return "\n".join(out), skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", help="the requirements file to rewrite")
    parser.add_argument("--print", dest="show", action="store_true",
                        help="write nothing, print the result instead")
    args = parser.parse_args(argv)

    with io.open(args.path, encoding="utf-8", newline="") as handle:
        original = handle.read()
    ending = "\r\n" if "\r\n" in original else "\n"
    text, pinned = rewrite(original.replace("\r\n", "\n"))
    if not pinned:
        print(f"pin_hashes: nothing pinned with == in {args.path}", file=sys.stderr)
        return 1
    if args.show:
        print(text)
    else:
        with io.open(args.path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text.replace("\n", ending))
    for name, version, count in pinned:
        print(f"{name}=={version}: {count} artefact hash(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
