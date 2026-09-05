"""What a session did to the traffic, as pure arithmetic over a stats dict.

Carved out of ``engine.py`` on 2026-09-04, and the reason is worth keeping: adding
the ``reordered`` counter pushed that module past the crowd band of the file-size
ratchet (``tests/test_code_shape.py``), whose answer is to move code out rather
than raise the number. These five names were the obvious passengers - none of them
touches a thread, a handle or a packet, they only READ a snapshot, and two of the
three callers were already importing them across a module boundary.

Nothing here imports anything: it sits at the bottom of the layering, below
``core`` and ``engine``, so the GUI, the repro report and the tests can all ask
"how much damage did this session do" without dragging the engine in.
"""

# Which counter a dropped packet lands in, by the reason BeanCore.decide() gave.
# Module level on purpose: written as a literal inside the capture loop it was
# rebuilt for every dropped packet, and a session set to 100% loss drops as often
# as it sees. It is also the SINGLE SOURCE for what counts as damage below.
DROP_BY_REASON = {"syn": "drop_syn", "mtu": "drop_mtu", "nat": "drop_nat",
                  "rst": "drop_rst", "lan": "drop_lan",
                  "internet_only": "drop_internet_only", "block": "drop_block",
                  "flap": "drop_flap", "rate": "drop_rate"}

# Which counter a forged reset belongs to, by the reason that asked for it. Two
# causes, and they must not share a number: `rst_reset` means an ESTABLISHED
# connection was torn down and put in cooldown - it ships to the user as
# `connections_reset` in the stats CSV and in the reproduction report - while a
# blocked connection is refused at the door and has no cooldown at all. Counting
# a refusal as a teardown would make both numbers unreadable, which is the shape
# of silent lie this project keeps removing. Guarded by
# test_rst_local.py::test_every_forged_reset_is_counted_under_its_own_cause, which
# lives with the rest of the reset path rather than with the counters.
RST_BY_REASON = {"rst": "rst_reset", "block": "block_rejected"}

# Damage the simulated link inflicted: every reason decide() can name, plus the
# unnamed default (the configured Loss). Derived from the map above so that a new
# impairment cannot quietly fall outside the figure - which is exactly how
# "Effective loss" came to read 0.0% through a session losing 90% to a speed
# limit. Guarded by
# test_engine.py::test_every_drop_counter_and_drop_reason_is_classified.
IMPAIRMENT_DROP_KEYS = (*dict.fromkeys(DROP_BY_REASON.values()), "drop_loss")

# Losses the TOOL caused, not the link: its delay queue filled up, the session
# ended with packets still parked in it, or re-injecting one failed outright.
# Deliberately NOT part of the loss figure.
# The README defines the term - traffic dropped above a speed limit is counted
# "because that is how a congested link behaves" - and tips.stat_shutdown says of
# these outright "They were not lost in the network". Both have their own tiles,
# and overflow additionally raises a log warning and a banner. Counting them here
# would also let the figure exceed 100%: the delay queue holds out-of-scope
# packets too, so with a narrow target it can drop more than were ever in scope.
TOOL_DROP_KEYS = ("drop_overflow", "drop_shutdown", "drop_send")


def impairment_loss_pct(stats):
    """Share of the traffic the tool was aiming at that the impairments killed.

    Numerator: every drop ``decide()`` made. Denominator: packets that passed the
    targeting gate (``scoped_seen``), not everything captured - with a target set,
    other applications' traffic is watched but never impaired, so counting it only
    dilutes the answer. Measured before this became one function: 50% loss with a
    third of the traffic in scope reported 16.7% while the target application
    itself saw 50.1%.

    Both parts are per-packet and every drop counted here happened to a packet
    that was in scope, so the result cannot exceed 100%. With no targeting set,
    ``scoped_seen == seen`` and this is simply the loss the session inflicted.

    Takes a stats dict rather than an engine so the GUI can compute it from the
    snapshot it already holds. A snapshot without ``scoped_seen`` (an older file,
    a partial fake) falls back to ``seen``.
    """
    scoped = stats.get("scoped_seen", stats.get("seen", 0))
    if not scoped:
        return 0.0
    return 100.0 * sum(stats.get(k, 0) for k in IMPAIRMENT_DROP_KEYS) / scoped


def corruption_pct(stats):
    """Share of the targeted traffic whose payload was actually altered.

    Same denominator as ``impairment_loss_pct``, for the same reason. ``corrupted``
    counts successful payload flips only - a packet with no payload (a bare ACK)
    has nothing to corrupt and is not counted.
    """
    scoped = stats.get("scoped_seen", stats.get("seen", 0))
    if not scoped:
        return 0.0
    return 100.0 * stats.get("corrupted", 0) / scoped
