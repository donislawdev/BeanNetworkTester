#!/usr/bin/env python3
"""Build the project website from ``site/`` into a directory of static files.

    python tools/build_site.py                 # -> build/site
    python tools/build_site.py --out _site     # what the Pages workflow uses

Why a generator of our own instead of a static-site generator
-------------------------------------------------------------
The page is a landing surface with a handful of subpages, and every candidate
generator brings a second ecosystem (Node or Ruby) into a repository that ships
one runtime dependency. What we would get in exchange - templating, i18n routing,
asset pipelines - is a few hundred lines here, and what we would pay is a
dependency tree, a second CI cache and a framework that changes its API. The
decisive argument is the other direction: this project keeps only what a machine
enforces, and a site built by our own code is a site the existing pytest suite can
hold to the same conventions as the program (see tests/test_site.py).

What is a single source, and what that buys
-------------------------------------------
* colours come from ``beantester/gui/theme.py``, read with ``ast`` rather than
  imported - so this runs on a Linux runner with no tkinter, and the page cannot
  drift into a second, slightly different dark theme;
* the copyright line comes from ``beantester/appinfo.py``;
* URLs are derived from one ``repo_url``, so the download button cannot point at a
  stale place;
* the version is deliberately NOT printed on the page. ``VERSION.txt`` is the next
  version from the moment the owner bumps it, which is BEFORE that release exists,
  so a page advertising it would offer a download that is not published yet. The
  button points at ``/releases/latest``, which is correct at every moment.

Failure is loud on purpose
--------------------------
Every mistake this thing can make - a missing translation, an empty description, a
placeholder nobody defined, two pages claiming one slug - produces a page that
looks fine and ranks nowhere, and nobody would notice for months. So each one
raises ``SiteError`` instead of falling back to a default. The one thing a builder
must never do is succeed quietly.
"""
import argparse
import ast
import html
import json
import os
import posixpath
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beantester import appinfo                                      # noqa: E402

SITE_DIR = "site"
DEFAULT_OUT = os.path.join("build", "site")
THEME_FILE = os.path.join("beantester", "gui", "theme.py")

# Search engines truncate a title around 60 characters and a description around
# 160. These are the bounds a page has to live inside to be shown whole, and they
# are checked rather than trusted, because "the description got cut in half" is
# invisible from the source.
TITLE_LEN = (15, 65)
DESC_LEN = (50, 160)

SLUG_RE = re.compile(r"^$|^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")
PLACEHOLDER_RE = re.compile(r"\{\{([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\}\}")


class SiteError(Exception):
    """A source file is wrong in a way that would publish a broken page."""


class Raw(str):
    """A context value that is already HTML and must not be escaped again.

    Everything else IS escaped: page titles, descriptions and every translated
    string land inside attributes and text nodes, and one apostrophe or ampersand
    in Polish copy would otherwise break the markup around it.
    """


# -- reading the sources -------------------------------------------------------- #

def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise SiteError("missing file: %s" % path)
    except json.JSONDecodeError as exc:
        raise SiteError("%s is not valid JSON: %s" % (path, exc))


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        raise SiteError("missing file: %s" % path)


def load_registry(root):
    """``site/site.json``: the one place the address, the languages and the palette
    mapping live. A move to another domain is meant to be one line, here."""
    reg = _read_json(os.path.join(root, SITE_DIR, "site.json"))
    for key in ("base_url", "repo_url", "default_language", "languages", "palette"):
        if not reg.get(key):
            raise SiteError("site.json: '%s' is missing or empty" % key)
    if reg["base_url"].endswith("/"):
        raise SiteError("site.json: base_url must not end with '/' (it is joined with paths)")

    # One code per language, used for THREE things: the directory, the `lang`
    # attribute and `hreflang`. There used to be a separate `html_lang` field
    # holding the same value in both languages, which is a second place for one
    # fact and would have drifted the day somebody edited one of them. The code is
    # the BCP-47 tag (`pt-BR` if it ever comes to that), and tag matching is
    # case-insensitive, so the lower-case directory name is the same tag.
    codes, dirs = [], []
    for lang in reg["languages"]:
        for key in ("code", "name", "dir"):
            if key not in lang:
                raise SiteError("site.json: language %r has no '%s'" % (lang, key))
        codes.append(lang["code"])
        dirs.append(lang["dir"])
    if len(set(codes)) != len(codes):
        raise SiteError("site.json: duplicate language code in %s" % codes)
    if len(set(dirs)) != len(dirs):
        raise SiteError("site.json: two languages share one directory in %s" % dirs)
    if reg["default_language"] not in codes:
        raise SiteError("site.json: default_language %r is not one of %s"
                        % (reg["default_language"], codes))
    if dict(zip(codes, dirs))[reg["default_language"]] != "":
        raise SiteError("site.json: the default language must live at the root (dir \"\")")
    return reg


def language_codes(registry):
    return [lang["code"] for lang in registry["languages"]]


def palette(root, mapping):
    """CSS custom properties read out of ``theme.py`` WITHOUT importing it.

    Importing would pull in tkinter, which the Linux runner does not need to have,
    and would make a website build depend on the GUI stack. Parsing also has to
    handle the shape the file really uses: ``FG, MUT = "#e4e6eb", "#9aa0aa"`` is a
    tuple assignment, and a parser that only understood ``NAME = value`` would
    silently miss five of the eleven colours (verified against theme.py, which
    declares FG/MUT and ACC/OK/WARN that way).

    A name that is no longer in theme.py raises. The alternative - falling back to
    a literal - is how a renamed constant turns into two dark themes nobody
    compared.
    """
    tree = ast.parse(_read_text(os.path.join(root, THEME_FILE)))
    found = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and isinstance(value, ast.Constant):
            found[target.id] = value.value
        elif isinstance(target, ast.Tuple) and isinstance(value, ast.Tuple):
            for name, item in zip(target.elts, value.elts):
                if isinstance(name, ast.Name) and isinstance(item, ast.Constant):
                    found[name.id] = item.value

    out = {}
    for var, name in mapping.items():
        if name not in found:
            raise SiteError("theme.py no longer declares %r (mapped to %s in site.json)"
                            % (name, var))
        colour = found[name]
        if not (isinstance(colour, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", colour)):
            raise SiteError("theme.py: %s is %r, which is not a 6-digit colour" % (name, colour))
        out[var] = colour
    return out


def load_i18n(root, codes, default_code):
    """One file per language, flat dotted keys, exactly like ``lang/*.json``.

    The same three rules the program's own i18n test enforces (convention 9):
    identical key sets, no empty text, and the default language never leaves a key
    as its own translation. A half-translated page is worse than an untranslated
    one, because it looks finished.
    """
    texts = {}
    for code in codes:
        data = _read_json(os.path.join(root, SITE_DIR, "i18n", "%s.json" % code))
        meta = data.pop("_meta", None)
        if not isinstance(meta, dict) or meta.get("code") != code:
            raise SiteError("i18n/%s.json: _meta must declare {\"code\": \"%s\", \"name\": ...}"
                            % (code, code))
        texts[code] = data

    reference = set(texts[default_code])
    for code, data in texts.items():
        missing = sorted(reference - set(data))
        extra = sorted(set(data) - reference)
        if missing or extra:
            raise SiteError("i18n/%s.json: key sets differ from %s (missing: %s, extra: %s)"
                            % (code, default_code, missing[:5], extra[:5]))
        for key, value in sorted(data.items()):
            if not isinstance(value, str) or not value.strip():
                raise SiteError("i18n/%s.json: %r has no text" % (code, key))
        if code == default_code:
            same = sorted(k for k, v in data.items() if v == k)
            if same:
                raise SiteError("i18n/%s.json: %s left as its own key" % (code, same[:5]))
    return texts


def load_pages(root, registry):
    """Every page directory under ``site/pages/``, with its metadata and bodies.

    A page exists in EVERY declared language or the build fails. Adding a language
    is meant to be a directory of files, and the honest moment to find out that a
    translation is missing is here, not in a search result.

    Two declared exceptions, both data rather than a magic page name:
    * ``output`` writes the page to one exact path (``404.html``, which is the file
      GitHub Pages serves for a miss) in the default language only. Pages serves one
      error document per site, so a translated set of them would be dead weight.
    * ``noindex`` keeps the page out of the sitemap and gives it a robots meta
      instead of a canonical. An error page that advertises itself as a destination
      is an error page in search results.
    """
    base = os.path.join(root, SITE_DIR, "pages")
    if not os.path.isdir(base):
        raise SiteError("no page directory: %s" % base)

    pages, seen = [], {}
    for page_id in sorted(os.listdir(base)):
        page_dir = os.path.join(base, page_id)
        if not os.path.isdir(page_dir):
            continue
        meta = _read_json(os.path.join(page_dir, "page.json"))
        if meta.get("id") != page_id:
            raise SiteError("pages/%s/page.json: 'id' must be %r, not %r"
                            % (page_id, page_id, meta.get("id")))
        if meta.get("schema") not in (None, "software_application"):
            raise SiteError("pages/%s/page.json: unknown schema %r "
                            "(the only kind today is 'software_application')"
                            % (page_id, meta.get("schema")))
        codes = ([registry["default_language"]] if meta.get("output")
                 else language_codes(registry))
        per_lang = meta.get("languages") or {}
        missing = [c for c in codes if c not in per_lang]
        if missing:
            raise SiteError("pages/%s: no metadata for language(s) %s" % (page_id, missing))
        if meta.get("output") and sorted(per_lang) != codes:
            raise SiteError("pages/%s: a page with 'output' is written once, in %s only, "
                            "so it must declare exactly that language (declares %s)"
                            % (page_id, codes[0], sorted(per_lang)))

        page = {"id": page_id, "order": meta.get("order", 999), "languages": {},
                "output": meta.get("output"), "noindex": bool(meta.get("noindex")),
                "schema": meta.get("schema"), "codes": codes}
        for code in codes:
            entry = per_lang[code]
            slug = entry.get("slug", None)
            title = (entry.get("title") or "").strip()
            description = (entry.get("description") or "").strip()
            if slug is None or not SLUG_RE.match(slug):
                raise SiteError("pages/%s [%s]: %r is not a valid slug "
                                "(lower case, digits and '-', '/' between segments)"
                                % (page_id, code, slug))
            if not TITLE_LEN[0] <= len(title) <= TITLE_LEN[1]:
                raise SiteError("pages/%s [%s]: the title is %d characters, allowed %d..%d"
                                % (page_id, code, len(title), *TITLE_LEN))
            if not DESC_LEN[0] <= len(description) <= DESC_LEN[1]:
                raise SiteError("pages/%s [%s]: the description is %d characters, allowed %d..%d"
                                % (page_id, code, len(description), *DESC_LEN))

            lang = _language(registry, code)
            if page["output"]:
                # Written to one exact file at the root, so it owns no directory and
                # cannot collide with a page that does.
                dir_path = ""
            else:
                dir_path = posixpath.join(lang["dir"], slug).strip("/")
                if dir_path in seen:
                    raise SiteError("pages/%s [%s]: '%s' is already taken by %s"
                                    % (page_id, code, dir_path or "/", seen[dir_path]))
                seen[dir_path] = "%s [%s]" % (page_id, code)

            page["languages"][code] = {
                "slug": slug, "title": title, "description": description,
                "dir_path": dir_path,
                "body": _read_text(os.path.join(page_dir, "%s.html" % code)),
            }
        pages.append(page)

    if not pages:
        raise SiteError("site/pages/ holds no pages")
    return sorted(pages, key=lambda p: (p["order"], p["id"]))


def _language(registry, code):
    for lang in registry["languages"]:
        if lang["code"] == code:
            return lang
    raise SiteError("no language %r in site.json" % code)


# -- rendering ------------------------------------------------------------------ #

def render(text, context, where):
    """Substitute ``{{dotted.key}}`` from ``context``. An unknown key is an error.

    A templating engine that leaves an unresolved placeholder on the page, or
    quietly replaces it with an empty string, publishes the mistake. There is no
    silent mode here on purpose.
    """
    missing = []

    def one(match):
        key = match.group(1)
        if key not in context:
            missing.append(key)
            return match.group(0)
        value = context[key]
        return value if isinstance(value, Raw) else html.escape(str(value), quote=True)

    out = PLACEHOLDER_RE.sub(one, text)
    if missing:
        raise SiteError("%s: nothing defines %s" % (where, sorted(set(missing))))
    return out


def _merge(context, extra, where):
    """Add keys, refusing to shadow one that already exists.

    Silent shadowing is how a translated string starts being overwritten by a
    computed value that happens to share its name, and the page still renders.
    """
    for key, value in extra.items():
        if key in context:
            raise SiteError("%s: %r is defined twice" % (where, key))
        context[key] = value
    return context


def _absolute(base_url, dir_path):
    """The public address of a page directory, with the trailing slash Pages serves."""
    return "%s/%s" % (base_url, dir_path + "/" if dir_path else "")


def head_meta(page, code, registry, texts, description):
    """Canonical, hreflang, social cards and structured data, as HTML.

    Composed here and not in the template because the set differs per page and the
    template language has no conditionals - and because every one of these is a
    claim a test can then read back out of the output.

    Two decisions worth keeping straight:
    * ``hreflang`` is emitted for EVERY language including this one, which is what
      makes the annotations reciprocal - Google ignores a set where a version does
      not list itself. Exactly one ``x-default``, pointing at the default language.
    * a page marked ``noindex`` (the 404) gets that and nothing else. A canonical or
      an alternate on an error page tells a crawler the error page is a destination.
    """
    entry = page["languages"][code]
    base = registry["base_url"]
    if page.get("noindex"):
        return Raw('<meta name="robots" content="noindex">')

    canonical = _absolute(base, entry["dir_path"])
    lines = ['<link rel="canonical" href="%s">' % html.escape(canonical, quote=True)]
    for lang in registry["languages"]:
        target = _absolute(base, page["languages"][lang["code"]]["dir_path"])
        lines.append('<link rel="alternate" hreflang="%s" href="%s">'
                     % (html.escape(lang["code"], quote=True),
                        html.escape(target, quote=True)))
    default_url = _absolute(base, page["languages"][registry["default_language"]]["dir_path"])
    lines.append('<link rel="alternate" hreflang="x-default" href="%s">'
                 % html.escape(default_url, quote=True))

    # A square 256 px icon is what the project has. `summary` is the card that fits
    # it: `summary_large_image` wants roughly 2:1 and would crop or letterbox this.
    # A dedicated banner is a drawing job, not a build job.
    image = "%s/%s" % (base, registry["og_image"].lstrip("/"))
    lang = _language(registry, code)
    social = [("og:type", "website"), ("og:site_name", texts[code]["site.name"]),
              ("og:title", entry["title"]), ("og:description", description),
              ("og:url", canonical), ("og:image", image),
              ("og:locale", lang.get("og_locale", code))]
    social += [("og:locale:alternate", other.get("og_locale", other["code"]))
               for other in registry["languages"] if other["code"] != code]
    for prop, value in social:
        lines.append('<meta property="%s" content="%s">'
                     % (prop, html.escape(str(value), quote=True)))
    for name, value in (("twitter:card", "summary"), ("twitter:title", entry["title"]),
                        ("twitter:description", description), ("twitter:image", image)):
        lines.append('<meta name="%s" content="%s">'
                     % (name, html.escape(str(value), quote=True)))

    if page.get("schema") == "software_application":
        lines.append(_software_json_ld(registry, texts[code], canonical, description, code))
    return Raw("\n".join(lines))


def _software_json_ld(registry, texts, canonical, description, code):
    """``SoftwareApplication``, honestly: no rating, and no version.

    Google's rich result for a software app needs ``aggregateRating`` or ``review``.
    This project has neither - there is no rating to report - and inventing one
    would be a fabricated review, so the markup describes the application and does
    not become rich-result eligible. That is a deliberate trade, and the test
    ``test_the_structured_data_invents_neither_a_rating_nor_a_version`` keeps a
    later session from "fixing" it with a number nobody gave us.

    ``softwareVersion`` is left out for the same reason the page does not print a
    version: VERSION.txt names the next release from the moment it is bumped, which
    is before that release exists.
    """
    software = registry.get("software") or {}
    data = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "applicationCategory": software.get("application_category", "DeveloperApplication"),
        "author": {"@type": "Person", "name": appinfo.AUTHOR},
        "description": description,
        "downloadUrl": "%s/releases/latest" % registry["repo_url"].rstrip("/"),
        "inLanguage": code,
        "isAccessibleForFree": True,
        "license": software.get("license_url", ""),
        "name": texts["site.name"],
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "operatingSystem": software.get("operating_system", ""),
        "url": canonical,
    }
    # `</script>` inside the block would end the element early, so the one character
    # that can do that is escaped. sort_keys keeps two builds byte-identical.
    body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    return '<script type="application/ld+json">\n%s\n</script>' % body.replace("<", "\\u003c")


def sitemap(pages, registry):
    """Every indexable page, with its language alternates.

    No ``lastmod``: it would need a clock, which would make two builds differ, and a
    date that is not the real date of the change is worse than none. Sitemaps carry
    the alternates as well as the pages do, which is what Google asks for when a set
    of localised pages is meant to be read as one.
    """
    base = registry["base_url"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
           '        xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for page in pages:
        if page.get("noindex") or page.get("output"):
            continue
        for code in language_codes(registry):
            out.append("  <url>")
            out.append("    <loc>%s</loc>"
                       % html.escape(_absolute(base, page["languages"][code]["dir_path"])))
            for lang in registry["languages"]:
                target = _absolute(base, page["languages"][lang["code"]]["dir_path"])
                out.append('    <xhtml:link rel="alternate" hreflang="%s" href="%s"/>'
                           % (html.escape(lang["code"], quote=True),
                              html.escape(target, quote=True)))
            default = _absolute(
                base, page["languages"][registry["default_language"]]["dir_path"])
            out.append('    <xhtml:link rel="alternate" hreflang="x-default" href="%s"/>'
                       % html.escape(default, quote=True))
            out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def robots(registry):
    """Open to everything, and it names the sitemap.

    There is nothing here worth hiding, and the one line that earns its place is the
    sitemap pointer: it is the only way a crawler finds the file without being told
    in Search Console.
    """
    return ("User-agent: *\n"
            "Allow: /\n"
            "\n"
            "Sitemap: %s/sitemap.xml\n" % registry["base_url"])


def _asset_prefix(dir_path):
    depth = len([part for part in dir_path.split("/") if part])
    return "../" * depth


def _relative_url(from_dir, to_dir):
    """A relative link between two page directories, always ending in '/'.

    Relative rather than root-absolute so the same output works under a domain root
    AND under a project path like /BeanNetworkTester/ - the fallback we may need if
    the custom domain is ever dropped.
    """
    rel = posixpath.relpath(to_dir or ".", from_dir or ".")
    if rel == ".":
        return "./"
    return rel if rel.endswith("/") else rel + "/"


def language_switcher(page, current_code, registry, label):
    """The language row in the header, as HTML.

    Built here rather than in the template because the template language has no
    loops, and a hand-written row would go stale the moment a third language is
    added - which is exactly the drift this project keeps losing to.

    A page that exists in one language only (the 404) gets no row at all. Offering a
    language this page does not have would be a link to a miss, from the page that
    exists because of a miss.
    """
    if len(page["codes"]) < 2:
        return Raw("")
    parts = []
    here = page["languages"][current_code]["dir_path"]
    for lang in registry["languages"]:
        code = lang["code"]
        if code not in page["languages"]:
            continue
        name = html.escape(lang["name"], quote=True)
        if code == current_code:
            parts.append('<span aria-current="page" lang="%s">%s</span>'
                         % (html.escape(code, quote=True), name))
        else:
            target = page["languages"][code]["dir_path"]
            parts.append('<a href="%s" hreflang="%s" lang="%s">%s</a>'
                         % (html.escape(_relative_url(here, target), quote=True),
                            html.escape(code, quote=True),
                            html.escape(code, quote=True), name))
    return Raw('<span class="langs" role="group" aria-label="%s">%s</span>'
               % (html.escape(label, quote=True), "".join(parts)))


def page_context(page, code, registry, texts, home_dir):
    """Everything a page's template and body may refer to, for one language."""
    entry = page["languages"][code]
    lang = _language(registry, code)
    repo = registry["repo_url"].rstrip("/")
    context = dict(texts[code])
    _merge(context, {
        "site.base_url": registry["base_url"],
        "site.repo_url": repo,
        "site.download_url": "%s/releases/latest" % repo,
        "site.issues_url": "%s/issues" % repo,
        "site.copyright": appinfo.COPYRIGHT,
        "page.title": entry["title"],
        "page.description": entry["description"],
        "page.lang": code,
        "page.url": "%s/%s" % (registry["base_url"],
                               entry["dir_path"] + "/" if entry["dir_path"] else ""),
        "page.asset_prefix": _asset_prefix(entry["dir_path"]),
        "page.home_url": _relative_url(entry["dir_path"], home_dir),
        "page.language_switcher": language_switcher(page, code, registry,
                                                    texts[code]["nav.language"]),
        "page.head_meta": head_meta(page, code, registry, texts, entry["description"]),
    }, "page %s [%s]" % (page["id"], code))
    return context


# -- writing -------------------------------------------------------------------- #

def _write(out, rel_path, text):
    path = os.path.join(out, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # newline="\n" on purpose: the same bytes on Windows and on the CI runner, so
    # "the build changed" never means "the machine changed".
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return rel_path


def _copy(out, source, rel_path):
    path = os.path.join(out, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(source, path)
    return rel_path


def _prune(out, written):
    """Delete whatever a previous build left behind, and the empty directories.

    Without this a renamed page keeps serving from its old address forever, which
    is the one kind of stale that a visitor sees and we do not.
    """
    keep = {os.path.normpath(p.replace("/", os.sep)) for p in written}
    for dirpath, _dirnames, filenames in os.walk(out, topdown=False):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.normpath(os.path.relpath(full, out)) not in keep:
                os.remove(full)
        if dirpath != out and not os.listdir(dirpath):
            os.rmdir(dirpath)


def build(root=ROOT, out=None):
    """Generate the whole site. Returns the relative paths written, sorted."""
    out = out or os.path.join(root, DEFAULT_OUT)
    if os.path.isdir(out) and os.listdir(out) and not os.path.isfile(
            os.path.join(out, "index.html")):
        raise SiteError("refusing to write into %s: it holds files and no index.html, "
                        "so it does not look like a previous site build" % out)

    registry = load_registry(root)
    texts = load_i18n(root, language_codes(registry), registry["default_language"])
    pages = load_pages(root, registry)
    template = _read_text(os.path.join(root, SITE_DIR, "templates", "base.html"))

    home = next((p for p in pages if p["id"] == "home"), pages[0])
    written = []
    for page in pages:
        for code in page["codes"]:
            entry = page["languages"][code]
            home_dir = home["languages"][code]["dir_path"]
            context = page_context(page, code, registry, texts, home_dir)
            body = render(entry["body"], context,
                          "pages/%s/%s.html" % (page["id"], code))
            context["page.body"] = Raw(body)
            document = render(template, context, "templates/base.html")
            target = page["output"] or posixpath.join(
                entry["dir_path"], "index.html").lstrip("/")
            written.append(_write(out, target, document))

    written.append(_write(out, "sitemap.xml", sitemap(pages, registry)))
    written.append(_write(out, "robots.txt", robots(registry)))
    # Pages built by a workflow are served as they are, so this changes nothing today.
    # It costs one empty file and removes a whole class of surprise if the source is
    # ever switched to a branch: Jekyll would then drop every path starting with an
    # underscore, silently.
    written.append(_write(out, ".nojekyll", ""))
    written.append(_write(out, "assets/style.css", _stylesheet(root, registry)))
    for asset in registry.get("assets", []):
        source = os.path.join(root, asset["source"].replace("/", os.sep))
        if not os.path.isfile(source):
            raise SiteError("site.json lists an asset that is not there: %s" % asset["source"])
        written.append(_copy(out, source, asset["target"]))

    _prune(out, written)
    return sorted(written)


def _stylesheet(root, registry):
    """The palette from theme.py, in front of the hand-written CSS, in one file.

    One file rather than two: a second stylesheet is a second request for no
    benefit, and the variables have to arrive before the rules that use them.
    """
    colours = palette(root, registry["palette"])
    lines = ["/* Generated by tools/build_site.py from beantester/gui/theme.py.",
             "   Do not edit: change the colour in theme.py, where the program reads it too. */",
             ":root {"]
    lines += ["  %s: %s;" % (var, value) for var, value in colours.items()]
    lines += ["}", ""]
    return "\n".join(lines) + _read_text(os.path.join(root, SITE_DIR, "assets", "style.css"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Bean Network Tester website.")
    parser.add_argument("--out", default=None,
                        help="output directory (default: %s)" % DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        written = build(ROOT, args.out)
    except SiteError as exc:
        print("site build failed: %s" % exc, file=sys.stderr)
        return 1
    print("wrote %d files to %s" % (len(written), args.out or DEFAULT_OUT))
    for path in written:
        print("  %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
