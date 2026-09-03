"""``gui/form_search.py`` - finding a setting on the Control page by name.

The matching half is pure, so it is tested here without Tk and without a
subprocess; the highlighting and the scrolling are guarded in
``test_gui_layout.py``.

Most of these build their own tiny registry rather than asserting on real
Polish labels: a test pinned to a translation breaks the day somebody improves
the wording, which teaches the wrong lesson. The two that DO use the shipped
registry ask questions the synthetic one cannot - that every field is reachable,
and that accented labels are reachable without their accents.
"""
from beantester import fields as F
from beantester.gui import form_search as S
from beantester.i18n import set_language
from fakes import check


class FakeField:
    """The four attributes the index reads. Anything else is not its business."""

    def __init__(self, key, label, cli=""):
        self.key = key
        self.label = label
        self.cli = cli


def tiny_index(monkeypatched_labels=None):
    """A two-section registry whose labels are literal, so assertions can be too."""
    sections = (
        F.Section("engine", "Engine room", ("throttle", "brake")),
        F.Section("view", "View options", ("row_limit",), surface="settings"),
    )
    fields = {"throttle": FakeField("throttle", "Throttle limit", cli="throttle"),
              "brake": FakeField("brake", "Emergency brake", cli="brake-hard"),
              "row_limit": FakeField("row_limit", "Row limit", cli="rows")}
    labels = monkeypatched_labels or {}

    # `build_index` translates through i18n; here the "translation" is the label
    # itself, which is what makes the expectations readable.
    real_t, real_field_name = S.T, S.field_name
    S.T = lambda key, **kw: labels.get(key, key)
    S.field_name = lambda key, **kw: labels.get(key, key)
    try:
        return S.build_index(sections, fields)
    finally:
        S.T, S.field_name = real_t, real_field_name


def test_the_index_carries_every_section_and_every_field():
    """A registry entry nobody indexed is a setting the search cannot find."""
    set_language("en")
    index = S.build_index()
    sections = [e for e in index if e.kind == S.SECTION]
    fields = [e for e in index if e.kind == S.FIELD]
    check("search: one entry per section", len(sections) == len(F.SECTIONS),
          f"({len(sections)} against {len(F.SECTIONS)})")
    placed = [key for s in F.SECTIONS for key in s.fields]
    check("search: one entry per placed field", len(fields) == len(placed),
          f"({len(fields)} against {len(placed)})")
    missing = sorted(set(placed) - {e.key for e in fields})
    check("search: no field is left out of the index", not missing, f"({missing})")


def test_a_blank_query_finds_nothing():
    """The empty state is the common one - it must not light up the whole page."""
    index = tiny_index()
    for query in ("", "   ", "\t", None, "--"):
        check(f"search: {query!r} finds nothing", S.find(index, query) == [])


def test_matching_ignores_case_and_finds_the_middle_of_a_word():
    index = tiny_index()
    hits = [e.key for e in S.find(index, "THROTTLE")]
    check("search: case is ignored", "throttle" in hits, f"({hits})")
    hits = [e.key for e in S.find(index, "mergency")]
    check("search: a substring in the middle matches", "brake" in hits, f"({hits})")


def test_a_section_name_finds_the_section_and_its_fields():
    """Somebody typing a group name is looking for the group, not one field."""
    index = tiny_index()
    hits = S.find(index, "engine room")
    kinds = {(e.kind, e.key) for e in hits}
    check("search: the section itself is a hit", (S.SECTION, "engine") in kinds, f"({kinds})")
    check("search: its fields come with it",
          {(S.FIELD, "throttle"), (S.FIELD, "brake")} <= kinds, f"({kinds})")


def test_a_cli_flag_finds_the_field_it_drives():
    """`--loss` is what the README and every repro command say; typing it must work."""
    index = tiny_index()
    for query in ("brake-hard", "--brake-hard", "brake_hard"):
        hits = [e.key for e in S.find(index, query)]
        check(f"search: {query!r} finds its field", hits == ["brake"], f"({hits})")


def test_hits_come_back_in_page_order():
    """`F3` walks this list, so it has to run down the page the way the eye does."""
    index = tiny_index()
    order = [e.key for e in index]
    hits = S.find(index, "limit")          # matches "Throttle limit" and "Row limit"
    positions = [order.index(e.key) for e in hits]
    check("search: hits are in document order", positions == sorted(positions),
          f"({[e.key for e in hits]})")


def test_a_settings_field_is_found_but_never_offered_as_a_jump():
    """Decision of 2026-08-18: say where it lives instead of shrugging.

    The Control page cannot scroll to a field that renders in another window, so
    the split is what stops the page promising a jump it cannot make.
    """
    index = tiny_index()
    here, elsewhere = S.summarise(S.find(index, "row limit"))
    check("search: nothing to jump to on this page", here == [], f"({[e.key for e in here]})")
    check("search: the settings field is reported instead",
          [e.key for e in elsewhere] == ["row_limit"], f"({[e.key for e in elsewhere]})")
    check("search: and it knows which window to name",
          elsewhere[0].section_label == "View options", f"({elsewhere[0].section_label})")


def test_an_accented_label_is_reachable_without_its_accents():
    """🔴 The reason `fold` exists: people type Polish without the diacritics.

    Derived from the shipped labels rather than hard-coded, so it keeps asking
    the real question after any wording change: take a real label that HAS an
    accent, strip it, and demand that the stripped spelling still finds it.
    """
    set_language("pl")
    index = S.build_index()
    accented = [e for e in index
                if e.kind == S.FIELD and S.fold(e.label) != e.label.casefold()]
    check("search: the Polish labels do carry accents (else this test is empty)",
          accented, "(no accented label found)")
    entry = accented[0]
    stripped = S.fold(entry.label)
    hits = [e.key for e in S.find(index, stripped)]
    check(f"search: {entry.label!r} is reachable as {stripped!r}",
          entry.key in hits, f"({hits})")
    check("search: and it is still reachable WITH the accents",
          entry.key in [e.key for e in S.find(index, entry.label)])
    set_language("en")


# The word each language's "Latency (ping) and packet order" card uses for ORDER.
# A dict rather than one string because the guard is about the SECTION TITLE doing
# its job in the language somebody is actually reading, and Chinese does not
# contain the English word.
ORDER_WORD = {"en": "order", "pl": "kolejnosc", "zh": "顺序"}


def test_the_spike_pair_is_findable_by_the_effect_it_is_used_for():
    """Searching for packet ORDER must reach the spike fields, in every language.

    This is a copy-pinning test on purpose, and the exception is argued rather
    than assumed. ``form_search`` matches names - field labels, section titles and
    CLI flags - and deliberately NOT tooltip bodies (owner decision, 2026-08-18).
    So the ONLY thing that puts these two fields in front of somebody testing a
    UDP protocol against reordering is the word living in a NAME. Explaining it in
    the tooltip instead is invisible to the search, and nothing would say so.

    Measured on 2026-09-04, before the section was renamed from "Latency (ping)":
    zero hits for this word in both en and pl. After: the section and all four
    fields inside it. Reword the card freely - just keep a word for order in it,
    or this reddens and tells you what you took away.
    """
    for code, word in ORDER_WORD.items():
        set_language(code)
        index = S.build_index()
        hits = {e.key for e in S.find(index, word)}
        for key in ("spike_prob", "spike_ms"):
            check(f"search[{code}]: {word!r} reaches {key}", key in hits,
                  f"(hits: {sorted(hits)})")
    set_language("en")
