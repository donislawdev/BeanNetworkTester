"""The tool that writes our supply-chain hashes cannot be talked off PyPI.

`tools/pin_hashes.py` asks the PyPI JSON API what artefacts a pinned version has
and writes their digests into `requirements*.txt`. Those digests are what pip
refuses to install around, so an answer fetched from the wrong place would be a
lie the whole build then depends on.

A scanner flags the `urlopen` call because it cannot see the shape of its argument,
and names `file://` as the risk. That specific risk is not reachable and this file
proves it rather than asserting it. The reachable one is quieter: `version` is only
barred from whitespace and semicolons, so before the fix a `?` or `#` in it turned
the path into a query or a fragment - a different endpoint, answering about
something else, silently.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from urllib.parse import urlsplit                                    # noqa: E402

from fakes import check                                              # noqa: E402
from pin_hashes import _url                                          # noqa: E402

# Every shape that has ever been suggested as an escape, plus the ordinary one.
HOSTILE = [
    "3.1.3",                       # the real thing, so this cannot pass on nothing
    "../../../etc/passwd",
    "..%2F..%2Fetc",
    "x?a=b",
    "x#frag",
    # An at-sign and an authority - the shape of an escape attempt. Written with an
    # IP rather than a hostname on purpose: a hostname here reads as an email address
    # to `test_no_stray_email_addresses_in_the_public_tree`, which is right to say so
    # about a public repository, and an IP is the more realistic attempt anyway.
    "x@127.0.0.1",
    "/../..//",
    "file:///c:/windows/win.ini",
    "https://evil.example/pypi",
]


def test_no_version_can_move_the_request_off_pypi():
    """Scheme and host are fixed, whatever the version says."""
    for version in HOSTILE:
        parts = urlsplit(_url("pydivert", version))
        check(f"scheme stays https for {version!r}", parts.scheme == "https",
              f"({parts.scheme})")
        check(f"host stays pypi.org for {version!r}", parts.netloc == "pypi.org",
              f"({parts.netloc})")


def test_no_version_can_truncate_the_path_into_a_query():
    """The whole version stays one path segment - no query, no fragment.

    This is the half that was actually reachable: `1.0?x=y` used to ask PyPI a
    different question and get a confident answer to it.
    """
    for version in HOSTILE:
        url = _url("pydivert", version)
        parts = urlsplit(url)
        check(f"no query for {version!r}", parts.query == "", f"({url})")
        check(f"no fragment for {version!r}", parts.fragment == "", f"({url})")
        check(f"the path still ends at /json for {version!r}",
              parts.path.endswith("/json"), f"({parts.path})")


def test_the_name_is_escaped_too():
    """The regex bars a slash in a name today. The escaping does not rely on it.

    A guard that only holds while a second, unrelated pattern keeps its current
    shape is a guard waiting to stop holding.
    """
    parts = urlsplit(_url("../evil", "1.0"))
    check("host survives a hostile name", parts.netloc == "pypi.org", f"({parts})")
    check("the name stays one segment", parts.path.count("/") == 4, f"({parts.path})")
