"""Render the Chocolatey and WinGet package sources for a published release.

Everything under ``packaging/`` is a TEMPLATE with ``{{PLACEHOLDER}}`` markers, and
this script is the only thing that fills them. That is convention 34 applied to
packaging: a version number written into a manifest by hand is a second source of
truth for ``VERSION.txt``, and it goes stale in the release where somebody forgets
it - quietly, because a manifest with the wrong version still parses.

The checksums and the asset names come from ONE input, the release's own
``SHA256SUMS.txt``. It carries both (``<hash> *<file>``) for the zip and for the
MSI, so there is nothing to retype and nothing to keep in step.

    python tools/build_packages.py --sums SHA256SUMS.txt

The WinGet manifest installs the MSI first, so a full render needs the MSI's line.
The one render that happens BEFORE the MSI exists - ``tools/sign_release.py``
rendering the MSI's own source - asks for that template alone:

    python tools/build_packages.py --sums SHA256SUMS.txt --only msi

Output goes to ``build/packaging/`` (git-ignored, like the website's build). What
this script does NOT do is submit anything: pushing to the Chocolatey feed or
opening a pull request against microsoft/winget-pkgs is a human step, deliberately.
See ``packaging/README.md`` for the order those steps have to happen in.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beantester import appinfo                                    # noqa: E402

PACKAGING_DIR = os.path.join(ROOT, "packaging")
OUT_DIR = os.path.join(ROOT, "build", "packaging")
TEMPLATE_SUFFIX = ".in"
PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

# The Chocolatey package id and the WinGet identifier. Lower-case-with-hyphens is
# the Chocolatey convention, Publisher.Package is the WinGet one.
CHOCO_ID = "bean-network-tester"
WINGET_ID = f"{appinfo.AUTHOR}.{appinfo.TOOL_ID}"
# Pinned rather than "latest": a schema version is a contract, and a manifest that
# silently follows a moving target fails in the reviewer's CI, not ours.
#
# 🔴 1.12.0, and the way this number was got wrong once is the useful part. It was
# 1.28.0 from 2026-08-12 to 2026-08-25, read from the folder listing under
# `microsoft/winget-pkgs/doc/manifest/schema` - the newest directory there. Both
# `winget validate` and the local install accepted it. The SUBMISSION did not: the
# first pull request came back with `Manifest-Version-Error` from "02. Manifest
# Validation", within minutes.
#
# What the pipeline actually accepts is what MERGED manifests carry, and on
# 2026-08-25 the ones landing on master carried 1.12.0. So the authoritative source
# for this field is other people's accepted submissions, not the documentation tree -
# a schema can be documented before the validation service takes it.
# Checked that 1.12.0 still defines every field this manifest needs:
# `NestedInstallerType`, `NestedInstallerFiles`, `ArchiveBinariesDependOnPath` and
# `ElevationRequirement`.
WINGET_SCHEMA = "1.12.0"

# 🔴 The MSI's UpgradeCode: the identity of the PRODUCT, generated once and never
# again. Windows Installer finds a machine's previous version through this GUID and
# nothing else. Change it and every machine that already has the package keeps the
# old install forever, side by side with the new one, with no upgrade path and no
# way to reach the old one from the new package - and it is not fixable afterwards,
# because the fix would have to run on machines we cannot reach.
#
# This is why it is a constant here and not a value in the template: the renderer is
# the one place that owns a value, and `test_the_msi_upgrade_code_never_changes`
# pins this literal so a careless regeneration reddens instead of shipping.
MSI_UPGRADE_CODE = "4BE626D0-E975-4E56-92B4-146EF6AEDF3C"


def _read_json(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return json.load(f)


PACKAGED_ASSETS = (".zip", ".msi")


def parse_sums(path):
    """``<hash> *<file>`` lines -> {".zip": (hash, file), ".msi": (hash, file)}.

    The star is sha256sum's binary marker. Only the two assets a package installs
    are kept; a release candidate has no MSI, so that key may be missing, and the
    caller decides whether that is an error.
    """
    found = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            digest, _, name = line.partition(" ")
            # Order matters: the separator is whitespace and THEN the `*` binary-mode
            # marker, so stripping the star first leaves it attached to a leading
            # space and it rides into the URL. Measured, not imagined - it did.
            name = name.strip().lstrip("*").strip()
            suffix = os.path.splitext(name)[1].lower()
            if suffix not in PACKAGED_ASSETS:
                continue
            # Two lines for one kind of asset means two files were concatenated, and
            # picking either one would publish a checksum nobody chose.
            if suffix in found:
                raise SystemExit(f"{path}: two {suffix} lines ({found[suffix][1]}, {name})")
            found[suffix] = (digest.strip(), name)
    if ".zip" not in found:
        raise SystemExit(f"{path}: no .zip line found")
    return found


def release_date(version):
    """The date this version was released, read from the changelog that ships it.

    ``CHANGELOG.md`` already has to carry a dated section for ``VERSION.txt`` - a
    test enforces that - so it is the one place that knows, and WinGet's
    ``ReleaseDate`` reads from it rather than from a second answer typed here.
    """
    wanted = re.compile(r"^##\s*\[" + re.escape(version) + r"\]\s*-\s*(\d{4}-\d{2}-\d{2})")
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        for line in f:
            found = wanted.match(line.strip())
            if found:
                return found.group(1)
    raise SystemExit(f"CHANGELOG.md has no dated section for {version} - close it first")


def values(version, digest, asset, msi=None):
    """Every placeholder, each read from the one place that owns it.

    ``msi`` is the MSI's ``(hash, file)``, or None before the MSI exists - and then
    the MSI's own placeholders are simply absent, so a template that needs them is
    refused by name in ``build`` instead of rendering with a hole.
    """
    site = _read_json("site", "site.json")
    home = _read_json("site", "pages", "home", "page.json")["languages"]["en"]
    tagline = _read_json("site", "i18n", "en.json")["site.tagline"]
    repo = site["repo_url"].rstrip("/")
    slug = repo.split("github.com/", 1)[-1]      # owner/name, which is what a CDN wants
    tag = f"v{version}"
    # Every entry here is used by a template, and a test keeps it that way in both
    # directions: an unknown placeholder is a typo, a dead entry is a manifest that
    # quietly stopped carrying a field.
    table = {
        "VERSION": version,
        "URL": f"{repo}/releases/download/{tag}/{asset}",
        "SHA256": digest.lower(),
        "SHA256_UPPER": digest.upper(),
        "CHOCO_ID": CHOCO_ID,
        "WINGET_ID": WINGET_ID,
        "WINGET_SCHEMA": WINGET_SCHEMA,
        "UPGRADE_CODE": MSI_UPGRADE_CODE,
        # The registry's spelling, braces included. WinGet matches an installed MSI
        # against it EXACTLY - its log says `Include:UpgradeCode='{...}'[Exact]`.
        "UPGRADE_CODE_BRACED": "{" + MSI_UPGRADE_CODE + "}",
        "APP_NAME": appinfo.APP_NAME,
        "TOOL_ID": appinfo.TOOL_ID,          # the data folder's name, which has no spaces
        "EXE_NAME": appinfo.EXE_NAME,
        "PUBLISHER": appinfo.AUTHOR,
        "LICENSE": appinfo.LICENSE_NAME,
        "LICENSE_URL": f"{repo}/blob/master/LICENSE",
        "COPYRIGHT": appinfo.COPYRIGHT,
        "PROJECT_URL": site["base_url"].rstrip("/"),
        "REPO_URL": repo,
        "RELEASE_NOTES_URL": f"{repo}/releases/tag/{tag}",
        # 🔴 A CDN, and PINNED to the tag - Chocolatey's moderation held 0.5.0 back over
        # this on 2026-09-05. `{repo}/raw/...` is treated as raw.githubusercontent.com,
        # which is not a CDN; jsDelivr, Statically and the Githack variants are. The
        # BRANCH was the second fault, and nobody had complained about it yet: an icon on
        # `master` follows whatever the branch does next, under a package that is already
        # approved. Same bytes either way (measured that day: 21 155 B, image/png, from
        # both hosts), so this moves the address and not the picture.
        "ICON_URL": f"https://cdn.jsdelivr.net/gh/{slug}@{tag}/bean.png",
        "RELEASE_DATE": release_date(version),
        "TAGLINE": tagline,
        # The same words inside a single-quoted PowerShell string, where an apostrophe
        # is written twice. The tagline is website copy and is edited as such; one
        # "don't" in it must not turn into a syntax error in Chocolatey's install.
        "TAGLINE_PS": tagline.replace("'", "''"),
        "DESCRIPTION": home["description"],
        # Where the exe sits inside the archive: one top-level directory, named
        # after the tool, exactly as `release.yml` zips `dist/BeanNetworkTester`.
        "NESTED_EXE": f"{appinfo.TOOL_ID}/{appinfo.EXE_NAME}",
    }
    if msi is not None:
        msi_digest, msi_asset = msi
        table["MSI_URL"] = f"{repo}/releases/download/{tag}/{msi_asset}"
        table["MSI_SHA256_UPPER"] = msi_digest.upper()
    return table


def display_path(path):
    """``path`` relative to the repository, or absolute when that is impossible.

    ``os.path.relpath`` RAISES on Windows when the two paths sit on different
    drives, and this is only ever used to print what was written. Rendering into
    a directory on another volume is a legitimate thing to ask for, and it is
    what the Windows CI runner does by default - the repository is on one drive
    and the temporary directory on another, which is how this was found.
    """
    try:
        return os.path.relpath(path, ROOT)
    except ValueError:
        return path


def templates():
    # Sorted directories as well as files: os.walk lists them in whatever order the
    # file system keeps, which is alphabetical on NTFS and not on ext4, and a render
    # (or a refusal half-way through one) should not depend on the machine.
    for base, dirs, names in os.walk(PACKAGING_DIR):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(base, name)
            yield path, os.path.relpath(path, PACKAGING_DIR)


def package_kind(relative):
    """The top directory of a template - ``chocolatey``, ``msi`` or ``winget``."""
    return relative.replace(os.sep, "/").split("/", 1)[0]


def kinds():
    return sorted({package_kind(rel) for _, rel in templates()
                   if rel.endswith(TEMPLATE_SUFFIX)})


def render(text, table, where):
    unknown = sorted({m.group(1) for m in PLACEHOLDER.finditer(text)} - set(table))
    if unknown:
        raise SystemExit(f"{where}: unknown placeholder(s) {unknown}")
    return PLACEHOLDER.sub(lambda m: str(table[m.group(1)]), text)


def build(sums_path, version=None, only=None):
    """Render every template, or only the ``only`` kind (see ``kinds``)."""
    version = version or appinfo.__version__
    assets = parse_sums(sums_path)
    # The commonest way to get this wrong is to feed the PREVIOUS release's file.
    # The asset name carries the tag, so the mismatch is catchable, and silently
    # publishing a manifest that points at the wrong build is not recoverable.
    for _, asset in assets.values():
        if f"v{version}" not in asset:
            raise SystemExit(f"{asset} is not the asset for v{version} - wrong SHA256SUMS.txt?")
    digest, asset = assets[".zip"]
    msi = assets.get(".msi")
    table = values(version, digest, asset, msi=msi)

    selected = [(path, rel) for path, rel in templates()
                # Only templates become package files. Everything else under
                # packaging/ is for the person reading the repository - README.md
                # talks ABOUT placeholders, and copying it would both ship it and
                # trip the check below.
                if rel.endswith(TEMPLATE_SUFFIX)
                and (only is None or package_kind(rel) == only)]
    if not selected:
        # Saying this out loud beats writing nothing and letting the caller wonder.
        # The way to get here is a checkout without packaging/ - which is why a test
        # keeps those files tracked - or an `only` that names no kind.
        raise SystemExit(f"{PACKAGING_DIR}: no {TEMPLATE_SUFFIX} templates found"
                         + (f" for '{only}' (kinds: {', '.join(kinds())})" if only else ""))

    # Everything is rendered before anything is written. A refusal half-way through
    # used to leave the packages rendered so far in OUT_DIR, which looks like a
    # finished render to whoever packs it next.
    rendered = []
    for path, relative in selected:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        # 🔴 Said by name, because the generic "unknown placeholder" would send the
        # reader hunting for a typo. The WinGet manifest installs the MSI first - it
        # is the only installer that gives the program a Start Menu entry - so a
        # sums file without the MSI cannot produce it. A release candidate has no
        # MSI and is never submitted; the render before signing uses `--only msi`.
        wanted = {m.group(1) for m in PLACEHOLDER.finditer(text)}
        if msi is None and any(name.startswith("MSI_") for name in wanted):
            raise SystemExit(
                f"{sums_path}: no .msi line, and {relative} installs the MSI. Render "
                f"from the published release's SHA256SUMS.txt, or pass --only msi for "
                f"the render that happens before the MSI is built.")
        text = render(text, table, relative)
        left = PLACEHOLDER.search(text)
        if left:
            raise SystemExit(f"{relative}: {left.group(0)} survived rendering")
        rendered.append((os.path.join(OUT_DIR, relative)[: -len(TEMPLATE_SUFFIX)], text))

    written = []
    for target, text in rendered:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        written.append(display_path(target))
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sums", required=True,
                        help="the release's SHA256SUMS.txt (carries hash AND asset name)")
    parser.add_argument("--version", default=None,
                        help="override VERSION.txt (for trying a past release)")
    parser.add_argument("--only", default=None, choices=kinds(),
                        help="render one kind of package; 'msi' is the render that "
                             "happens before the MSI exists (tools/sign_release.py)")
    args = parser.parse_args(argv)
    for name in build(args.sums, args.version, args.only):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
