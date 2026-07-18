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
import sys
import urllib.request

DEFAULT_REPO = "donislawdev/BeanNetworkTester"


def fetch_releases(repo):
    """Every published release for ``owner/name`` (newest first), via the public API."""
    url = "https://api.github.com/repos/%s/releases?per_page=100" % repo
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "bnt-downloads",
    })
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
