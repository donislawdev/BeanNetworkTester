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
# Sources (measured, not recalled):
#   [OOKLA25]  Ookla Q1 2025 medians: HughesNet 683 ms / 47.8 Mbit/s, Viasat
#              684 ms / 49.1 Mbit/s; Starlink US ~105 Mbit/s down, 14.8 up.
#   [STAR-WWW] Mohan et al., "A Multifaceted Look at Starlink Performance"
#              (WWW 2024): reconfiguration every 15 s, latency peak averaging
#              +74 ms at the interval boundary.
#   [STAR-CON] "Making Sense of Constellations" - during a reconfiguration the
#              GSL interfaces stop transmitting for 100 ms, but packets are
#              QUEUED, not dropped. This is why LEO carries a spike and no flap.
#   [MILEHIGH] Rula et al., "Mile High WiFi" (WWW 2018), 45 flight-hours over
#              16 flights: RTT ~750 ms and 7% median loss for satellite (MSS),
#              ~40% loss at the 90th percentile; ~200 ms / 3.3% for air-to-ground.
#   [BLOAT]    Bufferbloat surveys: >70% of home links affected; idle 14 ms ->
#              320 ms under a sustained upload, extremes 200-2000 ms.
#   [3GPP-RTT] UMTS 100-200 ms RTT, HSPA 80-150 ms; real throughput 0.384-2 Mbit/s.
# --------------------------------------------------------------------------- #
PRESETS = {
    # ordered best -> worst (top = best network, bottom = worst)
    "presets.perfect":     dict(loss=0,   corrupt=0,   dup=0,   lat=0,   jit=0,   down=0,     up=0),
    # JUDGEMENT: "good" is not a measurable quantity. Ping 30 ms to a server on
    # the internet, a whisper of loss, and the link is not the bottleneck.
    "presets.good_wifi":   dict(loss=0.1, corrupt=0,   dup=0,   lat=15,  jit=5,   down=0,     up=0),
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
    "presets.weak_wifi":   dict(loss=2,   corrupt=0.2, dup=0.5, lat=80,  jit=40,  down=512,   up=256),
    "presets.cafe":        dict(loss=3,   corrupt=0.3, dup=1,   lat=120, jit=90,  down=256,   up=96),
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
    # application RECONNECT rather than merely degrade.
    "presets.metro":       dict(loss=2,   corrupt=0,   dup=0,   lat=50,  jit=40,  down=1024,  up=256,
                                spike_prob=5, spike_ms=400, flap_period=30, flap_down=10),
    # [3GPP-RTT]. The old 384/128 was UMTS R99's kbit/s pair in a KB/s field,
    # which made "3G" deliver 3.1 Mbit/s - HSPA+, not the experience anybody
    # picks this preset to reproduce.
    "presets.3g":          dict(loss=1,   corrupt=0,   dup=0,   lat=90,  jit=60,  down=96,    up=32),
    # JUDGEMENT: roaming varies by operator and agreement more than by
    # technology. The shape is what matters - your traffic goes home first.
    "presets.roaming":     dict(loss=1.5, corrupt=0,   dup=0,   lat=200, jit=80,  down=256,   up=64),
    # Geostationary: SLOW in latency, not in bandwidth - the opposite of what
    # "satellite" suggests. 680 ms ping and 25 Mbit/s, between what HughesNet
    # delivers (8-20) and Viasat (25-60). [OOKLA25]
    "presets.satellite":   dict(loss=1,   corrupt=0,   dup=0,   lat=340, jit=100, down=3072,  up=384),
    # [MILEHIGH]. 7% loss is the measured MEDIAN for satellite in-flight, not a
    # worst case. Per-user throughput is provider policy, not technology: one
    # operator throttled every user to 100 kbit/s. The flap models losing the
    # beam. Aircraft on newer LEO kit behave like `presets.leo` instead.
    "presets.inflight":    dict(loss=7,   corrupt=0,   dup=0,   lat=375, jit=150, down=64,    up=24,
                                flap_period=60, flap_down=3),
    # V.90 in practice: ~41 kbit/s down, ~33 up. These two were always right.
    "presets.modem56k":    dict(loss=0.5, corrupt=0,   dup=0,   lat=100, jit=30,  down=5,     up=4),
    # Not a real network and not meant to be one: the everything-at-once case.
    # Its old 256/128 made the WORST preset faster than the 3G one.
    "presets.terrible":    dict(loss=10,  corrupt=2,   dup=2,   lat=300, jit=150, down=32,    up=16),
}


# Letters with a STROKE are single codepoints, not base + combining mark, so NFD
# leaves them alone: Polish "ł" survived the fold, and ``--preset "Lacze
# satelitarne"`` (or a profile named "Slabe WiFi") resolved to nothing at all.
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
