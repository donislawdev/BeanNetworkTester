"""Filter expressions: parsing, matching and the translated validation errors.

The mini-language behind the target-process, destination-IP and destination-port
fields (and any future filter field), tested in isolation - no psutil, no
tkinter, no WinDivert.
"""
import pytest

from beantester import (KIND_INT, KIND_IP, KIND_PROCESS, PORT_BOUNDS, Matcher,
                        parse_matcher, port_expression, split_terms,
                        validate_matcher)
from fakes import check


def _port(text):
    return parse_matcher(text, KIND_INT, "fields.port", bounds=PORT_BOUNDS)


def _ip(text):
    return parse_matcher(text, KIND_IP, "fields.ip")


def _proc(text):
    return parse_matcher(text, KIND_PROCESS, "fields.target_process")


# --- empty fields ----------------------------------------------------------- #


def test_empty_expression_matches_everything():
    for matcher, value in ((_port(""), 443), (_ip(None), "8.8.8.8")):
        check("empty expression is empty", matcher.is_empty)
        check("empty expression matches anything", matcher.matches(value))
    check("empty expression is falsy", not _port("   "))
    check("non-empty expression is truthy", bool(_port("80")))


# --- numeric fields (ports) -------------------------------------------------- #


def test_int_single_and_list():
    m = _port("80")
    check("single port matches", m.matches(80) and not m.matches(443))
    m = _port("80, 443 ,8080")
    check("list matches every listed port",
          m.matches(80) and m.matches(443) and m.matches(8080))
    check("list rejects an unlisted port", not m.matches(22))


def test_int_range_is_inclusive_on_both_ends():
    m = _port("1000-2000")
    check("range includes the lower end", m.matches(1000))
    check("range includes the upper end", m.matches(2000))
    check("range includes the middle", m.matches(1500))
    check("range excludes below", not m.matches(999))
    check("range excludes above", not m.matches(2001))
    check("a single-value range is one port",
          _port("80-80").matches(80) and not _port("80-80").matches(81))


def test_int_comparisons():
    check("> excludes the boundary",
          _port(">1024").matches(1025) and not _port(">1024").matches(1024))
    check(">= includes the boundary", _port(">=1024").matches(1024))
    check("< excludes the boundary",
          _port("<80").matches(79) and not _port("<80").matches(80))
    check("<= includes the boundary", _port("<=80").matches(80))


def test_int_exclusion_only_means_everything_else():
    m = _port("!53")
    check("exclusion passes other ports", m.matches(80) and m.matches(443))
    check("exclusion rejects the excluded port", not m.matches(53))
    m = _port("!53,!443")
    check("several exclusions all apply",
          m.matches(80) and not m.matches(53) and not m.matches(443))


def test_int_positive_and_negative_combined():
    m = _port("1000-2000,!1500")
    check("range minus one port keeps the rest", m.matches(1499) and m.matches(1501))
    check("range minus one port drops it", not m.matches(1500))
    m = _port(">1024,!3389")
    check("comparison minus one port", m.matches(5000) and not m.matches(3389))
    # a negative that removes nothing is harmless, not an error
    m = _port("80,443,!8080")
    check("a redundant exclusion changes nothing",
          m.matches(80) and m.matches(443) and not m.matches(8080))


def test_int_wildcard_and_regex():
    m = _port("8*")
    check("wildcard matches the decimal text", m.matches(8) and m.matches(80)
          and m.matches(8080))
    check("wildcard does not match unrelated ports", not m.matches(443))
    m = _port("re:^44")
    check("regex matches the decimal text", m.matches(443) and not m.matches(80))


def test_int_missing_value_never_matches_a_positive():
    # ICMP has no port: a positive rule must not claim it...
    check("no port -> positive rule does not match", not _port("80").matches(None))
    check("no port -> comparison does not match", not _port(">1024").matches(None))
    # ...but "everything except 53" still covers it
    check("no port -> exclusion-only rule matches", _port("!53").matches(None))


def test_int_mixed_expression():
    m = _port("80,443,8000-8100,>9000,!8080")
    for value in (80, 443, 8000, 8100, 9001):
        check(f"mixed expression matches {value}", m.matches(value))
    for value in (22, 8080, 9000):
        check(f"mixed expression rejects {value}", not m.matches(value))


# --- IP fields ---------------------------------------------------------------- #


def test_ip_single_list_and_canonical_form():
    m = _ip("1.2.3.4, 8.8.8.8")
    check("IP list matches both", m.matches("1.2.3.4") and m.matches("8.8.8.8"))
    check("IP list rejects others", not m.matches("9.9.9.9"))
    # comparison is on the address, not the text: shorthand IPv6 still matches
    m = _ip("2001:0db8:0000:0000:0000:0000:0000:0001")
    check("IPv6 shorthand equals its long form", m.matches("2001:db8::1"))


def test_ip_range_cidr_and_wildcard():
    m = _ip("10.0.0.1-10.0.0.50")
    check("IP range includes both ends",
          m.matches("10.0.0.1") and m.matches("10.0.0.50"))
    check("IP range excludes outside", not m.matches("10.0.0.51"))
    m = _ip("192.168.1.0/24")
    check("CIDR matches inside", m.matches("192.168.1.7"))
    check("CIDR rejects outside", not m.matches("192.168.2.7"))
    m = _ip("192.168.1.*")
    check("IP wildcard matches inside", m.matches("192.168.1.7"))
    check("IP wildcard rejects outside", not m.matches("192.168.2.7"))


def test_ip_comparisons_exclusions_and_regex():
    m = _ip(">10.0.0.5")
    check("IP comparison", m.matches("10.0.0.6") and not m.matches("10.0.0.5"))
    m = _ip("10.0.0.1-10.0.0.50,!10.0.0.7")
    check("IP range minus one host",
          m.matches("10.0.0.6") and not m.matches("10.0.0.7"))
    m = _ip("!8.8.8.8")
    check("IP exclusion-only", m.matches("1.1.1.1") and not m.matches("8.8.8.8"))
    m = _ip("re:^10\\.")
    check("IP regex", m.matches("10.1.2.3") and not m.matches("11.1.2.3"))


def test_ipv6_ranges_cidr_and_families_never_mix():
    m = _ip("2001:db8::1-2001:db8::ff")
    check("IPv6 range includes both ends",
          m.matches("2001:db8::1") and m.matches("2001:db8::ff"))
    check("IPv6 range excludes outside", not m.matches("2001:db8::100"))
    m = _ip("2001:db8::/32")
    check("IPv6 CIDR matches inside", m.matches("2001:db8:1::9"))
    check("IPv6 CIDR rejects outside", not m.matches("2001:dead::1"))
    # an IPv4 rule never matches an IPv6 address and vice versa
    check("IPv4 rule ignores IPv6", not _ip("10.0.0.0/8").matches("2001:db8::1"))
    check("IPv6 rule ignores IPv4", not _ip("2001:db8::/32").matches("10.0.0.1"))
    m = _ip("10.0.0.0/8, 2001:db8::/32")
    check("both families in one expression",
          m.matches("10.1.1.1") and m.matches("2001:db8::5"))


def test_ip_unparsable_value_never_matches_a_positive():
    check("garbage address does not match a positive", not _ip("1.2.3.4").matches("nope"))
    check("missing address does not match a positive", not _ip("1.2.3.4").matches(None))


# --- process fields ------------------------------------------------------------ #


def test_process_name_substring_stays_backward_compatible():
    m = _proc("chrome")
    check("bare name is a case-insensitive substring",
          m.matches(101, "chrome.exe") and m.matches(102, "CHROME.EXE"))
    check("bare name also catches longer names", m.matches(103, "chromedriver.exe"))
    check("bare name rejects others", not m.matches(104, "firefox.exe"))


def test_process_list_exclusions_and_wildcards():
    m = _proc("chrome, !chromedriver")
    check("name list minus an exclusion", m.matches(101, "chrome.exe"))
    check("excluded name is dropped", not m.matches(102, "chromedriver.exe"))
    m = _proc("chrome*, firefox*")
    check("wildcards match both apps",
          m.matches(1, "chrome.exe") and m.matches(2, "firefox.exe"))
    check("wildcard is anchored at the start", not m.matches(3, "mychrome.exe"))


def test_process_pids_ranges_and_comparisons():
    m = _proc("101, 2500")
    check("PID list matches", m.matches(101, "a") and m.matches(2500, "b"))
    check("PID list rejects others", not m.matches(7, "c"))
    m = _proc("100-200")
    check("PID range is inclusive", m.matches(100, "a") and m.matches(200, "b"))
    check("PID range excludes outside", not m.matches(201, "c"))
    m = _proc(">1000")
    check("PID comparison", m.matches(2500, "a") and not m.matches(999, "b"))
    m = _proc("chrome, 2500")
    check("names and PIDs mix in one field",
          m.matches(1, "chrome.exe") and m.matches(2500, "firefox.exe"))


def test_process_regex():
    m = _proc("re:^fire")
    check("regex matches the process name", m.matches(1, "firefox.exe"))
    check("regex is anchored as written", not m.matches(2, "mozilla-firefox"))
    m = _proc("re:^(chrome|firefox)\\.exe$")
    check("alternation works", m.matches(1, "chrome.exe") and m.matches(2, "firefox.exe"))
    check("alternation excludes the rest", not m.matches(3, "chromedriver.exe"))


def test_process_comparison_on_a_name_is_rejected():
    with pytest.raises(ValueError) as e:
        _proc(">chrome")
    check("comparison on a name explains itself", "PID" in str(e.value), f"({e.value})")


# --- errors -------------------------------------------------------------------- #


def test_bad_expressions_raise_translated_errors():
    import beantester as n
    n.set_language("en")
    bad = [
        (_port, ">abc", "number"),
        (_port, "2000-1000", "reversed"),
        (_port, "99999", "range"),          # outside 0-65535
        (_port, "abc", "not a number"),
        (_ip, "999.1.1.1", "IP address"),
        (_ip, "10.0.0.1-2001:db8::1", "IPv4 and IPv6"),
        (_ip, "10.0.0.50-10.0.0.1", "reversed"),
        (_ip, "re:[", "regular expression"),
        (_proc, "re:(", "regular expression"),
    ]
    for build, text, fragment in bad:
        with pytest.raises(ValueError) as e:
            build(text)
        check(f"{text!r} rejected with a useful message", fragment in str(e.value),
              f"({e.value})")
    n.set_language("pl")


def test_errors_are_translated_into_the_ui_language():
    import beantester as n
    n.set_language("pl")
    with pytest.raises(ValueError) as e:
        _port("abc")
    check("validation error is Polish in the PL UI", "Pole" in str(e.value),
          f"({e.value})")
    n.set_language("en")
    with pytest.raises(ValueError) as e:
        _port("abc")
    check("validation error is English in the EN UI", "Field" in str(e.value),
          f"({e.value})")
    n.set_language("pl")


def test_error_names_the_offending_field_and_term():
    import beantester as n
    n.set_language("en")
    with pytest.raises(ValueError) as e:
        _port("80,abc,443")
    msg = str(e.value)
    check("error names the field", "Port" in msg, f"({msg})")
    check("error quotes the bad term only", "abc" in msg and "443" not in msg, f"({msg})")
    n.set_language("pl")


def test_validate_matcher_helper():
    check("validate_matcher accepts a good expression",
          validate_matcher("80,443", KIND_INT, "fields.port", PORT_BOUNDS))
    with pytest.raises(ValueError):
        validate_matcher("nope", KIND_INT, "fields.port", PORT_BOUNDS)


# --- parsing details ------------------------------------------------------------ #


def test_split_terms_handles_spaces_and_escaped_commas():
    check("empty items are dropped", split_terms(" 80 , ,443 , ") == ["80", "443"])
    check("an escaped comma stays inside the term",
          split_terms(r"re:^a{1\,2}$, 80") == [r"re:^a{1,2}$", "80"])
    check("other backslashes survive for the regex",
          split_terms(r"re:^\d+$") == [r"re:^\d+$"])


def test_regex_with_an_escaped_comma_compiles_and_matches():
    m = _proc(r"re:^ch.{1\,8}e\.exe$")
    check("regex with an escaped comma compiles and matches", m.matches(1, "chrome.exe"))


def test_matcher_describe_and_raw():
    m = _port(" 80 , 443 ")
    check("raw keeps what the user typed", m.raw == "80 , 443", f"({m.raw!r})")
    check("describe normalises the spacing", m.describe() == "80, 443", f"({m.describe()!r})")
    check("parse_matcher passes a Matcher through", parse_matcher(m, KIND_INT) is m)


def test_port_expression_normalises_legacy_values():
    check("legacy int port becomes text", port_expression(443) == "443")
    check("legacy float port becomes text", port_expression(443.0) == "443")
    check("legacy 0 means 'no port'", port_expression(0) == "")
    check("None means 'no port'", port_expression(None) == "")
    check("an expression passes through", port_expression(" 80,443 ") == "80,443")


def test_matcher_never_raises_from_matches():
    """The hot path must survive odd values: no exception, just 'no match'."""
    m = _port("80")
    for value in (None, "abc", object(), [1], True):
        check(f"matches({value!r}) returns a bool", isinstance(m.matches(value), bool))
    check("Matcher is the exported base class", isinstance(m, Matcher))


def test_describe_round_trips_an_escaped_comma():
    """``describe()`` is the CANONICAL text - it must parse back to the same matcher.

    Found by the property test: ``split_terms`` unescapes ``\\,`` into a literal
    comma inside the term, and ``describe()`` used to emit it bare - i.e. as a term
    SEPARATOR. A regex containing a comma (``re:^a{2,3}$``) therefore came back as
    two broken terms. Only ``describe()`` was affected (``raw`` keeps the text the
    user typed), which is why nothing else caught it.
    """
    from beantester.matchers import KIND_PROCESS, parse_matcher

    original = parse_matcher(r"re:^a{2\,3}$", KIND_PROCESS)
    canonical = original.describe()
    check("the escape survives describe()", "\\," in canonical, f"({canonical})")

    reparsed = parse_matcher(canonical, KIND_PROCESS)
    check("describe() parses back to ONE term", len(reparsed.terms) == 1,
          f"({[t.text for t in reparsed.terms]})")
    for name in ("aa", "aaa", "a", "bbb"):
        check(f"same verdict for {name!r} after a round trip",
              original.matches(1, name) == reparsed.matches(1, name))
    check("and it still matches what it should", original.matches(1, "aa"))
    check("and rejects what it should", not original.matches(1, "a"))
