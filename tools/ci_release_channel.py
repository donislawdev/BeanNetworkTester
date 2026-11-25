#!/usr/bin/env python3
"""Which release a channel's workflow is about, and whether it may publish it.

One rule for every channel that is fed from a published release - the container
image (docker.yml), PyPI (pypi.yml) and npm (npm.yml): only a STABLE release is
published, a tag ``vX.Y.Z`` with nothing after it, on a release that is published
and not marked as a pre-release. A release candidate is built and tried like a pull
request, and nothing leaves the runner. Standard library only: it runs on the
runner's system Python.

    python3 tools/ci_release_channel.py decide --channel pypi --event release \\
        --tag v1.1.0 --draft false --prerelease false >> "$GITHUB_OUTPUT"
"""
import argparse
import re
import sys

TAG = re.compile(r"v\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?")
STABLE = re.compile(r"v\d+\.\d+\.\d+")

# What each channel calls the thing it publishes, and what not publishing means.
CHANNELS = {
    "image": {"thing": "an image", "things": "images",
              "held": "its image is built and tried and nothing is pushed"},
    "pypi": {"thing": "a PyPI package", "things": "PyPI packages",
             "held": "its wheels are built and tried and nothing goes to PyPI"},
    "npm": {"thing": "an npm package", "things": "npm packages",
            "held": "its packages are built and tried and nothing goes to npm"},
}


def decide(event, tag, draft, prerelease, channel):
    """``{"tag", "version", "publish", "notice"}`` - or ``ValueError`` saying why not.

    ``draft`` and ``prerelease`` are the API's answers for ``tag`` ("true"/"false").
    """
    words = CHANNELS.get(channel)
    if words is None:
        raise ValueError(f"{channel!r} is not a channel ({', '.join(CHANNELS)})")
    if event not in ("release", "workflow_dispatch", "pull_request"):
        raise ValueError(f"{event!r} is not an event this workflow runs on")
    if not TAG.fullmatch(tag or ""):
        raise ValueError(f'"{tag}" is not a release tag, for example v1.1.0')
    if draft != "false":
        raise ValueError(f"{tag} is not published yet, and {words['thing']} is only ever "
                         "made of what people can download")
    stable = bool(STABLE.fullmatch(tag)) and prerelease == "false"
    publish = event != "pull_request"
    notice = ""
    if not stable:
        if event == "workflow_dispatch":
            raise ValueError(f"{tag} is not a stable release, and only stable releases become "
                             f"{words['things']}. Run this workflow with the tag of one, such "
                             "as v1.1.0.")
        if publish:
            notice = (f"{tag} is not a stable release, so {words['held']}. Only stable "
                      f"releases become {words['things']}.")
        publish = False
    return {"tag": tag, "version": tag[1:], "publish": "true" if publish else "false",
            "notice": notice}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    which = sub.add_parser("decide")
    which.add_argument("--channel", required=True, choices=sorted(CHANNELS))
    for name in ("--event", "--tag", "--draft", "--prerelease"):
        which.add_argument(name, required=True)
    args = parser.parse_args(argv)
    # Errors and notices on stderr: the workflow appends stdout to $GITHUB_OUTPUT,
    # which takes key=value lines only.
    try:
        outputs = decide(args.event, args.tag, args.draft, args.prerelease, args.channel)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if outputs["notice"]:
        print(f"::notice::{outputs['notice']}", file=sys.stderr)
    for key in ("tag", "version", "publish"):
        print(f"{key}={outputs[key]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
