#!/usr/bin/env python3
"""Print GitHub Release download counts for this project.

Uses the public REST API - no token needed once the repository is public. Shows a
per-release, per-asset breakdown plus the grand total, so you can track how many
people actually downloaded each build.

    python tools/downloads.py
    python tools/downloads.py --repo donislawdev/BeanNetworkTester

The README's downloads badge shows the same grand total live; this is for the detail.
"""
import argparse
import json
import re
import sys
import urllib.request

DEFAULT_REPO = "donislawdev/BeanNetworkTester"


REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def fetch_releases(repo):
    """Every published release for ``owner/name`` (newest first), via the public API.

    ``repo`` is checked before it becomes part of a URL. Not because a scheme
    could be smuggled in - the scheme here is a literal - but because the value
    lands in the PATH, so `--repo ../../gists` would quietly ask a different
    endpoint the question and print whatever came back as if it were releases.
    An owner and a name, nothing else.
    """
    if not REPO.match(str(repo or "")):
        raise ValueError("expected owner/name, got %r" % (repo,))
    url = "https://api.github.com/repos/%s/releases?per_page=100" % repo
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "bnt-downloads",
    })
    # The audit that rule asks for is DONE, and it is the `REPO.match` above: the
    # scheme and the host are literals, and the one value that reaches the URL is an
    # owner and a name or nothing. Guarded by
    # test_the_downloads_tool_refuses_anything_that_is_not_owner_slash_name.
    # Suppressed so the finding stops costing an analysis on every scan; the
    # suppression itself is inventoried by test_repo_conventions.py.
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Show GitHub release download counts.")
    parser.add_argument("--repo", default=DEFAULT_REPO,
                        help="owner/name (default: %(default)s)")
    args = parser.parse_args(argv)

    try:
        releases = fetch_releases(args.repo)
    except Exception as exc:      # noqa: BLE001 - a CLI tool reports, it does not traceback
        print("error: could not fetch releases for %s: %s" % (args.repo, exc),
              file=sys.stderr)
        return 1

    if not releases:
        print("No releases found for %s (is it public and published?)." % args.repo)
        return 0

    grand_total = 0
    for release in releases:
        tag = release.get("tag_name", "?")
        marker = " (pre-release)" if release.get("prerelease") else ""
        assets = release.get("assets", [])
        subtotal = sum(asset.get("download_count", 0) for asset in assets)
        grand_total += subtotal
        print("\n%s%s - %d downloads" % (tag, marker, subtotal))
        for asset in assets:
            print("    %8d  %s" % (asset.get("download_count", 0), asset.get("name")))

    print("\nTotal across all releases: %d" % grand_total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
