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
import posixpath
import re
import shutil
import subprocess
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_site                                                   # noqa: E402

SITE = os.path.join(ROOT, "site")
HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
EXTERNAL = re.compile(r'(?:href|src|srcset|content)="((?:https?:)?//[^"]+)"')
# A stylesheet reaches the network too, and a web font is exactly how a page starts
# telling somebody else who is reading it.
CSS_EXTERNAL = re.compile(r'(?:@import\s+|url\()\s*["\']?((?:https?:)?//[^"\')\s]+)')


def _build(tmp_path, name="out"):
    """Build the real site into a temporary directory and return (out, files)."""
    out = str(tmp_path / name)
    return out, build_site.build(ROOT, out)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _sandbox(base):
    """A copy of ``site/`` plus the files the builder reads outside it.

    The listed assets are only copied, never parsed, so a one-byte stand-in keeps a
    sandbox cheap enough to make one per mutation.
    """
    root = str(base)
    os.makedirs(root, exist_ok=True)
    shutil.copytree(SITE, os.path.join(root, "site"))
    gui = os.path.join(root, "beantester", "gui")
    os.makedirs(gui)
    shutil.copyfile(os.path.join(ROOT, build_site.THEME_FILE), os.path.join(gui, "theme.py"))
    # The pages name field labels and preset names through the program's own language
    # files, so a sandbox without them is not a copy of the real inputs.
    shutil.copytree(os.path.join(ROOT, "lang"), os.path.join(root, "lang"))
    # The scenarios page reads the shipped corpus, so a sandbox without it is not a
    # copy of the real inputs.
    shutil.copytree(os.path.join(ROOT, "scenarios"), os.path.join(root, "scenarios"))
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
              f'<html lang="{lang["code"]}"' in html)
        check(f"{lang['code']}: nothing is left unsubstituted",
              "{{" not in html, f"({[m for m in re.findall(r'{{.*?}}', html)][:3]})")


def test_every_page_carries_a_title_and_a_description_search_engines_can_show(tmp_path):
    """Bounds, not presence: a description cut in half is invisible from the source."""
    out, written = _build(tmp_path)
    pages = [p for p in written if p.endswith(".html")]
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

    🔴 A REQUEST is not a LINK, and the first version of this test conflated them. It
    matched `href` and `src` together, so adding the owner's accounts to the footer
    made it fail - correctly by its own wording, wrongly by its purpose. What must be
    ours is everything the page FETCHES: images, stylesheets, scripts, and whatever CSS
    pulls in with `url()` or `@import`. Where a visitor can CLICK is a different
    question, answered by the test below.

    Checked by HOST, not by string prefix: an earlier version compared the start of the
    URL against ours, which a host like `github.com.example.net` satisfies.
    """
    from urllib.parse import urlsplit
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    ours = urlsplit(registry["base_url"]).netloc.lower()

    fetched = []
    for rel in written:
        if not rel.endswith((".html", ".css")):
            continue
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        fetched += [(rel, u) for u in re.findall(r'(?:src|srcset)="([^"]+)"', text)]
        fetched += [(rel, u) for u in re.findall(r'<link\b[^>]*href="([^"]+)"', text)]
        fetched += [(rel, u) for u in CSS_EXTERNAL.findall(text)]
    check("the scan found things the page fetches", len(fetched) >= 10, f"({len(fetched)})")
    for rel, url in fetched:
        if not url.startswith(("http://", "https://", "//")):
            continue                      # relative: served from this site by definition
        host = urlsplit(url if "//" in url else "//" + url).netloc.lower()
        check(f"{rel}: fetches {url} from somebody else", host == ours,
              f"(only {ours} may be fetched)")


def test_every_outbound_link_goes_somewhere_we_named(tmp_path):
    """Links may leave the site - but only to hosts the registry lists.

    The other half of the split above. A page is allowed to point at GitHub and at the
    owner's accounts, because those are in `site.json`. Anything else absolute is
    either a typo or something nobody decided to publish, and both should fail here
    rather than ship.
    """
    from urllib.parse import urlsplit
    out, written = _build(tmp_path, "links")
    registry = build_site.load_registry(ROOT)
    allowed = {urlsplit(registry["base_url"]).netloc.lower(),
               urlsplit(registry["repo_url"]).netloc.lower()}
    allowed |= {urlsplit(entry["url"]).netloc.lower() for entry in registry.get("social", [])}
    check("the allow list came from the registry", len(allowed) >= 4, f"({sorted(allowed)})")

    seen = 0
    for rel in [p for p in written if p.endswith(".html")]:
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        for url in re.findall(r'<a\b[^>]*href="((?:https?:)?//[^"]+)"', text):
            host = urlsplit(url if "//" in url else "//" + url).netloc.lower()
            check(f"{rel}: {url} is a host the registry names", host in allowed,
                  f"(allowed: {sorted(allowed)})")
            seen += 1
    check("there were outbound links to check", seen >= 10, f"({seen})")


def test_every_page_has_one_headline_and_no_image_without_a_description(tmp_path):
    """Two mechanical rules that no screenshot shows.

    A page with two ``h1`` elements, or none, tells a crawler nothing about what it
    is. An image without ``alt`` is invisible to a screen reader and to image search
    alike, and it is the easiest thing in the world to leave out.
    """
    out, written = _build(tmp_path)
    for rel in [p for p in written if p.endswith(".html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        # One search, one number. The second copy of the pattern used to live
        # inside an f-string EXPRESSION, where a backslash is legal only from
        # Python 3.12 - and `requires-python` here says 3.10.
        headings = re.findall(r"<h1[\s>]", page)
        check(f"{rel}: exactly one h1", len(headings) == 1, f"({len(headings)})")
        for tag in re.findall(r"<img\b[^>]*>", page):
            check(f"{rel}: every image describes itself ({tag[:60]})",
                  re.search(r'\balt="', tag))


def test_the_language_switcher_reaches_every_language_and_marks_the_current_one(tmp_path):
    """A language nobody can click is a language that does not exist."""
    out, _ = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    for lang in registry["languages"]:
        rel = os.path.join(lang["dir"], "index.html") if lang["dir"] else "index.html"
        html = _read(os.path.join(out, rel))
        check(f"{lang['code']}: the current language is marked, not linked",
              f'<span aria-current="page" lang="{lang["code"]}">{lang["name"]}</span>' in html)
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


# -- more than one page: reachability, uniqueness, links ------------------------ #

def test_no_page_is_an_orphan(tmp_path):
    """Every page is linked from every other page, in its own language.

    A page nothing links to is reachable through the sitemap and nowhere else: a
    reader never finds it, and a crawler treats it as an afterthought. The footer
    list is generated from the page registry precisely so that adding a page cannot
    forget to link it, and this is the check that the generation really happened.
    """
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    pages = build_site.load_pages(ROOT, registry)
    indexable = [p for p in pages if not p["output"]]
    check("there is more than one page to link", len(indexable) > 1, f"({len(indexable)})")

    for code in build_site.language_codes(registry):
        for page in indexable:
            rel = posixpath.join(page["languages"][code]["dir_path"], "index.html").lstrip("/")
            text = _read(os.path.join(out, rel.replace("/", os.sep)))
            for other in indexable:
                if other["id"] == page["id"]:
                    continue
                label = other["languages"][code]["link_text"]
                check(f"{rel} links to {other['id']} ({label})",
                      f">{label}</a>" in text, "(missing from the footer list)")


def test_no_two_pages_claim_the_same_title_or_description(tmp_path):
    """Duplicate titles and descriptions are a real defect, not untidiness.

    Two pages with one title compete for the same result, and a search engine picks
    one and quietly discounts the other. It is also the most likely mistake when a
    page is created by copying its neighbour, which is exactly how these were made.
    """
    registry = build_site.load_registry(ROOT)
    pages = build_site.load_pages(ROOT, registry)
    for code in build_site.language_codes(registry):
        for field in ("title", "description", "link_text"):
            values = [p["languages"][code][field] for p in pages if code in p["languages"]]
            duplicates = sorted({v for v in values if values.count(v) > 1})
            check(f"{code}: every page has its own {field}", not duplicates,
                  f"({duplicates})")


def test_the_polish_pages_have_polish_addresses(tmp_path):
    """A localised page with an English address is a half-translated page.

    Not cosmetic: the words in a URL are read by both a person deciding whether to
    click and a search engine deciding what the page is about. The home page is
    exempt - its slug is empty in every language by design.
    """
    registry = build_site.load_registry(ROOT)
    pages = build_site.load_pages(ROOT, registry)
    default = registry["default_language"]
    for page in pages:
        if page["output"] or page["id"] == "home":
            continue
        for code in page["codes"]:
            if code == default:
                continue
            own = page["languages"][code]["slug"]
            english = page["languages"][default]["slug"]
            check(f"{page['id']} [{code}]: the address is translated, not copied",
                  own and own != english, f"({own!r} vs {english!r})")


def test_every_internal_link_reaches_a_page_that_exists(tmp_path):
    """A broken internal link is invisible from the source and obvious to a visitor.

    Resolved against the built tree the way a browser would: relative to the
    directory the page sits in, with a directory link meaning its index.html. This is
    the guard that makes localised slugs safe to hand-write - get one wrong and the
    link that names it fails here instead of in production.
    """
    out, written = _build(tmp_path)
    pages = [p for p in written if p.endswith(".html")]
    checked = 0
    for rel in pages:
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        here = posixpath.dirname(rel)
        for href in re.findall(r'(?:href|src)="([^"]+)"', text):
            if href.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            target = href.split("#")[0].split("?")[0]
            if not target:
                continue
            full = posixpath.normpath(posixpath.join(here, target.lstrip("/"))
                                      if target.startswith("/")
                                      else posixpath.join(here, target))
            if target.startswith("/"):
                full = posixpath.normpath(target.lstrip("/"))
            candidates = [full, posixpath.join(full, "index.html")]
            exists = any(os.path.exists(os.path.join(out, c.replace("/", os.sep)))
                         for c in candidates)
            check(f"{rel}: {href} reaches something", exists, f"(looked for {candidates})")
            checked += 1
    check("the link scan actually followed links", checked >= 20, f"({checked})")


def test_the_pages_never_write_a_name_from_the_program_by_hand(tmp_path):
    """A preset name in the prose must come from ``lang/<code>.json``, not from memory.

    Measured, not feared: the first draft of these guides invented three Polish preset
    names and two field labels. The prose read perfectly and no test could see it,
    because a guide that tells somebody to fill in a field nobody can find is wrong in
    the same way a correct sentence is right. The pages now name them through
    ``{{app.<key>}}``, so a rename in the program either follows or fails the build.

    Preset names are checked strictly - they are distinctive phrases and cannot appear
    by accident. Field labels are not: "Buffer" and "Jitter" are ordinary words that
    start sentences, so the placeholder mechanism carries them and the test below only
    proves the wiring works. That half is deliberately not airtight, and saying so is
    better than a guard with false alarms nobody trusts.
    """
    import json as jsonlib
    from beantester import presets
    registry = build_site.load_registry(ROOT)
    for code in build_site.language_codes(registry):
        strings = jsonlib.load(open(os.path.join(ROOT, "lang", "%s.json" % code),
                                    encoding="utf-8"))
        names = [strings[key] for key in presets.PRESETS if key in strings]
        check(f"{code}: there are preset names to look for", len(names) > 10, f"({len(names)})")
        for path in sorted(glob_pages(code)):
            text = _read(path)
            for name in names:
                check(f"{os.path.basename(os.path.dirname(path))} [{code}]: "
                      f"{name!r} is written by hand instead of {{{{app.presets.*}}}}",
                      name not in text, "(use the placeholder)")


def glob_pages(code):
    import glob
    return glob.glob(os.path.join(SITE, "pages", "*", "%s.html" % code))


def test_the_program_strings_really_reach_the_built_pages(tmp_path):
    """The other half: every ``{{app.*}}`` a page uses resolves to the program's text.

    Proves the wiring rather than the absence of hand-written copies - so a renamed
    field label shows up on the site, and a key that stops existing fails the build.
    """
    out, _ = _build(tmp_path, "appstrings")
    registry = build_site.load_registry(ROOT)
    pages = build_site.load_pages(ROOT, registry)
    used = 0
    for code in build_site.language_codes(registry):
        strings = build_site.load_app_strings(ROOT, code)
        for page in pages:
            if code not in page["languages"]:
                continue
            body = page["languages"][code]["body"]
            keys = re.findall(r"\{\{(app\.[a-z0-9_.]+)\}\}", body)
            if not keys:
                continue
            rel = posixpath.join(page["languages"][code]["dir_path"], "index.html").lstrip("/")
            target = page["output"] or rel
            text = _read(os.path.join(out, target.replace("/", os.sep)))
            for key in keys:
                check(f"{target}: {key} is a real key in lang/{code}.json", key in strings,
                      "(missing)")
                check(f"{target}: the page shows {strings[key]!r} for {key}",
                      strings[key] in text, "(not in the built page)")
                used += 1
    check("the pages use the program's strings at all", used >= 10, f"({used})")


def test_the_exit_codes_on_the_page_are_the_programs_exit_codes(tmp_path):
    """A hand-written table of exit codes is a second copy of ``exitcodes.py``.

    It is on the site because a pipeline author needs it, and it is guarded because
    the whole point of that table is that a build can trust the numbers. Until the
    table is generated (which is the honest fix), this is what stands between it and
    a silent divergence.
    """
    from beantester import exitcodes
    out, written = _build(tmp_path, "codes")
    codes = {value for name, value in vars(exitcodes).items()
             if name.isupper() and isinstance(value, int)}
    check("there are exit codes to look for", len(codes) >= 8, f"({sorted(codes)})")
    # Selected through the registry, not by substring: the first version matched
    # "limit-predkosci" because it contains "ci", and then asserted that a page about
    # speed limits lists every exit code.
    registry = build_site.load_registry(ROOT)
    ci = [p for p in build_site.load_pages(ROOT, registry) if p["id"] == "ci"]
    check("the CI page is in the registry", len(ci) == 1, f"({[p['id'] for p in ci]})")
    pages = [posixpath.join(ci[0]["languages"][code]["dir_path"], "index.html").lstrip("/")
             for code in ci[0]["codes"]]
    for rel in pages:
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        listed = {int(n) for n in re.findall(r"<td>(\d+)(?:\s*/\s*\d+)?</td>", text)}
        listed |= {int(n) for n in re.findall(r"<td>\d+\s*/\s*(\d+)</td>", text)}
        missing = sorted(codes - listed)
        check(f"{rel}: every exit code the program can return is on the page", not missing,
              f"(missing {missing}, found {sorted(listed)})")


# -- the layer search engines read ---------------------------------------------- #

def test_every_indexable_page_declares_itself_canonical(tmp_path):
    """One canonical, absolute, and pointing at the page it sits on.

    A relative or missing canonical lets a crawler pick which of several addresses
    is the real one, and a canonical copied from another page hands the ranking to
    that page. Both are silent.
    """
    out, written = _build(tmp_path)
    base = build_site.load_registry(ROOT)["base_url"]
    for rel in [p for p in written if p.endswith("index.html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        found = re.findall(r'<link rel="canonical" href="([^"]+)">', page)
        check(f"{rel}: exactly one canonical", len(found) == 1, f"({found})")
        expected = "%s/%s" % (base, rel[:-len("index.html")])
        check(f"{rel}: the canonical is this page, absolute", found[0] == expected,
              f"(got {found[0]}, expected {expected})")


def test_the_language_annotations_are_reciprocal_with_one_x_default(tmp_path):
    """Google's two hard requirements for hreflang, checked across the real files.

    Each version must list ITSELF as well as every other, or the whole set can be
    ignored - so this reads every page and compares the sets, rather than trusting
    that one generator wrote them all the same way. And exactly one ``x-default``,
    because two is undefined behaviour dressed as thoroughness.
    """
    out, _ = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    base = registry["base_url"]
    default = registry["default_language"]
    # Derived per PAGE, not per language: every page has its own localised address in
    # each language, so a set of expectations built from the language directories
    # alone would only ever have described the home page. The first version of this
    # test did exactly that and passed until a second page existed.
    pages = [p for p in build_site.load_pages(ROOT, registry) if not p["output"]]
    check("there are pages to compare", len(pages) >= 2, f"({len(pages)})")
    for page in pages:
        expected = {code: "%s/%s" % (base, entry["dir_path"] + "/" if entry["dir_path"] else "")
                    for code, entry in page["languages"].items()}
        for code in page["codes"]:
            rel = posixpath.join(page["languages"][code]["dir_path"], "index.html").lstrip("/")
            text = _read(os.path.join(out, rel.replace("/", os.sep)))
            pairs = dict(re.findall(
                r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', text))
            for other, url in expected.items():
                check(f"{rel}: lists {other} (including itself)", pairs.get(other) == url,
                      f"(got {pairs.get(other)}, expected {url})")
            x_default = re.findall(r'hreflang="x-default" href="([^"]+)"', text)
            check(f"{rel}: exactly one x-default", len(x_default) == 1, f"({x_default})")
            check(f"{rel}: x-default is the default language",
                  x_default[0] == expected[default], f"({x_default[0]})")


def test_the_social_card_says_the_same_thing_as_the_page(tmp_path):
    """A card that contradicts the page is what gets shared, not the page."""
    out, written = _build(tmp_path)
    for rel in [p for p in written if p.endswith("index.html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        title = re.search(r"<title>(.*?)</title>", page, re.S).group(1)
        desc = re.search(r'<meta name="description" content="(.*?)">', page, re.S).group(1)
        canonical = re.search(r'<link rel="canonical" href="([^"]+)">', page).group(1)
        meta = dict(re.findall(r'<meta (?:property|name)="((?:og|twitter):[^"]+)" '
                               r'content="([^"]*)">', page))
        for key, value in (("og:title", title), ("og:description", desc),
                           ("og:url", canonical), ("twitter:title", title),
                           ("twitter:description", desc)):
            check(f"{rel}: {key} matches the page", meta.get(key) == value,
                  f"(got {meta.get(key)!r})")
        for key in ("og:type", "og:site_name", "og:image", "og:locale", "twitter:card",
                    "twitter:image", "og:image:alt", "twitter:image:alt"):
            check(f"{rel}: {key} is set", meta.get(key), "(missing)")


def test_the_card_image_reports_the_size_the_file_really_has(tmp_path):
    """Dimensions read from the PNG, not typed next to it.

    A number typed into a registry beside an image is a number that stops being true
    the day the image is replaced, and a card with wrong dimensions reflows or crops
    in somebody else's timeline, where we never see it.
    """
    out, written = _build(tmp_path, "card")
    registry = build_site.load_registry(ROOT)
    source = build_site.asset_source(registry, ROOT, registry["og_image"])
    width, height = build_site._png_size(source)
    check("the icon is a PNG with real dimensions", width > 0 and height > 0,
          f"({width}x{height})")
    for rel in [p for p in written if p.endswith("index.html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        check(f"{rel}: the declared width is the file's width",
              f'content="{width}"' in page, f"({width})")
        check(f"{rel}: the declared height is the file's height",
              f'content="{height}"' in page, f"({height})")


def test_the_browser_chrome_colour_comes_from_the_programs_palette(tmp_path):
    """`theme-color` paints the address bar on a phone, so it is a colour like any
    other: it lives in theme.py or it becomes a second dark theme."""
    out, written = _build(tmp_path, "chrome")
    registry = build_site.load_registry(ROOT)
    expected = build_site.palette(ROOT, registry["palette"])["--bg"]
    for rel in [p for p in written if p.endswith(".html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        check(f"{rel}: theme-color is the page background from theme.py",
              f'<meta name="theme-color" content="{expected}">' in page, f"({expected})")


def test_the_structured_data_invents_neither_a_rating_nor_a_version(tmp_path):
    """The honest half of the schema, and the half a later session might "fix".

    Google's software-app rich result needs ``aggregateRating`` or ``review``. This
    project has neither, so the markup is not rich-result eligible - and the fix for
    that is NOT to write a number down. A rating nobody gave is a fabricated review.
    ``softwareVersion`` is absent for the same reason the page prints no version: the
    file naming it names the NEXT release from the moment it is bumped.
    """
    import json as jsonlib
    out, written = _build(tmp_path)
    blocks = 0
    for rel in [p for p in written if p.endswith(".html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        for raw in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>',
                              page, re.S):
            blocks += 1
            check(f"{rel}: the block does not close its own script element",
                  "</script>" not in raw)
            data = jsonlib.loads(raw.replace("\\u003c", "<"))
            # Two kinds are expected now, and an unexpected third one is a finding:
            # this test used to assert that EVERY block is a SoftwareApplication, which
            # was true until the breadcrumbs arrived and then failed for the right
            # reason. The allow list keeps that signal instead of dropping the check.
            kind = data.get("@type")
            check(f"{rel}: {kind} is a kind this site publishes on purpose",
                  kind in ("SoftwareApplication", "BreadcrumbList"), f"({kind})")
            if kind != "SoftwareApplication":
                continue
            for field in ("name", "url", "operatingSystem", "downloadUrl"):
                check(f"{rel}: {field} is set", data.get(field), "(missing)")
            check(f"{rel}: a free app declares the price Google requires",
                  data.get("offers", {}).get("price") == "0", f"({data.get('offers')})")
            for invented in ("aggregateRating", "review", "ratingValue", "softwareVersion"):
                check(f"{rel}: no {invented} (nobody gave us one)", invented not in data)
    check("the site carries structured data at all", blocks >= 1, f"({blocks})")


def test_every_guide_carries_the_trail_back_to_the_home_page(tmp_path):
    """A breadcrumb, in the language of the page, generated from the registry.

    Found by measuring the built output rather than by reading the plan: the guides
    carried no structured data at all, because the idea had been waved off with "flat
    pages have no hierarchy". Home -> page is the hierarchy, and it is what a search
    result shows instead of a bare URL.

    The home page must NOT have one (a trail of length one says nothing) and neither
    must the error page, which asks not to be indexed at all.
    """
    import json as jsonlib
    out, _ = _build(tmp_path, "crumbs")
    registry = build_site.load_registry(ROOT)
    base = registry["base_url"]
    pages = build_site.load_pages(ROOT, registry)
    home = next(p for p in pages if p["id"] == "home")

    def trails(rel):
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        found = []
        for raw in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>',
                              text, re.S):
            data = jsonlib.loads(raw.replace("\\u003c", "<"))
            if data.get("@type") == "BreadcrumbList":
                found.append(data["itemListElement"])
        return found

    check("the home page has no trail",
          not trails("index.html"), "(a one-step trail says nothing)")
    check("the error page has no trail", not trails("404.html"), "(it is noindex)")

    seen = 0
    for page in pages:
        if page["output"] or page["id"] == "home":
            continue
        for code in page["codes"]:
            rel = posixpath.join(page["languages"][code]["dir_path"], "index.html").lstrip("/")
            found = trails(rel)
            check(f"{rel}: exactly one breadcrumb trail", len(found) == 1, f"({len(found)})")
            steps = found[0]
            check(f"{rel}: the trail is home then this page", len(steps) == 2, f"({steps})")
            check(f"{rel}: it starts at the home page of this language",
                  steps[0]["item"] == "%s/%s" % (
                      base, home["languages"][code]["dir_path"] + "/"
                      if home["languages"][code]["dir_path"] else ""),
                  f"({steps[0]['item']})")
            check(f"{rel}: it names the page with its own label",
                  steps[1]["name"] == page["languages"][code]["link_text"],
                  f"({steps[1]['name']!r})")
            check(f"{rel}: both steps are absolute",
                  all(step["item"].startswith(base) for step in steps), f"({steps})")
            seen += 1
    check("there were trails to check", seen >= 4, f"({seen})")


def test_the_sitemap_lists_exactly_the_pages_that_may_be_indexed(tmp_path):
    """Both directions: every indexable page is in it, and nothing else is.

    A missing page is a page Google finds late. An extra entry is worse - a sitemap
    that lists a 404 or a noindex page is a sitemap Search Console reports as broken,
    and the report is about the sitemap, not about the page.
    """
    from xml.etree import ElementTree
    out, written = _build(tmp_path)
    base = build_site.load_registry(ROOT)["base_url"]
    xml = _read(os.path.join(out, "sitemap.xml"))
    root = ElementTree.fromstring(xml)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    listed = sorted(node.text for node in root.findall("s:url/s:loc", ns))
    indexable = sorted("%s/%s" % (base, rel[:-len("index.html")])
                       for rel in written if rel.endswith("index.html"))
    check("the sitemap lists every indexable page", listed == indexable,
          f"(only in one: {set(listed) ^ set(indexable)})")
    check("the 404 page is not offered as a destination",
          not any("404" in loc for loc in listed), f"({listed})")
    check("every entry is absolute", all(loc.startswith(base) for loc in listed))


def test_the_sitemap_is_the_shape_a_validator_will_accept(tmp_path):
    """Nothing in the file except the sitemap namespace - no foreign elements.

    🔴 This is a fixed bug with a guard, not a precaution. The first sitemap carried
    the language alternates as ``xhtml:link``, which is the form Google documents, and
    it made the file **fail XSD validation**: ``tUrl`` in the official schema ends with
    ``<xsd:any namespace="##other" processContents="strict"/>``, and *strict* means a
    validator must resolve a schema for the foreign element. Nothing imports an XHTML
    schema, so validators reject the document while Google accepts it - and a file a
    validator calls broken is a signal nobody can tell apart from a real fault.

    The alternates were removed rather than defended: the reciprocal ``hreflang`` set
    already sits in the head of every page, and one method is what Google asks for.
    """
    from xml.etree import ElementTree
    out, written = _build(tmp_path, "sitemapshape")
    registry = build_site.load_registry(ROOT)
    ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
    root = ElementTree.fromstring(_read(os.path.join(out, "sitemap.xml")))
    check("the root is a urlset in the sitemap namespace", root.tag == "{%s}urlset" % ns,
          f"({root.tag})")

    allowed = {"{%s}%s" % (ns, name) for name in ("loc", "lastmod", "changefreq", "priority")}
    urls = list(root)
    check("there are url entries", urls, "(none)")
    for url in urls:
        check("every child of urlset is a url", url.tag == "{%s}url" % ns, f"({url.tag})")
        kinds = [child.tag for child in url]
        foreign = [tag for tag in kinds if tag not in allowed]
        check("no foreign-namespace elements inside url (strict validation rejects them)",
              not foreign, f"({foreign})")
        check("exactly one loc", kinds.count("{%s}loc" % ns) == 1, f"({kinds})")

    locs = [url.find("{%s}loc" % ns).text for url in urls]
    check("every address is absolute",
          all(loc.startswith(registry["base_url"]) for loc in locs), f"({locs[:3]})")
    check("no address is listed twice", len(set(locs)) == len(locs),
          f"({len(locs) - len(set(locs))} duplicates)")
    pages = [p for p in build_site.load_pages(ROOT, registry) if not p["output"]]
    expected = len(pages) * len(build_site.language_codes(registry))
    check(f"every page in every language is listed ({expected})", len(locs) == expected,
          f"(got {len(locs)})")


def test_the_reference_tables_are_generated_from_the_registries(tmp_path):
    """The three tables on the reference page come from the program, not from prose.

    This is the drift the site could not otherwise avoid: seventeen profiles,
    twenty-nine flags and ten exit codes are exactly the kind of list that is copied
    once and then quietly disagrees with the program for years.
    """
    from beantester import exitcodes, fields, presets
    out, written = _build(tmp_path, "tables")
    registry = build_site.load_registry(ROOT)
    ref = next(p for p in build_site.load_pages(ROOT, registry) if p["id"] == "reference")
    for code in ref["codes"]:
        app = build_site.load_app_strings(ROOT, code)
        rel = posixpath.join(ref["languages"][code]["dir_path"], "index.html").lstrip("/")
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        for key in presets.PRESETS:
            name = app["app." + key]
            check(f"{rel}: the profile {name!r} is in the table", f"<td>{name}</td>" in text,
                  "(missing row)")
        for field in fields.FIELD_DEFS:
            if getattr(field, "cli", None):
                check(f"{rel}: --{field.cli} is in the table",
                      f"<code>--{field.cli}</code>" in text, "(missing row)")
        for name, value in vars(exitcodes).items():
            if name.isupper() and isinstance(value, int):
                check(f"{rel}: exit code {value} is in the table", f"<td>{value}</td>" in text,
                      "(missing row)")


def test_the_scenario_table_lists_exactly_what_ships(tmp_path):
    """Every scenario file appears, and nothing that is not a file does.

    The numbers - steps, length, whether it repeats - are read out of the JSON rather
    than described, because a sentence about a timeline is exactly the kind of prose
    that survives the timeline being edited. Both directions: a new scenario has to show
    up, and a row cannot name a file that is gone.
    """
    import glob
    out, _ = _build(tmp_path, "scenarios")
    registry = build_site.load_registry(ROOT)
    page = next(p for p in build_site.load_pages(ROOT, registry) if p["id"] == "scenarios")
    shipped = sorted(os.path.basename(p) for p in
                     glob.glob(os.path.join(ROOT, "scenarios", "*.json")))
    check("the program ships scenarios to list", len(shipped) >= 5, f"({shipped})")
    for code in page["codes"]:
        rel = posixpath.join(page["languages"][code]["dir_path"], "index.html").lstrip("/")
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        listed = re.findall(r"<td><code>([^<]+\.json)</code></td>", text)
        check(f"{rel}: every shipped scenario is in the table", sorted(listed) == shipped,
              f"(only in one: {set(listed) ^ set(shipped)})")


def test_no_page_writes_its_own_table_of_exit_codes(tmp_path):
    """The CI page used to carry a hand-typed copy. It uses the generated one now.

    Kept as a guard rather than as a memory: a second table is easy to add and hard to
    notice, and the whole argument for generating this one was that a pipeline author
    trusts the numbers.
    """
    import glob
    from beantester import exitcodes
    codes = sorted(str(value) for name, value in vars(exitcodes).items()
                   if name.isupper() and isinstance(value, int))
    offenders = []
    for path in glob.glob(os.path.join(SITE, "pages", "*", "??.html")):
        text = _read(path)
        rows = re.findall(r"<td>(\d+)</td>", text)
        if len([c for c in rows if c in codes]) >= 3:
            offenders.append(os.path.relpath(path, ROOT))
    check("no page body lists exit codes by hand (use {{page.exit_code_table}})",
          not offenders, f"({offenders})")


def test_every_exit_code_has_a_sentence_in_every_language():
    """A new exit code must not reach the site as a blank row.

    The program prints its own table in English only (convention 3), so the sentence
    lives in the site's language files - which means it needs the same completeness
    rule as everything else there.
    """
    import json as jsonlib
    from beantester import exitcodes
    registry = build_site.load_registry(ROOT)
    names = [name for name, value in vars(exitcodes).items()
             if name.isupper() and isinstance(value, int)]
    check("there are exit codes to describe", len(names) >= 8, f"({names})")
    for code in build_site.language_codes(registry):
        strings = jsonlib.load(open(os.path.join(SITE, "i18n", "%s.json" % code),
                                    encoding="utf-8"))
        for name in names:
            key = "exit.%s" % name.lower()
            check(f"{code}: {key} has a sentence", strings.get(key, "").strip(), "(missing)")


def test_the_footer_names_the_accounts_and_carries_no_brand_mark(tmp_path):
    """Accounts as text plus a glyph we drew - never somebody else's mark.

    Checked at the source (2026-08-11): the GitHub logo and the Octocat are trademarks
    with no open-source licence and modification forbidden, and the other networks are
    the same. Convention 35 requires every third-party asset here to be
    GPLv3-compatible with a notice, a licence text and a registry entry, which a
    trademark-restricted file cannot be - and a fork would be redistributing it. So
    this asserts both halves: the links are there, and no vendored mark is.
    """
    import glob
    out, written = _build(tmp_path, "footer")
    registry = build_site.load_registry(ROOT)
    accounts = registry.get("social", [])
    check("there are accounts to link", len(accounts) >= 3, f"({accounts})")
    for rel in [p for p in written if p.endswith("index.html")]:
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        for entry in accounts:
            check(f"{rel}: links {entry['name']}", f'href="{entry["url"]}"' in text, "(missing)")
            check(f"{rel}: names {entry['name']} in words", f">{entry['name']}</a>" in text,
                  "(missing)")
        check(f"{rel}: carries the drawn glyph", 'class="glyph"' in text, "(missing)")

    vendored = [os.path.relpath(p, ROOT) for p in
                glob.glob(os.path.join(SITE, "**", "*.svg"), recursive=True)]
    check("no vendored mark or icon file under site/", not vendored, f"({vendored})")
    for path in glob.glob(os.path.join(SITE, "**", "*.*"), recursive=True):
        lowered = _read(path).lower() if path.endswith((".html", ".css", ".json")) else ""
        check(f"{os.path.basename(path)}: no brand mark by name",
              "octocat" not in lowered and "invertocat" not in lowered, "(found)")


def test_llms_txt_describes_the_site_it_was_built_from(tmp_path):
    """One file per language, listing every page, generated from the registry.

    Verified before adding it: llms.txt is a proposal at version 2 (August 2026), not a
    standard, but it is published by OpenAI, Anthropic and Google for their own docs,
    generated by several documentation platforms and audited by Lighthouse. It earns a
    generated file here because people ask an assistant which tool to use, and an
    assistant has to extract what this is, what it costs, what it runs on and where to
    get it - facts a page for humans spreads across a layout.
    """
    out, written = _build(tmp_path, "llms")
    registry = build_site.load_registry(ROOT)
    base = registry["base_url"]
    pages = [p for p in build_site.load_pages(ROOT, registry) if not p["output"]]
    for lang in registry["languages"]:
        rel = posixpath.join(lang["dir"], "llms.txt").lstrip("/")
        check(f"{rel} was written", rel in written, f"({[w for w in written if 'llms' in w]})")
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        check(f"{rel}: starts with the site name as an H1", text.startswith("# "),
              f"({text[:40]!r})")
        check(f"{rel}: carries the one-blockquote summary the format asks for",
              "\n> " in text, "(no blockquote)")
        for page in pages:
            url = "%s/%s" % (base, page["languages"][lang["code"]]["dir_path"] + "/"
                             if page["languages"][lang["code"]]["dir_path"] else "")
            check(f"{rel}: lists {page['id']}", url in text, f"(missing {url})")
        check(f"{rel}: points at the download", "/releases/latest" in text, "(missing)")
        check(f"{rel}: says what it runs on", "Windows" in text, "(missing)")


def test_robots_lets_everything_in_and_names_the_sitemap(tmp_path):
    """The pointer is the only line here that does any work."""
    out, _ = _build(tmp_path)
    base = build_site.load_registry(ROOT)["base_url"]
    text = _read(os.path.join(out, "robots.txt"))
    check("robots.txt allows crawling", "Disallow: /\n" not in text, f"({text})")
    check("robots.txt names the sitemap", f"Sitemap: {base}/sitemap.xml" in text, f"({text})")


def test_the_error_page_works_from_an_address_that_does_not_exist(tmp_path):
    """The one page whose own address is unknown when it is served.

    GitHub Pages returns `404.html` AT the path that missed and does not redirect, so
    a relative reference resolves against that path: a miss at `/pl/x/y/` would fetch
    `/pl/x/y/assets/style.css` and the error page would render unstyled, with a home
    button pointing back at the address that had just failed. Measured on the built
    file, because the first version of this page did exactly that.
    """
    out, _ = _build(tmp_path, "notfound")
    page = _read(os.path.join(out, "404.html"))
    prefix = build_site._root_prefix(build_site.load_registry(ROOT))
    refs = re.findall(r'(?:href|src)="([^"]+)"', page)
    check("the error page has links to check", refs, "(none)")
    for ref in refs:
        ok = ref.startswith(("http://", "https://", "#")) or ref.startswith(prefix)
        check(f"404.html: {ref} does not depend on where the page was served from", ok,
              f"(expected an absolute URL, a fragment, or a path under {prefix})")


def test_the_error_page_is_a_file_pages_serves_and_asks_not_to_be_indexed(tmp_path):
    """GitHub Pages serves `/404.html` on a miss, and only that path."""
    out, written = _build(tmp_path)
    check("404.html sits at the root", "404.html" in written, f"({written})")
    page = _read(os.path.join(out, "404.html"))
    check("it asks not to be indexed", '<meta name="robots" content="noindex">' in page)
    check("it carries no canonical", "rel=\"canonical\"" not in page)
    check("it carries no language alternates", 'rel="alternate"' not in page)
    check("it offers a way out", "href=" in page)
    check(".nojekyll is written", ".nojekyll" in written)


# -- the workflow that publishes it --------------------------------------------- #
# Read as text, not through a YAML library: PyYAML is not in requirements-dev.txt, so
# importing it would make these tests an error on a fresh checkout. Every scan below
# fails when it cannot find what it expects - a guard that passes vacuously because
# the file moved under it is not a guard. Same approach as
# test_version_and_release.py::test_ci_and_release_freeze_the_same_python.

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "pages.yml")


def _workflow():
    """The workflow with its comment lines removed.

    A comment is not configuration, and a scan over raw text cannot tell them apart.
    Found immediately: the first version of the permissions check below failed on this
    very workflow, because a comment explaining why `pages: write` is NOT granted to
    the whole file contains those two words. Reading the prose as settings would have
    been the other failure too - a guard satisfied by a comment claiming the right
    thing while the setting says something else.
    """
    raw = _read(WORKFLOW)
    check("the Pages workflow is still there and non-trivial", len(raw) > 500,
          f"({len(raw)} bytes)")
    return "\n".join(line for line in raw.splitlines()
                     if not line.lstrip().startswith("#"))


def _jobs(text):
    """The workflow's jobs, as {name: block}. Only what follows the `jobs:` line."""
    lines = text.splitlines()
    start = [i for i, line in enumerate(lines) if line.rstrip() == "jobs:"]
    check("the workflow declares jobs", len(start) == 1, f"({start})")
    body = lines[start[0] + 1:]
    heads = [i for i, line in enumerate(body) if re.match(r"^  [A-Za-z0-9_-]+:\s*$", line)]
    check("the jobs are named", heads, "(none found)")
    out = {}
    for position, index in enumerate(heads):
        end = heads[position + 1] if position + 1 < len(heads) else len(body)
        out[body[index].strip().rstrip(":")] = "\n".join(body[index:end])
    return out


def test_the_workflow_uploads_exactly_what_it_built(tmp_path):
    """The directory the generator writes and the directory Pages takes are one.

    A mismatch here is the quietest failure in the whole chain: the build is green,
    the deployment is green, and the site that goes live is whatever was in the other
    directory - which is nothing.
    """
    text = _workflow()
    built = re.findall(r"build_site\.py --out (\S+)", text)
    uploaded = re.findall(r"^\s+path:\s*(\S+)\s*$", text, re.M)
    check("the workflow builds the site", len(built) == 1, f"({built})")
    check("the workflow uploads one directory", len(uploaded) == 1, f"({uploaded})")
    check("it uploads what it built", built[0] == uploaded[0],
          f"(built {built[0]}, uploaded {uploaded[0]})")


def test_the_workflow_rebuilds_when_any_source_of_the_page_changes(tmp_path):
    """Every input the page is built from is in the paths filter.

    Derived from the registry rather than typed twice: the asset list in
    `site/site.json` names the files the page ships, and an asset missing from the
    filter means replacing the icon or the screenshot changes nothing on the live
    site - and looks exactly like a page nobody edited.
    """
    text = _workflow()
    registry = build_site.load_registry(ROOT)
    needed = ["site/**", "tools/build_site.py", build_site.THEME_FILE.replace(os.sep, "/")]
    needed += [asset["source"] for asset in registry.get("assets", [])]
    # Derived, not typed: if the generator reads the scenario corpus - and it does, for
    # the table on the scenarios page - then editing a scenario changes the site, so the
    # filter has to fire on it. Without this the page would keep serving the previous
    # list and look like a page nobody edited.
    if "scenarios" in _read(os.path.join(ROOT, "tools", "build_site.py")):
        needed.append("scenarios/**")
    for path in needed:
        check(f"the paths filter covers {path}", f'"{path}"' in text, "(missing)")


def test_only_the_job_that_deploys_may_write_to_pages():
    """Least privilege, and the comment in ci.yml said where it belongs.

    A workflow-level `pages: write` would hand that power to every job in the file,
    including the one that runs a build and could one day run something else.
    """
    text = _workflow()
    jobs = _jobs(text)
    top = text.split("jobs:")[0]
    check("the workflow token only reads the repository by default",
          re.search(r"(?m)^permissions:\s*$\s+contents: read\s*$", top), f"({top[-200:]})")
    for scope in ("pages: write", "id-token: write"):
        check(f"{scope} is not granted at the top of the file", scope not in top)
        owners = [name for name, block in jobs.items() if scope in block]
        check(f"exactly one job asks for {scope}", len(owners) == 1, f"({owners})")
        check(f"{scope} belongs to the job that deploys",
              "deploy-pages" in jobs[owners[0]], f"({owners})")
    builders = [name for name, block in jobs.items() if "build_site.py --out" in block]
    check("the building job asks to READ the Pages configuration, not to write it",
          "pages: read" in jobs[builders[0]], "(missing)")


def test_the_site_guards_run_before_anything_is_published():
    """The tests in this file gate the publication, in the job that builds it."""
    text = _workflow()
    jobs = _jobs(text)
    builders = [name for name, block in jobs.items() if "build_site.py --out" in block]
    check("one job builds the site", len(builders) == 1, f"({builders})")
    block = jobs[builders[0]]
    check("it runs the site guards", "pytest tests/test_site.py" in block, "(missing)")
    check("the guards run before the build, not after",
          block.index("pytest tests/test_site.py") < block.index("build_site.py --out"))


def test_a_deployment_is_never_cancelled_half_way():
    """Cancelling a deploy in flight can leave a half-replaced site, and Pages has
    no rollback. Late is better."""
    text = _workflow()
    check("the workflow serialises deployments",
          re.search(r"(?m)^concurrency:\s*$\s+group: pages\s*$", text), "(missing)")
    check("a running deployment is not cancelled",
          re.search(r"(?m)^\s+cancel-in-progress: false\s*$", text), "(missing)")


def test_the_workflow_refuses_to_publish_to_an_address_the_pages_do_not_claim():
    """The owner's DNS step, enforced instead of remembered.

    Every canonical, hreflang and sitemap entry in the output names `base_url`. If the
    repository publishes somewhere else - because the custom domain is not set yet -
    the pages would point at an address that does not serve them, and Google would be
    reading a set of canonicals aimed into the dark. So the build compares the two and
    stops, before anything is uploaded.
    """
    text = _workflow()
    jobs = _jobs(text)
    builders = [name for name, block in jobs.items() if "build_site.py --out" in block]
    block = jobs[builders[0]]
    check("the build reads the Pages configuration",
          "actions/configure-pages@" in block, "(missing)")
    check("it compares that address with base_url", "base_url" in block, "(missing)")
    check("the comparison happens before the upload",
          block.index("base_url") < block.index("upload-pages-artifact"))
    check("a mismatch stops the run", "sys.exit(1)" in block, "(missing)")
    deployers = [name for name, b in jobs.items() if "deploy-pages@" in b]
    check("one job deploys", len(deployers) == 1, f"({deployers})")
    after = jobs[deployers[0]]
    for evidence in ('<link rel="canonical"', 'hreflang="x-default"', "sitemap.xml"):
        check(f"the deployed site is read back for {evidence}", evidence in after,
              "(missing)")


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
    would make every mutation below "pass" while proving nothing - the same shape as
    the fake packet whose two ports were equal, which made assertions about
    direction hold without checking anything. Measured, not assumed: this builds,
    and each mutation then fails with its own message.
    """
    root = _sandbox(tmp_path / "clean")
    written = build_site.build(root, str(tmp_path / "clean-out"))
    check("the sandbox builds when nothing is mutated", len(written) >= 4, f"({written})")


def test_the_build_refuses_a_source_that_would_publish_a_broken_page(tmp_path):
    """Ten ways to be wrong, each of which still renders a plausible page.

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

    root = _sandbox(tmp_path / "card_image_nothing_produces")
    _edit_json(os.path.join(root, "site", "site.json"),
               lambda d: d.update({"og_image": "assets/nothing-makes-this.png"}))
    _fails(root, out, "the social card names an image the build does not produce")

    root = _sandbox(tmp_path / "scenario_without_steps")
    _edit_json(os.path.join(root, "scenarios", "cafe-wifi.json"),
               lambda d: d.update({"steps": []}))
    _fails(root, out, "a shipped scenario has no steps")

    root = _sandbox(tmp_path / "no_scenarios_at_all")
    shutil.rmtree(os.path.join(root, "scenarios"))
    _fails(root, out, "the scenario corpus is missing entirely")

    root = _sandbox(tmp_path / "unknown_schema")
    _edit_json(os.path.join(root, "site", "pages", "home", "page.json"),
               lambda d: d.update({"schema": "Prodcut"}))
    _fails(root, out, "a page asks for a kind of structured data that does not exist")

    root = _sandbox(tmp_path / "translated_error_page")
    _edit_json(os.path.join(root, "site", "pages", "404", "page.json"),
               lambda d: d["languages"].update({"pl": dict(d["languages"]["en"])}))
    _fails(root, out, "a single-output page declares a language that will never be written")


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
