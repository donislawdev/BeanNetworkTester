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
import struct
import sys
from urllib.parse import urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from beantester import appinfo, exitcodes, fields, presets          # noqa: E402

SITE_DIR = "site"
DEFAULT_OUT = os.path.join("build", "site")
THEME_FILE = os.path.join("beantester", "gui", "theme.py")

# Search engines truncate a title around 60 characters and a description around
# 160. These are the bounds a page has to live inside to be shown whole, and they
# are checked rather than trusted, because "the description got cut in half" is
# invisible from the source.
TITLE_LEN = (15, 65)
DESC_LEN = (50, 160)
# A nav label, not a title: long enough to say what the page is, short enough that
# nine of them fit in a footer without wrapping into a wall.
LINK_LEN = (4, 42)

SLUG_RE = re.compile(r"^$|^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$")
PLACEHOLDER_RE = re.compile(r"\{\{([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*)\}\}")


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


def load_app_strings(root, code):
    """The PROGRAM's own language file, exposed to the pages as ``app.<key>``.

    The site names things the reader will see on screen - field labels, preset names -
    and those strings live in ``lang/<code>.json``, which is where the program itself
    reads them. Writing them out by hand got three preset names and two field labels
    wrong on the first attempt, in a way nothing could catch: the prose read
    perfectly, and only a comparison against the language file found it. A guide that
    tells somebody to fill in a field that does not exist under that name is worse
    than no guide.

    Trailing colons are stripped for the same reason ``i18n.field_name`` strips them:
    a label is written to sit in front of an input, and a sentence quoting it is not a
    form (convention 17a).

    A missing key raises through ``render``, so a renamed string breaks the build
    instead of quietly publishing yesterday's name.
    """
    data = _read_json(os.path.join(root, "lang", "%s.json" % code))
    out = {}
    for key, value in data.items():
        if key == "_meta" or not isinstance(value, str):
            continue
        out["app." + key] = value[:-1] if value.endswith(":") else value
    if not out:
        raise SiteError("lang/%s.json holds no strings" % code)
    return out


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
            link_text = (entry.get("link_text") or "").strip()
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
            if not LINK_LEN[0] <= len(link_text) <= LINK_LEN[1]:
                raise SiteError("pages/%s [%s]: link_text is %d characters, allowed %d..%d "
                                "(it is a nav label, not a title)"
                                % (page_id, code, len(link_text), *LINK_LEN))

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
                "link_text": link_text,
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


def _root_prefix(registry):
    """Path prefix for a document that can be served from ANY address.

    Everything else on this site uses relative references, which keeps the output
    working under a domain root and under a project path alike. The error document
    cannot: GitHub Pages returns ``404.html`` AT the address that missed, without
    redirecting, so a relative reference resolves against the missing path. A miss at
    ``/pl/x/y/`` would look for ``/pl/x/y/assets/style.css`` and render the error page
    with no styling, and its "home" button would point back at the address that had
    just failed - the page would be broken exactly when it is used.

    Taken from the configured address rather than hard-coded to "/", so a deployment
    under a project path keeps working.
    """
    path = urlsplit(registry["base_url"]).path.rstrip("/")
    return (path + "/") if path else "/"


def asset_source(registry, root, target):
    """The repository file that produces an output asset, or a loud failure.

    ``og_image`` names a path on the SITE (``assets/bean.png``), while the file lives
    somewhere else in the repository (``bean.png``), and the asset list is what ties
    the two together. Looking it up instead of guessing means an ``og:image`` that
    names a file nothing produces fails the build rather than the card: a social
    preview pointing at a 404 is invisible until somebody shares the link.
    """
    for asset in registry.get("assets", []):
        if asset["target"] == target:
            path = os.path.join(root, asset["source"].replace("/", os.sep))
            if not os.path.isfile(path):
                # Reached before the copy step, so it has to say the same thing that
                # step would: a missing source is a missing source, not an OSError
                # from whoever happened to open it first.
                raise SiteError("site.json lists an asset that is not there: %s"
                                % asset["source"])
            return path
    raise SiteError("site.json: og_image is %r, which no entry in 'assets' produces "
                    "(so the card would point at a missing file)" % target)


def _png_size(path):
    """(width, height) from a PNG header, or None for anything else.

    Social cards render faster when the dimensions arrive with the tag, and the file
    itself is the only honest source for them - a number typed into a registry beside
    the image is a number that stops being true when the image is replaced.
    """
    with open(path, "rb") as handle:
        head = handle.read(24)
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", head[16:24])


def head_meta(page, code, registry, texts, description, root, home):
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
    size = _png_size(asset_source(registry, root, registry["og_image"]))
    lang = _language(registry, code)
    social = [("og:type", "website"), ("og:site_name", texts[code]["site.name"]),
              ("og:title", entry["title"]), ("og:description", description),
              ("og:url", canonical), ("og:image", image),
              ("og:locale", lang.get("og_locale", code)),
              ("og:image:alt", texts[code]["og.image_alt"])]
    if size:
        social += [("og:image:width", size[0]), ("og:image:height", size[1])]
    social += [("og:locale:alternate", other.get("og_locale", other["code"]))
               for other in registry["languages"] if other["code"] != code]
    for prop, value in social:
        lines.append('<meta property="%s" content="%s">'
                     % (prop, html.escape(str(value), quote=True)))
    for name, value in (("twitter:card", "summary"), ("twitter:title", entry["title"]),
                        ("twitter:description", description), ("twitter:image", image),
                        ("twitter:image:alt", texts[code]["og.image_alt"])):
        lines.append('<meta name="%s" content="%s">'
                     % (name, html.escape(str(value), quote=True)))

    if page.get("schema") == "software_application":
        lines.append(_software_json_ld(registry, texts[code], canonical, description, code))
    if page["id"] != home["id"]:
        lines.append(_breadcrumb_json_ld(registry, page, home, code, canonical))
    return Raw("\n".join(lines))


def _breadcrumb_json_ld(registry, page, home, code, canonical):
    """The trail from the home page to this one.

    Added after MEASURING the built output, which found every guide carrying no
    structured data at all. The idea had been dismissed once with "nine flat pages
    have no hierarchy", and that was wrong: home -> page IS the hierarchy, it is the
    trail a search result shows in place of a raw URL, and it costs one generated
    block per page.

    Built from the registry, so the names are the same labels the navigation uses and
    a renamed page cannot leave a stale trail behind.
    """
    base = registry["base_url"]
    data = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1,
             "name": home["languages"][code]["link_text"],
             "item": _absolute(base, home["languages"][code]["dir_path"])},
            {"@type": "ListItem", "position": 2,
             "name": page["languages"][code]["link_text"],
             "item": canonical},
        ],
    }
    body = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    return '<script type="application/ld+json">\n%s\n</script>' % body.replace("<", "\\u003c")


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
    """Every indexable page, and NOTHING else in the file.

    🔴 The first version carried the language alternates as ``xhtml:link`` elements,
    the form Google documents, and it made the file **fail XSD validation**. The
    mechanism, read out of the official schema rather than guessed: ``tUrl`` ends with

        <xsd:any namespace="##other" ... processContents="strict"/>

    and *strict* means a validator has to resolve a schema for the foreign element.
    Nothing imports an XHTML schema there, so every XSD validator rejects the
    document while Google accepts it. A file that a validator calls broken is a
    signal we cannot tell apart from a real fault, which is worse than no signal.

    Removing them costs nothing, and that is the point: the reciprocal ``hreflang``
    set already sits in the ``<head>`` of every page, and Google asks for ONE of the
    three methods, not all of them. This file is now a plain list of addresses that
    validates strictly.

    No ``lastmod`` either: it would need a clock, two builds would stop being
    byte-identical, and a date that is not the real date of a change is worse than
    none.
    """
    base = registry["base_url"]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in pages:
        if page.get("noindex") or page.get("output"):
            continue
        for code in language_codes(registry):
            out.append("  <url>")
            out.append("    <loc>%s</loc>"
                       % html.escape(_absolute(base, page["languages"][code]["dir_path"])))
            out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def llms_txt(pages, registry, code, texts):
    """``/llms.txt``: the site in Markdown, for something reading it without eyes.

    Checked before adding it (2026-08-11, llmstxt.org): it is a proposal rather than a
    W3C standard, at version 2 since August 2026, published by OpenAI, Anthropic and
    Google for their own documentation, generated by Mintlify, GitBook, WordPress and
    Wix, audited by Chrome's Lighthouse, and used by thousands of sites. So: a
    convention with real adoption, not a standard - worth one generated file, not
    worth restructuring anything for.

    Why it earns its place here in particular: people ask an assistant which tool to
    use, and an assistant answering that question has to extract what this program is,
    what it costs, what it runs on and where to get it. A page built for a person
    buries those facts in prose between a navigation bar and a footer. This file states
    them once, in the order that matters, with a link per page - and it is generated
    from the same registry as the pages, so it cannot describe a site that no longer
    exists.
    """
    base = registry["base_url"]
    lines = ["# %s" % texts["site.name"], "",
             "> %s" % texts["llms.summary"], "",
             texts["llms.note"], "",
             "## %s" % texts["llms.pages"], ""]
    for page in pages:
        if page.get("noindex") or page.get("output") or code not in page["languages"]:
            continue
        entry = page["languages"][code]
        lines.append("- [%s](%s): %s" % (entry["link_text"],
                                         _absolute(base, entry["dir_path"]),
                                         entry["description"]))
    lines += ["", "## %s" % texts["llms.source"], "",
              "- [%s](%s)" % (texts["nav.source"], registry["repo_url"]),
              "- [%s](%s)" % (texts["cta.download"],
                              "%s/releases/latest" % registry["repo_url"].rstrip("/")),
              ""]
    return "\n".join(lines)


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


def page_links(pages, current, code, css_class, skip_home=False, root_prefix=None):
    """Links to the site's other pages, as HTML.

    Generated from the page registry for the same reason the language row is: a
    hand-written list is a list that forgets the page added after it. This is also
    what keeps a page from becoming an orphan - a page nothing links to is a page a
    crawler reaches only through the sitemap, and a reader never.

    ``skip_home`` is for the landing page's own list of guides, where a link back to
    the page you are standing on is noise.

    ``root_prefix`` exists for the error document, and it is not a detail: 404.html is
    served AT the address that missed, so a relative link from it resolves against a
    path that does not exist. The stylesheet was fixed for this once already, and this
    list reintroduced the same bug by another route until the guard from that fix
    caught it. Anything that can be served from an unknown address addresses the site
    from its root.
    """
    here = current["languages"][code]["dir_path"]
    items = []
    for page in pages:
        if page["output"] or page["id"] == current["id"]:
            continue
        if skip_home and page["id"] == "home":
            continue
        entry = page["languages"][code]
        if root_prefix is not None:
            href = root_prefix + (entry["dir_path"] + "/" if entry["dir_path"] else "")
        else:
            href = _relative_url(here, entry["dir_path"])
        items.append('<li><a href="%s">%s</a></li>'
                     % (html.escape(href, quote=True),
                        html.escape(entry["link_text"], quote=True)))
    if not items:
        return Raw("")
    return Raw('<ul class="%s">%s</ul>' % (css_class, "".join(items)))


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


def _cell(value, unit=""):
    """A number for a reference table: zero reads as "not set", not as "0"."""
    if value in (0, 0.0, None, ""):
        return "-"
    text = ("%g" % value) if isinstance(value, (int, float)) else str(value)
    return "%s %s" % (text, unit) if unit else text


def preset_table(app, texts):
    """Every shipped profile with the numbers it really sets, from ``presets.PRESETS``.

    This is the kind of table that exists on a site as a hand-typed copy and is wrong
    within two releases. Generated, it is worth more than that: it is the only place a
    reader can compare all seventeen profiles at once, and it cannot disagree with the
    program. Column heads come from the program's own field labels, so they match the
    window a reader is looking at.
    """
    heads = [texts["table.preset"], app["app.fields.loss"], app["app.fields.latency"],
             app["app.fields.jitter"], app["app.fields.download"], app["app.fields.upload"]]
    rows = ["<tr>%s</tr>" % "".join("<th>%s</th>" % html.escape(h, quote=True) for h in heads)]
    for key, values in presets.PRESETS.items():
        cells = [html.escape(app["app." + key], quote=True),
                 _cell(values.get("loss"), "%"), _cell(values.get("lat"), "ms"),
                 _cell(values.get("jit"), "ms"), _cell(values.get("down"), "KB/s"),
                 _cell(values.get("up"), "KB/s")]
        rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in cells))
    return Raw("<table>%s</table>" % "".join(rows))


def settings_table(app, texts):
    """Every setting that has a command-line flag, from ``fields.FIELD_DEFS``.

    The flag names, units and ranges come from the registry the program validates
    against, and the label comes from the language file, so this table says the same
    thing as the form and as ``--help`` without being a third copy of either.
    """
    heads = [texts["table.flag"], texts["table.setting"], texts["table.unit"],
             texts["table.range"]]
    rows = ["<tr>%s</tr>" % "".join("<th>%s</th>" % html.escape(h, quote=True) for h in heads)]
    for field in fields.FIELD_DEFS:
        if not getattr(field, "cli", None):
            continue
        label = app.get("app." + field.label, field.key)
        unit = app.get("app." + field.unit_key, field.unit) if getattr(
            field, "unit_key", None) else (field.unit or "")
        bounds = getattr(field, "bounds", None)
        span = "%g - %g" % bounds if bounds else "-"
        cells = ["<code>--%s</code>" % html.escape(field.cli, quote=True),
                 html.escape(label, quote=True), html.escape(unit or "-", quote=True),
                 html.escape(span, quote=True)]
        rows.append("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in cells))
    return Raw("<table>%s</table>" % "".join(rows))


def exit_code_table(texts):
    """Every exit code the program can return, from ``exitcodes``.

    The numbers and their canonical names are read out of the module. The sentence
    explaining each one lives in the site's own language files, because the program
    prints its table in English only (convention 3) and a Polish page must not carry
    an English column. ``test_site.py`` requires a sentence for every code, in every
    language, so a new exit code cannot be published as a blank row.
    """
    numbered = sorted((value, name) for name, value in vars(exitcodes).items()
                      if name.isupper() and isinstance(value, int))
    heads = [texts["table.code"], texts["table.meaning"]]
    rows = ["<tr>%s</tr>" % "".join("<th>%s</th>" % html.escape(h, quote=True) for h in heads)]
    for value, name in numbered:
        key = "exit.%s" % name.lower()
        if key not in texts:
            raise SiteError("the site has no sentence for exit code %d (%s): add %r"
                            % (value, name, key))
        rows.append("<tr><td>%d</td><td>%s</td></tr>"
                    % (value, html.escape(texts[key], quote=True)))
    return Raw("<table>%s</table>" % "".join(rows))


def scenario_table(root, texts):
    """The scenario files that ship next to the program, read from ``scenarios/``.

    A scenario is a timeline: ``{"loop": bool, "steps": [{"at": seconds, "settings":
    {...}}]}``. What a reader wants before opening one is how long it runs, how many
    times conditions change and whether it repeats - and those are facts in the file,
    so they are read rather than described.

    This is the point where the SITE starts depending on the scenario corpus, which is
    why ``pages.yml`` had to gain ``scenarios/**`` in its paths filter: without it,
    editing a scenario would change this table and never redeploy, which looks exactly
    like a page nobody edited.
    """
    folder = os.path.join(root, "scenarios")
    files = sorted(f for f in os.listdir(folder) if f.endswith(".json")) \
        if os.path.isdir(folder) else []
    if not files:
        raise SiteError("no scenario files in %s (the table would be empty and the page "
                        "would claim the program ships none)" % folder)
    heads = [texts["table.scenario"], texts["table.steps"], texts["table.length"],
             texts["table.repeats"]]
    rows = ["<tr>%s</tr>" % "".join("<th>%s</th>" % html.escape(h, quote=True) for h in heads)]
    for name in files:
        data = _read_json(os.path.join(folder, name))
        steps = data.get("steps") or []
        if not steps:
            raise SiteError("scenarios/%s has no steps" % name)
        last = max(int(step.get("at", 0)) for step in steps)
        rows.append("<tr><td><code>%s</code></td><td>%d</td><td>%d s</td><td>%s</td></tr>"
                    % (html.escape(name, quote=True), len(steps), last,
                       html.escape(texts["table.yes"] if data.get("loop") else texts["table.no"],
                                   quote=True)))
    return Raw("<table>%s</table>" % "".join(rows))


def social_links(registry, texts):
    """The owner's accounts, as text with a drawn glyph - never a brand mark.

    Checked before writing this (2026-08-11): the GitHub logo and the Octocat are
    trademarks with NO open-source licence, modification is forbidden and anything
    beyond a narrow list needs written permission. The same is true of the other
    marks. Convention 35 requires every third-party asset in this repository to be
    GPLv3-compatible, with a notice, a licence text and a registry entry - a
    trademark-restricted file cannot be, and a fork would be redistributing somebody
    else's mark. So the names are used NOMINATIVELY as text, which is what the
    trademark sections of both READMEs already describe, and the glyph is ours.
    """
    items = []
    for entry in registry.get("social", []):
        items.append('<li><a href="%s" rel="me noopener">%s</a></li>'
                     % (html.escape(entry["url"], quote=True),
                        html.escape(entry["name"], quote=True)))
    if not items:
        return Raw("")
    return Raw('<p class="social-label">%s</p><ul class="social">%s</ul>'
               % (html.escape(texts["footer.elsewhere"], quote=True), "".join(items)))


# A branch of source code: two nodes and a fork. Drawn here rather than taken from
# anywhere, so the repository carries no third-party mark (see social_links).
SOURCE_GLYPH = (
    '<svg class="glyph" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" '
    'focusable="false" fill="none" stroke="currentColor" stroke-width="1.6" '
    'stroke-linecap="round">'
    '<circle cx="4" cy="3.5" r="1.8"/><circle cx="4" cy="12.5" r="1.8"/>'
    '<circle cx="12" cy="8" r="1.8"/>'
    '<path d="M4 5.3v5.4"/><path d="M5.8 3.9h2.9a1.5 1.5 0 0 1 1.5 1.5v1.1"/>'
    '</svg>')


def page_context(page, code, registry, texts, home, colours, root, pages):
    """Everything a page's template and body may refer to, for one language."""
    entry = page["languages"][code]
    lang = _language(registry, code)
    repo = registry["repo_url"].rstrip("/")
    context = dict(texts[code])
    _merge(context, load_app_strings(root, code), "program strings [%s]" % code)
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
        "site.theme_color": colours["--bg"],
        "page.asset_prefix": (_root_prefix(registry) if page["output"]
                              else _asset_prefix(entry["dir_path"])),
        "page.home_url": (_root_prefix(registry) if page["output"]
                          else _relative_url(entry["dir_path"],
                                             home["languages"][code]["dir_path"])),
        "page.language_switcher": language_switcher(page, code, registry,
                                                    texts[code]["nav.language"]),
        "page.preset_table": preset_table(load_app_strings(root, code), texts[code]),
        "page.settings_table": settings_table(load_app_strings(root, code), texts[code]),
        "page.exit_code_table": exit_code_table(texts[code]),
        "page.scenario_table": scenario_table(root, texts[code]),
        "page.social_links": social_links(registry, texts[code]),
        "page.source_glyph": Raw(SOURCE_GLYPH),
        "page.nav_links": page_links(pages, page, code, "foot-nav",
                                     root_prefix=_root_prefix(registry) if page["output"]
                                     else None),
        "page.guide_links": page_links(pages, page, code, "guides", skip_home=True,
                                       root_prefix=_root_prefix(registry) if page["output"]
                                       else None),
        "page.head_meta": head_meta(page, code, registry, texts, entry["description"], root,
                                    home),
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
    colours = palette(root, registry["palette"])
    template = _read_text(os.path.join(root, SITE_DIR, "templates", "base.html"))

    home = next((p for p in pages if p["id"] == "home"), pages[0])
    written = []
    for page in pages:
        for code in page["codes"]:
            entry = page["languages"][code]
            context = page_context(page, code, registry, texts, home, colours,
                                   root, pages)
            body = render(entry["body"], context,
                          "pages/%s/%s.html" % (page["id"], code))
            context["page.body"] = Raw(body)
            document = render(template, context, "templates/base.html")
            target = page["output"] or posixpath.join(
                entry["dir_path"], "index.html").lstrip("/")
            written.append(_write(out, target, document))

    written.append(_write(out, "sitemap.xml", sitemap(pages, registry)))
    # One at the root for the default language, one per language directory: the
    # convention allows a file on any subpath, and a Polish reader's assistant should
    # not have to answer from the English text.
    for lang in registry["languages"]:
        target = posixpath.join(lang["dir"], "llms.txt").lstrip("/")
        written.append(_write(out, target,
                              llms_txt(pages, registry, lang["code"], texts[lang["code"]])))
    written.append(_write(out, "robots.txt", robots(registry)))
    # Pages built by a workflow are served as they are, so this changes nothing today.
    # It costs one empty file and removes a whole class of surprise if the source is
    # ever switched to a branch: Jekyll would then drop every path starting with an
    # underscore, silently.
    written.append(_write(out, ".nojekyll", ""))
    written.append(_write(out, "assets/style.css", _stylesheet(root, colours)))
    for asset in registry.get("assets", []):
        source = os.path.join(root, asset["source"].replace("/", os.sep))
        if not os.path.isfile(source):
            raise SiteError("site.json lists an asset that is not there: %s" % asset["source"])
        written.append(_copy(out, source, asset["target"]))

    _prune(out, written)
    return sorted(written)


def _stylesheet(root, colours):
    """The palette from theme.py, in front of the hand-written CSS, in one file.

    One file rather than two: a second stylesheet is a second request for no
    benefit, and the variables have to arrive before the rules that use them.
    """
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
