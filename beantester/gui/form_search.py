"""Finding a setting on the Control page by name - the pure half.

Why this exists
---------------
The Control page renders the whole field registry: a dozen collapsible sections
and forty-odd fields, several of them folded away on a fresh install. Somebody
who knows what they want ("opoznienie") had no way to get to it except opening
every section and reading. This turns the registry into something searchable.

Everything here is pure: no Tk, no widgets, no state. It answers one question -
which registry entries does this query name? - and `gui/pages/control.py` does
the highlighting and the scrolling. That split is what makes the matching
testable at all, since the GUI half needs a fake Tk and a subprocess.

Three decisions, all the owner's (2026-08-18), written down because each one
narrows the answer and would otherwise look arbitrary:

* **Names only.** Field labels and section titles - not tooltip bodies. Searching
  the tips finds "loses packets" and half the page with it, which is a different
  feature (a symptom index) and would make one word match everything.
* **CLI flags too.** Somebody who knows `--loss` should be able to type it and be
  taken to the field it drives. This is the one place where the search is not
  about the visible text - and it is cheap, because `fields.py` already carries
  the flag.
* **Settings-window fields are indexed, but never jumped to.** They are not on
  this page and they never will be, so a hit there answers "it lives in the
  Settings window" instead of "not found". A dead end that knows where the thing
  is beats an honest shrug.

🔴 **The index must be built AFTER `set_language`, never at import time.** Every
label here comes out of `i18n`, so an index built once would keep answering in
the language the process started in - and a language switch rebuilds the whole
UI precisely so that nothing keeps the old words.
"""
import unicodedata

from .. import fields as F
from ..i18n import T, field_name

SECTION, FIELD = "section", "field"


def fold(text):
    """Case- and accent-insensitive form of a string, for comparing by hand.

    🔴 Polish labels carry diacritics and people type without them: somebody
    looking for "Opoznienie" must find "Opoznienie" spelled with the o-acute and
    the z-dot. `casefold` alone does not do that - it lowercases, and the accent
    survives - so the string is decomposed (NFKD) and the combining marks are
    dropped. Without this the feature works for half the Polish labels and nobody
    can tell which half.
    """
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in decomposed
                   if not unicodedata.combining(ch)).casefold().strip()


class Entry:
    """One searchable thing: a section title, or a field inside one."""

    __slots__ = ("kind", "key", "section_id", "label", "section_label",
                 "surface", "haystack")

    def __init__(self, kind, key, section_id, label, section_label, surface,
                 haystack):
        self.kind = kind
        self.key = key                      # field key, or the section id
        self.section_id = section_id
        self.label = label                  # as shown, already translated
        self.section_label = section_label
        self.surface = surface              # "control" | "settings"
        self.haystack = haystack            # folded strings this entry answers to

    @property
    def on_control(self):
        return self.surface == "control"

    def __repr__(self):                     # pragma: no cover - debugging only
        return "Entry(%s %s)" % (self.kind, self.key)


def _field_haystack(field, label, section_label):
    """What a field answers to: its own name, its section's name, its flag.

    The section title is included so that typing a group name ("blokowanie")
    lights up the fields inside it rather than only the header - which is what
    somebody scanning for a subject, not a field, is actually asking for.
    """
    parts = [label, section_label]
    if field.cli:
        # Both spellings, because the flag is written `--dst-ip` in the README and
        # the settings key is `dst_ip` in every config file - and a person types
        # whichever they last read.
        parts += [field.cli, field.cli.replace("-", "_"), "--" + field.cli]
    parts.append(field.key)
    return tuple(fold(part) for part in parts if part)


def build_index(sections=None, fields=None):
    """Every searchable entry, in the order the page renders them.

    Document order matters: "next hit" walks this list, so it must run down the
    page the way the eye does, or F3 jumps around at random.
    """
    sections = F.SECTIONS if sections is None else sections
    fields = F.FIELDS if fields is None else fields
    index = []
    for section in sections:
        section_label = T(section.label)
        index.append(Entry(SECTION, section.id, section.id, section_label,
                           section_label, section.surface,
                           (fold(section_label), fold(section.id))))
        for key in section.fields:
            field = fields[key]
            label = field_name(field.label)
            index.append(Entry(FIELD, key, section.id, label, section_label,
                               section.surface,
                               _field_haystack(field, label, section_label)))
    return tuple(index)


def find(index, query):
    """Entries the query names, in page order. Blank query finds nothing.

    Substring rather than prefix, deliberately: "limit" has to find "Limit
    pobierania" and "Limit wierszy", and a person searching a form types the
    distinctive middle of a word as often as its start. A leading `--` is dropped
    so that pasting a flag straight out of the README works.
    """
    needle = fold(query)
    if needle.startswith("--"):
        needle = needle[2:]
    if not needle:
        return []
    return [entry for entry in index
            if any(needle in straw for straw in entry.haystack)]


def summarise(hits):
    """(how many are on this page, which entries are somewhere else).

    The second half is what turns "not found" into "it is in the Settings
    window": the page shows the count for what it can jump to, and names the rest
    rather than pretending they do not exist.
    """
    here = [entry for entry in hits if entry.on_control]
    elsewhere = [entry for entry in hits if not entry.on_control]
    return here, elsewhere
