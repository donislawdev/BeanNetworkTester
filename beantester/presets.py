"""Network presets, ordered best (top) -> worst (bottom).

The GUI list and the CLI ``--preset`` order follow this dict's key order.
Keys are canonical i18n ids (``presets.*``); display names come from the
language files, and ``resolve_preset`` accepts either form.
"""
import unicodedata

from .fields import FIELD_DEFS
from .i18n import loaded_language_codes, translate
from .settings import DEFAULT_SETTINGS

# --------------------------------------------------------------------------- #
# HOW TO READ (and how to change) THE NUMBERS BELOW
#
# `lat` is HALF the ping you want. The engine adds it to EVERY packet, and with
# the default two-way traffic filter that is both the request and the reply, so
# the round trip grows by 2 x lat (measured: --latency 200 took a loopback ping
# from <1 ms to ~408 ms). `jit` does NOT double the same way - each packet draws
# its own uniform, so the SPREAD grows by sqrt(2), with 2 x jit as the extreme.
#
# `down`/`up` are KB/s at 1 KB = 1024 B (BeanCore._rate_bps). Multiply by 8/1000
# for Mbit/s: 128 KB/s = 1.05 Mbit/s, 1024 = 8.4, 12288 = 101.
#
# 🔴 A number here CLAIMS SOMETHING ABOUT THE REAL WORLD, and nothing in this
# repo can falsify it - no test goes red when a preset stops resembling the link
# it is named after. So every value is either backed by a SOURCE named in the
# comment beside it, or marked JUDGEMENT. Do not "tidy up" a value from memory:
# in July 2026 a from-memory pass over this table got Starlink's handover, GEO
# bandwidth and 3G latency wrong, each badly enough to reverse a design decision
# (see PROJECT_NOTES, rule 5, the sources bullet).
#
# Sources (measured, not recalled). Every entry carries enough to be looked up:
# a citation nobody can check is decoration, and three of these used to be exactly
# that. Figures are FACTS quoted with attribution, which is what the sources are
# for - no wording is reproduced from any of them.
#
#   [OOKLA25]  Ookla(R) Speedtest(R) analysis of US satellite providers, Q1 2025
#              (published July 2025; figures as reported, accessed 2026-08-11):
#              HughesNet median multi-server latency 683 ms and 47.79 Mbit/s
#              down; Viasat 684 ms and 49.12 Mbit/s; Starlink 45 ms, 104.71 down
#              and 14.84 up. NOT from Ookla's Open Data tiles - see the note at
#              the bottom of this block before reaching for those.
#   [STAR-WWW] Mohan, Ferguson, Cech, Bose, Renatin, Marina and Ott, "A
#              Multifaceted Look at Starlink Performance", ACM Web Conference
#              (WWW) 2024, doi:10.1145/3589334.3645328, arXiv:2310.09242:
#              reconfiguration every 15 s, latency peak averaging +74 ms at the
#              interval boundary.
#   [STAR-CON] Tanveer, Puchol, Singh, Bianchi and Nithyanand, "Making Sense of
#              Constellations: Methodologies for Understanding Starlink's
#              Scheduling Algorithms", CoNEXT 2023 Companion,
#              doi:10.1145/3624354.3630586, arXiv:2307.00402: during a
#              reconfiguration the GSL interfaces stop transmitting for 100 ms,
#              but packets are QUEUED, not dropped. Hence a spike and no flap.
#   [MILEHIGH] Rula, Newman, Bustamante, Molavi Kakhki and Choffnes, "Mile High
#              WiFi: A First Look At In-Flight Internet Connectivity", WWW 2018,
#              doi:10.1145/3178876.3186057. 45 flight-hours over 16 flights:
#              RTT ~750 ms and 7% median loss for satellite (MSS), ~40% loss at
#              the 90th percentile; ~200 ms / 3.3% for air-to-ground.
#   [BLOAT]    The PHENOMENON is Gettys and Nichols, "Bufferbloat: Dark Buffers
#              in the Internet", ACM Queue 9(11), 2011 (also CACM 55(1), 2012),
#              doi:10.1145/2063166.2071893. 🔴 The NUMBERS beside it here - idle
#              14 ms rising to ~320 ms under a sustained upload, extremes
#              200-2000 ms, "most home links affected" - are a typical range
#              assembled from general reporting, NOT figures from that paper.
#              Treat them as a shaped default, not as a measurement.
#   [WIFI-BLL] da Silva and Pedroso, "Packet Loss Characterization Using Cross
#              Layer Information and HMM for Wi-Fi Networks", Sensors 22(22):8592,
#              2022, doi:10.3390/s22228592. A real 802.11b/g/n network, 24 600
#              minutes of traffic: mean BURST LOSS LENGTH (consecutive packets
#              lost) 3.00 in the good channel state, 3.03 and 4.66 in the two
#              intermediate ones, 5.67 in the bad one, and 5.37 over the whole
#              trace. 🔴 That last figure carries a standard deviation of 31.68
#              and a maximum burst of 8853, i.e. it is heavy-tailed - see the
#              note on `loss_burst` below before copying it anywhere.
#   [E-MODEL]  ITU-T Rec. G.107, the E-model. Defines Burst Ratio as the average
#              length of observed loss bursts over the length expected under
#              random loss, so BurstR = 1 means independent loss and BurstR > 1
#              means bursty, and it cautions against using the algorithm above
#              BurstR = 2.0 pending further verification (allowing higher when
#              loss is under 2%). Used here only as a sanity anchor for what
#              counts as ordinary burstiness, not as a source for any number.
#   [3GPP-RTT] GENERAL KNOWLEDGE, deliberately not dressed as a citation: UMTS
#              round trips of roughly 100-200 ms, HSPA 80-150 ms, real
#              throughput 0.384-2 Mbit/s. Widely reported engineering ranges; no
#              single document is being leaned on, and inventing a specification
#              number to make it look sourced would be worse than saying this.
#
# HOW `loss_burst` WAS CHOSEN, and why it is not the number the paper prints
# -----------------------------------------------------------------------------
# `loss_burst` is the average number of packets lost IN A ROW (0 = the loss is
# spread evenly). It shapes `loss`, it does not add to it.
#
# 🔴 The obvious move - take [WIFI-BLL]'s overall mean of 5.37 and write it down -
# is wrong, and the reason is worth keeping. That mean comes from a heavy-tailed
# distribution (sd 31.68, longest burst 8853), so it is dragged upward by rare
# enormous bursts. Our chain is GEOMETRIC and memoryless: it cannot produce
# "mostly short, occasionally 8853", so fitting its mean to 5.37 would deliver far
# more MEDIUM bursts than the measurement ever saw. The three Wi-Fi presets
# therefore take the paper's PER-STATE means instead, which describe a channel in
# one condition rather than a mixture of all of them - good state 3.00, the worse
# intermediate 4.66, bad state 5.67.
#
# Sanity check on the other side: under [E-MODEL], a burst ratio of 1 is random
# loss and the standard is cautious above 2. So single-digit run lengths are the
# realistic range for a working link, and the run of twenty that flattens a TCP
# window is a case a tester dials in deliberately - not something a preset should
# claim a real network does.
#
# Where it is left at 0, that is a decision and not an omission:
#   * `perfect`, `distant`, `bufferbloat` lose nothing, so a run length there
#     would be a knob that cannot move;
#   * `dsl` and `modem56k` are wired, where loss is queue overflow rather than a
#     radio going away, and tail drop on one flow is close to independent;
#   * `leo` is left alone on the strength of a SOURCE, which is the strongest
#     reason on this list: [STAR-CON] measured the 15-second reconfiguration
#     QUEUEING packets rather than dropping them, which is why this preset carries
#     a latency spike and not an outage. Bursting it would contradict its own
#     citation;
#   * `5g` and `lte` lose 0.1-0.3%, little enough that a run length would be an
#     unsourced number a tester would rarely see act.
# -----------------------------------------------------------------------------

# 🔴 LICENSING, before somebody improves this: the figures above are FACTS with
# attribution, which is exactly what is allowed - facts carry no copyright and a
# handful of them is not a substantial part of any database. That stops being
# true if anyone ingests **Ookla's Open Data tiles**: those are CC BY-NC-SA 4.0,
# and both the NonCommercial and the ShareAlike terms conflict with this
# project's GPLv3. Cite published findings; do not import the dataset.
# Ookla, Speedtest, Starlink, HughesNet and Viasat are trademarks of their
# respective owners, named here only to identify whose measurements these are.
# This project is not affiliated with, endorsed by or sponsored by any of them.
#
# CHECKED AND CLEAN, so nobody has to check it twice (2026-09-01, at the source
# rather than from memory):
#   * [WIFI-BLL] is open access under **CC BY 4.0**, copyright the authors
#     ("© 2022 by the authors. Licensee MDPI"), verified on the article page.
#     Two independent reasons it is fine here: individual figures are facts and
#     carry no copyright at all, and even if they did, CC BY permits reuse with
#     attribution - which is given, with authors, venue and DOI. No wording is
#     reproduced, and the underlying trace is NOT ingested, which is the line
#     that matters (see the Ookla note above).
#   * [E-MODEL] is an ITU-T Recommendation and ITU reserves its rights in the
#     TEXT. Nothing of that text is here: one definition in our own words and one
#     threshold, both attributed, and it is used only as a sanity anchor rather
#     than as the source of any value in the table. A definition and a number are
#     not the copyrighted expression.
#   * Neither belongs in `THIRD-PARTY-NOTICES.md` or `licenses/`. Those carry
#     what the BUILD ships - libraries, DLLs, fonts, icons (convention 35). A
#     bibliographic citation in a comment ships no third-party work, which is why
#     the five older sources here have no entry either.
# --------------------------------------------------------------------------- #
PRESETS = {
    # ordered best -> worst (top = best network, bottom = worst)
    "presets.perfect":     dict(loss=0,   corrupt=0,   dup=0,   lat=0,   jit=0,   down=0,     up=0),
    # JUDGEMENT: "good" is not a measurable quantity. Ping 30 ms to a server on
    # the internet, a whisper of loss, and the link is not the bottleneck.
    # `loss_burst` is the exception and is SOURCED: the good-channel state in
    # [WIFI-BLL] loses 3.00 packets in a row on average.
    "presets.good_wifi":   dict(loss=0.1, corrupt=0,   dup=0,   lat=15,  jit=5,   down=0,     up=0,
                                loss_burst=3),
    # 168 Mbit/s down is mid-band 5G. Upload was 8192 (67 Mbit/s), which no
    # market reaches: 5G upload runs 50-120% above 4G, so ~21 Mbit/s. [OOKLA25]
    "presets.5g":          dict(loss=0.1, corrupt=0,   dup=0,   lat=18,  jit=8,   down=20480, up=2560),
    # VDSL2: 50-100/10 Mbit/s on a short loop, ping ~40 ms. The old 1536/256 was
    # the canonical ADSL pair in KBIT/s pasted into a KB/s field (8x too fast).
    "presets.dsl":         dict(loss=0.5, corrupt=0,   dup=0,   lat=20,  jit=8,   down=4096,  up=512),
    "presets.lte":         dict(loss=0.3, corrupt=0,   dup=0,   lat=30,  jit=20,  down=4096,  up=1280),
    # The 15 s reconfiguration stops transmission for 100 ms out of every
    # 15 000, i.e. 0.67% of the timeline, and QUEUES the packets [STAR-CON] -
    # so it is a spike, NOT a flap. Peak averages +74 ms [STAR-WWW]. Loss <1%.
    "presets.leo":         dict(loss=0.5, corrupt=0,   dup=0,   lat=20,  jit=15,  down=12288, up=1536,
                                spike_prob=0.7, spike_ms=100),
    # Fast pipe, far away, nothing broken - the shape every other high-ping
    # preset misses. Warsaw to us-east-1 is ~110-120 ms; New York to London is
    # ~59 ms on the fastest transatlantic cable, 70-80 ms typically.
    "presets.distant":     dict(loss=0,   corrupt=0,   dup=0,   lat=60,  jit=5,   down=12288, up=2048),
    # JUDGEMENT (both): "weak" and "crowded" are not measurable quantities. What
    # is defensible is the SHAPE - a wireless link far from its AP retries, so
    # throughput collapses and jitter dominates. The old 2048/1024 and 1024/384
    # made "weak" and "cafe" faster than most home DSL, which is the one thing
    # they must not be.
    # The two run lengths ARE sourced: [WIFI-BLL] measures 4.66 packets in a row
    # in the worse intermediate channel state and 5.67 in the bad one, so a
    # degraded link takes the first and a crowded one the second.
    "presets.weak_wifi":   dict(loss=2,   corrupt=0.2, dup=0.5, lat=80,  jit=40,  down=512,   up=256,
                                loss_burst=5),
    "presets.cafe":        dict(loss=3,   corrupt=0.3, dup=1,   lat=120, jit=90,  down=256,   up=96,
                                loss_burst=6),
    # Idle it is a good link; under load the queue is the impairment. 2000 ms of
    # buffer on a 1 Mbit/s uplink is the classic "the video call dies when
    # somebody starts a backup" [BLOAT]. NOTE: the buffer only bites once the
    # application SATURATES the link (BeanCore.decide steps 11 and 12 both sit
    # inside `if rate > 0`) - light test traffic sees a plain 8.4/1 Mbit/s link.
    "presets.bufferbloat": dict(loss=0,   corrupt=0,   dup=0,   lat=10,  jit=5,   down=1024,  up=128,
                                buffer=2000),
    # Handovers account for up to 96% of downlink loss on rails, and the events
    # cluster near stations. JUDGEMENT: the 10% duty cycle (3 s out of every 30)
    # is a choice, not a measurement - no study gives a canonical figure. It is
    # the only preset that takes the link fully down long enough to make an
    # application RECONNECT rather than merely degrade. The run length is
    # JUDGEMENT too: it describes the fading BETWEEN those handovers, which is
    # why it sits a little above the bad Wi-Fi state rather than modelling the
    # handover itself - the flap already does that.
    "presets.metro":       dict(loss=2,   corrupt=0,   dup=0,   lat=50,  jit=40,  down=1024,  up=256,
                                spike_prob=5, spike_ms=400, flap_period=30, flap_down=10,
                                loss_burst=6),
    # [3GPP-RTT]. The old 384/128 was UMTS R99's kbit/s pair in a KB/s field,
    # which made "3G" deliver 3.1 Mbit/s - HSPA+, not the experience anybody
    # picks this preset to reproduce. The run length is JUDGEMENT: a radio link
    # fades in clusters, but no source gives a run length for UMTS.
    "presets.3g":          dict(loss=1,   corrupt=0,   dup=0,   lat=90,  jit=60,  down=96,    up=32,
                                loss_burst=4),
    # JUDGEMENT: roaming varies by operator and agreement more than by
    # technology. The shape is what matters - your traffic goes home first.
    # The run length is JUDGEMENT for the same reason as `3g`.
    "presets.roaming":     dict(loss=1.5, corrupt=0,   dup=0,   lat=200, jit=80,  down=256,   up=64,
                                loss_burst=4),
    # Geostationary: SLOW in latency, not in bandwidth - the opposite of what
    # "satellite" suggests. 680 ms ping and 25 Mbit/s, between what HughesNet
    # delivers (8-20) and Viasat (25-60). [OOKLA25]. The run length is
    # JUDGEMENT: rain fade clusters losses, but [OOKLA25] reports rates, not
    # run lengths.
    "presets.satellite":   dict(loss=1,   corrupt=0,   dup=0,   lat=340, jit=100, down=3072,  up=384,
                                loss_burst=4),
    # [MILEHIGH]. 7% loss is the measured MEDIAN for satellite in-flight, not a
    # worst case. Per-user throughput is provider policy, not technology: one
    # operator throttled every user to 100 kbit/s. The flap models losing the
    # beam. Aircraft on newer LEO kit behave like `presets.leo` instead. The run
    # length is JUDGEMENT: [MILEHIGH] measures the loss RATE, not how it arrives,
    # and this is the worst-behaved link in the table that still claims to be a
    # real one.
    "presets.inflight":    dict(loss=7,   corrupt=0,   dup=0,   lat=375, jit=150, down=64,    up=24,
                                flap_period=60, flap_down=3, loss_burst=8),
    # V.90 in practice: ~41 kbit/s down, ~33 up. These two were always right.
    "presets.modem56k":    dict(loss=0.5, corrupt=0,   dup=0,   lat=100, jit=30,  down=5,     up=4),
    # Not a real network and not meant to be one: the everything-at-once case.
    # Its old 256/128 made the WORST preset faster than the 3G one. The run
    # length needs no source for the same reason the rest of this row does not:
    # it is meant to be fatal, not realistic.
    "presets.terrible":    dict(loss=10,  corrupt=2,   dup=2,   lat=300, jit=150, down=32,    up=16,
                                loss_burst=15),
}


# Letters with a STROKE are single codepoints, not base + combining mark, so NFD
# leaves them alone: Polish "ł" survived the fold, and ``--preset "Slabe WiFi"``
# (or ``"Zapchane lacze domowe (bufferbloat)"``) resolved to nothing at all.
STROKE_LETTERS = str.maketrans({
    "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O",
    "ð": "d", "Ð": "D", "ħ": "h", "Ħ": "H", "ŧ": "t", "Ŧ": "T",
})


def fold_name(text):
    """Normalize a name for lenient matching (casefold + strip diacritics)."""
    decomposed = unicodedata.normalize("NFD", str(text).translate(STROKE_LETTERS))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def resolve_preset(name):
    """Resolve a preset given its canonical id or a translated name in any
    loaded language (diacritics-insensitive). Returns the id or None."""
    if name in PRESETS:
        return name
    wanted = fold_name(name)
    for key in PRESETS:
        for lang in loaded_language_codes():
            if fold_name(translate(key, lang)) == wanted:
                return key
    return None


def closest_preset(name):
    """The preset name a typo most likely meant, or ``None``.

    Suggests what a person can actually TYPE, which is why it searches the
    translated names and not only the canonical ids: a user reaching for
    "modem56k" writes that, not "presets.modem56k", and a suggestion drawn from
    the id list would find nothing close and stay silent exactly when it is
    needed. The tool already answers a mistyped config key and a mistyped
    scenario key this way - a preset was the one closed vocabulary still
    replying with seventeen ids and no hint.
    """
    import difflib

    candidates = {}
    for key in PRESETS:
        candidates[key] = key
        for lang in loaded_language_codes():
            candidates[translate(key, lang)] = key
    match = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    if match:
        return match[0]
    # Second pass folded, so a near-miss differing only in diacritics or case
    # still lands - the same tolerance resolve_preset gives an exact match.
    folded = {fold_name(text): text for text in candidates}
    match = difflib.get_close_matches(fold_name(name), list(folded), n=1, cutoff=0.6)
    return folded[match[0]] if match else None


# Presets store their fields under short keys ("lat", "jit") and the settings
# model uses the long ones. Which is which is DERIVED from the field registry
# (``Field.in_profile`` + ``Field.preset_key``), so a field joins the profile
# scope by exactly one flag. It used to be a second hand-written table, which
# meant ``in_profile`` could say a field was in a profile while the save path
# quietly dropped it - the flag and the storage disagreeing with nothing to
# notice.
PRESET_TO_SETTING = {(f.preset_key or f.key): f.key
                     for f in FIELD_DEFS if f.in_profile}
SETTING_TO_PRESET = {v: k for k, v in PRESET_TO_SETTING.items()}

# What a profile field holds when nobody asked for anything. NOT zero: ``buffer``
# defaults to 1000 ms and 0 means UNBOUNDED there - the runaway token bucket the
# bounded buffer exists to prevent (see BeanCore.decide step 11). Filling a
# missing field with a blanket zero would have quietly reinstated it.
PRESET_DEFAULTS = {short: DEFAULT_SETTINGS[long]
                   for short, long in PRESET_TO_SETTING.items()}


def preset_to_settings(preset):
    """``PRESETS`` entry (or preset id/name) -> settings-shaped dict.

    ALWAYS complete: a preset names only the fields it means something by, and
    every other profile field comes back at its default. Callers fill widgets
    from this, so a partial answer would leave the PREVIOUS profile's flapping
    or latency spikes on screen after picking a clean link.
    """
    if isinstance(preset, str):
        canon = resolve_preset(preset)
        if canon is None:
            return {}
        preset = PRESETS[canon]
    out = {long: DEFAULT_SETTINGS[long] for long in SETTING_TO_PRESET}
    out.update({PRESET_TO_SETTING[k]: v for k, v in preset.items()
                if k in PRESET_TO_SETTING})
    return out


def settings_to_preset(s):
    """Settings dict -> the shape a profile/preset is stored in."""
    return {short: s.get(long, DEFAULT_SETTINGS[long])
            for long, short in SETTING_TO_PRESET.items()}
