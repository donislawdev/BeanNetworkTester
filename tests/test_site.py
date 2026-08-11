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

    Checked by HOST, not by string prefix: a first version compared the start of the
    URL against ours, which a host like `github.com.example.net` satisfies. And the
    CSS is scanned too - `@import` and `url()` are requests as much as a `src` is,
    and the first version could not see a web font at all.
    """
    from urllib.parse import urlsplit
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    allowed = {urlsplit(registry["base_url"]).netloc.lower(),
               urlsplit(registry["repo_url"]).netloc.lower()}
    check("the allow list resolved to real hosts", all(allowed) and len(allowed) == 2,
          f"({allowed})")

    urls = []
    for rel in written:
        if not rel.endswith((".html", ".css")):
            continue
        text = _read(os.path.join(out, rel.replace("/", os.sep)))
        urls += [(rel, u) for u in EXTERNAL.findall(text)]
        urls += [(rel, u) for u in CSS_EXTERNAL.findall(text)]
    for rel, url in urls:
        host = urlsplit(url if "//" in url else "//" + url).netloc.lower()
        check(f"{rel}: {url} is one of ours", host in allowed, f"(allowed: {sorted(allowed)})")


def test_every_page_has_one_headline_and_no_image_without_a_description(tmp_path):
    """Two mechanical rules that no screenshot shows.

    A page with two ``h1`` elements, or none, tells a crawler nothing about what it
    is. An image without ``alt`` is invisible to a screen reader and to image search
    alike, and it is the easiest thing in the world to leave out.
    """
    out, written = _build(tmp_path)
    for rel in [p for p in written if p.endswith(".html")]:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        check(f"{rel}: exactly one h1", len(re.findall(r"<h1[\s>]", page)) == 1,
              f"({len(re.findall(r'<h1[\\s>]', page))})")
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
    out, written = _build(tmp_path)
    registry = build_site.load_registry(ROOT)
    base = registry["base_url"]
    pages = [p for p in written if p.endswith("index.html")]
    expected = {lang["code"]: "%s/%s" % (base, lang["dir"] + "/" if lang["dir"] else "")
                for lang in registry["languages"]}
    for rel in pages:
        page = _read(os.path.join(out, rel.replace("/", os.sep)))
        pairs = dict(re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">',
                                page))
        for code, url in expected.items():
            check(f"{rel}: lists {code} (including itself)", pairs.get(code) == url,
                  f"(got {pairs.get(code)}, expected {url})")
        x_default = re.findall(r'hreflang="x-default" href="([^"]+)"', page)
        check(f"{rel}: exactly one x-default", len(x_default) == 1, f"({x_default})")
        check(f"{rel}: x-default is the default language",
              x_default[0] == expected[registry["default_language"]], f"({x_default[0]})")


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
            check(f"{rel}: it is a SoftwareApplication",
                  data.get("@type") == "SoftwareApplication", f"({data.get('@type')})")
            for field in ("name", "url", "operatingSystem", "downloadUrl"):
                check(f"{rel}: {field} is set", data.get(field), "(missing)")
            check(f"{rel}: a free app declares the price Google requires",
                  data.get("offers", {}).get("price") == "0", f"({data.get('offers')})")
            for invented in ("aggregateRating", "review", "ratingValue", "softwareVersion"):
                check(f"{rel}: no {invented} (nobody gave us one)", invented not in data)
    check("the site carries structured data at all", blocks >= 1, f"({blocks})")


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
