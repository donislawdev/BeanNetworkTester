"""The website generator: the page must never publish quietly-broken SEO.

Why these guards and not others
-------------------------------
A landing page fails differently from a program. Nothing crashes: the page renders,
the visitor sees something reasonable, and the mistake is a truncated description,
a language nobody can reach, a stylesheet with a misspelled variable, or a download
button pointing at a stale address. None of that shows up in a screenshot, and the
whole point of the site is the click that leaves it. So the tests spend their effort
on the two failure modes that are invisible:

* the SOURCES are wrong in a way that still builds (a missing translation, a
  description search engines will cut, two pages claiming one address) - the builder
  has to refuse, and here it is held to refusing;
* the OUTPUT drifts away from the program (a second dark theme, a link that no
  longer reaches the releases page) - the palette is read out of ``theme.py`` and
  the URLs out of one registry, and these check that it stayed that way.
"""
import os
import re
import shutil
import subprocess
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_site                                                   # noqa: E402

SITE = os.path.join(ROOT, "site")
HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
EXTERNAL = re.compile(r'(?:href|src)="((?:https?:)?//[^"]+)"')


def _build(tmp_path, name="out"):
    """Build the real site into a temporary directory and return (out, files)."""
    out = str(tmp_path / name)
    return out, build_site.build(ROOT, out)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _sandbox(base):
    """A copy of ``site/`` plus the two files the builder reads outside it.

    The listed assets are only copied, never parsed, so a one-byte stand-in keeps a
    sandbox cheap enough to make one per mutation.
    """
    root = str(base)
    os.makedirs(root, exist_ok=True)
    shutil.copytree(SITE, os.path.join(root, "site"))
    gui = os.path.join(root, "beantester", "gui")
    os.makedirs(gui)
    shutil.copyfile(os.path.join(ROOT, build_site.THEME_FILE), os.path.join(gui, "theme.py"))
    for asset in build_site.load_registry(ROOT).get("assets", []):
        target = os.path.join(root, asset["source"].replace("/", os.sep))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as handle:
            handle.write(b"x")
    return root


def _fails(root, out, why):
    """Assert the build refuses, and say what it should have refused."""
    try:
        build_site.build(root, out)
    except build_site.SiteError:
        return
    check("the build refuses when %s" % why, False)


def _edit_json(path, mutate):
    import json
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    mutate(data)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


# -- the output ----------------------------------------------------------------- #

def test_the_builder_writes_a_page_for_every_language(tmp_path):
    """Every declared language gets a real file, and the default one sits at the root."""
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    check("the build wrote files at all (an empty build passes every check below)",
          len(written) >= 4, f"({written})")
    for lang in registry["languages"]:
        target = os.path.join(out, lang["dir"], "index.html") if lang["dir"] else \
            os.path.join(out, "index.html")
        check(f"{lang['code']}: the page exists at {lang['dir'] or '/'}",
              os.path.isfile(target), f"({target})")
        html = _read(target)
        check(f"{lang['code']}: the document declares its language",
              f'<html lang="{lang["html_lang"]}"' in html)
        check(f"{lang['code']}: nothing is left unsubstituted",
              "{{" not in html, f"({[m for m in re.findall(r'{{.*?}}', html)][:3]})")


def test_every_page_carries_a_title_and_a_description_search_engines_can_show(tmp_path):
    """Bounds, not presence: a description cut in half is invisible from the source."""
    out, written = _build(tmp_path)
    pages = [p for p in written if p.endswith("index.html")]
    check("there are pages to measure", pages, "(none)")
    for rel in pages:
        html = _read(os.path.join(out, rel.replace("/", os.sep)))
        title = re.search(r"<title>(.*?)</title>", html, re.S)
        desc = re.search(r'<meta name="description" content="(.*?)">', html, re.S)
        check(f"{rel}: has a title", title and title.group(1).strip())
        check(f"{rel}: has a description", desc and desc.group(1).strip())
        check(f"{rel}: the title fits in {build_site.TITLE_LEN[1]} characters",
              len(title.group(1)) <= build_site.TITLE_LEN[1], f"({len(title.group(1))})")
        check(f"{rel}: the description fits in {build_site.DESC_LEN[1]} characters",
              len(desc.group(1)) <= build_site.DESC_LEN[1], f"({len(desc.group(1))})")


def test_the_download_button_points_at_the_release_page(tmp_path):
    """The site has exactly one job: send the visitor to the download.

    Pinned to ``/releases/latest`` rather than to an asset file name, because the
    asset carries the version (``BeanNetworkTester-v0.4.0-windows-x64.zip``), so a
    direct link would 404 for every release after the one it was written for.
    """
    out, written = _build(tmp_path)
    expected = "%s/releases/latest" % build_site.load_registry(ROOT)["repo_url"].rstrip("/")
    for rel in [p for p in written if p.endswith("index.html")]:
        html = _read(os.path.join(out, rel.replace("/", os.sep)))
        check(f"{rel}: links to the releases page", f'href="{expected}"' in html,
              f"(expected {expected})")


def test_the_page_asks_nothing_of_a_third_party(tmp_path):
    """No external font, script, image or tracker - measured on the output.

    Two reasons, and the second is the one a test can hold: the program sends no
    data anywhere, so a page that quietly reports its visitors to somebody else
    would contradict it, and every third-party request is a request that can be
    slow, blocked or gone.
    """
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    allowed = (registry["base_url"], registry["repo_url"].rstrip("/"))
    for rel in [p for p in written if p.endswith(".html")]:
        html = _read(os.path.join(out, rel.replace("/", os.sep)))
        for url in EXTERNAL.findall(html):
            check(f"{rel}: {url} is one of ours", url.startswith(allowed),
                  f"(allowed: {allowed})")


def test_the_language_switcher_reaches_every_language_and_marks_the_current_one(tmp_path):
    """A language nobody can click is a language that does not exist."""
    out, _ = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    for lang in registry["languages"]:
        rel = os.path.join(lang["dir"], "index.html") if lang["dir"] else "index.html"
        html = _read(os.path.join(out, rel))
        check(f"{lang['code']}: the current language is marked, not linked",
              f'<span aria-current="page" lang="{lang["html_lang"]}">{lang["name"]}</span>' in html)
        for other in registry["languages"]:
            if other["code"] == lang["code"]:
                continue
            check(f"{lang['code']}: links to {other['code']}",
                  f'hreflang="{other["code"]}"' in html)


def test_building_twice_writes_the_same_bytes(tmp_path):
    """Second run, same target: the class of bug only a repeat can see.

    A timestamp, a set iterated in hash order or a file left behind by the first run
    all look perfect once. This is also what keeps a deploy from reporting changes
    that are not changes.
    """
    out = str(tmp_path / "twice")
    first = build_site.build(ROOT, out)
    snapshot = {rel: _read(os.path.join(out, rel.replace("/", os.sep)))
                for rel in first if rel.endswith((".html", ".css"))}
    second = build_site.build(ROOT, out)
    check("the same files are written", first == second,
          f"(only in one run: {set(first) ^ set(second)})")
    for rel, text in snapshot.items():
        check(f"{rel}: identical on the second build",
              text == _read(os.path.join(out, rel.replace("/", os.sep))))


def test_the_builder_runs_as_a_script(tmp_path):
    """The workflow calls it as a script, so the script path is the one under test."""
    out = str(tmp_path / "cli")
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_site.py"),
                           "--out", out], capture_output=True, text=True)
    check("the builder exits clean", proc.returncode == 0, f"({proc.stderr[-400:]})")
    check("it says what it wrote", "wrote" in proc.stdout, f"({proc.stdout[:200]})")
    check("the page is there", os.path.isfile(os.path.join(out, "index.html")))


# -- the single sources --------------------------------------------------------- #

def test_the_palette_is_read_out_of_the_theme_module(tmp_path):
    """The page and the program must not become two different dark themes.

    The parser also has to survive the shape ``theme.py`` really uses: ``FG, MUT``
    and ``ACC, OK, WARN`` are tuple assignments, and a reader that only understood
    ``NAME = value`` would miss five of the colours and fall back to nothing.
    """
    registry = build_site.load_registry(ROOT)
    colours = build_site.palette(ROOT, registry["palette"])
    check("every mapped variable got a colour",
          set(colours) == set(registry["palette"]), f"({sorted(colours)})")
    theme = _read(os.path.join(ROOT, build_site.THEME_FILE))
    for var, name in registry["palette"].items():
        value = colours[var]
        check(f"{var} is {name} from theme.py, verbatim",
              re.search(r"\b%s\b[^\n]*%s" % (re.escape(name), re.escape(value)), theme),
              f"({value})")
    out, _ = _build(tmp_path, "palette")
    css = _read(os.path.join(out, "assets", "style.css"))
    for var, value in colours.items():
        check(f"the stylesheet declares {var}", "%s: %s;" % (var, value) in css)


def test_no_colour_is_written_down_a_second_time(tmp_path):
    """A hex literal under site/ would be a colour living in two places.

    Derived shades come from ``color-mix`` so that "slightly lighter accent" cannot
    become an independent value that stops following the program.
    """
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(SITE):
        for name in filenames:
            if not name.endswith((".html", ".css", ".json", ".svg", ".js")):
                continue
            path = os.path.join(dirpath, name)
            for number, line in enumerate(_read(path).splitlines(), 1):
                if HEX.search(line):
                    offenders.append("%s:%d" % (os.path.relpath(path, ROOT), number))
    check("no hex colour under site/ (they live in beantester/gui/theme.py)",
          not offenders, f"({offenders[:5]})")


def test_the_stylesheet_uses_only_variables_it_declares(tmp_path):
    """A misspelled ``var(--acccent)`` renders an unstyled page and nothing else."""
    out, _ = _build(tmp_path, "vars")
    css = _read(os.path.join(out, "assets", "style.css"))
    declared = set(re.findall(r"^\s*(--[a-z0-9-]+):", css, re.M))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    check("the scan found variables at all", declared and used,
          f"(declared {len(declared)}, used {len(used)})")
    check("every variable the CSS uses is declared", not used - declared,
          f"({sorted(used - declared)})")


def test_every_language_file_carries_the_same_keys_and_real_text():
    """Convention 9, applied to the site: identical key sets, nothing empty.

    Same rule as ``lang/*.json`` and for the same reason - a half-translated page
    looks finished, so nobody reports it.
    """
    registry = build_site.load_registry(ROOT)
    codes = build_site.language_codes(registry)
    texts = build_site.load_i18n(ROOT, codes, registry["default_language"])
    reference = set(texts[registry["default_language"]])
    check("there are texts to compare", len(reference) >= 10, f"({len(reference)})")
    for code in codes:
        check(f"{code}: the same keys as {registry['default_language']}",
              set(texts[code]) == reference,
              f"({sorted(set(texts[code]) ^ reference)[:5]})")


# -- refusing to publish something broken --------------------------------------- #

def test_the_sandbox_the_rejection_tests_use_is_itself_valid(tmp_path):
    """An UNMUTATED sandbox has to build, or every rejection test below is vacuous.

    ``_fails`` accepts any ``SiteError``, so a sandbox missing one file of its own
    would make all seven mutations "pass" while proving nothing - the same shape as
    the fake packet whose two ports were equal, which made assertions about
    direction hold without checking anything. Measured, not assumed: this builds,
    and each mutation then fails with its own message.
    """
    root = _sandbox(tmp_path / "clean")
    written = build_site.build(root, str(tmp_path / "clean-out"))
    check("the sandbox builds when nothing is mutated", len(written) >= 4, f"({written})")


def test_the_build_refuses_a_source_that_would_publish_a_broken_page(tmp_path):
    """Seven ways to be wrong, each of which still renders a plausible page.

    This is the half of the guard that matters: every one of these would go
    unnoticed for months, because the page would look fine.
    """
    out = str(tmp_path / "rejected")

    root = _sandbox(tmp_path / "no_translation")
    _edit_json(os.path.join(root, "site", "i18n", "pl.json"),
               lambda d: d.pop("cta.download"))
    _fails(root, out, "a language is missing a key")

    root = _sandbox(tmp_path / "empty_text")
    _edit_json(os.path.join(root, "site", "i18n", "pl.json"),
               lambda d: d.update({"cta.download": "   "}))
    _fails(root, out, "a translation is blank")

    root = _sandbox(tmp_path / "unknown_placeholder")
    body = os.path.join(root, "site", "pages", "home", "en.html")
    with open(body, "a", encoding="utf-8") as handle:
        handle.write("\n<p>{{cta.nothing_defines_this}}</p>\n")
    _fails(root, out, "a body names a placeholder nobody defines")

    root = _sandbox(tmp_path / "long_description")
    _edit_json(os.path.join(root, "site", "pages", "home", "page.json"),
               lambda d: d["languages"]["en"].update({"description": "x" * 400}))
    _fails(root, out, "a description is longer than a search result shows")

    root = _sandbox(tmp_path / "missing_body")
    os.remove(os.path.join(root, "site", "pages", "home", "pl.html"))
    _fails(root, out, "a page has no body in one of the languages")

    root = _sandbox(tmp_path / "renamed_colour")
    _edit_json(os.path.join(root, "site", "site.json"),
               lambda d: d["palette"].update({"--bg": "NO_SUCH_COLOUR"}))
    _fails(root, out, "theme.py no longer declares a mapped colour")

    root = _sandbox(tmp_path / "missing_asset")
    os.remove(os.path.join(root, "bean.png"))
    _fails(root, out, "a listed asset is not in the repository")


def test_two_pages_may_not_claim_one_address(tmp_path):
    """A duplicate slug means one of the two pages silently never ships."""
    root = _sandbox(tmp_path / "duplicate")
    home = os.path.join(root, "site", "pages", "home")
    clone = os.path.join(root, "site", "pages", "zzz-clone")
    shutil.copytree(home, clone)
    _edit_json(os.path.join(clone, "page.json"), lambda d: d.update({"id": "zzz-clone"}))
    _fails(root, str(tmp_path / "dup-out"), "two pages resolve to the same address")


def test_the_builder_will_not_write_into_a_directory_that_is_not_a_site(tmp_path):
    """`--out` is a path a human types, and pruning deletes files.

    So the builder only prunes what looks like its own previous output. Anything
    else, it refuses to touch.
    """
    out = tmp_path / "someones_folder"
    out.mkdir()
    (out / "important.txt").write_text("not mine", encoding="utf-8")
    _fails(ROOT, str(out), "the target holds files that are not a previous build")
    check("the stranger's file is still there", (out / "important.txt").is_file())


def test_a_renamed_page_stops_being_served(tmp_path):
    """Stale output is the one kind of stale a visitor sees and we do not."""
    out = str(tmp_path / "pruned")
    build_site.build(ROOT, out)
    stale = os.path.join(out, "old-page", "index.html")
    os.makedirs(os.path.dirname(stale), exist_ok=True)
    with open(stale, "w", encoding="utf-8") as handle:
        handle.write("<!doctype html>")
    build_site.build(ROOT, out)
    check("the file left by an earlier build is gone", not os.path.exists(stale))
