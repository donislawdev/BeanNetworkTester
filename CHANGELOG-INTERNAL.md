# Internal changelog

Technical, developer-facing history for Bean Network Tester. This file is NOT shipped to
users - the user-facing log is `CHANGELOG.md`. Keep entries technical: which
modules/registries were touched, decisions, format migrations, CI changes, and NEW TESTS.
This is the one place we record added tests (file/test name + what it guards). Entries may
reference conventions (for example "convention 24") and code symbols.

The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.
Entries go under `[Unreleased]`; the owner closes a version by setting `VERSION.txt` (never
bump the version here). Plain hyphen only, no em/en dashes (convention 33).

Breaking changes must be visible at a glance: a change that breaks a public contract (CLI
flags, exit codes, the NDJSON schema, on-disk file formats, or the facade's public API) gets
a `### BREAKING` section placed FIRST in that version, and each such line is prefixed with
`**BREAKING:**`. A breaking change also requires a version bump by the owner (convention 34).

## [Unreleased]

### BREAKING

- **BREAKING:** the effective-loss figure is redefined at both ends (audit F4). `gui/pages/stats.py`
  and `repro.py` computed `100 * drop_loss / seen`. The numerator was the configured Loss alone,
  ignoring `drop_rate`, `drop_flap`, `drop_block`, `drop_syn`, `drop_mtu`, `drop_nat`, `drop_rst`
  and `drop_lan`; the denominator was every captured packet, including traffic outside the
  targeting scope. Measured on this branch, driven through `BeanEngine` with `FakeDivert`:
  a 50 KB/s cap with **zero** configured loss went from **0.0% to 99.9%** (`drop_rate=999` of
  1000 packets), and 50% loss with a third of the traffic in scope went from **17.7% to 53.0%**
  (`seen=900`, `scoped_seen=300`, `drop_loss=159`). Both reproduce the audit's shape (0.0% against
  a real 90%, and 16.7% against the target application's 50.1%). `metrics.effective_loss_pct` and
  `metrics.effective_corruption_pct` therefore change meaning; reports across this line are not
  comparable. Additive alongside them: `metrics.packets_in_scope`, the `scoped_seen` counter in
  `st` (so it also appears in NDJSON `summary.counters`), and the CSV column `packets_in_scope`
  (`App.CSV_COLUMNS`). `_sample_record` in `cli.py` was deliberately left alone - it is a curated
  subset, and the summary already carries the full counter dict.
- **New single source in `engine.py`.** `DROP_BY_REASON` (the reason -> counter map, lifted out of
  the capture loop), `IMPAIRMENT_DROP_KEYS` **derived from it**, `TOOL_DROP_KEYS`, and two pure
  functions `impairment_loss_pct(stats)` / `corruption_pct(stats)` used by both the GUI and the
  repro report. They take a stats dict, not an engine, so the GUI computes from the snapshot it
  already holds and the tests need no session. `repro.py` and `gui/pages/stats.py` import them;
  no layering rule is touched (`engine` imports neither).
- **Why the tool's own drops are excluded**, recorded here because it is a judgement call:
  `README.md` defines the term around a congested link ("that is how a congested link behaves"),
  and `tips.stat_shutdown` says of queued-at-stop packets "They were not lost in the network".
  There is also a hard reason: the delay queue holds out-of-scope packets too, so counting
  `drop_overflow` against a `scoped_seen` denominator could produce a figure above 100%. As
  defined, every counted drop happened to a packet that is in the denominator, so the result
  cannot exceed 100%.
- **Hot path measured, not assumed** (Win11 AMD64, CPython 3.14.6, 150k 1500 B packets through
  `FakeDivert`, median of 5, benchmarked back to back against a `git worktree` of master).
  Nothing-impaired path 149.7k -> **157.1k pkt/s** (ranges 145.7-155.4 vs 150.6-163.3: overlapping,
  so read as no regression while gaining a third counter). 100%-loss path 234.5k ->
  **267.8k pkt/s** (188.2-238.2 vs 234.1-274.2: the new minimum sits at the old maximum), which is
  the dict literal no longer being built for every dropped packet.
- **Two deliberate rearrangements in the capture loop.** (1) `seen`, `bytes_*_total` and
  `scoped_seen` now share ONE `_slock` acquisition, placed after `decide()` because scope is not
  knowable before it - fewer acquisitions per packet than before the counter was added. If
  `decide()` ever raised, the packet would go uncounted where it used to be counted; it does not
  raise (`Matcher.matches()` is documented never to) and if it did, the capture thread dies and
  the session fail-stops. (2) `DROP_BY_REASON` at module scope instead of a literal per drop.
- New tests in `tests/test_engine.py`, all verified by mutation (four mutants, each caught with
  the pre-fix number): `test_effective_loss_counts_every_impairment_not_just_the_loss_setting`
  (reverting the numerator gives `pct=0.0` against `drop_rate=999`),
  `test_effective_loss_measures_the_traffic_that_was_targeted` (reverting the denominator gives
  `pct=17.7`; never bumping `scoped_seen` gives `scoped_seen=0`), and
  `test_every_drop_counter_and_drop_reason_is_classified` - a mechanical guard that every
  `drop_*` counter in `reset_stats()` is in `IMPAIRMENT_DROP_KEYS` or `TOOL_DROP_KEYS`, and that
  every reason `Decision(True, ...)` can carry in `core.py` routes through `DROP_BY_REASON`. That
  last one is the guard against F4's actual failure mode: a counter that exists, is correct, and
  is simply not part of the sum.
- i18n: new key `tips.eff_loss` in `lang/en.json` + `lang/pl.json` (the session row had **no**
  tooltip at all, which is part of why the figure could lie unnoticed); `SESSION_ROWS` in
  `gui/pages/stats.py` now names it. README EN + PL gained a bullet defining the figure; the
  existing prose about a speed limit causing loss above the set percentage was left untouched -
  it was already true, and now the number finally agrees with it.

- **BREAKING:** `--gui` combined with any other option now exits `USAGE(2)`. `args.gui` was
  parsed and then **never read anywhere** - `cli.py::main` routes to the GUI only when argv is
  empty or exactly `["--gui"]`, so every other combination fell through to a full CLI session
  while `--help` advertised "force the GUI". On real WinDivert that meant
  `--gui --loss 30 --duration 600` impaired the machine's network with no window and no STOP
  control. The guard sits at the top of `run_cli`'s `try` block (before `--license` /
  `--doctor` / `--cleanup-driver`) and uses the existing `CliError` path, so the message goes
  to stderr and stdout stays clean.
- Blast radius checked before the change: nothing in `tests/`, `smoke_gui.py`, `tools/` or the
  launcher facade passes `--gui`; `test_cli_fuzz.py` builds `FLAGS` from `FIELD_DEFS`, so the
  fuzzer never generates it; `test_cli_docs.py` compares flag NAMES, not help text. `USAGE` was
  already in the fuzzer's `ACCEPTABLE` set, so the new outcome fits the CLI contract rather
  than widening it.
- Rejected alternatives: opening the GUI and silently dropping the other flags (asking for 30%
  loss and getting zero without being told is the class of quiet lie this project removes), and
  opening the GUI with the form PREFILLED from the flags. The second is genuinely nicer and is
  still open - it needs `gui/app.py`, which is due for decomposition, so it is deferred rather
  than declined.
- New test: `tests/test_cli_runtime.py::test_gui_flag_combined_with_settings_is_a_usage_error`
  - asserts `USAGE(2)`, the reason on stderr, and an empty stdout (the data-channel invariant).
- Help text and the flag tables in both READMEs now state that the flag is valid on its own.
- Version bump deliberately NOT taken (convention 34): the owner closes it in `VERSION.txt`.

### Tests: the GUI target banner is pinned to the PROCESS, not to the field (audit F17)

- **The gap.** `test_gui_state.py::test_a_gui_session_keeps_the_target_banner_honest` only ever
  moves the EXPRESSION - the user types something that matches nothing, then something that does.
  The case a tester actually hits moves the other end: the field is left alone and the targeted
  program exits, or a harness restarts it onto a new pid. Nothing covered that, and a handoff note
  had concluded from reading the code that the verdict was taken only at session start. It is not:
  `App._refresh_target` re-reads `targeting.matched` on every tick and only the APPLY half is
  gated on the expression having changed.
- New guard: `::test_a_target_that_dies_mid_session_raises_the_banner_without_being_retyped`. Real
  engine, real resolver, `SyntheticDivert`, injected `FakeTable`; the test empties the socket table
  under a running session and asserts `_applied_target` did NOT move (otherwise it is the old test
  again), then that the banner rises, then that it comes back DOWN when the process reappears under
  a NEW pid with the same name - the recovery measured against a real capture the same day.
- **Three mutants, all caught, each on its intended assertion.** The one worth recording is the
  first: `_refresh_target` made to read the verdict ONLY when the expression changed, i.e. exactly
  the "banner appears at session start" behaviour the note had assumed already existed. It goes
  red, so the guard really does pin the live re-read. The other two: `ProcessTargeting.matched`
  forced to `True`, and the banner never taken back down.
- Test-only chunk, so no `CHANGELOG.md` entry (convention 39): nothing on screen changed, this
  fixes the fact that nothing was watching it.

### Added: the CLI reports a target that stops matching, and what share was in scope (audit F17)

- **Symptom, measured before writing anything** (2026-07-28, elevated, real WinDivert, probe
  narrowed to `--target <pid> --dst-ip 8.8.8.8 --dst-port 53 --syn-drop 100`). A process was
  targeted BY PID, impaired correctly (1 of 6 connections slipped, the rest timed out), then killed
  and restarted under a new pid: **5 of 5 fresh connections untouched**, `scoped_seen` flat, and the
  only targeting line in the whole run was the one `apply_targeting` prints at start. `exit=OK`.
- **Same probe, targeting BY NAME**, 3 lives x 4 held connections: `OK FAIL FAIL FAIL` in **3 of 3**
  lives. So the name path recovers by itself and the restart costs exactly one connection - the one
  opened before the process owns any socket, which is the `_pids` limitation F16 already documents,
  not a new one. `drop_syn` cross-checks at exactly 2 per caught connection (SYN + one retransmit
  inside the 2.5 s connect timeout).
- **The asymmetry this exposes.** `gui/app.py::_refresh_target` re-reads `targeting.matched` on
  every tick and raises `fields.target_no_match`, so the GUI has always shouted about this. The CLI
  - the CI/CD interface (convention 18) - resolved once in `apply_targeting(announce=True)` and
  never looked again; `_report_loop` did not mention targeting at all.
- **Fix, all in `cli.py`.** `_targeting_state(engine)` returns `(matched, describe())` or `None`,
  and `_report_loop` logs only the TRANSITION: `warn` when the target stops matching, `info` when it
  comes back. Reading `matched` is a plain bool on the live `ProcessTargeting` - no lock, no
  syscall, no socket table - so the loop can ask on every pass. `getattr` on `engine.targeting`
  because `run_cli(engine=...)` is a public seam. Sampled, not continuous: a verdict that flips and
  flips back between two passes is not seen, and the comment says so rather than implying otherwise.
- **End of run:** a `warn` when a target was set, traffic WAS captured and `scoped_seen` is 0, plus
  an `In scope: X of Y captured packets` line in the text summary. Guarded by `stats["seen"]` on
  purpose - with nothing captured at all the capture filter is the story and `--min-packets` is the
  flag that tells it, so saying both would point at the wrong thing.
- **Deliberately NOT done:** no new exit code and no `--min-scoped` flag. A target with no traffic
  of its own is a legitimate run, and making it an assertion would change the exit-code contract
  under everyone already running one. The number is in the JSON summary's `counters.scoped_seen` for
  a pipeline that wants to assert on it itself. The NDJSON `sample` schema is untouched (the frozen
  contract); the new line goes down the TEXT channel only.
- Two new guards in `tests/test_cli_runtime.py`:
  `::test_the_run_says_when_the_process_target_stops_matching` (transition reported, reported ONCE,
  and silent while the target keeps matching) and
  `::test_a_target_that_caught_nothing_is_called_out_at_the_end` (zero scope called out, non-zero
  scope not accused, no-traffic-at-all not blamed on the target). Both drive a `_TargetedEngine`
  fake: a real engine cannot play this part, since `--target` is stripped under `--simulate` and a
  real capture needs WinDivert plus elevation. `winenv.is_admin` is monkeypatched so the pair cannot
  become a THIRD environment-dependent result in this file.
- The fake's stats dict is copied from a real `BeanEngine().st`, so a counter added to the engine
  cannot leave it answering with a key the CLI reads.
- **Five mutants, all caught** (source rewritten as BYTES - `write_text` would flip the file to CRLF
  and trip the changelog hook): transition logging removed; transition logging fired every pass
  instead of on change; the zero-scope warning removed; its `stats["seen"]` guard removed; the
  `In scope` line removed. Each went red on its intended assertion.

### Fixed: the first packet of a fresh connection can be in targeting scope (audit F16)

- **Symptom, measured end to end before writing anything.** `ProcessTargeting.__contains__` answers
  from `_ports`, a frozenset rebuilt on the resolver's thread, so a socket opened microseconds ago
  is unknown there - and the first packet of a connection is judged BEFORE any rebuild it triggers.
  20 fresh connections against a process target with `--syn-drop 100`: **20 established, `drop_syn`
  0**. `--syn-drop` combined with `--target` was a complete no-op, and every other impairment missed
  one packet per connection.
- **This is NOT the 0.02 ms.** The SOCKET-layer margin measured the same day is real, but nothing
  consumed it: the live map fed the REBUILD, not the packet-path test. The order being in our favour
  is worth nothing until something reads it at the right moment.
- **Fix.** `ProcessTargeting.syn_covers(port)` - a lock-free `pid_for` read checked against `_pids`,
  the set the last rebuild concluded - and `BeanCore.decide` step 1 calls it **for a TCP SYN only**,
  i.e. once per connection rather than once per packet. `_syn_covers` is bound in `set_target`, so
  the packet path does not even do a `getattr`, and a plain port set (tests, one-shot resolution)
  binds `None` and keeps exactly the behaviour it had.
- **It drags a second fix with it, and this is the part that would have been missed.** Step 4 arms a
  reset on the first in-scope TCP packet. With SYNs now in scope that becomes the SYN - and the RST
  forged from a SYN copies its `ack_num` as the sequence, which a SYN does not have, so it goes out
  with `seq=0` and no ACK. RFC 793 lets a stack in SYN_SENT ignore that, and **it was measured doing
  exactly that** (2026-07-28: the client hung until its own timeout, `rst_sent` reported 1). So a
  reset is no longer ARMED from a SYN, while a SYN arriving inside an existing cooldown is still
  held down. Without this, F16 would have traded a working reset for a hang.
- **Acceptance, and it corrected the limitation as written.** Predicted 19 of 20 blocked; the first
  run gave **6**. The gap is not the 0.02 ms: `_pids` is rebuilt from pids owning CURRENTLY OPEN
  sockets, and the probe connected, closed at once and idled 0.2 s, so a rebuild landing in that
  gap dropped the process out again. A second probe **holding its sockets open** was blocked **19
  of 20** (`drop_syn` 38 - each connection's SYN plus its retransmit), the single escape being
  attempt 0, before the process had any socket at all. Two candidate causes existed and this
  separated them: it is `_pids` churn, not the watcher failing to process the event in time.
- **So the documented limit was too narrow and is now precise:** not "the first connection of a
  freshly started target" but "any target with no open socket when a rebuild runs". A browser or an
  app under test is covered; a script opening one connection, closing it and pausing keeps slipping
  through. Both measured numbers (6/20 closing, 19/20 holding) are in the docstring, because the
  difference between them IS the limitation.
- Also: `_pids` is up to one resolver cycle stale, so a recycled PID can pull one packet of an
  unrelated socket into scope - a DIFFERENT false positive from the stale `_ports` this code already
  lived with. UDP has no SYN and is not covered.
- **Contract widened on purpose:** `set_table` documented `snapshot`/`name_of`/`ancestors`/`refresh`;
  `pid_for` is now part of it. Both real tables always had it, but `syn_covers` reads it through
  `getattr` so a table that does not - a test double, an older implementation - answers False
  instead of raising `AttributeError` **on the capture thread**.
- **Hot path measured** against a worktree of master (150k 1500 B packets, median of 5). No
  targeting: 135.9k -> 140.3k pkt/s. **Targeting on with every packet missing** - the common path
  when a target is set, and where the new test lives: 164.0/164.7k -> 164.5/170.4k. No regression
  either way; the added cost is one boolean that short-circuits on `is_syn`, below the noise floor.
- Six new guards across `tests/test_core.py` and `tests/test_targeting_socketwatch.py`; **six
  mutants, every one caught after a repair worth recording** - two of them first pointed at
  `test_core.py`, which drives a local fake rather than `ProcessTargeting`, so the real `getattr`
  guard was not covered by anything. It has its own test now.
- `test_core_properties.py::test_an_armed_gate_wins_over_every_later_step` drove every gate with
  `is_syn=True`; the rst gate now needs an ordinary packet. The test states why, rather than being
  quietly relaxed.

### Docs: the SOCKET-layer timing now says what was measured (prose only, no behaviour change)

The whole SOCKET-layer targeting design (PR #38) is justified by two numbers that came from a
2026-07-22 spike note and were never re-measured. Both are wrong, in different ways, and the
conclusion drawn from the first claimed more than it supports.

**Re-measured 2026-07-28** (Win11, elevated, three sniff-only handles opened SEQUENTIALLY and
compared on one clock - the QPC stamp WinDivert puts on every event - across 10 outbound TCP
connections to 8.8.8.8:53):

| claim in the code | measured |
|---|---|
| `SOCKET_CONNECT` ~0.1 ms before the SYN | before in **10/10**, by **0.018-0.027 ms** (median 0.020) |
| `FLOW_ESTABLISHED` ~28 ms after | **37.7-41.3 ms** after (median 38.7) |

- **The ORDER holds, the margin does not.** `SOCKET_CONNECT` really does precede the SYN every
  time, so choosing the SOCKET layer over polling stands. But the margin is **five times smaller**
  than the docstring said.
- **"The race is closed at the source" is now cut.** Those tens of microseconds are the gap between
  the two events AT THE DRIVER. Whether `socketwatch`'s own handling - thread wake, parse, dict
  insert - finishes inside that gap has **not** been measured, and at 20 us it is no longer
  self-evident the way it looked at 100 us. The prose now guarantees ordering and explicitly does
  not guarantee slack.
- **The FLOW number was a property of somebody's network, not of the FLOW layer.** 38.7 ms tracks
  the round trip to the peer (ping to the same host on this link: 23-47 ms), because the flow is
  established once the handshake completes. Recorded as such, so nobody reads it as a constant.
  The reason for rejecting FLOW is unchanged: it lands after the handshake either way.

Corrected in `socketwatch.py` (module docstring), `engine.py::_pid_for`, `targeting.py` (module
docstring) and PROJECT_NOTES in three places. **Deliberately NOT touched:** the `~0.1 ms` in
`model_worker.py`, `gui/panels/event_log.py` and `gui/pages/conns.py` - that is the virtualised
table's repaint cost, a different measurement that happens to share a number. Historical changelog
entries are left as written; they record what was believed at the time.

No test guards this and none can - it is prose. What can be done was done: the numbers now carry
their conditions, so the next session can tell whether they still apply to its machine.

### Fixed: the forged RST now lands on loopback connections too (audit F15)

Measured on the owner's machine (2026-07-28, elevated, real driver) by watching what the
APPLICATION sees rather than what a counter says:

- **Non-loopback: the RST works.** DNS over TCP to 8.8.8.8:53, connection established and
  exchanging, tool started after 6 s -> the client got `ConnectionResetError` (WinError 10054) at
  **6.6 s** after 26 answered queries, with `rst=1/1`. This closes the audit's oldest unverified
  claim, that `rst_sent` only proves `send()` did not raise. It proves more than that: Windows
  accepts the packet `_build_rst_packet` forges, and the application's connection really dies.
- **Loopback: it does not.** The same shape against an own echo server on 127.0.0.1 gave 26
  exchanges, then silence, then the client's own 3 s timeout - `TIMED OUT`, never a reset, while
  `rst=5/1` (five packets blackholed during the cooldown, one RST "sent"). So with the `loopback`
  traffic filter - which the GUI offers - "Reset connections" silently degrades to a blackhole and
  still reports an RST as sent.
- **A measurement trap worth keeping.** The first attempt fired on the SYN, because `--rst-prob 100`
  catches the first packet of a flow, and a bare RST with `seq=0` and no ACK is ignored in SYN_SENT
  (RFC 793). That run measured the SYN case, not the established one. When testing behaviour ON a
  connection: establish it, pass some traffic, and only then switch the impairment on.

**Two hypotheses, one measurement each, and the first was wrong.**

1. `_build_rst_packet` builds a fresh `pydivert.Packet`, whose address starts with `Loopback=0`, so
   the flag was carried over from the provoking packet. **One line on purpose** - changing the
   direction at the same time would have made a success ambiguous. Re-ran the probe:
   `TIMED OUT at 9.5s after 26 exchanges`, byte for byte the baseline. **Falsified.**
2. Rather than guess again, the mechanism was measured: a sniff-only handle on `loopback and tcp`
   printed every packet of a real 127.0.0.1 conversation as **`outbound=1, loopback=1`, exactly
   once each - the server's replies included.** Loopback has no inbound presentation at all, so an
   RST injected as `Direction.INBOUND` was put on a path the stack never reads. The RST is now
   built to look exactly like those captured rows: OUTBOUND, loopback flag set, for loopback
   packets only. Ordinary traffic keeps INBOUND, which is measured to work.

**Result:** `CONNECTION RESET at 6.5s after 26 exchanges` (WinError 10054), and the tool's own
counters moved from `rst=5/1` to `rst=1/1` - independent confirmation, since a connection that dies
at once has no further packets to swallow during the cooldown.

New test: `tests/test_rst_local.py::test_a_loopback_rst_is_injected_the_way_loopback_packets_travel`,
asserting direction and flag for both cases against a hand-built IPv4+TCP ACK. Conditional on
pydivert (win32-only), the same shape as `test_the_driver_queue_param_numbers_match_pydivert`.
Three mutants, every one caught - including "every RST becomes a loopback one", which would have
broken the ordinary path this fix must not touch.

### Added: the wait inside the driver is measured, not guessed (audit F10, part b)

- **The audit asked for an "overload heuristic". None was written, because the dependency already
  answers the question.** `pydivert.Packet.timestamp` is the raw QueryPerformanceCounter value
  WinDivert stamps each packet with (`packet/__init__.py:216`), so `QPC_now - stamp` IS the time
  that packet spent in the driver's queue. Reading the capability surface first (convention 6)
  turned a heuristic into a measurement.
- `winenv.qpc_now()` / `qpc_frequency()` (Windows-only, `None` elsewhere). Deliberately not
  `time.perf_counter()`: it is derived from QPC but carries an arbitrary epoch offset, so
  subtracting a raw stamp from it is meaningless.
- **Sampled on TIME, not on a packet count.** A 1-in-N sample never fires on a quiet link - 24
  packets in 12 seconds would never reach 1-in-256 - and a quiet link is exactly where a 2 s driver
  queue would go unnoticed. `DRIVER_WAIT_SAMPLE_S = 0.05` gives 20 samples a second at any rate,
  and the per-packet cost is one float compare against a `now` the loop had already read.
- `driver_wait_peak_ms` in `st` (the only float in there), a Session-tab row, the repro report, the
  stats CSV. `DRIVER_WAIT_WARN_MS = 50.0` - chosen against the MEASURED idle value on the owner's
  machine (0.049-0.163 ms, median ~0.08), so the threshold is several hundred times normal rather
  than a guess at one. Warning rate-limited at 5 s like the other two, with the first occurrence in
  the event log so the repro report carries it.
- **The QPC pair is an injected dependency**, like the clock and sleep `run_cli` takes: `start()`
  reads the frequency only `if self._qpc_freq is None`, so a test can drive the capture loop with a
  known clock.
- **Hot path measured** against a worktree of the F10a branch (150k packets, median of 5, twice
  each): 148.4 / 149.6k -> 154.1 / 154.4k pkt/s. A float compare cannot make anything faster, so
  that spread is noise and the honest reading is **no measurable cost**. NOT covered by this
  benchmark: the QPC call itself - synthetic packets have no `timestamp`, so the sampler returns at
  the `getattr`. On the real path that call happens 20 times a second regardless of traffic.
- Five new tests; **five mutants, four caught, and the fifth is recorded rather than papered over**:
  - mutating away `if waited_ms <= 0` changes nothing observable, because the peak comparison and
    the warn comparison both already reject a negative. The branch is a cheap skip of the stats
    lock, not a guard, and its comment now says exactly that instead of claiming it prevents a
    negative reading.
  - two mutants were caught only after repairs. The direct-call tests said nothing about whether
    the capture loop ever REACHES the sampler - deleting the call site left them all green - so
    `test_the_capture_loop_actually_takes_the_sample` runs a real session with the QPC injected.
    And it injects **1 MHz, not this machine's real 10 MHz**: with a matching frequency, a mutant
    that lets `start()` overwrite the injected value is invisible on Windows and only breaks on the
    Linux runner. Same trap as the pydivert import in part a, from the other side.

### Added: the driver's own queue is read and reported (audit F10, part a)

- **Symptom.** `pydivert.WinDivert(filt)` never received a `set_param()`, and the package contained
  no `get_param()` at all, so WinDivert's queue was invisible: with `QUEUE_TIME` at its default a
  packet may be held for up to **two seconds**, which is latency this tool adds while being blind
  to it, and no session artefact said what queue produced its numbers.
- **Measured on the owner's machine before designing anything** (2026-07-28, elevated, real driver,
  throwaway ICMP handle): `QUEUE_LEN=4096`, `QUEUE_TIME=2000`, `QUEUE_SIZE=4194304`, QPC frequency
  10 MHz. `QUEUE_SIZE` binds before `QUEUE_LEN` for full frames - 4 MiB / 1500 B = **2796 packets**
  - so at a saturated gigabit (83k pkt/s of 1500 B) a frozen capture thread has roughly 34 ms
  before the driver starts discarding.
- **Deliberately NOT retuned.** The trade is real in both directions and both are invisible today:
  a large `QUEUE_TIME` is latency the tool hides, a small one is LOSS the tool cannot even count,
  because a packet the driver drops never reaches us. Picking values before measuring the actual
  queue delay would be the "machinery around the wrong primitive" convention 6 warns about. The
  measurement is part b.
- `BeanEngine._read_driver_queue()` reads the three params after the handle opens (guarded by
  `crashlog.quiet`), stores them, and `session_info()` carries them into the repro report as
  `session.driver_queue`; one `log.driver_queue` line at START. `None` - not zeroes - on the
  simulate path, because "no driver" and "a queue of nothing" are different claims.
- **The param numbers are spelled out, not imported, and that is the interesting bit.** Reaching
  for `pydivert.consts.Param` here would import a **win32-only** dependency: the read would return
  None on the Linux half of the CI matrix while passing on Windows - the exact bug shape that only
  appears on the runner you did not run. `DRIVER_QUEUE_PARAMS` holds the ABI numbers, and
  `tests/test_engine.py::test_the_driver_queue_param_numbers_match_pydivert` compares them with the
  real enum wherever pydivert IS importable, so they cannot drift in silence.
- `--doctor` gains a line that says where the values live and why it does not read them itself:
  they need an open handle, and opening one loads the driver, falsifying the "windivert driver"
  check printed two lines above it in the same report.
- Three new tests, three mutants, every one caught (including the ABI numbers being swapped).
  No hot-path change: this is three calls, once per session.

### BREAKING: metrics.connections_reset counts connections, not packets (audit F7)

- **Symptom.** `repro.py` had `connections_reset=stats["drop_rst"]`, and `drop_rst` counts every
  PACKET dropped while a connection sits in its RST cooldown. With `--rst-cooldown 30` on a busy
  flow that is thousands against a handful of resets; the guard test now pins the smallest possible
  case - one reset connection reported itself as **50**.
- **Verified before designing the fix**, because the same lie could have been on screen: it is not.
  `tips.stat_rst` already reads "Packets of reset connections (RST)", so the live tile has always
  been honest. The repro report was the only surface claiming connections. Nothing in either README
  mentions the key.
- **Fix.** New engine counter `rst_reset`, bumped in the capture loop when `dec.emit_rst` is set -
  i.e. when a connection is actually torn down. Counted there rather than inside `_send_rst`
  deliberately: the flow is put into cooldown and its traffic dropped whether or not an RST can be
  built and injected for it, so `rst_reset >= rst_sent`, and the gap means "held down without an
  RST going out". The report now carries three keys for the three questions: `connections_reset`,
  `rst_packets_dropped` (the old value of the misnamed key) and `rst_sent`. CSV column
  `connections_reset` (`App.CSV_COLUMNS`); NDJSON `summary.counters` gets it for free.
- **No GUI tile added.** `drop_rst` and `rst_sent` already have tiles with correct tooltips, and
  `rst_reset` differs from `rst_sent` only when an injection could not be built or sent - a third
  tile for that is noise on a grid that is already 18 wide. The precise accounting belongs in the
  report, which is where the wrong number was.
- **Hot path:** one `_bump` behind `if dec.emit_rst`, which is per RESET, not per packet. Nothing
  on the common path, so not benchmarked.
- Two mutants, both caught - **after two repairs to the tests, both worth recording.** The first
  run reported "CAUGHT" on a pytest **exit code 4**, which is a usage error (I had guessed the test
  id), not a failing assertion. The second attempt put the report assertion in
  `test_summary_repro_views.py::test_build_repro_report`, whose session never resets anything: the
  mutant left `connections_reset` and `rst_reset` both at 0 and the test passed while guarding
  nothing. It lives in `tests/test_rst_local.py::test_rst_cooldown_sends_once_then_drops_silently`
  now, the one session where the three numbers genuinely differ, and the mutant fails there with
  `assert 50 == 1`.

### BREAKING: connection rows separate captured from delivered, and count the queue's drops (audit F5)

Two independent divergences in one table, fixed together because both need the same missing
mechanism: per-flow attribution of what happens AFTER the capture thread has moved on.

- **(a) `dropped` was recorded a step too early.** `_log_conn(dropped=dec.drop)` ran before
  `_enqueue`, so a packet the QUEUE refused counted nowhere in its row: measured
  `drop_overflow=5500` against `dropped=0` on the row it happened to, and `drop_shutdown=4000` with
  `dropped=0` and `bytes_in=4.8 MB` on a row that received nothing. `_enqueue` now returns whether
  it refused, and `stop()` charges every stranded ORIGINAL to the row that was expecting it.
- **(b) `bytes`/`bytes_in`/`bytes_out` were CAPTURED bytes under headings every other surface uses
  for DELIVERED** (session panel "Downloaded (MB)", repro report). Measured: a row reading
  `bytes_in = 5 122 600 B` whose application received `409 600 B`, a factor of 12.5. Rows now carry
  both: `bytes*` (captured, unchanged) and `sent`/`sent_in`/`sent_out` (delivered, new). The GUI's
  `down`/`up`/`kb` columns are the DELIVERED pair - so they finally agree with the session panel -
  and `down_seen`/`up_seen` are new columns for captured. `traffic_totals` (the footer) follows the
  columns above it and sums delivered; `conns.totals` says "Delivered" outright.
- **The mechanism.** Queue entries gained the flow key as a fifth element
  `(release, counter, packet, copy, key)`; the injector credits delivered bytes with it, `stop()`
  charges stranded packets with it, and the send-failure path charges the row too (F14's counter
  gets its per-flow half here).
- **Ordering is load-bearing, and the first version got it wrong.** Moving `_log_conn` AFTER
  `_enqueue` (so it could log the refusal in one call) opens a race: with no latency set the
  injector can deliver a packet before the row exists, and `_log_delivered` then has nowhere to
  credit it. It usually loses that race - it must wake on `_cv` first - which is exactly the
  "usually" that becomes a flake later. The row is created first; a refusal is charged afterwards
  through `_charge_flow`, off the common path.
- **`_log_delivered` runs WITHOUT `_clock`**, on the same reasoning as `SocketWatcher.pid_for`
  (convention 20): `sent`/`sent_in`/`sent_out` have exactly one writer, the inject thread, because
  the capture thread only ever initialises them at row creation. Readers only read, and an int
  rebind is atomic. `_charge_flow` (used for `dropped`, which the capture thread also writes) does
  take the lock. Guarded by
  `tests/test_engine.py::test_only_the_injector_writes_the_delivered_counters`, a source scan -
  nothing else can enforce a single-writer invariant, and a future edit crediting delivered bytes
  from another thread would drop updates silently and only under load.
- **Hot path measured, and it costs something** (Win11 AMD64, CPython 3.14.6, 150k 1500 B packets,
  median of 5, three repetitions against a worktree of the parent branch): parent 157.4 / 161.4 /
  160.9k pkt/s, this branch 153.8 / 153.5 / 153.8k - about **4% down**, consistently, on the
  synthetic path. Dropping the lock recovered roughly 1 point of the 5 the locked version cost
  (160.4 -> 152.0k with it); the rest is the dict lookup and the adds themselves, i.e. the price of
  the feature. Note the synthetic `send()` is a list append, so a real WinDivert syscall dilutes
  this - unmeasured, and not claimed.
- New tests: `tests/test_engine.py::test_a_connection_row_records_the_drops_the_queue_made`
  (asserts the row before AND after STOP: 190 refused, then 200 once the stranded ten are charged),
  `::test_an_undisturbed_row_has_delivered_equal_to_captured` (so the new columns are not a
  permanent discrepancy), and `tests/test_views.py::test_delivered_and_captured_are_different_columns`.
  Five mutants, every one caught **after one repair**: the first version of the views test only
  compared sort ORDER, and the mutant that put captured back under `down` kept the same order, so
  it passed. It now reads the `DERIVED` cells directly and uses a row pair that leads on opposite
  columns.
- Existing tests updated to the new contract rather than to green: `_conn()` in `test_views.py`
  defaults `sent_* == bytes_*` (an undisturbed flow), and the export test now asserts an impaired
  row where the two pairs genuinely differ.
- i18n: new `conns.down_seen` / `conns.up_seen` / `tips.col_down_seen` / `tips.col_up_seen`;
  `tips.col_down` / `col_up` / `col_kb` and `conns.totals` reworded to say which quantity they hold
  and to point at the other pair. Both READMEs describe the split with the measured example.

### Fixed: three small ones - stray .tmp, orphaned scenario runner, STOP racing a capture fault (audit F11, F12, F13)

**F11 - `export_connections_csv` left its temp file on failure.** It writes `path + ".tmp"` and
`os.replace`s it, but the `except` only logged: the half-written temp file stayed next to the real
one, and the next export silently overwrote it. `jsonfile.write_json` has had the cleanup (and a
test asserting no `*.tmp` after a failed write) for a while; this is the same guarantee.
New test: `tests/test_conns_export.py::test_a_failed_connections_export_leaves_no_tmp_file_behind`,
forcing the failure from inside the row loop (unsubtractable timestamps) so the temp file
definitely exists when it blows up. NOT changed: the stats CSV appends without an atomic write, so
a process death mid-flush can still truncate a line. Rewriting an append log through a temp file
costs the whole file per export; the exposure is a partial final line, and it is recorded here
rather than engineered away.

**F12 - `start_scenario()` orphaned the previous runner.** It overwrote `self._scenario_runner`
without stopping it, and `stop_scenario()` only ever knew about the current object, so the old
thread kept applying its own steps to the same engine. `self.stop_scenario()` first. Found by
reading; NOT reproduced in the running program, because the GUI and CLI both start one scenario per
session - which is a property of today's callers, not of the engine. New test:
`tests/test_engine.py::test_a_second_scenario_stops_the_first_instead_of_orphaning_it`.

**F13 - the capture-fault path waited on a stop that was joining it.** `_fail_stop(blocking=True)`
called `stop()`, which blocks on `_stop_lock`. When a `recv()` failed for its own reason in the few
instructions between the `_running` check and that call, an external STOP already held the lock and
was joining this very thread with a 2.0 s timeout: no deadlock, but STOP took the full 2 s. The
docstring claimed it "cannot deadlock against an external STOP: that path closes the divert first,
so the capture loop sees `_running` already False and never reaches here" - true when the fault IS
that stop closing the divert, and that sentence is why nobody looked further.

- **First attempt was wrong and the suite caught it.** Routing the capture path through
  `_worker_stop` (the audit's first suggestion, one line) broke
  `test_a_dead_capture_thread_fails_open`: a divert that fails on its very first reads faults while
  `start()` still holds the lock, which is not a corner case but the case the blocking path exists
  for. It would have handed every such teardown to the watchdog a tick later.
- **What landed:** `_fault_stop_blocking()` polls `acquire(timeout=FAULT_LOCK_POLL_S)` (0.05 s) and
  bails only when `_running` has gone False. No new state is needed to tell the two holders apart:
  `_stop_locked` clears `_running` as its second statement, so "held and still running" is a start
  and "held and not running" is a stop that already owns the teardown.
- `_fail_stop` now keeps the FIRST fault (`if not self.fault`). The watchdog's "worker thread died
  unexpectedly" is a symptom; letting it overwrite the cause blanks out the only useful half of the
  report. Both are still logged.
- New tests in `tests/test_failsafe.py`, all structural rather than wall-clock so they cannot
  flake: `::test_a_capture_fault_racing_an_external_stop_does_not_wait_for_it`,
  `::test_a_capture_fault_still_waits_for_a_start_that_holds_the_lock` (the other half - a mutant
  that bows out on a start is caught too), and `::test_the_first_fault_is_the_one_kept_for_the_report`.
- **One of those tests was itself wrong, and mutation is what found it.** The fault test held
  `_stop_lock` and called `_fail_stop` on the SAME thread - `_stop_lock` is an `RLock`, so the
  nested `_worker_stop` re-entered, the stop completed, `_running` went False and the second fault
  returned at the guard. It passed for the wrong reason and guarded nothing. Driving the faults
  from another thread fixed it. Worth remembering when writing anything that leans on this lock.

Five mutants across the three, every one caught after that repair.

### Fixed: a failed injection is counted, and stops flooding the log (audit F14)

- **Symptom.** `_inject_loop`'s `except` around `self._divert.send(packet)` logged and moved on.
  The packet is already off the heap at that point: `bytes_in`/`bytes_out` are not bumped, no drop
  counter is bumped, and `seen` counted it at capture - so it left the seen/delivered/dropped
  balance entirely. That balance is the only mechanism keeping these numbers honest, and
  `drop_shutdown` was added for precisely this class of hole ("instead of letting them vanish from
  the balance"); the send-failure path was missed at the time.
- **Found by a question, not by a test.** The owner asked what happens to statistics if the
  connection breaks mid-session. Answering it properly meant reading the path.
- **Fix (`engine.py`).** New `drop_send` counter bumped in the `except`, classified into
  `TOOL_DROP_KEYS` - the tool failing, not the simulated link, so it stays out of
  `impairment_loss_pct` while entering the balance. `SEND_WARN_S = 5.0` and `_warn_send_failed()`
  mirror `OVERFLOW_WARN_S` / `_warn_overflow()` exactly, including the first-occurrence
  `log_event("WARN", ...)` so the repro report carries it.
- **Why the rate limit is part of the same fix.** The comment above `OVERFLOW_WARN_S` already
  states the rule - a per-packet line "becomes the second bug" - and this path had no limit at
  all. `App._drain_log` drains the whole queue per tick and inserts EVERY line into the Tk widget
  on the UI thread with no per-tick bound, so a burst of failures freezes the window on top of
  losing the packets. Measured by mutation: 400 failures produced **400 log lines** before, at
  most 2 after.
- **The F4 classification guard did its job on the first new counter since it was written.**
  `test_every_drop_counter_and_drop_reason_is_classified` goes red with
  `unclassified: ['drop_send']` if the counter is added to `st` without being classified - checked
  by mutation, not assumed.
- **NOT verified:** no send failure was reproduced on a live WinDivert, so how often the real
  driver refuses a packet, and whether it arrives in bursts, is unknown. The balance hole does not
  depend on that number - it is a hole at one failure as much as at a thousand.
- Surfaced additively: live tile `stats.send_failed` (`gui/pages/stats.py::CELLS`), CSV column
  `dropped_send_failed` (`App.CSV_COLUMNS`), and `_drain_engine_warning` now also fires for it,
  with overflow keeping precedence (that one the user can act on by lowering the latency or rate).
  `drop_send` reaches NDJSON `summary.counters` and the repro report's `counters` for free.
- i18n: `log.send_error` **retired** (its only caller is gone) and replaced by `log.send_failed`
  carrying `{n}` and `{e}`; new `events.send_failed`, `warn.send_failed`, `stats.send_failed`,
  `tips.stat_send_failed`. Net +4 keys in both lang files, key sets identical. Both READMEs list
  the new counter and now state as a group that the three tool-loss counters are excluded from
  "Effective loss" on purpose.
- **Hot path:** every added line is inside the `except`, so it cannot execute on a successful send
  - a structural argument, but measured anyway against a `git worktree` of master (150k 1500 B
  packets, median of 5): 157.6k -> 162.6k pkt/s, no regression.
- New tests, all mutation-verified (four mutants, every one caught):
  `tests/test_engine.py::test_a_packet_the_tool_could_not_re_inject_is_counted_as_a_drop` (a
  `RefusingDivert` whose `send` always raises; asserts the balance closes and that the figure stays
  at 0.0% because this is not impairment damage),
  `::test_failed_injections_do_not_flood_the_log`, and
  `tests/test_gui_release_fixes.py::test_the_banner_also_fires_when_the_tool_cannot_re_inject`.

### Docs: the effective-loss figure names its boundary (prose only, no behaviour change)

- **Where it came from.** The owner ran the F9 acceptance (ping 30, one reply lost out on the
  network) and asked why the tool showed 59 packets and zero loss. Both numbers are correct - 30
  requests out, 29 replies back, nothing broken here - but `tips.eff_loss`, added one commit
  earlier, opened with "how much of the traffic you aimed at never arrived", which reads as "never
  reached the far end". That is the wrong quantity, and it is the second reading of the same
  sentence, so the sentence is at fault, not the reader.
- `tips.eff_loss` (both lang files) now leads with "how much of the traffic you aimed at THIS TOOL
  broke" and states outright that a packet lost out in the network never arrives here, so nothing
  here can count it. Same for the README bullet in EN and PL, which gained the worked ping example
  (59 packets, zero drops, and why both are right). Values only - no new keys, no code touched.
- **No test guards this**, and none can: it is prose. What can be said is that nothing else in the
  repo repeats the claim - `tips.stat_loss`, `tips.col_dropped` and `conns.scope_note` all already
  scope themselves to the configured impairments, checked before writing this.

### Fixed: portless traffic (ICMP) reaches the connection log (audit F9)

- **Symptom.** `core._flowkey()` returns `None` when any of local port / peer address / peer port
  is missing, and `_log_conn()` returns immediately on a `None` key. ICMP has no ports, so it was
  counted in `seen` and in the byte totals and then dropped on the floor. Measured: 500 ICMP
  packets -> `seen=500`, `bytes_out_total=49000`, **0 rows**. Confirmed on live WinDivert by the
  owner (traffic filter "Ping (ICMP)", 30 s of pinging, empty tab) while `conns.scope_note` says
  "All captured connections" and `README.md` says "Statistics and Connections show ALL captured
  traffic". Both statements are now true; neither was edited, because neither was wrong about the
  intent.
- **Fix (`engine.py`, capture loop).** When the flow key is `None` but a peer address is known,
  the row is keyed `(proto, remote_ip)`. Both directions land on the same key (`remote_ip` is
  `dst_addr` outbound, `src_addr` inbound), so a ping is one row, not two. A 2-tuple cannot
  collide with the 3-tuple flow keys. **`_flowkey` itself is deliberately untouched**: it is also
  the key of `core`'s flow table, which drives NAT expiry, RST cooldown and flapping, so making
  ICMP a flow there would change what gets IMPAIRED rather than what gets listed.
- **The dependency was read before the design, not after** (convention 6). Installed pydivert,
  `packet/__init__.py`: `src_port` (line 553) **returns None rather than raising** when there is
  no TCP/UDP header - load-bearing, because the ports are assigned in the same statement BEFORE
  `remote_ip`, so a raise would leave `remote_ip` at `None` and the fallback key would have
  nothing to key on. Also `packet.icmp` (line 483) is `icmpv4 or icmpv6`, so the existing
  `proto = "ICMP"` detection in the capture loop is right for real packets; had pydivert exposed
  only `icmpv4`, ping rows would have been labelled "IP" and the fix would have looked like it
  worked.
- **Three consumers assumed ports always exist.** All three were fixed in the same change, and
  the first was a crash: `cli.py::_print_conns` pads with `{...:<6}`, and `format(None, '<6')`
  raises `TypeError: unsupported format string passed to NoneType.__format__` (verified), so
  `--log-conns` in text mode would have died on the first ping row - a regression this fix would
  have INTRODUCED. It now prints `-`. `gui/pages/conns.py::_render` passed the value straight to
  Tk, where `None` renders as the literal string "None"; new `port_cell()` blanks it.
  `views.py::_connection_blob` used `c.get('remote_port', '')`, but a portless row HAS the key
  holding `None`, so the default never fired and the blob read `8.8.8.8:none` - every ping row a
  hit for the search term "none". Now `or ''`.
- **Checked and NOT broken** (verified rather than assumed): sorting by a port column -
  `filter_sort_connections` casts inside `try/except (TypeError, ValueError)` -> 0.0, and the text
  branch goes through `str()`; the connections CSV export - `csv.writer` writes `None` as an empty
  cell, now pinned by `test_conns_export.py::test_export_connections_csv_writes_a_portless_row_with_empty_port_cells`;
  the context menu - `_selected()` reads the DISPLAYED cells, so "Limit to this IP:port" on a ping
  row fills the address and leaves the port blank, and "Target this process" is already disabled
  for a row with no process.
- **A fourth consumer, found by re-reading this change rather than by a test failing.**
  `ConnsPage._key_of` joined local port, address and remote port - unique for every row while
  every row had ports, and no longer: two portless rows to the SAME address (ping plus, say, ESP
  or GRE to a VPN gateway) both stringify to `"None|10.8.0.1|None"`. `SortableTree._ensure_index`
  builds `{key: position}` as a **dict**, so one of the two rows becomes unselectable and
  unscrollable-to. The protocol is now part of the identity. This is a defect this change would
  have INTRODUCED, like the `--log-conns` crash; guarded by
  `test_conns_columns.py::test_two_portless_rows_to_one_address_keep_separate_identities`
  (mutation: restoring the old key collapses the index to one entry).
- **Hot path:** one extra `key is None` comparison per packet. Measured against a `git worktree`
  of master (150k 1500 B packets, median of 5): 153.4k -> 158.8k pkt/s, i.e. no measurable cost
  (the difference is run-to-run spread, the two paths differ by one comparison).
- New tests, all verified by mutation (five mutants, every one caught):
  `tests/test_engine.py::test_portless_traffic_reaches_the_connection_log` (removing the fallback
  gives `rows=0`) with an `IcmpPacket` double shaped after the pydivert reading above;
  `::test_traffic_with_no_peer_address_still_gets_no_row` (dropping the `remote_ip is not None`
  guard invents a row keyed on nothing);
  `tests/test_cli_runtime.py::test_the_connection_listing_survives_a_row_with_no_ports` (reverting
  it reproduces the `TypeError` above); and
  `tests/test_conns_columns.py::test_a_portless_row_renders_empty_port_cells_and_is_not_searchable_as_none`,
  which covers the render blanking and the search blob in one page-level run.
- i18n: `tips.col_proto` gained ICMP to its protocol list; `tips.col_remote_port` and
  `tips.col_local_port` now say the cell is empty for portless traffic (and why the process column
  is empty with it). Values only in both lang files - **no new keys**. README EN + PL gained one
  clause in the Connections description.

### Fixed: drop_overflow and drop_shutdown count packets, not queue entries (audit F6)

- **Symptom.** `_enqueue()` runs once per element of `dec.releases`, and pipeline step 12 adds a
  second element for a duplicate. Both `drop_overflow` (in `_enqueue`) and `drop_shutdown` (in
  `stop()`, from `len(self._heap)`) therefore counted queue ENTRIES while `tips.stat_overflow` and
  `tips.stat_shutdown` both promise "Packets". Measured before the fix: `seen=1000`,
  `duplicated=1000` -> `drop_overflow=1900`, `drop_shutdown=100`, so the "Buffer overflow" tile
  could read higher than the "Packets" tile in the same session.
- **Fix (`engine.py` only).** `_enqueue(release, packet, copy=False)`; heap entries carry the flag
  as a fourth element `(release, counter, packet, copy)` (ordering unaffected, `counter` is unique
  so comparison never reaches index 2 or 3); `_inject_loop` unpacks four; `stop()` uses
  `sum(1 for entry in self._heap if not entry[3])`. The capture loop enqueues `releases[0]`
  directly and only branches into a loop for the duplicates, so the single-release path (every
  session without duplication) does not pay for an `enumerate`.
- **The warning follows the counter.** A refused copy no longer warns either, because
  `log.queue_overflow` interpolates the counter: firing it for a copy would print "the TOOL is now
  dropping packets you did not ask to lose (0 so far)". Only originals count and warn, which keeps
  the counter, the log line and the GUI banner (`_drain_engine_warning`, which reads
  `st["drop_overflow"]`) telling the same story. A queue that refuses only copies is losing the
  user nothing, so silence is correct.
- **Known, deliberate gap** (recorded in `_enqueue`'s docstring rather than engineered away): if
  the original is refused and the injector then frees a slot so the duplicate fits, the packet is
  delivered up to 20 ms late but counted once as lost. Closing it needs copy/original pairing
  through the heap.
- **Hot path measured, not assumed** (Win11 AMD64, CPython 3.14.6, 150k pre-built 1500 B packets
  through `FakeDivert`, median of 5, both trees benchmarked back to back from a `git worktree` of
  master): no duplication 153.8k -> 156.0k pkt/s, 100% duplication 100.9k -> 102.4k pkt/s. The
  medians moved about 1.4% in the new code's favour, but the per-run ranges overlap
  (147.8-155.5 vs 149.3-157.7), so the honest reading is NO MEASURABLE REGRESSION, not a speedup.
- New tests, both verified by mutation (reverting each half of the fix turns them red with exactly
  the pre-fix numbers): `tests/test_engine.py::test_overflow_counts_packets_lost_not_queue_entries`
  (100% duplication into a 10-slot queue: `drop_overflow == 390` before, `195` after, against
  `seen=200`) and `::test_drop_shutdown_counts_packets_never_delivered_not_queue_entries`
  (`drop_shutdown == 400` before, `200` after). Both are deterministic, not statistical:
  `dup=100%` fires on every packet and the 60 s latency releases nothing before STOP.

### Fixed: two tooltips that described counters they do not describe (audit F8)

Both in `lang/en.json` and `lang/pl.json`, both user-visible, neither catchable by a test - this is
the failure mode rule 5 is about: true-sounding prose next to correct code.

* `tips.stat_loss` said "Packets dropped because of the configured Loss (or link outages)". Link
  outages have had their own counter (`drop_flap`) since they stopped inflating "Dropped", and
  `tips.stat_flap` says so in the next cell: "Counted separately from loss". Two tooltips
  contradicting each other, with the wrong one attached to the number a tester reads first.
* `tips.data_down` promised "Hovering also shows how much the app tried to download".
  `add_tooltip(widget, key)` renders one static translated string (`gui/tooltip.py`); there is no
  dynamic path and never was. The offered figure exists only as `metrics.offered_mb` in the repro
  report - and note it is the SUM of both directions, so it is not "how much the app tried to
  download" either. Replaced with something true and useful in its place: dropped packets are not
  counted in this figure, which is the difference between it and the connections table's bytes.

No code change, so no new test; `test_i18n_coverage` already pins key parity (465 keys, identical
sets) and `test_no_em_or_en_dashes_in_repo_text` the punctuation.

### Fixed: an impairment no longer expires when its flow record does (audit F2, and F1's tail)

`_reset_until` and `_flow_last` are `_FlowTable`s that retired a generation every `FLOW_ROTATE_S`
(30 s), so a record survived 30-60 s - and both tables hold the state that IS an impairment. Two
settings were therefore capped by a constant nobody had connected them to:

* **`rst_cooldown`** accepts up to 3600 s. Measured at 120 s, the same flow was reset again after
  30.3, then 60.8, then 60.8 s.
* **NAT expiry** was worse than capped. A retired record reads back as "never seen", so the next
  inbound packet reopens the mapping with nothing sent. Measured: a 5 s timeout blackholed for 20 s
  and then passed traffic; **a 30 s and a 120 s timeout dropped ZERO packets**, because the record
  died at the rotation just before the first inbound packet arrived.

`_FlowTable.keep_for(seconds)` raises the age window; `set_rst` passes the cooldown, and `set_nat`
switches ageing OFF for `_flow_last` (`float("inf")`) while NAT is on. Matching the window to the
timeout is not enough for NAT and was measured failing exactly as above - the record has to outlive
the timeout AND the blackhole after it, and that blackhole is meant to last until the application
sends. The RST cooldown is a fixed span, so there the window is simply the cooldown.

**Why raising the window is safe, and the property that says so:** the SIZE ceiling is enforced on
every write, independently of the age window, so a longer window makes the table older and never
bigger. Measured through the real setter: 250k flows with `nat_timeout=3600` peaked at 199,999
against the 200,000 ceiling.

After: cooldowns of 60 / 120 / 300 s reset at exactly those intervals; a NAT blackhole held for the
full 900 s of the probe at 5, 30 and 120 s timeouts (1800 packets dropped) and ended on the first
outbound packet, which is the documented contract.

New tests in `tests/test_core.py`:
`test_a_long_rst_cooldown_is_honoured_not_truncated_by_the_flow_table`,
`test_an_expired_nat_mapping_stays_shut_until_the_application_sends` and
`test_the_size_ceiling_holds_even_with_the_age_rotation_switched_off` - the last one drives the
table through `set_nat` on purpose, because the existing churn test assigns `nat_timeout_s`
directly and so never exercises the ageing-off path. The first two were verified by mutation:
making `keep_for` a no-op reproduces the audit's numbers exactly (`gaps=[30.3, 60.8, 60.8, ...]`
and `dropped=0, passed=720`).

Prose corrected in the same commit (convention: a behaviour change updates the sentence that
justified the old one): the `_FlowTable` docstring said eviction "can lose an impairment, never
invent one" as if that covered both paths. It covers the SIZE path; on the AGE path it was not a
trade but a silent cap. The step-3 comment added by the F1 fix said the blackhole ends at the first
rotation - that is now what the fix prevents.

### Fixed: the injector asks Windows for a fine timer tick, and for it to be honoured (audit F3)

`_inject_loop` holds a delayed packet with `Condition.wait(timeout=...)`, and Windows rounds that
timeout UP to the system timer tick - 15.6 ms unless the process asks for better. That rounding
was the entire added-latency error. Measured on the REAL capture path (ping through live
WinDivert, `--dst-ip 8.8.8.8`, two independent runs): a **constant +12.6 ms of round-trip
overshoot, independent of the setting** - +12.2 ms at `--latency 10` and +12.8 ms at `--latency
50`, where a proportional error would have been ~62 ms at the higher setting. The control run at
`--latency 0` measured +0.4 and -0.3 ms, so it was not the capture path, the driver or the link.

`BeanEngine.start()` now takes a fine tick for the life of the SESSION and `_stop_locked` gives it
back after the injector thread is joined; `winenv.request_fine_timers` / `release_fine_timers` are
the (Windows-only, no-op elsewhere) wrappers. Session-scoped rather than process-scoped: the pair
costs ~1.3 us (measured), so nothing needs to hold a finer tick while the tool sits idle.

**Two things this cost, both found by measuring rather than by reading docs:**

* **`timeBeginPeriod` alone is a fix that works and then stops.** Windows 11 throttles a
  BACKGROUND process's timer resolution: the request kept returning success with a perfectly
  balanced request/release log, while the effect vanished after roughly ten seconds - in one
  process, `Condition.wait(10 ms)` went 10.1, 10.3, then 15.6 ms for every later session. This
  tool lives in the background (start a session, switch to the app under test), so shipping only
  the obvious call would have regressed silently on users while measuring clean here.
  `winenv._allow_fine_timers_in_background()` opts out via `SetProcessInformation`
  (`ProcessPowerThrottling` + `PROCESS_POWER_THROTTLING_IGNORE_TIMER_RESOLUTION`, state 0), once
  per process. With it, the same wait held 10.1-10.7 ms across 40 s of sampling and across eight
  back-to-back sessions.
* **Querying the system-wide resolution proves nothing.** `NtQueryTimerResolution` reported a
  current tick of 1.0 ms - something else on the machine was holding it - while our own waits were
  still being rounded to 15.6 ms, because since Windows 10 2004 the tick is per-process. A session
  that checks the global number and concludes "the timer is already fine" is reading a number that
  does not apply to it. That is written into the `request_fine_timers` docstring.

Result through the engine, eight sessions in one process (sparse traffic, the case the audit
measured at +8.3 ms): overshoot **+0.22 to +0.55 ms**, worst case down from ~25 ms to ~11 ms.

**Accepted on the real capture path** (ping, 40 packets per setting, live WinDivert):

    krok            nominal   min   p50   p90   max      nadwyzka p50   (przed)
    latency 10           45    45    46    50    61            +1 ms    +12.6 ms
    latency 50          125   125   126   130   135            +1 ms    +12.6 ms
    baseline             25    24    25    28   112

Same +1 ms at both settings, so the surcharge is gone rather than scaled; p90 is +5 ms at both.
Two measurement lessons worth keeping, because the first acceptance run (10 packets per setting)
read as a HALF fix at +6.3 / +9.5 ms:

* **Average over ten pings is the wrong statistic here.** About 1% of packets sit in a tail, a ping
  carries two impaired packets, and one outlier moves a ten-sample mean by 4-8 ms. The median was
  right all along - the ten-sample run's own minima were already exactly nominal (45 and 125).
* **The tail is the LINK, not us.** In the 40-packet run the untouched baseline produced the worst
  outlier of the whole session (max 112 ms, against 61 and 135 with the tool in the path). An
  earlier reading that blamed a "worse tail" on this change did not survive a bigger sample.

New tests in `tests/test_failsafe.py`:
`test_the_fine_timer_request_is_balanced_on_every_session_path` (clean stop, double stop, second
session and a start that raises - an unbalanced pair is invisible from inside the program, it just
means the process keeps a finer system timer for life), `test_a_refused_fine_timer_request_is_never
_released` (releasing one we never took decrements somebody else's refcount),
`test_the_background_timer_opt_out_is_asked_for_once_per_process` and
`test_the_fine_timer_calls_are_safe_to_make_anywhere`. The first two were verified by mutation:
dropping the release turns the first red with `['request']`, releasing unconditionally turns the
second red with `['request', 'release']`.

### Fixed: a dropped packet no longer revives the NAT mapping it was dropped for (audit F1)

`BeanCore.decide()` step 3 read and wrote the activity stamp in one `_FlowTable.touch()`, so the
write happened BEFORE the expiry verdict and applied to the drop path too. The packet rejected
with reason `nat` therefore stamped the flow as active, and the mapping was back: the direction
lost exactly one packet per `nat_timeout_s` and carried traffic in between, with nothing outbound
involved. Measured before the fix (timeout 5 s, one outbound at t=0, inbound only afterwards):
`t=10 DROP, t=11 pass, t=12 pass, t=13 pass, t=20 DROP`. The impairment exists to test whether an
application sends keep-alives, and in that shape the test could not fail.

Split into `get()` + a `set()` placed after the verdict, so the drop path skips the write. Same
cost - `touch()` was a `get` plus this same write - measured 160 ns/op both ways at 200k
iterations, difference below the noise floor. `_FlowTable.touch()` had exactly one caller and is
removed with it.

How long the blackhole holds is bounded by the flow table, and the comment in `core.py` now says
so with numbers instead of a general claim: the drop path returns above the `_prune()` call, so it
never rotates anything itself. Measured with the same setup - this flow alone: still blackholed at
t=200; one other flow driving `_prune`: reopened at t=30, the first rotation. That is the table's
documented safe direction (it can lose an impairment, never invent one) and is a different thing
from the resurrection above, where the dropped packet did the reopening itself.

New test: `tests/test_core.py::test_a_dropped_packet_does_not_revive_an_expired_nat_mapping` -
asserts every inbound packet after expiry is dropped (not just the first) and that an OUTBOUND
packet is what brings the mapping back. Verified by mutation, not assumed: restoring the
write-before-verdict order turns it red with `drops=[True, False, False, False]`, the exact
symptom above. The two existing NAT tests (`test_nat_expiry`, `test_nat_outbound_refreshes`) pass
unchanged - neither of them pinned the buggy behaviour, which is why it survived.

### Performance: PortTable.refresh collects the socket table outside its lock

The capture thread takes `PortTable._lock` too - `name_of(cheap=True)` -> `info()` in
`engine._process_for` - so whatever `refresh()` holds it for, the packet path can be made to wait
for. It used to hold it across the four `iphlpapi` calls, the port->pid dict build AND the
departed-pid diff, all O(number of sockets).

MEASURED first, 2026-07-25 (Win11, CPython 3.14, elevated, medians with a control), because "the hot
path waits N ms" is exactly the kind of claim convention 5 says to measure rather than estimate:

- Lock hold with everything inside: **0.495 ms median at 119 sockets** (p99 0.843, max 0.950).
  Python-side work scales linearly: 0.011 ms at 100 sockets, 0.303 at 10 000, **3.555 at 100 000**
  (syscalls excluded, so a floor).
- The capture thread's own `name_of(cheap=True)` is **0.4 us median** - and with a thread hammering
  `refresh(force=True)` alongside, its median, p95 and p99 did not move at all. Only **2 calls in
  20 000** waited, worst 1.5 ms. At the real rate the lock is held ~0.15% of the time.
- So at desktop scale this was NOT an observable problem, and the honest conclusion could have been
  "measured, rejected". What decided it was the scaling: a network tester is the thing that gets
  pointed at 100 000 connections, and this project's history is a series of "it was fine until
  someone ran a load test" (the flow table once settled at 3.2 million entries).
- Also learned while checking WHO refreshes: since chunk 2c the resolver resolves against the
  `SocketWatcher`, whose `refresh()` is a no-op - so in a real session only the watchdog refreshes
  the `PortTable`, ~3-5x a second. The up-to-20x a second case is the poller FALLBACK
  (`--simulate`, tests, non-Windows), which has no real capture thread to stall.

After the change: **the hold is flat at ~0.018 ms** whatever the table size (188x shorter at 100 000
sockets, and no longer a function of n). The whole call costs the same - the work left the lock
rather than disappearing. Kept internal-only deliberately: nothing a tester can observe changes, and
claiming a user-visible win would be unmeasured prose.

- Collection and the departed diff now run unlocked; only the reference swap, `_last`, the
  `_info` pops and `_expire_info` are taken under the lock.
- **Overlapping refreshes cannot move the map backwards.** Two threads can now collect at once, so
  each call takes a GENERATION under the lock before starting and installs only if nothing newer
  landed. A counter, not a timestamp: `time.monotonic()` has ~15 ms granularity on Windows, so two
  refreshes inside one tick would compare equal and both install. The hazard was real, not
  theoretical - the mutation below installs the stale map without the guard.
- The `native` handle is captured per call and the "it stopped answering" flip is re-checked under
  the lock (`self._native is native`), so a concurrent refresh cannot have its own conclusion undone.
- New tests in `tests/test_processes.py`, both mutation-checked:
  `::test_the_socket_table_is_collected_without_holding_the_lock` - probes the lock from ANOTHER
  thread, because `_lock` is an RLock and a same-thread acquire would succeed while held and prove
  nothing; putting the collection back inside turns it red.
  `::test_an_older_collection_does_not_overwrite_a_newer_map` - gate-driven rather than sleep-raced;
  removing the generation guard turns it red with the stale map installed.

### Changed: start() binds the targeting under the lock that protects it

`_start_locked` read `self._targeting` bare and then acted on that reference three times
(`set_table`, a synchronous `refresh`, `retarget`), while every other access to the field - in
`set_target` and `target_for` - is under `_target_lock`. A concurrent `set_target()` landing in the
middle would leave the resolver pointed at an ORPHAN while the core tested against the object that
replaced it, which is the same class of mismatch `set_target()` itself was fixed for.

- **This is consistency of access, NOT a fixed symptom, and the commit says so.** The race was not
  reproduced: 25 start/stop cycles against a concurrent applier in `test_concurrency_chaos.py` stayed
  green, and the window is narrow today because the CLI applies settings before start, so only a GUI
  "Apply" landing inside start could hit it. Recorded this way deliberately, so a later session does
  not read it as "we fixed a race we had seen".
- Lock order checked before widening the hold, not after: `_stop_lock` -> `_target_lock` ->
  `ProcessTargeting._lock` -> `PortTable._lock`, and nothing walks it the other way - the resolver
  never calls back into the engine, and `retarget()` is only reached with `_target_lock` already
  held. In this spot there is not even contention: `_resolver.start()` comes after the block and
  `stop()` joins the resolver, so the synchronous `refresh()` has no contender. Cost is one cold
  resolve (~36 ms elevated, per `portmap.info`) at session start.
- Rejected: locking only the READ. It narrows the window without closing it, and the point is that
  start binds ONE coherent object rather than that a mismatch becomes less likely.
- New test: `tests/test_target_resolver.py::test_start_binds_the_targeting_under_the_lock_that_protects_it`
  - a mechanical guard (an instrumented `_target_lock` that records acquisitions), not a timing test,
  because a timing test for this window would be flaky and prove nothing either way. Mutation-checked:
  reverting to the bare read turns it red. Its docstring states what it does not claim - that the
  race was real.

### Tests: the concurrency chaos suite now includes the SocketWatcher

The suite's own charter is "many threads hammering one engine" and it names the failure it exists to
catch - threads tested in isolation. Since the SOCKET-layer work the session runs a FOURTH thread
and, since the connection-log fix, the capture thread reads the watcher's live map WITHOUT a lock -
and no test in that file ever passed the engine a `socket_source`, so neither the watcher's lifecycle
nor that lock-free read took part in any chaos.

- `test_the_socket_watcher_survives_start_stop_cycles` - `CYCLES` start/stop rounds with a real
  event stream running: fail-open (running implies a live capture thread AND a watcher), the watcher
  cleared and its handle released on stop, and no `bean-socket-watcher` thread outliving its session.
  Checked after a 0.3 s grace, because `SocketWatcher.stop()` only joins for 0.25 s.
- `test_the_capture_thread_reads_the_live_socket_map_under_churn` - the real new surface: the capture
  thread resolving pids from the map while the watcher thread mutates it, the watchdog republishes it
  wholesale, and settings and targeting churn underneath. Runs on `FastDivert` and on the SAME ports
  the event source announces, or `pid_for` would always miss and a green run would prove nothing.
- **The crashlog watch is the test, not decoration.** `_pid_for` / `_process_for` swallow into
  `crashlog.once` by design, so a read that started raising would leave every other assertion green.
  Patching `once` also defeats its `_once_seen` dedupe, so repeated failures stay visible instead of
  collapsing into one entry.
- Conclusiveness is a CONDITION the test waits for (`MIN_STAMPED` rows carrying the event stream's
  pid), never a duration - the same reasoning as `MIN_BUILDS`/`MIN_ROWS`, and for the same reason: a
  wall-clock budget lets machine speed decide whether the test proved anything.
- Both claims MUTATION-CONFIRMED: a `SocketWatcher.pid_for` that raises turns it red through the
  crashlog watch, and an engine reverted to poller-only stamps 0 rows out of 2.8 million packets.
  The first mutation also independently confirmed the failure-domain split below - it reported
  `engine.ports` AND `engine.ports.pid`, not one collapsed entry.
- Stated in the docstring, so nobody assumes otherwise: this does NOT catch putting the lock back
  into `pid_for`. A lock contends, it does not raise, and this test does not measure contention -
  that property has its own guard in `test_socketwatch.py`.
- `_LiveSocketSource` is paced on purpose. Unpaced it saturates a core and starves the very threads
  the test is about, which would make a green run meaningless.

### Fixed: the connection log resolves the owner from the live socket map, not the poller

`_pid_for` / `_process_for` asked `portmap.PortTable` - a snapshot refreshed a few times a second -
so a flow that opened AND finished inside one refresh interval left a row with no owner at all.
Short-lived connections are what this tool gets pointed at, so that was the common case rather than
an edge one. The engine now asks the SOCKET-event map first (`SocketWatcher.pid_for`) and falls back
to the poller, so a row is stamped from its FIRST packet: the CONNECT event lands ~0.1 ms before the
SYN reaches the NETWORK layer (measured 2026-07-22).

- **The read had to become LOCK-FREE first, and that is the substance of this change.** `pid_for`
  used to take `_lock` - which the watcher thread holds on every socket event, and which
  `reconcile` holds across a whole snapshot merge. Calling that from `_log_conn` would have let the
  CAPTURE THREAD queue behind maintenance, which is exactly the stall convention 20 exists to
  prevent. `pid_for` now reads the reference once and does a C-level `get` on int keys (the same
  idiom as `PortTable.pid_for`), and `reconcile` builds the new state to the side and publishes it
  by REASSIGNMENT, so its O(n) pass is atomic to a reader instead of being observed half-applied.
- Name resolution is unchanged and still `cheap=True` (cache or nothing), so a brand-new pid can
  reach a row BEFORE its name does - names are warmed by the watchdog. That is written into the
  docstring rather than glossed over: a PID with no name yet is still an answer, and `_log_conn`
  keeps retrying the name while packets arrive.
- Deliberately NOT done: warming names from the watcher's map as well. It would close the remaining
  name lag, but it adds per-pid OS calls to the watchdog and deserves its own measurement first.
- The shared lookup lives in `_live_pid`, which has NO handler of its own on purpose. The first
  attempt had `_process_for` delegate to `_pid_for`, and because that one swallows and records under
  `engine.ports.pid`, a broken port table reported ONE failure instead of two - the name domain
  could no longer speak for itself. `test_processes.py::test_engine_records_a_broken_port_table_instead_of_going_quiet`
  caught it. The two callers are two failure domains and each wraps the raising helper itself, which
  is the same principle the watchdog already applies to refresh-vs-trim ("different jobs, different
  failure domains").
- `_Broken` in that test now models what the engine actually calls (`pid_for` + `name_of(cheap=)`)
  instead of `process_for_port`, which the engine no longer touches. The insight in its comment -
  that a fake missing the keyword raises TypeError and the test then passes while exercising the
  wrong failure - still holds, so it moved to the keyword that now matters rather than being
  deleted.
- New tests, each MUTATION-CHECKED rather than trusted:
  `test_socketwatch_wiring.py::test_a_fresh_socket_stamps_the_connection_row_from_the_live_map`
  (reverting the engine to poller-only turns it red), plus in `test_socketwatch.py`
  `::test_pid_for_takes_no_lock_because_the_capture_thread_calls_it` (restoring the lock turns it
  red) and `::test_reconcile_publishes_a_new_map_instead_of_mutating_in_place` (mutating in place
  turns it red).
- `test_socketwatch.py::test_a_lock_free_reader_survives_writes_in_flight` RUNS the safety claim
  instead of asserting it in prose: a reader hammering `pid_for` while another thread inserts,
  deletes and republishes the whole map never raised and only ever saw the real pid.
- The engine test drives a GATED divert, so it asserts that the live map is consulted rather than
  that the capture thread happened to lose a race with the watcher thread.
- `test_hot_path.py` (packet threads must never reach the OS) was run explicitly and stays green:
  both lookups are dict reads.

### Changed: SocketEvent carries only what the map is for (closes socket-event-fields)

The SOCKET-layer event used to carry `proto`, `remote_ip`, `remote_port` and `outbound` "for the
connection log later". Nothing ever read them, and an engineering review found out why that never
became a problem worth solving: for all four, the NETWORK-layer packet the engine already holds is
a strictly better source. The connection log takes `remote_ip` / `remote_port` / `proto` / direction
straight off the packet, and the packet even distinguishes ICMP, which the SOCKET layer does not.
The one thing a packet cannot tell us is the owning pid - which is precisely what is left.

- `socketwatch.py`: `SocketEvent` is now `kind pid local_port`. `_ipv4()` goes with it, so the real
  Windows source no longer decodes an address per event for nobody.
- Dropping `_ipv4()` also removes a live TRAP. It decodes IPv4 only (`addr[0]` read as a 32-bit
  int), so the first person to "just wire up the field we already have" would have shipped garbage
  for IPv6 into a user-visible column, in a tool whose traffic filters all cover v4 AND v6.
- PRESERVED from the deleted `test_ipv4_decodes_high_byte_first`, because the code is gone but the
  knowledge should not be: the 2026-07-22 spike established that WinDivert stores the IPv4 address
  MSB-first in `addr[0]`, and that the naive low-byte-first decode rendered 192.168.1.29 as
  29.1.168.192. If remote addresses are ever wanted again, start there - and extend it to IPv6.
- Helpers updated in `test_socketwatch.py`, `test_socketwatch_wiring.py` and
  `test_targeting_socketwatch.py`. `OPEN_PENDING` is now empty, which is its healthy state.
- Guard fix, found BY this closing: `test_no_stale_pending_markers` now skips `CHANGELOG*.md`. A
  changelog records what HAPPENED and is dated by its nature, so the entry below that announced the
  marker stays true after the marker is gone - flagging it was a false positive, and the first real
  closing walked straight into it. Re-verified by mutation after the fix: a marker naming an
  unlisted stage in an ordinary `.md` still turns the test red, so the scan was narrowed, not
  broken.

### Tests: a mechanical guard for prose with an expiry date (convention 44)

The 2b/2c drift fixed below was not a set of FALSE claims - it was four claims that were true when
written and were supposed to die when a stage landed, with nothing enforcing the expiry.
Convention 5 covers claims that are wrong; `check_notes.py` deliberately does not check prose at
all. So the sentences outlived the code they described by several PRs. This adds the missing
mechanical step, because discipline alone produced four stale sites in a single transition.

- New test: `tests/test_repo_conventions.py::test_no_stale_pending_markers` - scans every `.py`
  and `.md` in the repo for `PENDING(<id>)` markers and checks BOTH directions. A marker whose id
  is not in `OPEN_PENDING` fails (the stage closed, so the prose beside the marker is now a lie),
  and an id in `OPEN_PENDING` that nothing references fails (a leftover entry). Closing a stage is
  therefore ONE deletion from `OPEN_PENDING`, which turns the guard red on every marker still
  pointing at it - so the prose gets corrected in the same commit as the code that outdated it.
- `OPEN_PENDING` (same file) is the single source of open stage ids, and is deliberately NOT a
  roadmap: it is the set of ids that PROSE points at, which is what makes the second check
  meaningful rather than bureaucratic.
- MUTATION-CHECKED both ways instead of asserted (convention 5): a probe file carrying a marker
  for an unlisted stage, and an unreferenced id added to the set, were each confirmed to turn the
  test red with the offending `file:line` in the message. The probe was then removed.
- First real marker: the `SocketEvent` comment in `socketwatch.py`, which was itself a leftover
  ("carried for the connection log later (2c)"). `proto` / `remote_ip` / `remote_port` /
  `outbound` are still unconsumed - the comment now says so plainly and carries
  `PENDING(socket-event-fields)`, so whichever way that decision goes, the guard forces the
  sentence to be revisited rather than quietly kept.
- The guard skips its own file (that file holds the ids rather than pointing at them), and the
  `<id>` placeholder form used in prose does not match the pattern, so docs and changelogs can
  name the token without registering it.
- Rejected, MEASURED not guessed: scanning for the word "yet". 25 hits across `beantester/` and
  `tests/`, of which roughly 21 are permanently true ("width 1 == not laid out yet", "no honest
  answer yet"). A guard with that false-positive rate is switched off within a week.
- Convention 44, a sub-rule under process rule 5, and a new definition-of-done step (grep for the
  id when closing a stage) live in the private notes, which this test cannot see - the notes are
  not in this repo, so that half stays manual on purpose.

### Docs: de-stale the 2b/2c prose - targeting DOES resolve against the live socket map

Prose drift of the kind convention 5 exists for, with a twist: every one of these sentences was
TRUE when written and acquired an expiry date nobody enforced. Chunks 2b/2c/2d landed (PR #38),
so "not wired yet" became a lie sitting next to correct code - and `check_notes.py` deliberately
does not check prose, so nothing went red. Found during an engineering review; no behaviour
change, comments and docstrings only.

- `engine.py`: the `_socketwatch` attribute comment ("NOT read by targeting yet - that is 2c")
  and the `_start_socketwatch` docstring ("targeting does not read it yet") now point at
  `_targeting_table()` / `_start_locked`, which is where the poller-vs-watcher choice is actually
  made.
- `socketwatch.py`: the module docstring no longer claims the module is "in isolation... NOT
  wired into the engine or targeting yet (2b/2c)"; the lifecycle section header drops "in 2b".
- `tests/test_socketwatch_wiring.py`: the docstring kept the part that is still true (this file
  covers the plumbing only) and lost the false framing; it now names
  `tests/test_targeting_socketwatch.py` as the guard for the resolution contract.
- Deliberately NOT touched: the `SocketEvent` comment saying `remote_ip`/`remote_port` are
  "carried for the connection log later (2c)". Those fields are still unconsumed, and whether
  they get used or cut is a separate decision - fixing the sentence now would only mean writing
  prose that decision will rewrite.
- Follow-up on its own branch: a mechanical guard for expiring prose (`PENDING(<id>)` markers
  checked against one list of open stage ids), because discipline alone produced four stale
  sites in a single transition.

### Docs: correct the resolver recycle-check cost - it is elevation-bound, not "~180 ms"

Measured 2026-07-24 with Chrome open, elevated AND non-elevated (`runas /trustlevel:0x20000`),
because the deferred "~180 ms per rebuild" perf follow-up from the socket-layer work did not
reproduce elevated. It is real prose drift (convention 5): two docstrings disagreed - `_psutil_created`
claimed 0.005 ms, `info` claimed ~5 ms - and both were right for a different elevation.

- `create_time()` is ~0.005 ms per PID when `OpenProcess` succeeds and ~5.7 ms when it is DENIED
  (psutil then scans the whole system for that one PID). Denial is an ELEVATION question, not the
  "hardened process / Chrome renderer" one the older note assumed - renderers do not own sockets,
  so they never reach this loop. ELEVATED: 0 of 27 socket-owning PIDs denied, warm recycle check
  ~0.16 ms, cold `resolve('chrome')` ~36 ms. NON-ELEVATED: 16 of 27 denied, ~90-180 ms warm,
  ~381 ms cold - which is where the handoff's ~365/180 ms came from.
- Real impairment ALWAYS runs elevated (WinDivert will not open without admin; a non-admin START
  fails), so the check is cheap in every real session. The only non-elevated path that runs the
  resolver at all is `--simulate` (synthetic packets; the cost is on the resolver thread, never
  the capture one).
- DECISION, rejected: batching the denied PIDs in one `NtQuerySystemInformation`. It speeds only
  the non-elevated `--simulate` warm check, does nothing for the elevated hot path, and nothing
  for the cold resolve (name resolution dominates that, not create_time). Not worth the ctypes
  surface for a demo mode. This closes the "known perf follow-up" / "handed to a follow-up" notes
  in the entries below.
- Corrected in `portmap.py` (`_psutil_created` and `PortTable.info` docstrings) and PROJECT_NOTES.
  No code behaviour changed - nothing a user notices - so CHANGELOG.md is untouched.

### Fixed: the UI rebuild no longer piles up `<Configure>` handlers on the root

Follow-up to the teardown-crash fix. `App._build_ui` runs on every language switch, and the root
window outlives it, so binding `<Configure>` on the root inside `_build_ui` (with `add="+"`, nothing
removing it) accumulated one handler per rebuild. Measured on the fake tkinter: 2 after the first
build, 8 after three switches, linear. Each is cheap - and after the teardown fix the dead ones are
no-ops, not crash records - but it is O(rebuilds) work on every resize for the life of the process.

- The earlier "not fixed here" note named only `_on_root_configure` and undercounted (convention 5):
  the two banners built with `wrapping_label(root, ...)` (`engine_warning` always, `admin_warning`
  when non-admin) each bound their OWN `<Configure>` on the same persistent root and multiplied
  identically - half the handlers. A `wrapping_label` on a SHORT-LIVED container does not leak (its
  binding dies with the container); only the two whose container is the root do.
- `_on_root_configure` is now bound ONCE in `__init__`, before the first `_build_ui`, and the line is
  gone from `_build_ui`. It reaches its widgets through `self`, so a single binding always drives the
  freshly rebuilt ones - no unbind needed, and none was safe (`Misc.unbind(seq, funcid)` still clears
  the whole sequence on the oldest Python in the CI matrix, and the root carries other `<Configure>`
  bindings).
- The two banners are now plain `ttk.Label`s wrapped by that same single handler, not `wrapping_label`.
  Same look (left/anchored, an initial `wraplength` refined on the first resize). `gui/labels.py` and
  its short-lived-container callers are untouched; `wrapping_label` is no longer imported by
  `gui/app.py`.
- Not user-visible (identical look and wrapping, no behaviour change), so CHANGELOG.md is deliberately
  left alone - a user-facing line for an imperceptible change would be the filler convention 4 forbids.
- New test: `tests/test_gui_release_fixes.py::test_the_ui_rebuild_does_not_pile_up_configure_handlers_on_the_root` -
  asserts exactly one `<Configure>` handler on the root after several rebuilds, and that the banner
  still wraps to the width-derived value (not just its build-time default, which would pass even with
  the fold gone). Both halves verified by MUTATION: reintroducing the per-rebuild bind, and dropping
  the banner wrap, each turns it red.

### Fixed: two swallowed GUI teardown crashes, and the window geometry they were losing

From a field `crashes.ndjson`: two `swallowed`/`debug` records, `TclError: bad window path name
".!toplevel2"` at `gui/windows.py::_save_geometry` and `TclError: invalid command name ".!label"`
at `gui/labels.py::_resize`. They share one cause: `App._build_ui` rebuilds the main UI by
destroying every child of the root window, and a `Toplevel` is a child of the root.

- `App._build_ui` now skips the Toplevels the registry owns (new `WindowManager.toplevels()`). It
  used to tear the open panel windows down behind the registry's back, so the `windows.rebuild()`
  that follows a language switch ran `close()` on windows that no longer existed. That cost two
  things, not one: the TclError above, and the geometry was never saved - the window reopened where
  it had last been CLOSED, not where the user had just put it.
- `PanelWindow._save_geometry` returns early when the window is already gone (`winfo_exists`).
  Nothing in the app should destroy a registry window behind its back now, but the root still takes
  every Toplevel with it when the app quits.
- `bind_wraplength._resize` returns early when the label is gone. The `<Configure>` binding lives on
  the CONTAINER, which routinely outlives the label: the two banners built with
  `wrapping_label(root, ...)` in `gui/app.py` hang off the root window itself, and every rebuild
  destroys them and leaves their handler behind. Nothing unbinds it (it is added with `add="+"`, and
  `Misc.unbind(seq, funcid)` still clears the WHOLE sequence on the oldest Python in the CI matrix -
  verified only that 3.14 removes just the one binding). So this was never a one-off teardown race:
  it is one dead handler per rebuild, each recording an entry on every resize from then on.
- `on_close` already closed the windows before persisting the UI state, so their geometry survives a
  quit. That ORDER had no test; it has one now.
- `tests/fake_tk.py` made honest about destruction, or none of this could be caught: `destroy()` now
  destroys children and leaves the widget DEAD, `winfo_exists()` is real, and `configure()` /
  `geometry()` raise `TclError` afterwards, the way Tk does. `winfo_exists` HAD to be added rather
  than inherited: `W.__getattr__` answers any unknown attribute with a no-op returning `None`, so a
  `winfo_exists()` guard would have read as "destroyed" for every widget on the fake and silently
  switched off the code it guards in every GUI test.
- New tests: `tests/test_windows.py::test_a_language_switch_keeps_the_window_alive_and_saves_its_geometry`,
  `tests/test_windows.py::test_closing_a_window_that_is_already_gone_is_not_a_crash`,
  `tests/test_windows.py::test_closing_the_app_saves_an_open_window_before_the_root_goes`,
  `tests/test_gui_release_fixes.py::test_a_resize_after_the_label_is_gone_is_not_a_crash`. All four
  verified by MUTATION (convention 5): each guard was removed in turn and the test that claims to
  catch it went red. The `on_close` mutation is what showed the fourth test was originally guarding
  a duplicate call added in this chunk rather than the real one; the duplicate was removed.
- Left for a follow-up (now DONE, see the entry above): `App._build_ui` also re-bound `<Configure>`
  on the root every rebuild, so that handler multiplied too - as did the banners, which this note
  missed.

### Fixed: the connections "impaired?" column and its row highlight now use ONE signal

- Field report: rows showed orange with the column reading "no" (and "yes" rows with no colour) -
  "something is wrong with the connections table". Cause: the column read the stored per-flow
  `scoped` record (chunk 1) while `ConnsPage._tag_of` still asked the engine LIVE (`in_scope_now`
  -> `local_port in target_ports`). For a closed or idle flow those answer differently - the live
  check flips to False the instant the socket closes - so the colour and the column disagreed.
  `_tag_of` now reads the SAME stored `c["scoped"]`; column, highlight, sort (`views.py`) and CSV
  (`gui/app.py`) are one signal and can never diverge. `ConnsPage._in_scope` removed;
  `engine.in_scope_now` / `core.in_scope` are now unused (flagged for a follow-up removal).
- Updated `tests/test_conns_columns.py`: a flow with `scoped=True` whose port is OUT of the
  current target is now both "yes" AND highlighted (it used to be "yes" with an empty tag).
- Not fixed here (separate, measured, handed to a follow-up): a target LAUNCHED after START has
  its first connections logged before the resolver matches it (the resolve costs ~180 ms, the
  create_time recycle check - see PortTable.info), so they read a truthful "no". Shrinking that
  window means speeding up the resolve, which touches the recycle logic; deliberately deferred.

### Fixed: SocketWatcher STOP crash + slow, unreliable target-by-name (native toolhelp snapshot)

Follow-up to the chunk 2 rollout, from a field crash log + two reports: a "first target-start takes
seconds" pause AND targeting `chrome` BY NAME resolving to nothing (`BRAK pasującego procesu`) while
targeting its PID worked. Both trace to one slow, fragile path: process-name resolution.

- **SocketWatcher stop recorded a spurious crash.** `_loop` caught the `WinError 995` that `stop()`
  induces - closing the SOCKET handle unblocks the parked `recv()` with "I/O aborted" - and wrote it
  to crashes/ via `crashlog.once`, so every STOP left a `socketwatch.loop` entry. Now guarded by
  `if not self._stopping.is_set()`, exactly like the capture loop's `if self._running`; a real
  socket-stream failure while running is still recorded. Test:
  `test_socketwatch.py::test_stop_does_not_record_the_close_induced_error_as_a_crash`.
- **Root cause of both other symptoms: the process-name bulk fallback was `psutil.process_iter`
  (measured ~2.6-2.9 s).** When `psutil.Process(pid)` cannot open a HARDENED process (Chrome's
  network service and renderers refuse OpenProcess; the individual lookup also fetches ppid +
  create_time, any of which can fail), `portmap.info` falls back to that scan. That is why (a) the
  first synchronous start/apply resolve blocked for ~2 s, and (b) targeting BY NAME missed Chrome -
  no openable name, no match - while BY PID worked (a PID match needs no name). New
  `portmap._toolhelp_process_table()` reads every process's name+ppid via `CreateToolhelp32Snapshot`
  WITHOUT opening any of them: **measured ~6 ms for 350 procs, and it names hardened processes.**
  `_process_table()` prefers it (psutil fallback off Windows / in tests). Cold
  `ProcessTargeting.refresh('chrome')` 2148 ms -> ~365 ms, and it now matches Chrome by name. This
  also relieves the yes/no flicker: the resolver's periodic refreshes hit the same slow scan, so
  targeting was effectively stale/empty for ~2 s and connections in that window slipped to "no".
- The earlier `allow_bulk=False` attempt (previous commit) was REVERTED: it made the resolve fast by
  SKIPPING the bulk, which is exactly what broke target-by-name for Chrome (skipping the only path
  that can name a hardened process). Making the bulk fast is the correct fix; there is no `allow_bulk`
  flag any more.
- Docstring corrected (convention 5): `PortTable.info` claimed `create_time()` = 0.005 ms and
  0.13 ms per rebuild; measured ~5 ms/PID (~180 ms/rebuild with a browser open), because it opens a
  handle. The per-refresh recycle-verification cost is now stated honestly and flagged as a perf
  follow-up (batch the create times, or verify by a cached snapshot) - it runs on the resolver
  thread, not the capture one.
- Tests: `test_processes.py`'s fake psutil now provides `Process` (individual resolution) to match
  real psutil, and both `fake_psutil` + `_World` disable `_ALLOW_NATIVE_PROCESSES` so the bulk
  fallback reads their fake table, not the real machine's toolhelp snapshot.

### Added: socketwatch.py - live local_port->pid map from WinDivert SOCKET events (chunk 2a)

- New module `beantester/socketwatch.py` (`SocketWatcher`): the event-driven replacement for
  polling the socket table. WinDivert 2.2 SOCKET layer (sniff-only, `SNIFF|RECV_ONLY`) delivers
  BIND/CONNECT/ACCEPT/LISTEN/CLOSE with the owning ProcessId; the map adds on the first four and
  removes on CLOSE, pid-checked so a late CLOSE cannot evict a port the OS has recycled to a
  different process. `reconcile()` seeds from a `portmap` snapshot and prunes a port absent for
  TWO passes (grace against evicting a socket opened microseconds before the snapshot was taken).
  Names/ancestors delegate to `portmap` (no duplication); the event source is injected, so the map
  is unit-tested without WinDivert.
- Why SOCKET, not FLOW (measured spike 2026-07-22, elevated, sniff-only): SOCKET_CONNECT arrives
  ~0.1 ms BEFORE the outbound SYN reaches the NETWORK layer (closes the race); FLOW_ESTABLISHED
  arrives ~28 ms AFTER (post-handshake, the SYN already slipped). Two sniff handles (NETWORK+SOCKET)
  were confirmed to coexist. The real `_WinDivertSocketSource` was smoke-verified end to end: a
  known outbound connection's local port mapped to `os.getpid()` and was removed on close.
- Scope: chunk 2a is the module in ISOLATION. It is NOT wired into `BeanEngine` or
  `ProcessTargeting` yet (2b wires the lifecycle + bootstrap + fallback; 2c makes targeting read
  the live map). The polling path (`portmap` / `target_resolver`) is untouched and stays as the
  fallback for `--simulate` / tests / non-Windows.
- New tests: `tests/test_socketwatch.py` - map add/remove, pid-checked recycled-port removal, junk
  rejection, the reconcile two-pass grace (both prune and reappear-resets-grace), name delegation,
  the refresh no-op, the reader thread on an injected fake source, and the MSB-first IPv4 decode
  the spike corrected.
- `import beantester` still does not import pydivert: the real source constructs it lazily inside
  `start()`, so the package import and every unit test stay WinDivert-free.

### Changed: BeanEngine drives the SocketWatcher lifecycle (chunk 2b)

- `BeanEngine` now creates and starts a `SocketWatcher` in `_start_locked` and stops it in
  `_stop_locked`, next to the `TargetResolver` (both hold OS handles; both are session-length). A
  new `start(..., socket_source=None)` parameter injects the event source for tests. Bootstrap:
  start reconciles the watcher from a forced `portmap` snapshot, so connections open BEFORE the
  session are known from the first packet; the watchdog folds a fresh snapshot in each tick as the
  safety net (a missed CLOSE ages out, a dropped event is recovered).
- Started ONLY on the real-WinDivert path (`divert is None`) or with an injected source; on the
  synthetic/simulate/test path `self._socketwatch` stays None and the poller stands - the
  testable-without-WinDivert contract is intact. `_start_socketwatch` DEGRADES to the poller if the
  SOCKET handle cannot open (recorded via `crashlog.once`) rather than failing the session
  (convention 20 spirit: a second-handle failure must not take the user's network down).
- NO behaviour change yet: targeting still reads the polling table; the watcher is kept live but
  unused until 2c. Verified end to end by a real-path smoke (elevated, narrow pass-through filter):
  the engine opened the NETWORK impairing handle AND the SOCKET watcher together - retiring the
  coexistence risk flagged in the 2a design - and a known connection's local port mapped to
  `os.getpid()` in the watcher, cleared on stop.
- New tests: `tests/test_socketwatch_wiring.py` - bootstrap+run on an injected source, no watcher
  on the synthetic path, degrade-not-kill on a source that fails to open, and no watcher thread
  left after stop. Driven on an idle `FakeDivert` (the session stays up) with a fake port table.

### Changed: process targeting resolves against the live socket map (chunk 2c)

- `ProcessTargeting` gained `set_table()`, and the engine now points it at the `SocketWatcher`'s
  live map when a session has one (`_targeting_table()` returns the watcher, else `portmap`),
  rebinding in `_start_locked` (targeting is often built before start, against the poller).
  `_start_locked` was reordered so the watcher is created BEFORE the initial synchronous resolve -
  the very first resolve already reads the live map.
- Effect (the point of chunk 2): a connection of the targeted process is in impairment scope the
  instant its SOCKET_CONNECT event arrives, not at the next poll - and since SOCKET_CONNECT precedes
  the SYN, before its first packet. Verified end to end on real WinDivert (elevated, narrow
  pass-through filter): targeting bound to the watcher, and a fresh outbound connection read
  `in_scope` in ~0 ms. The polling path stays as the fallback, unchanged, so short-lived
  connections only still escape when there is no real WinDivert.
- Only the LIVE path changed: `engine.target_for` now builds against `_targeting_table()`. The
  one-shot reporting helpers (`processes.find_process_ports` -> `resolve_ports`, `make_targeting`)
  keep resolving against `portmap` - they are display snapshots, not session targeting.
- Prose corrected (rules 5/6): the `targeting.py` docstring claimed the race "cannot be closed,
  only made small" - true for the poller, false for the watcher. It now names which table closes
  it. PROJECT_NOTES targeting bullet + the targeting ADR moved from "Chunk 2 (planned)" to done.
- New tests: `tests/test_targeting_socketwatch.py` - the set_table swap, an end-to-end resolve of a
  CONNECT event through a watcher + resolver (no poll), and the engine binding targeting to the
  watcher (present) vs the poller (synthetic path).

### Fixed: the connections "impaired?" column is a session record, not a live port lookup

- **Symptom (reported from the field, Chrome):** targeting `chrome.exe` showed a connections
  table where the large majority of rows read "no" in the impaired? column, so the tool looked
  like it was missing most of the traffic. It was not - the column was misreporting FINISHED
  connections.
- **Cause:** `gui/pages/conns.py::_render` computed the column LIVE via
  `engine.in_scope_now` -> `BeanCore.in_scope` -> `local_port in target_ports`. A closed or idle
  flow's ephemeral port has left the socket table, so the live test returns False for every
  connection that is no longer open - which is most of them on a browser. Meanwhile the stored
  per-flow `scoped` flag (`engine._log_conn`) tracked only the LATEST packet, and both the CSV
  export (`gui/app.py`) and the column's sort key (`views.py::_SORT["scoped"]`) already read
  that stored flag - so the on-screen cell, its sort order and the CSV disagreed (two semantics,
  three call sites).
- **Fix:** `engine._log_conn` now keeps `scoped` STICKY per flow
  (`c["scoped"] = c["scoped"] or bool(scoped)`) - a session-long "was ever in impairment scope"
  record - and `conns.py::_render` reads that stored flag instead of the live lookup. Cell, sort
  key and CSV now all read the one stored flag. The LIVE "in scope now" signal is unchanged: it
  is the row HIGHLIGHT (`_tag_of`, still via `in_scope`), so a chrome->firefox narrowing drops
  the highlight without erasing the record.
- **Reversed decision (recorded so it is not re-reversed):** the column was deliberately made
  live once, to stop an idle flow keeping a stale "yes" after the target was narrowed. That
  concern is now carried by the HIGHLIGHT (live), while the COLUMN is the audit trail (sticky) -
  the two signals were conflated into one before.
- New test: `tests/test_engine.py::test_scoped_is_a_sticky_session_record` - three packets on one
  flow (in scope, then twice out) keep the flag True, and a never-scoped flow stays False, driven
  straight through `_log_conn` (no thread timing).
- Updated test: `tests/test_conns_columns.py::test_connection_columns_tag_and_footer` - the
  out-of-current-target `svchost` row now asserts column "yes" (stored record) with NO highlight
  tag (live), locking the two-signal split. `tests/test_conns_export.py` and
  `tests/test_engine.py::test_connection_records_scope_and_dropped` were already consistent with
  the stored flag and pass unchanged.
- i18n: `tips.col_scoped` reworded in `lang/en.json` + `lang/pl.json` (values only; key set and
  sort order unchanged, so `test_i18n.py` parity holds).
- Scope: this is the display/coherence half (Chunk 1). The underlying port->PID resolution is
  still a periodic socket-table snapshot, so short-lived connections that open and close inside a
  refresh window can still escape impairment (`tests/test_target_resolver.py` documents the race);
  closing that at the source with the WinDivert FLOW/SOCKET layer is tracked separately.

### Tests: property-based coverage for the two packet-mutating functions (F6)

Engineering-review finding F6: the property suites covered matchers and `decide()`, but the
only two functions that reach into packet BYTES - `BeanCore.corrupt_packet` (flips a payload
bit, on the capture thread) and `BeanCore.build_rst_fields` (forges the RST injected onto the
user's live connection) - had example tests only. New file
`tests/test_packet_mutation_properties.py` (Hypothesis, 7 properties):

- **corrupt_packet:** flips EXACTLY one bit and preserves length; is deterministic for a seed
  (reproducibility contract); touches no header field; an empty payload -> False untouched; and
  is TOTAL - a packet whose payload cannot even be read comes back False, never an exception
  (it runs on the capture thread, convention 20).
- **build_rst_fields:** the endpoint/seq logic restated as ONE invariant across both directions
  - the forged RST is always sent from the remote peer TO the local socket, marked inbound, with
  the sequence the local end expects next; a non-TCP packet yields `None`.
- Mutation-checked (all three substantive properties bite): an 8-bit flip fails the one-bit
  property, dropping the src/dst swap fails the endpoint invariant, and narrowing the `except`
  lets the hostile-packet case raise. No production code changed.

### Tests: cover the driver STOP+DELETE path and the in-app dialogs (F5)

Engineering-review finding F5: the two lowest-covered spots were both error/teardown
code that only ever runs on a user's machine. No production code changed.

- **`driver.stop_and_remove` was 0%** - it STOPS and DELETES a Windows service and runs on
  the way out of every real-capture session (`release_on_exit`), so it must not be exercised
  for the first time in the field. It is pure Service-Manager glue, so `tests/test_driver_windows.py`
  now drives every branch through a fake advapi (`_FakeAdvapi` + a real `ctypes.Structure` so
  `byref` has a target, `is_windows` forced True so it runs identically on the Linux CI): stop+
  delete, a delete that will not take, no SCM handle, access-denied vs not-installed vs an
  unexpected error, and the off-Windows no-op. Plus four `cleanup_driver` orchestration cases
  (per-service loop, stale `_MEI*` temp dirs, the admin gate, nothing installed). driver.py
  75% -> 88%; the stop_and_remove block (was fully uncovered) is now exercised. Mutation-checked:
  forcing the delete to read as failed turns the success test red.
- **`gui/dialogs.py` was 16%** - the dark in-app modals. New `tests/test_dialogs.py` drives them
  on the fake tkinter (where `wait_window` is a no-op, so each modal builds and returns its
  dismissal default) and exercises `_close` directly. 16% -> 85%; the remaining lines are the
  `crashlog.note` except-branches that only fire when a real Tk call raises, which the fake
  cannot provoke.

### Fixed: STOP no longer blocks for 2 s when it races the duration deadline (F2)

Engineering-review finding F2, measured before and after: a user STOP colliding with the
session deadline took **2091 ms**; it is now **~160 ms** (40-trial worst case).

- **The deadlock:** `stop()` holds `_stop_lock` and joins the worker threads with a 2.0 s
  timeout. When the watchdog fired the duration deadline at the same instant, its
  `stop(reason="duration")` blocked waiting for that same lock while the user's `stop()` was
  blocked waiting to join the watchdog - a lock-ordering inversion broken only by the join
  timeout. The capture thread's `_fail_stop` -> `stop()` had the same shape.
- **The fix:** `stop()` is split into `stop()` (external callers - GUI/CLI/atexit/tests -
  which BLOCK on `_stop_lock`, preserving start/stop serialisation), `_worker_stop()` (worker
  threads, which take the lock NON-blocking and bow out under contention), and the shared
  `_stop_locked()` body. The watchdog's deadline and liveness stops go through `_worker_stop`;
  `_deadline` is now cleared at the TOP of the stop body so a watchdog finishing a slow op sees
  nothing to fire.
- **Subtlety that cost a round:** `_fail_stop` is called by BOTH the capture thread and the
  watchdog. Routing both through `_worker_stop` regressed `test_a_dead_capture_thread_fails_open`
  - a divert that faults on its first reads does so while `start()` still holds `_stop_lock`, so
  the capture thread's non-blocking stop no-opped and the watchdog stopped it a tick later with a
  generic "died unexpectedly" instead of the real "driver went away". So `_fail_stop` grew a
  `blocking` flag: the capture thread blocks (safe - an external STOP closes the divert first, so
  the capture loop sees `_running` False and never reaches `_fail_stop`), only the watchdog's
  liveness path is non-blocking.
- New test `tests/test_failsafe.py::test_a_worker_stop_never_blocks_on_a_held_stop_lock` - holds
  `_stop_lock` and asserts `_worker_stop` returns anyway (structural, not wall-clock, so it cannot
  flake). Mutation-checked: making `_worker_stop` blocking turns it red.

### Fixed: BeanEngine.start() is now atomic - a partial start fails OPEN (convention 20)

Engineering-review finding F1, confirmed by experiment before the fix (forced `Thread.start()`
to raise after N workers and inspected the engine state), not by reading.

- **The hole:** `_start_locked` set `self._running = True` and opened the divert BEFORE spawning
  the resolver + capture/inject/watchdog threads, and called `_LIVE_ENGINES.add(self)` only AFTER
  all three were up. A failing `Thread.start()` (thread/memory exhaustion - most likely under the
  load this tool is aimed at) therefore left a "running" engine with an OPEN divert, no capture
  thread draining it, and **invisible to the `atexit` hook** - WinDivert queueing the user's
  packets into a void while the UI said "running". Worse, `_running` stayed True, so every later
  `start()` hit the `RuntimeError("already running")` guard: START was wedged for the process
  lifetime. GUI `_finish_start(err)` only shows a dialog and resets the button; it never calls
  `stop()`.
- **The fix:** `_LIVE_ENGINES.add(self)` moved to BEFORE the worker-spawn block (the moment the
  divert is open + `_running` is the moment atexit must be able to find it), and the spawn block
  wrapped in `try/except BaseException` that logs the fault, calls `self.stop(reason="fault")`
  (closes the divert, stops/joins whatever DID start, clears `_running`, discards from
  `_LIVE_ENGINES`) and re-raises. `_stop_lock` is an `RLock`, so the nested `stop()` from inside
  `start()` re-enters cleanly.
- New test: `tests/test_failsafe.py::test_a_failed_start_never_leaves_an_open_divert` - monkeypatches
  `threading.Thread.start` to fail after the resolver thread, then asserts: the error propagates,
  the engine is not left running, the divert is closed, it is gone from `_LIVE_ENGINES`, and a
  later `start()` succeeds (no longer wedged).

### Fixed: corrupt_packet() records its failures (F3); a core-scoped guard so it cannot swallow again (F4)

Engineering-review findings F3 + F4.

- **F3:** `BeanCore.corrupt_packet`'s `except Exception: return False` swallowed a REAL
  failure (a raising `packet.payload` setter, a foreign packet type) in a way
  indistinguishable from its legitimate empty-payload `return False`. A broken corruptor
  therefore read as `corrupted == 0` - "the traffic had no payloads" - and the tester
  would blame their traffic, not the tool. It now calls `crashlog.once("core.corrupt",
  exc)` before returning False. `crashlog` is imported LAZILY inside the handler, so
  core.py still imports only utils/matchers at load (layering contract) and stays free of
  logging/print in the hot path; `once()` caps the cost at one traceback. Verified by
  experiment: a raising setter now lands one `core.corrupt` record and returns False,
  while the empty-payload path stays a quiet False (no crash-log spam).
- **F4:** `test_no_silently_swallowed_exceptions` only recognises a `pass`/`...` body, so
  the `return False` swallow above passed it for as long as it existed. New guard
  `tests/test_code_hygiene.py::test_the_decision_core_never_swallows_an_exception_silently`
  asserts the stronger property for core.py ALONE: every broad `except` must reach
  `crashlog` (quiet/once/note/record) or re-raise. Scoped to the decision core on purpose
  - the wider package's 50-odd broad handlers are legitimate control-flow fallbacks
  (parse -> None, `matches()` -> False by hot-path contract, a DPI probe -> default), so
  holding them to this rule would fire on correct code. Mutation-checked: reverting F3
  turns the new guard red on `core.py:626`.

### Fixed: gitignore coverage artefacts (F7), drop stale numbers from the CI comment (F8)

Engineering-review findings F7 + F8. Neither ships; both are the "prose nothing guards"
class convention 5 warns about.

- **F7:** `.gitignore` matched only the bare `.coverage`, but `[tool.coverage.run]
  parallel = true` (pyproject) GUARANTEES per-process `.coverage.<host>.<pid>.<rand>`
  files, and the CI coverage step writes `coverage.xml`. Both appear as untracked after a
  coverage run, and `git add -A` would have committed them (against convention 3). Added
  `.coverage.*` and `coverage.xml`. Verified with `git check-ignore`.
- **F8:** the comment on the coverage step claimed "the same suite reads 51% instead of
  77%". 77 was the PREVIOUS gate value (it has since moved 75 -> 77 -> 80), and the real
  measured split lives in pyproject (45% vs 83.03% when measured). The comment no longer
  restates any number - it points at pyproject, the single source, so it cannot drift again.

### PROJECT_NOTES audit, part 2: measured numbers, and the coverage gate to 80

Every "costs N ms" in the audit's blast radius was re-measured instead of trusted. Conditions
are now attached to each figure (Win11 AMD64, CPython 3.14.6, median of 7), because a number
without conditions cannot be re-verified and the next session cannot tell drift from hardware.

- **`engine.connections_snapshot(limit=None)` was documented at ~25 ms "at the cap"; it is
  0.7 ms** (2.4 ms at 500k). `conns.py` repeated the same claim as "~70 ms for a 500 000-row
  copy" - wrong by ~30x under every interpretation (`list(values())` 2.3 ms, `dict()` 6.4 ms,
  per-row copy 222 ms at 500k). Left as an argument for moving the snapshot back onto the UI
  thread, which would have been a real regression.
- The decision survives for a **different and verified** reason, now written down instead:
  `connections_snapshot()` acquires the engine's `_clock`, the same lock the capture thread
  takes on every logged packet, so taking it on the UI thread makes the UI queue behind the
  capture thread. Cheap to copy, still wrong to copy there.
- **`views.filter_sort_connections` kept its heap-vs-sort ratio test** - re-measurement confirms
  the crossover (top 400: 12.6 ms heap vs 27.7 ms sort; top 50 000: 130.6 ms heap vs 28.0 ms
  sort). Only the absolute figures were dated. The docstring now carries a table plus a warning
  that first bit this audit: benchmark it with keys from a tiny range and Timsort exploits the
  runs, making the sort column look artificially fast and the optimisation look pointless.
- **Coverage gate raised 77 -> 80.** Measured with `COVERAGE_PROCESS_START`: **83.03%**
  (83.07% on re-run), so the gate keeps its ~3-point margin for subprocess-coverage variance.
  Also measured the counterfactual the comment asserted without evidence: **without** the env
  var the same suite reports **45%**, not the 51% claimed. Both numbers, and their conditions,
  now live in `pyproject.toml` only.
- Notes-side fixes with no code change: the connection table's "max 400 rows" (stated twice)
  is a limit removed when the tables were virtualised - `row_limit` defaults to 50 000, ranges
  0-1 000 000 and 0 means no limit; the scroll cost now has one source (`sortable_tree.py`)
  instead of two that disagreed (0.8 ms vs ~1 ms).

### PROJECT_NOTES audit, part 3: a mechanical guard for the note itself

`PROJECT_NOTES.md` is git-ignored (private Doc repo), so a pytest test would be skipped in CI
forever and would name a private file inside the public suite. The guard is therefore a Stop
hook, `.claude/hooks/check_notes.py`, next to the existing `check_changelog.py`; it exits
silently when the file is absent. Neither the hook nor the note is part of this repository -
this entry is the public record that they exist.

It refuses to end a turn when the note drifts in a way a machine can see: a named `tests/*.py`
that does not exist, a named `file.py::test_name` that does not exist, a package module the
note never mentions (the rule `test_readme_guards.py` already applies to the READMEs, which is
exactly why the README tree stayed right while the note's lost `crashlog.py`, `gui/labels.py`
and `gui/rates.py`), and a registered window the note never mentions (`event_log` - the window
whose docstring says "COPY THIS FILE to make a new one" - was undocumented, so the note pointed
newcomers at a worse template). All four checks verified by mutation: green on the real note,
red on each injected drift. It deliberately does not try to check prose.

### PROJECT_NOTES audit, part 1: prose that would have made the next session write a bug

A full claim-by-claim audit of `PROJECT_NOTES.md` against the code. Convention 5 ("every
`because` is a claim - check it or do not write it") applied to the note itself. This part
covers the findings that actively mis-instruct; numbers, stale lists and undocumented
mechanisms follow in their own commits.

- **Convention 16 was backwards about labels.** It told the next session to set
  `state="disabled"` on field labels. The code deliberately does the opposite: a
  state-disabled `ttk.Label` paints a FILLED BOX, so `ControlForm._apply_toggle_state` and
  `apply_overrides` swap the style to `CardOff.TLabel` instead, and
  `test_an_overridden_field_is_visibly_disabled` even asserts `state is None` on the label.
  The convention also cited `test_gui_layout.py::test_disabled_fields_are_visibly_disabled`
  as its guard - **that test has never existed**. Rewritten to separate the field rule
  (state + a `disabled` map) from the label rule (style swap, never state).
- **The same stale claim lived in `theme.py`**, five lines below the correct one: the comment
  above the label `disabled` maps said field labels "are set to state=disabled together with
  their entries". Nothing in the GUI sets `state` on a label. Comment corrected to say what
  the maps actually are: defensive, and free.
- Measured, so the note can stop guessing: removing the `disabled` foreground maps for EVERY
  label style leaves the whole suite AND `smoke_gui.py` green. The convention now says it has
  no guard instead of naming one.
- **Convention 40's guard covered half of what it claimed.**
  `test_shortcut_buttons_advertise_their_key` asserted on `btn_start` and `btn_apply` only, so
  dropping `shortcut="Ctrl+S"` from the Save button kept the suite green - verified by
  mutation. The test now drives a table of all four shortcut buttons and fails naming the
  offender; re-run against the same mutation it goes red. "Save file" / "Load file" moved from
  local variables to `App.btn_save` / `App.btn_load` so the guard can reach them.
- **Convention 42 described a replaced implementation:** `icon.make_gear_icon` is an
  anti-aliased RGBA PNG built with stdlib `zlib`/`struct`, not "plain `PhotoImage.put`". The
  per-pixel `put` version had no alpha and rasterised jagged teeth; it survives only as a
  fallback for a Tk build that cannot read PNG.

### The hot-path guard now covers the route Linux takes, on every machine

`test_hot_path.py` shipped with an explicit "NOT verified" note: `PortTable` reads the socket table
through `iphlpapi` when `_make_native()` succeeds and through `psutil.net_connections` when it does
not, and on Windows the first always wins. So `_psutil_port_pid_map` was watched by the guard and
had never once fired locally - the Linux behaviour was covered only by the ubuntu leg of CI, and
only by accident of which platform happened to run.

`_make_native` returning `None` IS what a non-Windows platform does, so substituting it exercises
that route anywhere. New `test_the_psutil_socket_table_path_is_just_as_clean` does exactly that.
Measured with the substitution in place, against the same session (traffic, targeting that matches
nothing, five seconds):

| | native path | forced fallback |
|---|---|---|
| `_Native._table` | 36 calls | **0** |
| `_psutil_port_pid_map` | **0** | 12 calls |
| from a packet thread | nothing | **nothing** |

The test asserts its own conclusiveness before asserting the invariant - the table really took the
psutil route (`table.native is False`), the fallback lookup really ran, and no native call leaked
through - so a substitution that silently did nothing fails instead of passing quietly.

Verified by mutation, and this is the part that makes it more than a duplicate: reopening
`_process_for`'s refresh (`allow_refresh=True`) makes it fail naming the OTHER function -
`[('_psutil_port_pid_map', 'Thread-1 (_capture_loop)')]` - where the Windows test names
`_Native._table`. Same regression, second route, and now it is caught on both without waiting for
a particular runner.

The module docstring's "NOT verified" paragraph is replaced rather than left to rot; it now says
what was measured.

### One stray lang/*.json stopped the program from starting (audit item #10, the edges)

`lang/*.json` is the one on-disk format with its own `json.load`, outside `jsonfile`, and it was
left out of the first #10 pass as a shipped file rather than a user file. It is not only shipped:
translations are meant to be added, and `load_languages` promises in its docstring that "a broken
or unreadable file is skipped so it can never break app startup".

`meta = data.pop("_meta", None) or {}` rescued a FALSY `_meta` - `null`, `0`, `""` - and nothing
else. A non-empty one of the wrong type (`"_meta": "en"`, a list, a number, `true`) sailed past
`or {}` and died on `meta.get()`, which sits OUTSIDE the per-file `try`. The AttributeError escaped
`load_languages`, which runs at startup. Measured with one such file dropped into the real `lang/`:
**`python -m beantester --version` exited 1 with a traceback.** One stray file, no program - CLI or
GUI.

Fixed with an `isinstance(meta, dict)` check. The file then behaves exactly like one carrying no
`_meta` at all, which is a supported case: the filename supplies the language code and the
translations are kept. That is deliberately NOT "skip the file" - discarding a translator's work
over a typo in one metadata field would be the wrong trade, and the first draft of the test
asserted the wrong thing here before the behaviour was thought through.

Two more edges measured, neither a bug, both now covered so nobody has to re-derive them:

- **a directory where a file belongs**: `open()` raises `IsADirectoryError` on Linux and
  `PermissionError` on Windows; both are `OSError`, `read_json` reports it, nothing raises.
- **a file that cannot be read**: reported the same way. The test asserts the portable invariant
  (it returns, with data or with a message) because `chmod` genuinely blocks reads on POSIX while
  on Windows it only toggles the read-only bit.

An unreadable file is also QUARANTINED, because `quarantine()` renames and renaming needs no read
access. That first looked like a wart worth splitting - `OSError` (do not quarantine, it may be
readable next time) versus `ValueError` (quarantine, the content is unusable) - and this file said
so. **Checking it reversed the conclusion, so the suggestion is withdrawn rather than left as a
trap.** `UiStateStore.persist()` runs unconditionally (on close, and on every window-state change)
and `write_json` ends in `os.replace`. Leave an unreadable file in place and the first save of the
session OVERWRITES it, destroying precisely the content nobody could read. The quarantine is what
preserves it. Current behaviour is correct and must stay.

CI is what forced the check: `test_an_unreadable_file_is_reported_not_crashed` passed on Windows,
where `chmod` only toggles the read-only bit, and failed on Linux, where it genuinely denies the
read - the test's cleanup chmod'd a fixed path that the quarantine had already renamed away. The
test now restores whatever is actually in the directory, and asserts the preservation half only on
platforms that really denied the read (root ignores `chmod` everywhere).

Verified by mutation: with `or {}` restored the suite fails with the original
`AttributeError: 'str' object has no attribute 'get'`.

### --dry-run called a scenario valid without ever opening it (audit item #10)

`--dry-run` is the gate a CI/CD pipeline runs before the real command. It returned `OK` for every
broken scenario file tried - a bare list, a string, a number, truncated JSON, an empty file - and
printed "Configuration is valid", because the scenario was loaded only inside `_run_session`,
which `--dry-run` returns before reaching. The same files correctly gave `SCENARIO(4)` on a real
run. A gate whose verdict disagrees with the thing it gates is worse than no gate.

`run_cli` now loads and validates the scenario inside the `--dry-run` branch, failing with
`SCENARIO(4)` and the parse error. `--print-config` and `--save-config` return early as before and
are deliberately left alone: neither claims the configuration is valid, they report or store the
SETTINGS, and a scenario is not part of those.

**Owner's call: this is a fix, not a BREAKING change** (`--dry-run` on a broken scenario goes from
`OK` to `SCENARIO(4)`). A script relying on the old outcome is relying on the gate lying to it. No
`### BREAKING` section, no version bump.

Tests: every shape in `BROKEN_JSON` must be rejected by `--dry-run` *and* the output must not
contain the word "valid"; the dry run and the real run must return the SAME code for the same
file; and all seven shipped `scenarios/*.json` must pass `--dry-run` - the check that the fix does
not start rejecting real files.

Worth recording, because it briefly looked like a regression: the first draft of that test invented
a scenario shape (`{"duration": 1, "loss": 5}`) instead of using the documented one
(`{"at": seconds, "settings": {...}}`). `--dry-run` rejected it, correctly, and for a moment that
read as the fix rejecting good files. The shipped-scenario loop was added as the answer - it
cannot be argued with.

Verified by mutation: without the change the suite fails with the original symptom, `code=0` and
`Configuration is valid` for a broken scenario.

### --config with valid JSON of the wrong shape was a traceback, not an exit code (audit item #10)

`settings.load_config_file` does a raw `json.load` and goes straight to `data.items()`. For
`[1, 2, 3]`, `"x"`, `42`, `null` or `true` the parse succeeds and the type error lands one line
later as an **AttributeError** - which `cli.py` does not catch, since it catches `ValueError` and
`OSError`. Measured on all five shapes: a Python traceback on stderr and exit **1 (RUNTIME)**,
where a bad config file is **CONFIG(3)**.

Two contracts at once: convention 18 (every way of ending has a code from `exitcodes.py`) and the
comment sitting directly above that `try` in `cli.py`, which promises "a clear CLI error, never a
raw traceback". For a CI/CD pipeline reading the exit code, the difference is being told the tool
crashed instead of being told its config is wrong.

`load_config_file` now checks the parsed value is a dict and raises `ValueError` otherwise, which
the existing handler already turns into `CONFIG(3)`. Deliberately NOT routed through
`jsonfile.read_json`: quarantine is right for the app's own state files, but silently moving aside
a file the user named explicitly on the command line would be a surprise.

The GUI path is unaffected - `App.load_config_file` catches `Exception` and shows a dialog - so
this was CLI-only, which is where the exit-code contract lives.

Tests in `tests/test_ondisk_formats.py`: every shape in `BROKEN_JSON` through `--config` must give
`CONFIG(3)`, an `error:` line on stderr and a clean stdout, plus the other direction - a
well-formed config file still loads. Run in-process, so an exception escaping `run_cli` fails the
test with its own traceback, which is the failure mode being guarded. Verified by mutation:
without the check the suite fails with the original `AttributeError: 'list' object has no
attribute 'items'`.

### ui.json: a valid dict with the wrong types stopped the app from starting (audit item #10)

`jsonfile.read_json` guarantees the file parses and is a dict. Nothing beyond that - and
`UiStateStore` trusted the rest, while its own module docstring promises that corruption "must
never break startup, so every failure degrades to the defaults". Measured, by building a real
`App` over a poisoned `bean_network_tester_ui.json`, three keys broke that promise outright:

| key | value | result |
|---|---|---|
| `page` | `[1, 2, 3]` | `TypeError: cannot use 'list' as a dict key (unhashable type: 'list')` |
| `conn_sort` | `[1, 2]` | `TypeError: object is not iterable` |
| `event_sort` | `"kb"` | `ValueError: dictionary update sequence element #0 has length 1; 2 is required` |

The window never appeared, and the traceback named none of the files involved.

`UiStateStore._clean` now drops values whose TYPE is not the one `DEFAULTS` promises, records
which keys it ignored in `self.problem` (already surfaced by `App._report_storage_problems`
through the existing `log.ui_state_problem` key, so no new i18n), and keeps everything else. It is
deliberately the same shape as `ProfileStore._clean`, which has always done this for the other
user file - the mechanism existed, it just was not applied here.

**Only the TYPE is checked, and that is a measured decision, not caution.** Every wrong VALUE of
the right type was tried first and already degrades gracefully: an unknown page id, an unknown
stats sub-page, an unknown language code, a missing profile name, a nonsense geometry string, a
negative or absurd sash position, a sort column that does not exist, `collapsed` holding ints or
nested lists, `conn_sort` with a list under `col`. Validating further would add rules that catch
nothing. Unknown keys are kept on purpose: `get` only reads keys it knows, and dropping them would
silently discard state written by a newer version.

New `tests/test_ondisk_formats.py` (4 tests, more coming for the config and scenario paths):
per-key type fuzzing at the store level, the whole poison set driven through a real `App` in one
subprocess, and the unparseable-file half - every shape in `BROKEN_JSON` must leave usable state,
a reported problem and a `.corrupt-<timestamp>` file rather than a clobbered one.

Verified by mutation: with `_clean` removed the suite fails with the original symptom,
`the app did not start: page=[1, 2, 3]: TypeError: cannot use 'list' as a dict key`.

### The chaos test was measuring the machine, not the code

CI failed `test_the_model_worker_survives_a_live_connection_table` with
`traffic really flowed while it did (8342)`. The test asserted `seen > 10_000` after a fixed three
seconds - a threshold read off a dev machine, where the same three seconds produce hundreds of
thousands of packets. A CI runner under coverage managed 8342, about fifteen times less.

The interesting part is that the test had already reached the state it exists for: the
`rows > 1000` assertion, checked one line earlier, PASSED. The table was big enough for the sort to
be real work. Only the packet count - a proxy for the same thing, and a worse one - was out of
range. A green run on a fast machine and a red one on a slow machine, with identical behaviour
under test.

Fixed by asserting the CONDITION and waiting for it, instead of assuming a duration produces it:

- the request/poll loop now runs for at least `STRESS_SECONDS` and then keeps going until
  `MIN_BUILDS` rebuilds have completed over a table of at least `MIN_ROWS` rows, with a 30 s hard
  cap so a broken run still ends;
- the packet-count assertion is gone. The row count already implies traffic - a thousand distinct
  flows cannot exist without it - and counting packets measured the runner;
- `FastDivert`'s docstring now says its measured throughput is a dev-machine number and not a
  promise, so nobody turns it back into a threshold.

Verified by simulating the slow runner rather than by hoping: throttled to ~3000 packets/s (below
what CI managed), the old assertions fail with the exact CI symptom
(`traffic really flowed while it did (2429)`) and the new ones pass. Unthrottled, both pass.

### A hot-path guard that watches the routes, not one object (audit item #8)

The rule is one sentence: nothing on the capture or inject thread may ask the OS a question. It
already had a guard - `test_target_resolver.py::test_the_capture_thread_never_touches_the_socket_table`
- but a narrow one, and its first limitation has already bitten this project:

- **it watches an object, so it can watch the WRONG object.** An earlier version gave the counting
  table only to the targeting and left the engine on `portmap.default_table()`. It passed while
  `_log_conn` -> `_process_for` -> `process_for_port` rebuilt the real table ~16 times a second on
  the capture thread. A live run caught what the test could not.
- **it only knows about the socket table.** Targeting is one route to the OS; `_log_conn` is a
  second, independent one; a third would be invisible to it.

New `tests/test_hot_path.py` watches the ROUTES instead. `portmap` is the only module in the
package that touches `psutil` or `iphlpapi`, through five entry points (`_psutil_port_pid_map`,
`_psutil_process_table`, `_psutil_created`, `_psutil_process_info`, `_Native._table`). Wrapping
all five catches any caller, including one nobody has written yet. Threads are compared by
IDENTITY against `engine._t_cap` / `_t_inj`, not by name substring, so it does not depend on how
CPython happens to name a thread.

The target expression deliberately matches nothing. With no matching port every packet is a miss,
so the resolver is woken continuously and the surface gets hammered - and the test stops depending
on which processes exist, so it means the same on a CI runner as here. Measured during a session
with traffic and targeting active:

| calls | function | thread |
|---|---|---|
| 5232 | `_psutil_created` | bean-target-resolver |
| 1431 | `_psutil_process_info` | bean-target-resolver |
| 448 | `_psutil_created` | watchdog |
| 212 | `_Native._table` | bean-target-resolver |
| 3 | `_psutil_process_table` | bean-target-resolver |
| **0** | **anything** | **capture / inject** |

The work is real and heavy, and none of it is where the user's packets wait. That is the design,
now asserted.

**Found no bug** - the invariant holds today. Verified by mutation, negative included:

- **caught:** `_process_for` reopening the refresh (`allow_refresh=True`), the regression that has
  already happened twice. The failure names both ends:
  `[('_Native._table', 'Thread-1 (_capture_loop)')]`.
- **not caught:** a name lookup on the capture thread that HITS the warm info cache. That is the
  guard's boundary, not a hole - it watches trips to the OS and a cache hit is not one - but a
  regression that only misses the cache occasionally will only be caught occasionally.

A second test asserts the RECORDER records: a wrapper that silently failed to install would leave
the guard permanently and invisibly green.

**Deliberately not a wall-clock budget.** The suite's existing timing assertions
(`test_failsafe`'s "start did not block the UI thread", `test_target_resolver`'s "stop did not wait
for the scan") all separate outcomes differing by an order of magnitude. "The hot path costs under
N microseconds" has no such separation: on a shared CI runner it measures the runner, and the first
thing anybody does with such a test is widen the bound until it stops failing.

**Not verified:** the Linux path. On this machine `_Native` initialises, so the `psutil` fallback
for the socket table never runs; `_psutil_port_pid_map` is watched but was never seen to fire here.
CI runs ubuntu too, where it is the main path. The assertions are written against the TOTAL over
the surface rather than any single function so they hold either way, but the ubuntu behaviour is
unverified locally.

Stability: 10 consecutive runs, 0 failures, median 3.8 s.

### Chaos through the whole stack (audit item #11, part 2)

New `tests/test_gui_stack_chaos.py`: the real `App` on the fake tkinter, a real engine on
synthetic traffic, the real connections page and its `AsyncModel`, and the `_tick` loop running
throughout - while a simulated user switches pages, types in the search box, flips sort columns,
toggles "freeze", and stops and restarts the session mid-rebuild.

The combination is what matters. The off-main-thread Tk call in the old target refresher survived
every test precisely because nothing ran the pieces together, and the fake tkinter is single
threaded so it could not have seen it.

Three choices worth recording:

- **The off-main-thread check watches the fake's widget base class**, not a handful of named
  widgets. A named spy only catches the widget somebody already suspected; patching `W.configure`,
  `W.pack`, `W.after` and friends covers every widget in the app, including ones added later.
  Note `config = configure` in the fake binds the ORIGINAL function at class creation, so both
  names need patching - patching one silently misses half the calls.
- **A failed tick is detected through the LOG, not through the loop surviving.** `_tick` catches
  everything by design (the loop must outlive a broken tick) and reports `log.ui_error`, so
  "the loop kept running" is true even when every single tick failed. The test takes the literal
  part of the translated template, ahead of the `{e}` placeholder, and asserts no line carries it.
- **Scope is stated in the docstring:** this is about thread boundaries, not volume. The traffic
  is `SyntheticDivert` on a twelve-row table; making the sort big enough to matter is part 1's
  job. Saying so keeps the next session from reading it as a load test.

Every assertion was verified by injecting the failure it exists for, and confirming the run goes
red: a widget touched from a worker thread, a tick that raises (injected into `_sample`, which
only `_tick` calls - the first attempt broke `conns.refresh`, which the test body also calls
directly, so it blew up on the wrong line and proved nothing), and a wedged model worker whose
`busy()` never clears.

Stability, which is the risk with a test like this: run 10 times consecutively, 0 failures,
median 3.4 s. Suite 591 -> 593 tests, +5.2 s (157.6 s -> 162.8 s).

### The model worker meets a live engine (audit item #11, part 1)

`test_concurrency_chaos.py` was engine-only, and the seven `AsyncModel` tests all feed the worker
a fake `build`. Nothing put the two together - which matters because `ConnectionsPage.refresh()`
hands the worker **the engine itself**, not a snapshot of it (a snapshot is ~70 ms at half a
million rows, most of what moving the sort off the UI thread bought back). So `_build_model` calls
`connections_snapshot()` on the worker thread, and that returns `list(self._conns.values())`:
the outer list is a copy taken under the lock, but every row in it is the live dict the capture
thread keeps updating. `model_worker.py` asserts in prose that this is safe. Nothing checked it.

New `test_the_model_worker_survives_a_live_connection_table` runs the real pipeline - snapshot,
filter, sort, totals, scope - on the real `AsyncModel` against a real engine under load, while
settings and targeting churn underneath.

**The traffic had to be built for it, and the reason is measured.** `SyntheticDivert` sleeps once
per packet, and Windows timer granularity turns that into a ceiling: it delivers **~1900
packets/s whatever `gen_kbps` says** (2000 kbps and 1 Gbps both land there), over a flow space of
three local ports against three hard-coded remote addresses - so the connection table stops at
**12 rows** however long a test runs. A model-worker test on that table sorts twelve rows and
proves nothing. `FastDivert` (test-local, unthrottled) measures **~126 000 packets/s and ~125 000
connection rows in three seconds**. It stays in the test file on purpose: production has no use
for an unthrottled generator, and widening `SyntheticDivert` to make a test look better would be
changing the tool to suit the test.

Verified by mutation, and the negatives are recorded in the test docstring so nobody re-derives
them:

- **caught:** `connections_snapshot` returning the live `dict.values()` view instead of a copy
  under the lock - the tempting optimisation here, and the one that turns every rebuild into a
  race with flow creation.
- **not caught:** taking the copy without the lock (window too narrow to hit in a few seconds);
  iterating a row (`dict(c)`, `**c`, `.items()`). The second is harmless only because `_log_conn`
  builds each row with its full key set and never adds one later, so a row never changes size -
  if that ever stops being true, this test will not warn anybody.

The test watches `crashlog.note` as well as the thread excepthook. `AsyncModel._run` catches
everything, records it and keeps the previous table on screen, so a worker raising on every build
would otherwise leave a green test and a quietly frozen table. It also asserts it ran in the
regime it claims (builds completed, table over 1000 rows, over 10 000 packets seen): a green run
that never got there would be decorative.

Stability: the file was run 10 times consecutively, 0 failures.

### stop() releases the divert before anything that can block

CI caught `test_failsafe.py::test_engine_stops_itself_when_the_duration_elapses` failing on
master. Not a flake to silence: measured, it failed **10 runs out of 30**, and the cause was a
real ordering problem in the stop path.

`stop()` sets `_running = False` first, which it must - `_capture_loop` runs `while self._running`
and that flag is how it ends. But the divert was closed sixteen lines further down, after
`stop_scenario()`, `_resolver.stop()`, `log_event()` and `notify_all()`. Between those two points
the capture thread is already gone and the divert is still open, so WinDivert keeps diverting into
a queue nobody drains - the exact failure FAIL-OPEN exists to prevent (convention 20). It is
invisible on a synthetic divert, whose `recv()` blocks until close, and real on the live one,
whose `recv()` returns immediately under traffic.

The window was not theoretical. `_resolver.stop()` joins with a 0.25 s timeout and a resolve in
flight uses it: an earlier session measured STOP at 252 ms with a scan running against ~100 ms
idle, and recorded that as STOP latency. It was also a quarter of a second of the user's packets
queued into a void.

Measured here with a divert whose `recv()` returns immediately and a 200 ms resolver join - time
the divert stayed OPEN after the capture thread had left:

| | before | after |
|---|---|---|
| idle resolver | +0.04 ms | -0.36 ms |
| resolver mid-scan (200 ms join) | **+200.06 ms** | -0.40 ms |

Negative means the divert was closed before the capture thread finished leaving, which is the
point - closing it is what ends that thread.

- `engine.stop()`: the `_divert.close()` block moves up, directly after the stop bookkeeping and
  ahead of `stop_scenario()` / `_resolver.stop()` / `log_event()`.
- It deliberately does NOT move above `self._running = False`. Checked: `recv()` would then raise
  while the session still looked live, so `_capture_loop` would take the `_fail_stop` path and
  report a fault for an ordinary stop - which would also break `test_concurrency_chaos`'s
  `engine.fault is None`. A microscopic window is unavoidable; the point is that no join sits
  inside it.

Two changes on the test side:

- `test_engine_stops_itself_when_the_duration_elapses` stopped treating `not is_running()` as
  "stop() has finished". It is not: the flag drops at the top of `stop()` and every promise (the
  divert closed, the STOP event logged, the workers joined) lands afterwards, so waiting on the
  flag and asserting a post-condition in the next statement is a race by construction. The test
  now waits for the post-conditions themselves. Worth recording: reordering the close alone did
  NOT make it green - the failure simply MOVED to the STOP-event assertion, which is how the
  wider problem surfaced.
- New `test_stop_releases_the_divert_before_anything_that_can_block` asserts the ORDER (close
  before the resolver join) rather than elapsed time, so it cannot flake. Verified by mutation:
  with the production change reverted it fails with `['resolver.stop', 'divert.close']`.

Verified: `tests/test_failsafe.py` run 40 times consecutively, 0 failures (10/30 before).

### Property tests for the decision pipeline (audit item #9)

`BeanCore.decide()` is a twelve-step pipeline over twenty-odd interacting fields, and every test
it had pinned ONE step at a time. `test_passthrough.py` already drove it with Hypothesis, but
only in the "everything switched off" configuration, so the INTERACTION between armed steps was
untested. New file `tests/test_core_properties.py`, 8 tests:

- **Totality.** `decide()` never raises, across the settings space x packet shapes. An exception
  there kills the capture thread with the divert still open, which is the fail-open failure of
  convention 20. `flap_enabled` is generated INDEPENDENTLY of `flap_period`, so "enabled with a
  zero period" stays covered - that combination is reachable only through the setter, because
  `apply_settings` derives the flag from the period.
- **Structural coherence.** `drop` and `releases` are the same statement made twice: a dropped
  packet has no release times, a delivered one has one or two, a duplicate never precedes its
  original, nothing is released before it arrived, and `emit_rst` implies a drop. The engine
  injects straight from `releases`, so an incoherent Decision is a lost or a doubled packet.
- **Pipeline order.** Each deterministic gate (lan, block, nat, rst, flap, mtu, syn), armed alone
  against 100% loss/corruption/duplication/spike, still names its own reason; and an earlier gate
  beats a later one. The order is documented as a contract in the module docstring - this states
  it as a test.
- **An unnamed drop belongs to loss.** With `loss = 0` every drop carries a reason. That is how
  the engine picks the counter, and `test_passthrough`'s DAMAGE_COUNTERS assertions rest on it.
- **Out of scope means untouched, and leaves no trace.** An off-target packet neither charges the
  token bucket nor writes a flow-table entry. Not covered anywhere before: if observation charged
  the bucket, merely watching a busy machine would eat the shaped link of the application under
  test, and the measurement would be wrong invisibly.
- **A bounded buffer bounds the added delay.** Generalises `test_bandwidth_buffer` across rates,
  packet sizes and buffer depths.

Two details worth recording, because they cost time:

- The bound in the buffer property is `max(buffer_s, size / rate)`, NOT `buffer_s`. A packet
  arriving into an EMPTY buffer is always accepted, even when its own serialisation takes longer
  than the whole buffer - deliberate, and guarded by
  `test_bandwidth_buffer.test_empty_buffer_never_blacks_out_the_link`. Writing the bound as plain
  `buffer_s` yields a test that is RED against correct code: measured, a 10 ms buffer with a
  65535 B packet at 1 KB/s leaves the bucket 64 s ahead of `now`, 6400x the buffer.
- `set_schedule()` reads `time.monotonic()` directly, so a core carrying a schedule is only
  deterministic once `reset_buckets(t)` has run after it. Production always does
  (`BeanEngine.start`); a property test that skips it flakes on the schedule position. Recorded
  in the test module docstring rather than changed - the coupling is harmless in production, and
  a rewrite here buys no stability.

**These tests found no bug.** The pipeline survived every attempt to falsify them before the file
existed: 3000 Hypothesis examples across the settings space and 300-seed sweeps per gate. Their
value is the regression net. The pipeline GROWS - step 2c (blocking) was added after the pipeline
was first documented - and a step inserted at the wrong position is invisible to example tests
that each arm a single knob. Every property was then verified by MUTATION: each guard was
confirmed to go RED against a deliberately broken `core.py` (the `rate > 0` guard removed, a drop
carrying a release time, MTU moved ahead of LAN mode, flapping dropping unnamed, the targeting
gate marking a packet in scope, the flow table written before that gate, and the tail drop
disabled). A guard that stays green under its own mutation is decoration.

Suite: 582 -> 590 tests, +4.9 s (149.3 s -> 154.2 s, measured on this machine, not estimated).

### The capture thread could still reach psutil - and the fix for that broke the process column

Two findings from reviewing the PID-reuse diff, both verified by running them.

- **Identity verification put a psutil call back on the capture thread.** `engine._process_for`
  reads with `allow_refresh=False`, but that only gated the socket-table rebuild - the NAME lookup
  underneath it went on to `info()`, which now verifies. Measured with a port table that actually
  resolves: 12 `create_time()` calls from `Thread-1 (_capture_loop)`. Once per NEW FLOW rather
  than per packet, so 3/s here - but this tool gets pointed at load generators and port scans,
  where new flows arrive in thousands per second.
- **Worse, the same hole predates this branch.** Checked against `master`: on a cache MISS the old
  `info()` called `_psutil_process_info` from whatever thread asked, so the capture thread could
  already trigger a resolve (~5 ms) and even a full `process_iter()` (~1.7 s). The previous chunk
  stopped `process_for_port` from refreshing the socket table and left that path open.
- Fixed with an explicit `cheap=True` mode on `info()` / `name_of()`, wired from
  `process_for_port(allow_refresh=False)`: **answer from the cache or not at all.** Resolving a
  name and verifying an identity are both psutil calls, and gating only one of them is what left
  the packet path making the other. Re-measured warm and cold: zero psutil calls from the capture
  thread in both.
- **That fix then emptied the connection log's process column** - the regression is only visible
  with no target set, which is most sessions: the capture thread no longer resolves, and the
  resolver only fills the cache for PIDs it matches, so with no target nothing filled it at all.
  Measured: 6 rows, 0 names. The column exists precisely because it used to read "?"; shipping
  that back would have undone a fixed bug. `PortTable.warm_names()` now runs on the WATCHDOG next
  to the socket-table refresh - cheap in the steady state (one identity check per PID, ~0.13 ms),
  paying the real resolve once. Re-measured: 6 rows, 6 names, with and without targeting, and
  still zero psutil from the capture thread.

### portmap: a PID is a number, not an identity (audit item P2)

- **The `pid -> (name, ppid)` cache could not expire, by any route.** `_expire_info` returned
  early below 512 entries (a normal machine holds 26-343, so it never ran), and `info()` bumped
  the timestamp on every cache HIT - which made the entry of a busily-read PID immortal, i.e.
  exactly the entry decisions rest on. Both reproduced against the real table: a target
  restarting onto a recycled PID was **not impaired**, and an innocent process inheriting the
  target's old PID **was**. The second is the serious one: this tool breaks networking, and
  breaking an application the user never named is the worst thing it can do quietly.
- **Fixed by verifying identity, not by guessing at ages.** Each entry now carries the process
  START TIME (`create_time`), and every cache hit checks it. The analysis had rejected this as
  "costs as much as re-resolving" - **that was wrong by three orders of magnitude**, and measuring
  it is what found the right design:

      create_time() for 2 PIDs : 0.01 ms      full re-resolve: 9.8 ms
      create_time() for 8 PIDs : 0.03 ms      full re-resolve: 38.9 ms

  `name()` is expensive because it must open the process and read its image path; `create_time()`
  does not. On this machine it succeeds for **24/24** socket-owning PIDs, including the protected
  ones that make `name()` fall back to a full `process_iter()`.
- **"Cannot tell" is not "recycled".** Treating a missing start time as proof of reuse looked like
  the safe reading and was in fact a way to destroy the cache wholesale on every fallback path:
  each lookup evicted, re-resolved, failed to stamp, and evicted again, so process names came back
  empty. Caught by the suite going red on the psutil fake. `_looks_recycled` now returns True only
  when both stamps are known AND differ; unverifiable environments fall back to the TTL exactly as
  before. Hardening must not degrade what it cannot harden.
- Two cheaper mechanisms kept as backstops: the TTL now counts from INSERTION and runs
  unconditionally (2.2 us a sweep, measured), and a PID that loses every socket is forgotten at
  once (2.5 us, measured) - a PID can only be reissued after its owner exits, and exiting closes
  its sockets.
- **Cost, measured properly on a second pass.** The first figure recorded here (1.4 -> 2.96 ms,
  ~5% of a core) was an AVERAGE polluted by a single outlier and roughly double the truth. Isolated
  by stubbing `_psutil_created` and comparing medians over 40 runs each, with a control run to
  confirm reproducibility:

      with verification    1.29 ms   (control: 1.28 ms)
      without              0.93 ms
      delta                +0.35 ms  (+38%)

  At the resolver's measured 17 rebuilds/s that is **22 ms/s, 2.2% of one core** - and 2.6% of the
  0.05 s floor it has to fit inside. On the RESOLVER thread; the capture thread is untouched, which
  is what the previous chunk bought. A batch verification in `PortTable.refresh()` would shave that
  to ~0.2%, and is deliberately not taken: it splits one mechanism into two and leaves ancestors on
  the TTL, to save two percent of a background thread that is not short of time.
- Two more things checked rather than assumed. The 0.001 s tolerance in `_looks_recycled` is never
  actually needed here - across 342 processes, `process_iter` and `Process.create_time()` agreed to
  **0.000000000 s**, so there are no false "recycled" verdicts; the tolerance stays as defence on
  platforms that are less exact. And PIDs that lose every socket and come back do exist (2 of them
  oscillated 3-4 times in 10 s of observation), costing about 0.8 extra resolves a second - noise
  against the numbers above.
- Verified beyond the suite: a **real** child process with a **real** socket resolves to
  `python.exe` while alive and to `""` the moment it exits - no stale name survives. A 10 s live
  session with targeting: 9020 packets, 171 rebuilds, 23 targeted ports, STOP 18 ms, no thread
  left behind.
- New tests in `tests/test_processes.py`, on a controllable `_World` (ports, processes, start
  times): the restarted target is impaired, the innocent inheritor is not, a living process keeps
  its entry (verifying must not become re-resolving), an unverifiable environment still resolves
  names, expiry works below the old 512 threshold and a busily-read entry no longer renews itself,
  and a PID that loses every socket is forgotten at once.

### STOP no longer waits for a resolve, and the number that explains why

- **Measured, because nobody here knew it: a COLD resolve costs 1.7 SECONDS.** On this desktop
  25 PIDs own sockets but the process-info cache ends up with 346 entries - the expensive part is
  one full `psutil.process_iter()`, triggered the moment a protected PID refuses `psutil.Process`.
  Once warm the same resolve is **1.4 ms**. A thousandfold difference that every fake in the
  suite hides, because fakes answer instantly.
- **That made `stop()` slow, and STOP is the control this tool may never make slow.** The
  resolver joined with a 2 s timeout, so pressing STOP while a cold scan was in flight blocked
  for **1647 ms** (measured; with an artificially slow table it ate the full 2000 ms and still
  left the thread running). The old GUI refresher was an unjoined daemon, so this was a
  regression introduced by the rewrite.
- Fixed with `TargetResolver.JOIN_S = 0.25`: long enough that an IDLE resolver is always joined
  (it is parked in `wait()` and exits in microseconds), short enough that a scan in flight can
  never hold STOP up. Not joining a straggler is safe - `stop()` has already cleared the target
  and set the stop flag, so it finishes at most one more scan into an object nobody reads and
  then exits; it is a daemon either way. Re-measured: **252 ms** with a 1.7 s scan in flight,
  **265 ms** with a 5 s one, **100 ms** idle (and that 100 ms is the engine's other joins).
- Guards: `test_stop_never_waits_for_a_scan_in_flight` (deliberately slow table, asserts under
  900 ms) and `test_stop_does_join_an_idle_resolver` (the other half - the common case must be
  clean, not merely fast).
- **A full GUI session was driven end to end for the first time** - real engine, real resolver,
  synthetic traffic, real GUI code - because everything until then had exercised the engine
  directly and left `_tick`'s new wiring unverified. Verified: resolver up for a targetless
  session, a non-matching target raises the banner, a matching one takes it down, clearing the
  field drops targeting, traffic never stalls, STOP stays under 900 ms and leaks no thread.
  Pinned as `test_gui_state.py::test_a_gui_session_keeps_the_target_banner_honest`, on a fake
  table so it stays fast and deterministic.
- Two false alarms during that work, recorded so they are not re-chased: `ProcessTargeting`
  defines `__len__`, so an object with an empty port set is FALSY - a diagnostic printing
  `"y" if tg else "N"` reported a live target as missing. And `python` owns no sockets on this
  machine, so a test using it as a "should match" target was wrong, not the code. Production uses
  `is None` throughout, which is why neither reached the program.

### Review pass over the whole targeting diff (four more findings)

Read line by line before merge, on the principle that a green suite had already missed three
things in this branch. Each one below was verified by running it, not by reasoning about it.

- **The watchdog's new port refresh could cancel the memory work.** `refresh_if_stale()` was put
  FIRST inside the tick's existing `try`, so a socket-table failure aborted the block and
  `_trim_conns()` plus `core.drain_retired()` never ran for that tick - the connection log would
  grow unbounded because a NAME lookup failed. Now its own `try`: cosmetic work and memory safety
  are different failure domains. Verified with a table that raises on every refresh: `_trim_conns`
  still ran 6 times in 1.5 s and the row count stayed under the cap.
- **A failed resolve in `apply_targeting` left the engine and the core disagreeing.** The
  synchronous announce-path refresh sat inside the `try` whose `except Exception` returns without
  calling `set_target`, so `engine._targeting` held a new object the core had never been pointed
  at. Moved out and wrapped in `crashlog.quiet`: a stale announcement is a far smaller problem
  than two halves disagreeing about what is being impaired, and the resolver corrects it within a
  tick. Verified with a table that always raises: engine, core and resolver all end up on the
  same object.
- **`TargetResolver.stop()` signalled `_stopping` outside its lock**, leaving a window where a
  concurrent `start()` could clear the flag, spawn a thread, and have the late `set()` kill it on
  its first check. `BeanEngine` serialises start/stop under `_stop_lock` so it could not happen
  today, but a threading primitive should not depend on its caller for safety. Verified with 200
  lifecycle cycles plus 300 start-immediately-after-stop pairs: no thread killed on arrival, no
  leak, no dangling `on_miss`.
- **Dead knobs removed from `ProcessTargeting`.** `interval`, `miss_interval` and `_last` were
  still written but no longer read by anything - pacing lives in `TargetResolver` now. Leaving
  constructor parameters that control nothing invites somebody to tune them. Also fixed the fake
  in `test_engine_records_a_broken_port_table_instead_of_going_quiet`, whose `process_for_port`
  lacked the `allow_refresh` keyword: it was raising `TypeError` instead of the `RuntimeError` the
  test meant to exercise, and passing for the wrong reason.

### The connection log was a SECOND socket-table scan on the capture thread

- **Moving targeting off the hot path did nothing for this one, and a green test suite said
  otherwise.** `_log_conn` -> `_process_for` -> `PortTable.process_for_port` calls
  `refresh_if_stale(miss=True)` whenever the port is unknown - four iphlpapi calls, sometimes a
  psutil walk - **on the capture thread**, for the connection log's process column. Measured live
  with a real port table and synthetic traffic: **47 rebuilds in 3 s from
  `Thread-1 (_capture_loop)`**, alongside the resolver's own 48.
- **The end-to-end test missed it because it watched the wrong object.** It injected a counting
  table into the `ProcessTargeting` but left the engine on `portmap.default_table()`, so it
  asserted on a table the capture thread never used and passed vacuously. The test now sets
  `engine._ports` to the same table and the fake grew the engine-side surface
  (`process_for_port`, `pid_for`, `refresh_if_stale`). Found by instrumenting a live run, not by
  the suite - which is the lesson worth keeping.
- Fix follows the pattern the project already uses for eviction and flow rotation: `_process_for`
  reads with `allow_refresh=False` (a pure lookup), and the **watchdog** calls
  `self._ports.refresh_if_stale()` on its 200 ms tick. Maintenance belongs on the maintenance
  thread. Cost: a brand-new socket can read as `""` for up to one refresh interval, and
  `_log_conn` already retries while packets keep coming, so the row fills itself in.
- Re-measured after the fix: socket-table refreshes come from `bean-target-resolver` (48) and
  `MainThread` (2). **Zero from the capture thread.**

### Targeting resolves off the capture thread (new `target_resolver.py`)

- **`ProcessTargeting.__contains__` used to call `refresh()` inline** - i.e. from
  `BeanCore.decide()`, on the CAPTURE THREAD, holding `core._lock`. One rebuild is four
  `iphlpapi` calls, an O(n) dict copy, a `psutil.Process()` per distinct PID and, whenever a
  protected PID refuses to open, a whole `psutil.process_iter()`. **And it was the normal case,
  not an edge one:** targeting exists to narrow traffic to one application, so every packet from
  every OTHER application is a miss, and a miss triggered the rebuild - a steady ~20 Hz of
  syscalls in the packet path whenever a target was set. A stalled capture thread is precisely
  what fail-open (convention 20), the watchdog, the eviction move and the table-sort move all
  exist to prevent: WinDivert keeps diverting into a queue nobody drains, so the user loses
  connectivity while the UI says "running". Targeting was the last place still doing it.
- **`__contains__` is now a frozenset lookup and nothing else.** A miss sets a plain bool
  (atomic under the GIL, free) and, only on the FALSE -> TRUE transition, calls the resolver's
  wake-up. That guard is the point: `Event.set()` takes a lock, so waking per packet would have
  moved the problem rather than removed it. `refresh()` stays public and synchronous for
  one-shot callers (`resolve_ports`, `make_targeting`) and tests.
- **New `beantester/target_resolver.py`.** Deliberately the same shape as `scenario_runner.py`:
  a small class owning one thread, lifecycle driven explicitly by `BeanEngine`. Two differences
  on purpose: `stop()` JOINS (it holds OS handles), and it waits on an `Event` rather than
  sleeping, so a miss is picked up in milliseconds instead of at the next tick. **One resolver
  per engine with a swappable target** - retargeting is a reference swap, not a thread restart,
  because the GUI applies settings repeatedly and `test_concurrency_chaos` does it hundreds of
  times. Wake ordering is clear-then-refresh-then-wait, so a miss arriving DURING a rebuild
  re-arms instead of being swallowed by it.
- **`engine.set_target` is now the single place the resolver is pointed at a target.**
  `self._targeting` was previously assigned only by `target_for`, so installing a live targeting
  directly left the engine believing it had none while the core tested against it. `target_for`
  keeps its memoisation (one live object per expression, so the port and process caches survive)
  but no longer resolves; `start()` reconciles the two and does one synchronous pass so the first
  packet meets a populated port set; `stop()` joins the thread.
- **The resolver's life matches a SESSION's**, not a target's: configuring a target without
  starting must not leave something scanning the socket table in the background.
- **`apply_targeting` refreshes only when `announce=True`.** It has to, because the log line
  reports what was matched and an unresolved target would always read as "matches nothing" - the
  very message this project made loud on purpose. That is the explicit user-applied path; the
  periodic path passes `announce=False` and never blocks. Strictly less work than before, where
  `target_for` refreshed on every call including the GUI's 2 s loop.
- **Found while re-reading, fixed by removal: the GUI refresher thread leaked on fast restart.**
  `_finish_start` spawned `_target_thread` unconditionally and nothing ever joined or signalled
  it, while `_target_refresher` looped on `while self.running` with a 2 s sleep. STOP followed by
  START inside that sleep left the OLD thread looping as well - one extra permanent scanner, each
  doing a full OS scan every 2 s, per fast restart cycle. Not reproduced live (driving the async
  start/stop on the fake-tk harness is awkward); `test_repeated_start_stop_cycles_do_not_stack_resolver_threads`
  is the guard that would have caught it.
- **A FLOOR under miss-driven rebuilds, found by re-reading the design rather than by a test.**
  Moving `miss_interval` out of `__contains__` removed the rate limit without putting it back
  anywhere: targeting narrows traffic to one application, so every packet from every OTHER
  application is a miss, misses arrive continuously, and the wake-up was re-armed as fast as it
  was consumed. Measured with a 5 s routine tick: **63 rebuilds a second**, bounded only by the
  GIL - with a real socket table that is a thread pegged at 100% scanning the OS. The resolver now
  enforces `min_interval` (`portmap.MISS_REFRESH_S`, the same 0.05 s the old code used), in ONE
  place instead of on the capture thread. Re-measured: 14 rebuilds/s with the floor, 33/s with it
  disabled. The cost is the worst-case delay before a brand-new socket starts being impaired -
  up to 50 ms, exactly the trade the old code made.
- **Dynamic process trees verified, not assumed.** A child spawned mid-session opens its own
  socket; the first packet slips through (the documented, unclosable race) and the miss wakes the
  resolver, which matches the child through its ancestor chain. Measured pick-up: ~3 ms without
  the floor, bounded by `min_interval` with it. Grandchildren (two levels) work the same way, and
  `myapp, !myapp-helper` keeps excluding a respawning helper despite its matching parent.
- **Caught in review, before merge: a target applied MID-SESSION got a frozen port set.** The
  resolver was started only when a target already existed at `start()`. Press START, watch, then
  type a process name - an ordinary workflow - and nobody was keeping the port set fresh: it
  froze at whatever the first resolve produced and sockets opened afterwards were never picked
  up. Precisely the failure live targeting exists to prevent, reintroduced by the fix for it.
  The resolver's life is now the SESSION's, unconditionally; with nothing to resolve it blocks on
  its event and costs nothing. Guarded by
  `test_a_target_applied_mid_session_still_gets_a_live_port_set`.
- **The GUI does not resolve on the UI thread while a session runs.** `_refresh_target` resolves
  inline only when the engine is STOPPED (no resolver to do it, and no session to stall); while
  running it lets the banner wait for the next 700 ms tick. Four syscalls and a psutil walk on
  the UI thread would be a frozen window, and a frozen window here is the user unable to press
  STOP on their own broken network.
- `TargetResolver.stop()` detaches the old targeting's `on_miss`, so a late packet cannot poke
  the event of a worker that is no longer listening.
- New `tests/test_target_resolver.py`: miss wakes the resolver and the new port is picked up
  (long interval, so only the WAKE can explain it), `stop()` joins rather than signals,
  retargeting does not churn threads, an orphaned targeting is detached, a failing table leaves
  the resolver alive, **the capture thread never touches the socket table** (end to end over
  synthetic traffic, asserting on the THREAD NAMES that made it look), no thread outlives a
  session, and five start/stop cycles stack nothing.
  `tests/test_release_fixes.py::test_an_unknown_port_forces_an_early_refresh` is rewritten as
  `..._asks_for_a_rebuild_without_scanning_inline`: it now asserts the socket table is NOT
  touched from the packet path and that 50 misses wake the resolver exactly once.

### AsyncModel: a build returning None no longer wedges the worker for good

- **`poll()` used `None` for two different things** - "no result arrived" and "the result". It
  started with `rows = None` and returned early on `rows is None`, so a build that genuinely
  produced `None` looked identical to an empty queue and **`_pending` was never cleared**. From
  that moment `request()` coalesced into `_latest` for ever and nothing ran again: the table
  stopped rebuilding for the rest of the session, and `busy()` stayed True, which leaves
  `conns._poll_soon()` rescheduling its 40 ms catch-up timer indefinitely on the UI thread.
- Fixed with a module-level `_NOTHING` sentinel. The caller's contract is unchanged (`poll()`
  still returns `None` for "nothing new to show"); what changed is that a result for the request
  in flight now clears `_pending` whatever its value.
- Latent, not live: `conns._build_model` always returns a dict. But convention 29 makes
  `AsyncModel` the mechanism every future heavy table is meant to use, so the contract had to
  hold before something is built on it.
- **Deliberately NOT fixed in the same pass:** the exception path in `_run` clears `_pending` but
  drops a request that queued into `_latest` while the build was failing. It self-heals - the page
  calls `request()` on every tick, so a newer payload starts within about a second - and
  re-submitting would mean calling `request()` (documented UI-thread only) from the worker thread,
  outside the lock to avoid deadlocking on it. Threading complexity for a case that already
  recovers is the wrong trade in a tool whose STOP button has to keep working.
- New test: `tests/test_model_worker.py::test_a_build_returning_none_does_not_wedge_the_worker`.
  Verified non-vacuous by restoring the old collision (`_NOTHING = None`) and confirming the
  worker wedges.

### portmap/engine/processes: port-resolution failures stop being invisible

- **`_Native.port_pid_map` accepted a PARTIAL socket table as the truth.** `ok |= self._table(...)`
  over the four (proto, family) combinations left `ok` True when three of four answered, and
  `refresh()` cached the result as authoritative. A missing table means sockets the tool cannot
  see, and an unseen socket is traffic the user asked to impair sailing through untouched -
  which on screen looks exactly like "the application coped". The failures are now counted and
  named: all four failing still returns `None` (psutil fallback, unchanged), a partial result is
  still returned but goes through `crashlog.once("portmap.native.<tables>")`, with the failing
  tables in the key so a different failure is recorded too.
- **The stricter option (any failure -> psutil) was rejected on purpose.** Measured on the dev
  machine, all four tables answer `rc=0` (tcp/v4 103 rows, tcp/v6 10, udp/v4 90, udp/v6 23), so
  the failure mode is NOT reproducible here. Trading a possible gap for a certain order-of-
  magnitude slowdown, on a path that cannot be tested, is the wrong bet; when a real machine
  reports it, `crashes/` will hold the evidence and the decision can be made on data.
- **`_Native._table` no longer pretends to reuse its buffer.** The comment claimed "grow and KEEP
  one buffer per table", but a fresh `create_string_buffer` was allocated on every call and the
  stored buffer was never read back - the cache only pinned memory. `self._buffers` becomes
  `self._sizes` (the size hint is the part that was doing work). Real reuse was considered and
  rejected: four allocations a few times a second against aliasing between calls in ctypes code.
- **`engine._process_for` / `_pid_for` now use `crashlog.once("engine.ports*")`.** They swallowed
  silently while the same file, 200 lines up, already used `crashlog.once("engine.packet")` for
  the same class of event on the same thread. `once()` and not `note()` because this is the
  capture path: a port table that starts failing turns every row's process into "?", which is
  worth one traceback, not one per packet.
- **`processes.port_process_map` uses `crashlog.quiet("processes.port_map")`.** Best-effort for
  the caller (an empty map still just means "?"), recorded for us.
- New tests in `tests/test_processes.py`: `test_port_process_map_records_a_failure_instead_of_swallowing_it`,
  `test_a_partial_socket_table_is_reported_not_silently_trusted`,
  `test_every_socket_table_failing_falls_back_to_psutil`,
  `test_engine_records_a_broken_port_table_instead_of_going_quiet`. They spy on `crashlog.record`
  (and reset `_once_seen`) instead of reading the crash directory, so they touch no disk.

### Changelog structure: `### BREAKING` first, now guarded

- Convention 39 requires `### BREAKING` to be the FIRST section of a version in both changelogs.
  The `--doctor` entry was added ABOVE it in both files, pushing it to second place - the exact
  drift the convention exists to prevent, committed two chunks after writing the convention down.
  Nothing caught it: `test_no_em_or_en_dashes` reads changelog TEXT, never its structure.
- Fixed in both files, and `tests/test_version_and_release.py::test_breaking_sections_come_first`
  now enforces it: in every version block of either changelog, if a `### BREAKING` heading exists
  it must be the first `###` under its `##`.

### Hygiene guard: measured, then deliberately NOT tightened

- The audit proposed extending `test_code_hygiene` to catch `except ...: return <default>`, not
  only `except ...: pass`. A prototype was run across the package first. Result: **66 silent
  handlers, of which 26 catch a NARROW type** (`OSError`, `(TypeError, ValueError)`) and are
  idiomatic, and 40 are broad. Of the 40: 7 are `crashlog.py` (already exempt), 12 sit in modules
  whose docstring states a "never raises" contract (`portmap` 6, `winenv` 4, `matchers.matches()`,
  `utils.is_local_ip`), 2 in `legal.py` already carry `# noqa: BLE001` with a reason, and 14 are
  in `gui/` - against roughly 100 correct `crashlog.*` uses in the same directory.
- **Conclusion: the codebase is disciplined and the guard would mostly encode the status quo**,
  at the cost of a wide diff and future false positives. Tightening was dropped; the three
  handlers that were genuinely inconsistent with their own neighbours were fixed above instead.
  If it is ever revisited, the mechanism to use is the one `legal.py` already established -
  `# noqa: BLE001 - <reason>` at the handler - not a central allowlist.

### Deferred: PID reuse in the portmap info cache (audit item P2)

- `PortTable._expire_info` returns early below 512 entries, so on a normal machine (50-250
  socket-owning PIDs) the `pid -> (name, ppid)` cache never expires and a recycled PID keeps the
  dead process's name. That matters beyond a wrong column: `ProcessTargeting.refresh()` matches on
  `name_of(pid)`, so the tool can impair a process the user did not target.
- **The obvious fix does not work.** `info()` refreshes `last_seen` on every cache HIT, so the
  dangerous case - a recycled PID that is being actively looked up - never expires no matter what
  the TTL is. Real fixes (TTL from INSERTION, `create_time()` validation, or evicting PIDs that
  vanish from the socket table) all add work to `PortTable.refresh()`, which today runs **on the
  capture thread** via `ProcessTargeting.__contains__`. TTL-from-insertion additionally gives a
  thundering herd: entries created together expire together, so one refresh re-resolves dozens of
  PIDs at once, in the packet path.
- Therefore P2 is scheduled straight after the targeting rewrite, when the cost no longer sits on
  the capture thread. Designing around a constraint that is about to be removed would be wasted work.

### driver.py: read a service with read rights, not ALL_ACCESS

- **`service_state` opened services with `SERVICE_ALL_ACCESS` (0xF01FF) just to read their
  state, and mapped the resulting failure to `None` = "not installed".** Measured on Windows 11
  from an ELEVATED shell, so this was never a "needs admin" problem:

      OpenServiceW(Schedule, SERVICE_ALL_ACCESS)    -> NULL, error 5 (ACCESS_DENIED)
      OpenServiceW(Schedule, SERVICE_QUERY_STATUS)  -> handle, QueryServiceStatus = running

  Same for `Dnscache`; `EventLog` grants both, which is why the path looked fine. Any service
  whose security descriptor withholds full control read back as absent. Now
  `SC_MANAGER_CONNECT` + `SERVICE_QUERY_STATUS`, which also makes the read work unelevated.
- **Third return value `NO_ACCESS`**, distinct from a state label and from `None`. "I cannot
  tell" and "it is not there" lead to opposite conclusions, so they no longer share a value.
  `installed_drivers()` keeps such a service in the dict (absence from that dict has to keep
  meaning "not installed"); `doctor()` renders it `warn` with a "re-run as Administrator" hint
  instead of `ok / not loaded`. Exit codes are untouched: `warn` is not `fail`, and
  `ok = all(state != "fail")` is unchanged.
- **`_advapi()` now loads advapi32 with `use_last_error=True`.** `ctypes.get_last_error()` in
  `stop_and_remove` read a thread-local ctypes never populated, so it was always 0 and both
  branches of the `if` returned the same string - dead code pretending to discriminate. With the
  flag it works, so a refusal is reported as `access denied` rather than `not installed`.
- **`stop_and_remove` deliberately keeps `SERVICE_ALL_ACCESS`.** Narrowing it to
  `SERVICE_STOP|DELETE|SERVICE_QUERY_STATUS` (0x10024) was measured and does NOT help: a
  hardened service denies `DELETE` itself. The only honest improvement there is the message.
- **`_advapi()` and the `SERVICE_STATUS` structure are cached** in module-level slots.
  `installed_drivers()` asks about three service names, and each call used to rebuild the
  binding, re-assign six sets of prototypes and define a fresh `ctypes.Structure` subclass.
  `ctypes.WinDLL(...)` (unlike `ctypes.windll.advapi32`) returns a NEW object per call, so
  without the cache the `use_last_error` change would have been a small regression. Both stay
  lazy: `ctypes.wintypes` does not import on Linux and CI runs on ubuntu too.
- New tests in `tests/test_driver_windows.py`:
  `test_reading_a_service_state_asks_only_for_the_right_to_read` (the regression guard - probes
  `Schedule`/`Dnscache`/`EventLog` on Windows and requires a real state back, plus a genuinely
  absent service still returning `None`), `test_advapi_and_status_type_are_built_once`,
  `test_doctor_says_it_could_not_look_rather_than_not_loaded` and
  `test_doctor_still_calls_a_clean_machine_not_loaded` (both directions of the doctor row).
- Not proven, stated plainly: no WinDivert driver was loaded on the test machine, so this is a
  correctness and robustness fix rather than a reproduced WinDivert failure. WinDivert's own
  service descriptor is probably permissive today; the point is that `--doctor` no longer
  depends on it staying that way.

### CI: one run of the test suite, under coverage

- **`.github/workflows/ci.yml`: the `tests` job ran the whole suite twice over, plus two
  overlapping subsets.** Four steps executed: `pytest tests`, then the
  `test_matchers_properties.py` + `test_cli_fuzz.py` subset, then `test_concurrency_chaos.py`,
  then `pytest tests --cov` over everything again. `testpaths = ["tests"]` (pyproject) already
  pulls both subsets into every full run, so the middle steps re-executed tests that had just
  passed - on ubuntu and windows, on 3.10 and 3.13, four cells deep.
- **Now a single step:** `pytest tests --cov=beantester` with `COVERAGE_PROCESS_START`, keeping
  the `fail_under = 77` gate and the `coverage.xml` artifact. Nothing changed about WHICH tests
  run. The rationale each deleted step carried (why the property/fuzz suites and the chaos suite
  earn their keep) moved into a comment on the surviving step, so the reasoning outlived the
  checkmarks it was attached to.
- **Accepted trade:** a failure now surfaces as one red step instead of a named one (pytest
  still names the file and test, so diagnosis is unaffected), and the wall-clock assertions
  (`test_failsafe.py` start/stop under 0.2 s, `test_model_worker.py`, `test_audit_fixes.py`) lose
  their uninstrumented reference run. They already ran under coverage in the old gate step and
  passed; if one starts flaking, split the clean run back out.

## [0.3.0] - 2026-07-20

### GUI fix: numeric preferences went red without a reason

- **`gui/panels/settings.py`: the `Pref` NUMBER rows grew the error line the registry fields
  already had.** `_on_pref_number` caught the `ValueError` from `parse_number` and dropped it,
  keeping only `style="Bad.TEntry"` - yet that exception already carries the translated
  `errors.field_range` / `errors.field_number` text, min and max included. The same window
  rendered the row limit through `ControlForm`, which does show it (`form.py::validate_section`),
  so one dialog answered the user's "what is allowed here?" for one field and stonewalled for the
  other two.
- **Shape copied from `ControlForm`, not invented:** one `Bad.TLabel` per `PREF_GROUPS` group
  (`wrapping_label`, packed only while non-empty so the card keeps its height), reasons joined
  with the same `"  •  "` separator, live messages kept per pref key in `_pref_messages` so
  fixing one field clears only its own reason. `_pref_errors[group] = (label, number_keys)`.
- No new i18n keys and no registry change: `prefs.py` is untouched, the text comes from the
  `errors.*` keys that already exist in both languages (convention 9 needs nothing here).
  Persisting is unchanged - an invalid value still never reaches `App.set_pref`.
- Tests: `test_prefs.py::test_settings_window_number_field_says_why_it_is_red` asserts the reason
  appears with its bounds, that a second bad field in the group ADDS a reason instead of replacing
  it, that fixing one field clears only its own, and that the last fix unpacks the line again.

### GUI fix: the running-state icon never reached the main window (Tk `-default` trap)

- **`gui/icon.py`: new `show_running_icon` / `show_idle_icon`** (over `_set_icon`), called from
  `App._sync_running_ui` in place of the bare `root.iconphoto(True, icon)`.
- **Root cause:** `iconphoto(True, img)` is Tk's `-default` - the icon for toplevels created
  from then on. On Windows it lands on the window CLASS, and a window owning an icon of its own
  keeps that one; the main window owns `bean.ico` from `apply_window_icon`'s `iconbitmap`. So
  the swap was a no-op where it mattered and DID paint the dot on the next Toplevel opened
  (the close-confirmation dialog), which is how the owner spotted it. Measured, not guessed:
  `WM_GETICON` on the toplevel returned the same `HICON` before and after `iconphoto(True, ...)`
  and a different one after `iconphoto(False, ...)`. Both calls are kept - `False` for this
  window, `True` so panels opened later carry the state too.
- **Idle restores through `iconbitmap(bean.ico)`, not the photo.** `bean.ico` ships 16/24/32/48/
  64/128/256 px frames; `bean.png` is 256 px only, so restoring through the photo would leave
  the taskbar on a downscale of it permanently after the first capture. Windows-only, guarded,
  falls back to the photo.
- The 0.2.0 entry below ("swaps `root.iconphoto` between an idle and a running icon") described
  a feature that only half-worked on the one platform this tool targets.
- Tests: `test_gui_state.py::test_the_running_icon_lands_on_the_window_not_just_the_default`
  asserts the swap hits BOTH the window and the default. Needed a fake that can see it -
  `fake_tk.Root` now records `iconphoto`/`iconbitmap` into `kw["icons"]` instead of swallowing
  them in `W.__getattr__`. Verified to fail pre-fix with `[('default', ...)]` alone. Limits:
  the fake can only prove which call we make - that Windows repaints the taskbar is not
  testable here (convention 41: confirmed by render).

### GUI fix: a widened throughput chart crept into its new window instead of filling it

- **`App._reconcile_chart_len` now zero-pads when GROWING** (new `App._resized_hist(hist, n)`).
  Two paths build the history and only one padded: `__init__` creates
  `deque([0] * n, maxlen=n)`, while the reconcile did `deque(hist, maxlen=n)` - correct when
  shrinking (the deque drops the oldest itself), but on a grow it left `len` at the OLD value
  and only raised `maxlen`.
- **Why it was visible:** `chart.draw_throughput_chart` labels the X axis from
  `len(down_hist) * sample_interval_s`, so raising `chart_seconds` from ~20 s to 250 s left the
  axis reading "-28 s" and counting up one sample per `TICK_MS`, ~4 minutes to fill, while
  `stats._throughput_title` reads the preference directly and said 250 immediately - breaking
  the invariant its own docstring promises ("never drifts from the live X-axis label"). The
  series is also drawn across the full plot width (`x = i / (len - 1)`), so the horizontal
  scale crept with every tick. `chart.py` and `stats.py` are unchanged: with `len == maxlen`
  restored as an invariant, both are already right.
- Tests: `test_prefs.py::test_a_resized_chart_spans_its_whole_window_at_once` (len matches the
  window after growing AND shrinking, newest sample stays newest, padding lands on the left).
  Verified to fail on the pre-fix code with `(171, 357)`. The existing
  `test_chart_history_length_follows_the_preference` asserted `maxlen` only, which was correct
  throughout - the bug lived in `len`, which is what the axis is computed from.

### GUI: dark mode for the parts Windows draws itself (system menu, menu frames)

- **New `theme.apply_dark_app_mode()`**, called once from the top of
  `theme.apply_dark_titlebar` (module flag `_app_mode_applied`, one attempt per process).
  Piggy-backed there deliberately: `App`, every `PanelWindow` in the registry and `dialogs.py`
  already call `apply_dark_titlebar`, so no window can ask for a dark frame and still get a
  white system menu - and no caller needed changing.
- **Why a second mechanism at all:** `DWMWA_USE_IMMERSIVE_DARK_MODE` is a PER-WINDOW attribute
  and only covers the DWM-drawn frame. The system menu (title-bar icon / Alt+Space) and the
  frame user32 puts around a classic `tk.Menu` popup follow a PROCESS-WIDE flag in undocumented
  `uxtheme` exports instead, which nothing in the package was setting - so every window had a
  white system menu, and the Connections context menu kept the light rim noted in convention 41
  ("Tk reaches the entries but not the system-drawn frame").
- **Implementation:** `uxtheme` ordinals 135 (`SetPreferredAppMode`, `AllowDarkModeForApp` on
  1809) and 136 (`FlushMenuThemes`). `ForceDark` (2), not `AllowDark` (1): the UI is dark
  unconditionally, so following the system theme would leave a light menu for a user running
  Windows in light mode. The flush is required - the menu theme is cached per process and is
  already light by the time we get here. Gated on `sys.getwindowsversion().build >= 17763`
  (first build with these exports), wrapped in `crashlog.note` (convention 30): the exports are
  undocumented, and the worst case on failure is the light menu we had before.
- Side effect, accepted by the owner: the native `filedialog` pickers render dark now. They stay
  native on purpose (see the `dialogs.py` docstring) and dark is the consistent look.
- **No test guard.** This is pixels painted by the OS outside the widget tree - the tkinter
  fake cannot observe it and `tools/ci_gui_render.py` only sees the client area. Verified by
  render on Windows 11 build 26200 (convention 41: check live, not from the code).

### GUI fixes: truncated About text, a button left highlighted, and a render check that lied

- **`panels/about.py` uses `labels.wrapping_label` for every prose line** (author, copyright,
  licence, licence terms, the no-telemetry line, the third-party heading). A plain `ttk.Label`
  never wraps - it is CUT at the frame edge - and the helper written for exactly this was not
  being used here. `pad` is `2 * 12 + 16`: the `padx` on both sides plus the few pixels a wrapped
  `ttk.Label` requests on top of its `wraplength` (measured against the render check, not
  guessed - at `pad=30` the widest wrapped line still overhung by 12 px).
- **`App._release_focus()`, called from `App.open_window`.** ttk gives a button keyboard focus
  when it is clicked and `theme.py` paints `focus` exactly like `active` (both -> `BTN_HOVER` +
  `ACC` border), so closing a window handed focus back to the button that opened it and it kept
  looking hovered. Focus goes to the toplevel instead, and the invoking widget's `active`/`focus`
  flags are cleared - the same remedy `theme.unhighlight_combobox` applies to a readonly combobox.
- **`tools/ci_gui_render.py` now FAILS on a truncated label** instead of filing every clipped
  label under "it probably wraps". The split is `wraplength > 0` -> note (it re-wraps), no
  `wraplength` -> `TRUNCATED LABEL`, which is a real defect. This check had been printing the two
  About lines as harmless notes for as long as they had been broken.
- **The render check also opens EVERY window in the `WINDOWS` registry** (it only ever opened
  About), and runs against an **empty user state** - `UiStateStore`/`ProfileStore` are pointed at
  a temp dir like `tests/gui_harness.py` does. It was reading the developer's own
  `bean_network_tester_ui.json`, so the `--lang en` pass rendered whatever language that file
  remembered (the "en" run was reporting Polish strings), and a saved geometry could have hidden
  the very clipping the check exists to find.
- **`tests/fake_tk.py`** models keyboard focus (`FOCUS`, `focus_set`/`focus_get`) and ttk state
  flags (`W.states`, `state(["!active"])` sets/clears; `Root.state()` still answers `"normal"`,
  since a toplevel's `state()` is the window state, not ttk flags).
- **Tests:** `tests/test_windows.py::test_opening_a_window_takes_the_highlight_off_the_button_that_opened_it`
  and `::test_every_prose_label_in_the_about_window_can_wrap`. Both were confirmed to fail against
  the pre-fix code, and the render check was confirmed to report `2 truncated label(s)` on it.

### GUI: focus is a ring, hover is a fill (they used to be the same picture)

- **`gui/theme.py`: every `("focus", <colour>)` entry that duplicated the style's `("active",
  <colour>)` is gone** (`TButton`, `Accent`, `Stop`, `Dirty`, `Help`, `Donate`, `Section`,
  `Gear`). Hover keeps the fill; focus is drawn by clam's **`Button.focus` element** through
  `focuscolor` (`focusthickness=1`, `focussolid=True` on `TButton`, inherited by the derived
  styles; the coloured buttons keep their own ink colour, because an accent ring on an
  accent-blue button is invisible). Measured, not assumed: at thickness 1 the ring costs no
  space (a button is 82x31 either way) and at 3 it grows to 86x35 - which is why this one
  number is not `scaled()`.
- **`tools/ci_gui_render.py` fails when a style paints `focus` and `active` the same.** The
  styles it checks come from two places, neither hand-kept: the widgets actually on screen, plus
  every name `theme.py` configures or maps (regex over the module source) - `Stop.TButton` only
  exists while a capture runs and `Dirty.TButton` only while the form is dirty, so a screen walk
  alone missed exactly the styles nobody looks at. Against the pre-fix theme it reports all 8
  offending styles; after the fix, none.
- Theme module docstring gained the rule as a third invariant, next to "no hard pixels" and
  "a disabled widget must look disabled". This is the other half of the "button left
  highlighted" fix above: that one stops focus LANDING on the button, this one stops focus from
  being painted as hover in the first place.

### GUI fix: a tooltip covered the whole row, not the text

- **A tooltip belongs to a WIDGET, so a label packed `fill`/`expand` shows its bubble over the
  blank space next to the sentence.** Measured on real Tk at 1366x768: `App.summary` was **508 px
  wider and 17 px taller than its own text** (it filled the fixed-height summary strip), so the
  bubble fired over empty header background nowhere near the line it explains. Same shape, smaller
  numbers, on the two `wrapping_label` scope notes (`pages/stats.py` 118 px, `pages/conns.py`).
- **Fix:** pack them to their content - `App.summary` -> `side="left", anchor="nw"`, both scope
  notes -> `anchor="w"` instead of `fill="x"`. A `wrapping_label` does NOT need `fill` to wrap:
  `labels.bind_wraplength` follows the PARENT's `<Configure>`, so the wrap width is unchanged.
- **Test:** `tests/test_gui_layout.py::test_a_tooltip_never_covers_empty_space` - walks all three
  pages and fails on any LEAF widget that has a tooltip, carries `text`, no `command`, and is
  packed with `fill`/`expand`. Containers are exempt on purpose (a stat tile or a `LabelFrame`
  with a tooltip does answer for everything inside it), and so are entries/comboboxes/buttons,
  where the whole box is the control. Confirmed to report all three offenders before the fix.

### GUI: the profile picker is a ttk.Combobox again (convention 41)

- **`gui/pages/control.py::_build_profiles`: `ttk.Menubutton` + `tk.Menu` -> `ttk.Combobox`**
  (readonly, no named style - the shared `TCombobox` look), bound to
  `App.on_profile_selected` (`unhighlight_combobox` + `load_selected_profile`), i.e. exactly
  how the traffic filter is built in `form.py`. The menu was introduced so group headings
  could be rendered non-pickable, but the headings had already been dropped from the menu, so
  all it still bought was a dropdown that could not be made to match: **on Windows a `tk.Menu`
  is a native Win32 popup**, so its frame (a light system border), its width (no `-width`
  option, so it is sized to the longest label instead of to the button) and the highlight on
  the current entry are outside Tk's reach - no amount of styling closes that gap.
- **Group headings dropped entirely** (owner's decision, convention 41: every row in a list
  must DO something). `App.profile_names()` is now `presets + own profiles`, full stop;
  `App._profile_separators` and the snap-back branch in `App.load_selected_profile` are gone,
  `_is_reserved_profile_name` is down to the preset check (a user profile may now be called
  "Presets"), and the `profiles.presets_separator` / `profiles.mine_separator` keys are
  deleted from `lang/en.json` + `lang/pl.json`. `smoke_gui.py`'s separator check is replaced
  by one asserting the picker offers presets then own profiles and nothing else.
- **Removed:** `App._rebuild_profile_menu`, `App._post_profile_menu` (a workaround for the
  Menubutton's post-on-mouse-down toggle - a combobox has no such problem), the
  `App.profile_menu` attribute, the `Profile.TMenubutton` layout/configure/map and the bare
  `TMenubutton` styles in `gui/theme.py`, and the `like_combobox` parameter of
  `theme.style_menu` (context menus were its only other caller). `App.profile_mb` ->
  `App.profile_cb`.
- **`theme.popdown_height(values)`** (+ `POPDOWN_ROWS = 20`) is now the single source for the
  "a list that fits must not spawn the popdown scrollbar" rule, used by the profile picker,
  the traffic filter (`form.py`) and the language box (`panels/settings.py`), which each had
  their own `height=len(...)`. The profile list is the only one the user can grow without
  limit, hence the cap at ttk's own default rather than a dropdown taller than the screen.
  `App._sync_profile_widgets` now refills `values=`/`height=` instead of rebuilding a menu.
- **Tests:** `test_gui_release_fixes.py::test_profile_menu_has_no_indicator_gutter` and
  `::test_profile_picker_uses_the_combobox_field_style` (both about the retired Menubutton)
  replaced by `::test_profile_picker_is_the_same_widget_as_the_traffic_filter`, which checks
  the built widget (readonly, no style override, `values` == `profile_names()`, `height` ==
  item count) AND greps `gui/pages/control.py` for `Menubutton`/`tk.Menu(`, so the imitation
  cannot come back.
- **PROJECT_NOTES convention 41** rewritten with two lessons: same role -> same widget (do not
  imitate a sibling widget with styles - the imitation has a ceiling that is invisible in the
  code), and every row in a list must do something. The stale "405 keys per lang file" figure
  in the repo-structure section (really 465) was replaced by the command that counts them -
  a number copied out of its source file drifts, which is exactly what convention "one fact,
  one source" is about.

### GUI fix: "restore the last profile" ignored the user's own profiles

- **`App._set_profile_key(key)` is now the single writer of `_profile_key`** (`gui/app.py`).
  Three paths change the current profile - `select_profile`, `save_profile`, `delete_profile` -
  but only the first also wrote `ui["profile"]`, the key the `restore_profile` preference reads
  on startup. Since **saving** is how a user ends up on their own profile, the preference
  restored the preset picked before the save; picking an own profile from the list already
  worked, which is why this looked like "it does not work for custom profiles". `delete_profile`
  now remembers the fallback (`DEFAULT_PROFILE`) instead of the deleted name.
- **The key is persisted on the spot** (`ui.persist()` inside `_set_profile_key`), the rule
  `set_pref` already follows: a deliberate user choice must survive an unclean exit, unlike
  session state written in `on_close`. One small atomic write per profile change.
- **`App.__init__` keeps a plain `self._profile_key = DEFAULT_PROFILE`** (commented): routing it
  through `_set_profile_key` would write the default into `ui.json` before
  `_restore_last_profile` reads the remembered one.
- **`_restore_last_profile` clears a dead pointer**: a name that resolves to neither a preset nor
  a stored profile (deleted by hand, `profiles.json` quarantined as corrupt, removed by another
  instance) is still ignored without an error, but `ui["profile"]` is reset so the file stops
  carrying a ghost.
- **Test:** `tests/test_prefs.py::test_restore_last_profile_covers_the_users_own_profiles` -
  save remembers, delete falls back, a vanished profile is ignored AND forgotten.

### Docs: intro wording and third-party links

- **README intro (EN + PL)** reworded: leads with the product name (branding + the auto-snippet),
  compares to Clumsy/NetLimiter by what the tool *does* rather than by the driver - NetLimiter does
  not use WinDivert, and the old phrasing implied it did - and names WinDivert **via PyDivert**, both
  linked.
- **Third-party section (EN + PL):** each named component now links to its homepage/source
  (WinDivert, PyDivert, psutil, CPython, Tcl/Tk, PyInstaller).

### CI: one run per commit

- **`ci.yml` `push` trigger scoped to `master`.** With `on: [push, pull_request]` a branch that
  had an open PR ran the whole matrix twice (a `push` event and a `pull_request` event; the
  concurrency group only dedupes within one event). Now feature branches run once via their PR,
  and `master` runs on push (after a merge). Halves the Actions runs on PR branches.

### Relicense: GPLv3

- **Relicensed from the proprietary Bean Network Tester License to the GNU GPL v3.** `LICENSE` is
  now the verbatim GPLv3 text (byte-identical to `licenses/GPL-3.0.txt`, so GitHub detects it and
  the copyleft terms actually apply). Touchpoints updated in one pass: `appinfo.LICENSE_NAME` and
  `COPYRIGHT` (dropped "All rights reserved"), the `pyproject` classifier
  (`Other/Proprietary` -> `OSI Approved :: GNU General Public License v3 (GPLv3)`),
  `about.license_terms` in `lang/en.json` + `lang/pl.json`, the License and third-party sections of
  both READMEs (removed the "closed source" line), and the `THIRD-PARTY-NOTICES.md` header. Exe
  metadata (`.spec` LegalCopyright) and the About window follow automatically via the `appinfo`
  constants. No version bump (owner closes the version).
- **Test:** `tests/test_version_and_release.py` - `test_license_is_not_mit_anymore` rewritten as
  `test_license_is_gplv3` (asserts the verbatim GPLv3 text is present and the old "may not be sold"
  wording is gone); `test_no_mit_references_left_in_metadata` renamed to
  `test_no_stale_license_references_in_metadata` (also asserts the Proprietary classifier is gone
  and the GPLv3 classifier is present).

### Docs: English README is now the default

- **Swapped the README language default.** `README.en.md` (English) is now `README.md` - the file
  GitHub renders on the project page - and the Polish text moved to `README.pl.md`. Cross-links at
  the top/bottom of each file updated to point at the new names; `pyproject.readme` now points at
  `README.md`.
- **Tests:** `tests/test_readme_guards.py` and `tests/test_cli_docs.py` - `READMES` tuple and the
  per-language pipeline guards retargeted (`test_english_readme_pipeline_matches_core_decide` reads
  `README.md`; `test_polish_readme_pipeline_keeps_lan_and_blocking` reads `README.pl.md`). No new
  tests, same guarantees against the new filenames.

### CI: release workflow and GitHub repo furniture

- **New `.github/workflows/release.yml`.** Tag push `v*` -> assert the tag matches
  `VERSION.txt`, build the onedir exe from `BeanNetworkTester.spec`,
  smoke it, zip it as `BeanNetworkTester-<tag>-windows-x64.zip`, write `SHA256SUMS.txt` (the
  checksum the README tells users to verify), and publish a GitHub Release via the preinstalled
  `gh` (job token, `contents: write` scoped to the workflow; no third-party action). A
  `v<version>-rc.N` (or `-beta.N` / `-alpha.N`) tag publishes as a GitHub Pre-release; a plain
  `v<version>` tag as Latest. The tag's base version must equal `VERSION.txt`. `ci.yml` is
  unchanged.
- **Repo furniture:** `SECURITY.md` (private vulnerability reporting, tool-specific scope),
  `.github/FUNDING.yml` (Sponsor button -> the project support page),
  `.github/ISSUE_TEMPLATE/` (bug-report + feature-request forms tailored to the tool: version,
  Windows, GUI/CLI/simulate, elevation, `--doctor`; plus `config.yml` disabling blank issues and
  linking support + security advisories), and `PULL_REQUEST_TEMPLATE.md` (checklist keyed to the
  project conventions: tests, both lang files, both changelogs, Conventional Commits, no bump).
- `dependabot.yml` already covered `pip` + `github-actions` - left as is.

### Repo: line endings, code of conduct, README badges

- **`.gitattributes`** pins text files to LF (`* text=auto eol=lf`; `*.png` / `*.ico` binary),
  ending the "LF -> CRLF" checkout churn on Windows and giving the Linux/Windows CI runners
  identical bytes. `git add --renormalize` was a no-op (the repo already stored LF), so no
  content changed.
- **`CODE_OF_CONDUCT.md`** (Contributor Covenant 2.1) completes the GitHub community profile;
  README, LICENSE, CONTRIBUTING, SECURITY and the issue/PR templates were already present.
- **README badges** in both languages (CI status, latest release, downloads, GPLv3, Windows).

### Repo: release-note grouping, downloads script, WinDivert link

- **`.github/release.yml`** groups the auto-generated release notes by PR label
  (New features / Bug fixes / Performance / Documentation / CI / Other) instead of one
  flat list.
- **`tools/downloads.py`** prints per-release, per-asset GitHub download counts via the
  public API (stdlib only, no token). The README downloads badge shows the same total live.
- **README (EN + PL):** the first WinDivert mention now links to its homepage
  (`reqrypt.org/windivert.html`).
- CodeQL and `dependency-review-action` are deferred to just after the repo goes public
  (both need a public repo or GitHub Advanced Security); steps are in the Doc repo runbook.

### Docs: README polish for the public repo

- Table of contents is now **expanded by default** (removed the `<details>` fold) in both READMEs.
- Added a **Contributing** section linking `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` and `SECURITY.md`.
- Added a short **AI-assisted-workflow disclosure** to the Author section.
- Section order left intact - a full read confirmed it was already logical and public-ready, so no
  reshuffle (would have been churn against the guards for no reader benefit).

### GUI: Settings window

- **New "surface" split of the field registry.** `fields.Section` gains `surface`
  (default `"control"`); the `tables` section is marked `surface="settings"`. Added views
  `CONTROL_SECTIONS` / `SETTINGS_SECTIONS`. The Control page and the Settings window are now
  both renderers of one registry: a new preference is one entry with `surface="settings"` and
  it renders itself (widget, label, unit, live validation) - no second code path. `row_limit`
  (still `ui_only`, convention 37) is the first field to move.
- **`gui/form.py::ControlForm` takes `sections=`** (defaults to `CONTROL_SECTIONS`); all its
  `SECTIONS` loops now read `self._sections`. `SECTION_BY_ID` stays a full lookup. The Control
  page passes the default; the Settings window passes `SETTINGS_SECTIONS`. Shared `app.vars`
  keep both forms in sync (a config-file load updates the Settings entry live).
- **New window `gui/panels/settings.py` (`SettingsWindow`, ID `settings`)** via the window
  registry (convention 25): language combobox (bound to the App's `lang_var`, locked mid-session
  like before) + `ControlForm(sections=SETTINGS_SECTIONS)`. Registered in `panels/__init__.py`.
- **`gui/app.py`**: header language combobox+label replaced by a gear button opening the
  Settings window (`Gear.TButton` in `theme.py`, icon from new `icon.make_gear_icon`, pure
  `PhotoImage.put`, DPI-scaled). `lang_var` / `_lang_name2code` still built in `_build_ui`
  (smoke and `_switch_language` depend on them); `lang_cb` is now owned by the Settings window
  (set on build, `None` on close). `_sync_running_ui` skips `lang_cb` when `None`.
- New i18n keys (both files): `windows.settings`, `buttons.settings`, `tips.settings`.
- `theme.apply_dark_titlebar` now forces a non-client repaint (`SetWindowPos` SWP_FRAMECHANGED)
  after setting the DWM attribute, and `windows.PanelWindow.open` re-asserts it once the window
  is mapped: a Toplevel shown without being activated (opened while the main window keeps focus)
  used to keep a white title bar until first click. Fixes it for every registered window.
- Dead-entry cleanup: `gui/app.py::FIRST_RUN_COLLAPSED` no longer lists `"tables"` (that section
  is settings-surface, rendered `collapsible=False`, so the collapse hint did nothing).
- Tests: `test_windows.py::test_settings_window_holds_the_language_box_and_the_view_fields`
  (row_limit renders in Settings, not on the Control page; no Control field leaks in; language
  box owned + rebound across a language switch + dropped on close). Updated
  `test_gui_layout.py::test_stop_button_and_language_picker_reflect_the_session` and
  `test_gui_release_fixes.py::test_short_dropdowns_do_not_spawn_a_popdown_scrollbar` to open the
  Settings window before asserting on `lang_cb` (it left the header). Added
  `test_windows.py::test_settings_sections_render_open_and_do_not_touch_collapse_state` (the
  clobber guard: two ControlForms must not fight over `app.collapsed_sections`) and, in
  `test_field_registry.py`, `test_sections_split_cleanly_by_surface` +
  `test_ui_only_fields_live_on_the_settings_surface` (convention 42 / 37 invariants).

### GUI preferences (ui.json-backed)

- **New `gui/prefs.py`** - a small preference registry *separate* from `fields.FIELD_DEFS`.
  `Pref(kind=NUMBER|BOOL|ACTION)`; `PREFS` + `PREF_GROUPS`. These persist in `*_ui.json` under
  `pref.<key>` (never in a traffic config file, never a CLI flag). `App.pref(key)` reads+validates,
  `App.set_pref(key, v)` writes through and persists immediately (a preference must survive an
  unclean exit). `SettingsWindow` renders the groups (numbers with live `parse_number` validation,
  checkbuttons, and an action button). See convention 42 for the two-kind model (registry
  `surface="settings"` field vs a `Pref`).
- Wired behaviours in `gui/app.py`:
  - `chart_seconds` -> `App.chart_samples()` (seconds / tick period) sizes the throughput deques;
    `_reconcile_chart_len()` resizes them live in `_sample()` (keeps the most recent samples).
  - `log_lines` -> `_append_log_line` trims `_log_lines` and the Text widget to the preference
    (with a +100 hysteresis so it is not an every-line reslice); the rebuild-restore uses it too.
  - `confirm_close` -> `on_close` only prompts when the switch is on.
  - `restore_profile` -> `_restore_last_profile()` (startup only, never on a language rebuild)
    refills the form from the saved `ui.json` "profile"; `select_profile` now persists that key.
    Fills the form only, never auto-applies (convention 15).
  - `reset_ui_layout()` (the `reset_layout` action) clears geometry / page / collapsed / sorts /
    sash and the `window.*` geometries back to `ui_state.DEFAULTS`, then recentres and rebuilds.
  Note: driver cleanup on exit was NOT added - `driver.release_on_exit` (called from `on_close`)
  already unloads the driver when a run loaded it, so a toggle would only disable useful behaviour.
- `gui/app.py::FIRST_RUN_COLLAPSED` unchanged here; `README.md`/`README.en.md` project layout lists
  `prefs.py`. New i18n keys (both files, and both files re-sorted to the documented key order):
  `prefs.*` (labels/units/hints/groups), `tips.chart_seconds|log_lines|confirm_close|restore_profile|reset_layout`,
  `dialogs.reset_layout_title|body`, `log.layout_reset`.
- Tests: `tests/test_prefs.py` - registry (every pref grouped once; all texts resolve in en+pl;
  `coerce` clamps/falls back), accessors (round-trip + persistence), and each wired behaviour
  (chart resize, log trim, confirm-close honoured, restore-on-start fills only when enabled,
  reset-layout forgets window state). Extended
  `test_windows.py::test_settings_window_holds_the_language_box_and_the_view_fields` to assert the
  pref widgets render.

### Startup / performance

- `bean_network_tester.py`: the launcher facade now resolves the GUI (`App`, `Tooltip`,
  `add_tooltip`, `make_bean_icon`) LAZILY via a module `__getattr__` (PEP 562), mirroring
  `beantester/gui/__init__.py`, instead of an eager `from beantester.gui import App` at module
  load. Importing the launcher no longer pulls in `tkinter` or the `gui/` package. This matters
  on the GUI-launch path: with `asInvoker` + `winenv.elevate_self` (convention 19) a non-admin
  start spawns a second elevated process, and the doomed pre-elevation process used to import
  all of `gui/` (and Tk) for nothing before relaunching. Verified: `import bean_network_tester`
  leaves `tkinter` out of `sys.modules` until `App` is first accessed; `_HAS_TK` is still
  exposed (computed lazily). Guard `test_launcher_compat.py` stays green (it asserts the
  engine/CLI API surface, not GUI symbols).

- `gui/app.py`: START/STOP no longer block the Tk main thread. The blocking parts - the psutil
  target resolution + `engine.start()` (WinDivert driver load, ~0.5-1 s) and `engine.stop()`
  (worker-thread joins) - now run on a short-lived worker via `_begin_transition(kind, work)`.
  The worker leaves `(kind, err)` on a new `self._ui_queue`; `_tick` drains it (`_drain_ui_queue`)
  and applies the result on the main thread (`_finish_start` / `_finish_stop`), exactly like the
  log queue and the target-warning handoff (convention 26 - no widget touch off the main thread).
  While in flight, `self._transition` is `"starting"`/`"stopping"`; the button keeps showing
  START/STOP with NO transitional label (owner UX decision: the work is normally milliseconds -
  measured driver open ~6 ms on a warm driver - and a second click is a no-op while a transition
  is set, so there is nothing to relabel or disable). `_poll_transition` re-arms via
  `root.after(30 ms)` so the button flips as soon as the worker finishes instead of on the next
  `_tick` (the fake-tk `after` never fires, so tests drive it through `_settle_transition`).
  `_refresh_start_enabled` early-returns during a transition, and the `_on_engine_stopped` trigger
  in `_tick` is gated on `_transition is None` so a mid-stop tick does not fire it early. `on_close` sets
  `self._closing` before `engine.stop()`; a start finishing after that does not resurrect the UI,
  and `engine.stop()` still serialises on the engine's `_stop_lock`, so no divert can leak
  (fail-open, convention 20). `_settle_transition()` (join worker + drain) lets a headless test
  drive the async path deterministically.

### Engine / filters

- New `drop_shutdown` counter (`engine.py`). `BeanEngine.stop()` records `len(self._heap)`
  before clearing the delay queue, so packets captured but never injected (parked in the queue at
  STOP) are accounted for instead of vanishing from the seen/delivered/dropped balance. Seeded in
  `reset_stats`; bumped once under `_slock` after releasing `_cv` (the cv->slock order matches
  `_enqueue`). Flows into the NDJSON summary `counters` automatically - `cli.py` builds
  `counters=stats_snapshot()` AFTER `engine.stop()`. NOT added to the per-interval `sample` record
  (only ever nonzero at STOP). Additive to the NDJSON schema (a new key; existing keys unchanged),
  so NOT a `### BREAKING` change - same as earlier counter additions (`drop_rate`, `drop_block`).

- New `loopback` traffic filter: one entry in `filters.py::FILTER_DEFS`
  (`loopback and (ip or ipv6) and (tcp or udp or icmp or icmpv6)`). Combobox order and
  `--filter` choices derive from the registry, so no GUI/CLI code changed; i18n key
  `filters.loopback` added to both lang files; both READMEs' filter prose + `--filter` row updated.
  Covered by the existing `test_presets_filters.py::test_every_filter_covers_ipv4_and_ipv6`.
  Confirmed on real WinDivert (elevated Windows run): `--filter loopback --latency 200` took
  `ping 127.0.0.1` RTT from <1 ms to ~408 ms avg (200 ms each direction) and the packet counter
  tracked the loopback traffic, so WinDivert captures and reinjects 127.0.0.1/::1 correctly.

### GUI

- `drop_shutdown` shown in the live counters grid: entry in `gui/pages/stats.py::STAT_ROWS`
  (after `drop_overflow`) plus the key added to the hardcoded tuple in `refresh_counters`; i18n
  keys `stats.shutdown_dropped` + `tips.stat_shutdown` in both lang files. Label/tip deliberately
  reassuring, because it is routinely nonzero on any stop that used latency or a speed limit
  (packets were queued, not lost in transit). CSV column `dropped_at_stop` added to
  `App.CSV_COLUMNS` (every `drop_*` counter has a friendly `dropped_*` name).

- `tips.stat_corrupted` reworded (both lang files). `corrupted` counts successful payload
  bit-flips only: `BeanCore.corrupt_packet` returns False for a payload-less packet (bare ACK)
  and the engine never bumps the counter, so on real TCP traffic it trails the configured
  corruption percentage. The tooltip now says so. Behaviour unchanged - correct, since there is
  no payload to corrupt.

- Per-field "?" help sheet generalised beyond filter expressions. `fields.Field` gained
  `help_title` / `help_body` (i18n keys, default ""); `gui/form.py::ControlForm._place_one`
  renders the existing `Help.TButton` for any field declaring `help_body` (new `_show_field_help`,
  opens `dialogs.show_help`), in an `elif` after the `kind == EXPR` branch. Hover shows the field's
  own `tip`, a click opens the sheet. The `buffer` field now declares
  `dialogs.buffer_help` / `dialogs.buffer_help_title` (new keys in `lang/en.json` + `lang/pl.json`).
  `settings.DEFAULT_SETTINGS["buffer"]` changed 2000 -> 1000 ms (rate-limiter link buffer,
  `BeanCore.buffer_s`): not a public contract (no test asserts the default; `--buffer` and
  `core.set_buffer` unchanged). Chosen after a measurement sweep - delivered rate is accurate at
  every buffer and under sustained overload loss converges regardless, so the buffer only trades
  added latency against onset-of-loss; 1000 ms halves worst-case added latency and tracks sub-2 s
  schedule steps. Both READMEs updated.

- Control-page jitter on START/STOP: `form.py::ControlForm` no longer `pack`/`pack_forget`s the
  per-section override/lock note. The label is packed ONCE at build time (in `_place_fields`) and
  kept mapped; `apply_overrides` now only sets its `text` ("" when idle). An empty `ttk.Label`
  reserves the same one-line height as a full one (measured), so the section height is constant and
  the scrolled form stops reflowing/jumping when the `fields.locked_running` note appears at START.
  Guard already present: `test_gui_layout.py::test_schedule_overrides_greys_the_constant_limits`
  asserts the note text is `""` when idle (unchanged by this fix).

- Profile picker styling (`theme.py`, `pages/control.py`): `Profile.TMenubutton` now uses the flat
  `Menubutton.indicator` arrow inside `Combobox.field` instead of `Combobox.downarrow`. clam draws
  the downarrow as a bordered, sunken button (a lighter `BORDER`/#39404e box) which read as a
  "white arrow" next to the flat traffic-filter combobox; the indicator is a bare triangle.
  `style_menu(menu, like_combobox=True)` paints the profile dropdown on `FIELD` (matching the
  `*TCombobox*Listbox` popdown colour) instead of the `BG2` card colour; context menus keep `BG2`.

- Connections avg column: extracted `views.avg_packet_bytes(c)` (rounds `bytes / max(1, packets)`)
  and routed BOTH `conns.py::_render` and `App.export_connections_csv` through it. They had
  duplicated the formula and diverged - the table rounded (`f"{avg:.0f}"`), the CSV floored
  (`bytes // packets`), so 767.5 B/pkt read 768 on screen and 767 in the file. Tests:
  `test_views.py::test_avg_packet_bytes_rounds_like_the_table` and
  `test_conns_export.py::test_export_connections_csv_avg_matches_the_table_rounding`.

- Session average throughput: extracted `rates.average_kbps(total_bytes, elapsed_s)` (pure) and
  used it in `pages/stats.py`; the figure was computed inline from a MB value already rounded to
  two decimals, now it divides the full-precision byte count. Test:
  `test_gui_helpers.py::test_average_kbps_is_total_bytes_over_elapsed`.

- Release-polish pass (bug fixes + UI cleanup):

- Running-state chrome: `App._sync_running_ui` now also sets the window title
  (`APP_NAME` + `T("app.title.running")` tag) and swaps `root.iconphoto` between an idle and a
  running icon. Both flow through the ONE place already called after every start/stop and every
  language-switch rebuild, so the tag/icon never desync (same reason status/filter live there).
  `gui/icon.py`: `make_bean_icon(active=)` stamps a red recording dot (`_put_dot`); `_running_variant`
  copies the idle PhotoImage (keeps a user `bean.png`'s art) and stamps the dot, falling back to a
  drawn active bean. `apply_window_icon` now returns `(idle, running)`; `App` keeps both refs
  (`_icon_idle`/`_icon_running`) so Tk does not GC them. New i18n key `app.title.running`
  (en `"● RUNNING"`, pl `"● DZIAŁA"`). CLI is untouched (GUI-only, `test_layering` still holds).
  Test: `test_gui_state.py::test_language_switch_keeps_running_state` now asserts the title carries
  the tag while running and reverts to bare `APP_NAME` on stop.

- Release-polish pass (bug fixes + UI cleanup):
  - Native crash capture is now armed LAZILY (`crashlog.arm_native`), not at launch:
    `install(native=True)` only records intent (`_arm_wanted`) and registers
    `atexit(_cleanup_native)`; it no longer opens the file. `BeanEngine._start_locked` calls
    `crashlog.arm_native()` right after `driver.mark_driver_used()` - the one moment a native
    crash becomes possible (real WinDivert loaded), so `--simulate`/tests never arm it. faulthandler
    must hold its file open before a hard crash, so it cannot be created purely on-demand, but this
    means opening the GUI leaves NO `crashes/` folder. `_cleanup_native` (atexit) closes the stream,
    removes the empty `native-crash.txt` and `os.rmdir`s an empty `crashes/`; a real segfault skips
    atexit so a genuine report survives. `reset()` clears the new native flags for test isolation.
    DEBUG-severity records still persist (owner decision).
  - Profile picker (`gui/app.py`, `gui/pages/control.py`): the `Menubutton` is now posted
    explicitly via `App._post_profile_menu` bound to `<Button-1>` (returns `"break"`), fixing the
    intermittent press/release toggle where the dropdown reopened shut. `_rebuild_profile_menu` was
    simplified to a plain `add_command` list (presets, `add_separator`, then user profiles): the
    disabled group-heading entries rendered as muddy "blurry" text and the selected-item tick (both
    the native radiobutton indicator and a hand-drawn glyph) looked wrong, so both are gone - the
    current profile shows on the button via `textvariable`. The `profiles.presets_separator`/
    `mine_separator` i18n keys are kept (still used by `profile_names`/`_profile_separators` for the
    reserved-name guard), just no longer shown in the menu.
  - Connections tint (`gui/pages/conns.py`, `gui/theme.py`): `_tag_of` is an instance method gated
    on `_scope_active` and the flow's CURRENT scope (see the dropdown/scope pass below), so the
    "impaired" tag never floods when no target narrows.
    `CONN_COLORS["impaired"]` switched from a muddy `background` to an amber `foreground`.
  - `SortableTree._on_select` (`gui/widgets/sortable_tree.py`) drops blank-slot iids from the
    widget selection (re-`selection_set`/`selection_remove`), so a click below the last real row
    no longer leaves an empty row visibly selected.
  - Chart (`gui/chart.py`): new `_axis_label(value, peak)` gives adaptive precision (int >=10,
    1 dp >=1, else 2 dp) so an idle `peak=1` axis no longer collapses to "0 0 0 1 1"; five Y
    ticks only when `ph >= scaled(70)`, otherwise two (floor + peak). i18n `frames.throughput`
    caption "~80 s" -> "~84 s" to match the axis (120 samples x 0.7 s).
  - Windows (`gui/windows.py`): `PanelWindow.open` now sets `maxsize` (`_max_size` = `SIZE *
    MAX_FACTOR` clamped by `scaling.max_window_size`) and calls `theme.disable_maximize`, so every
    registered window is capped and non-maximisable like the main window (convention 25, updated
    in PROJECT_NOTES).

- Tooltips are suppressed while a Tk grab is held (`gui/tooltip.py`): new `_grab_active(widget)`
  guards the shared `_show_bubble`, so a field's bubble no longer draws over an open combobox
  popdown (the list the user just opened). Detection uses the raw `grab current` Tcl call - the
  ttk popdown is a Tcl-only window, so `Misc.grab_current`/`_nametowidget` raises on it;
  `grab_current()` stays as a fallback for the test double (no `.tk`). Same pattern as
  `WheelDispatcher._popdown_open`. Silence goes through `crashlog.quiet` (convention 30), not
  `except: pass`. Modal dialogs also grab but carry no tooltips and block background hover events,
  so nothing regresses.

- Dropdown/combobox polish pass (screenshot-driven, on the Connections/Control pages):
  - Scenario dialog (`gui/app.py::load_scenario`) passes `initialdir=paths.scenarios_dir()`; new
    `paths.scenarios_dir()` resolves the bundled `scenarios/` via `_resource_bases()` (same pattern
    as `lang_dir`), so it points at `_MEIPASS`/`_internal` when frozen. Single source for the path.
  - `theme.unhighlight_combobox` now also hands focus to the widget's `master` after a pick: a
    readonly combobox kept keyboard focus after a mouse selection, so the accent focus ring
    (`TCombobox` map `bordercolor=[("focus", ACC)]`) lingered as a stuck highlight. Applies to the
    traffic filter (`form.py::_on_choice`) and the language picker (`app.py`). Silence via
    `crashlog.quiet` (convention 30).
  - Readonly comboboxes get `height=len(values)` (`form.py` CHOICE field, `app.py` language picker):
    a list that fits no longer spawns the popdown scrollbar, which renders as a light `SCROLL_BG`
    bar over the near-black listbox. Confirmed by pixel probe: the bar was the themed scrollbar
    (#3a4150), not an unstyled one - it just should not appear for a 6-item list.
  - `_rebuild_profile_menu` (`app.py`) adds `hidemargin=True` to every `add_command`: tk.Menu
    reserved an indicator gutter for the check/radio tick that was removed, leaving a stray indent.
  - Profile picker now uses `Profile.TMenubutton` (`gui/theme.py`, applied in `gui/pages/control.py`):
    a custom layout that borrows the combobox's own `Combobox.field` + `Combobox.downarrow` elements
    (label from `Menubutton.label`), so it renders pixel-identical to a readonly combobox while still
    posting the grouped menu. The bare `TMenubutton` looked flat next to the traffic filter.

- Live targeting scope for the Connections view (`core.py`, `engine.py`, `gui/pages/conns.py`):
  new read-only `BeanCore.in_scope(local_port, remote_ip, remote_port)` mirrors `decide` steps 1-2
  (process + destination gates) under the core lock, plus `BeanCore.targeting_active()`; both
  delegated by `BeanEngine.in_scope_now` / `targeting_active`. The connections page recomputes a
  row's scope from the CURRENT target (`_in_scope`, called for visible rows only via
  `SortableTree.repaint`) for both the scope column and the "impaired" tag, instead of reading the
  flow's stored `scoped` (which was the LAST packet's decision - an idle flow kept a stale flag, so
  a firefox row stayed highlighted after the target was narrowed to chrome). `_build_model` now
  returns `scope_active = engine.targeting_active()` (one lock) in place of the old O(n)
  `any(scoped) and any(not scoped)` snapshot scan.

- Tooltips can advertise a keyboard shortcut (`gui/tooltip.py`, wired in `gui/app.py`): new
  `tooltip_text(key, shortcut)` appends `[F5]`-style bracket line (no translatable word -> no i18n
  key); `add_tooltip(widget, key, shortcut=)` uses it and stores the `Tooltip` on the widget
  (`_bnt_tooltip`) for tests. Wired to START/STOP (`F5`), Apply (`Ctrl+Enter`), Save (`Ctrl+S`),
  Load (`Ctrl+O`). New convention 40 in PROJECT_NOTES.

- Statistics -> Session panel now shows host identity: computer name + private IPv4/IPv6
  (`gui/pages/stats.py` `SESSION_ROWS` + `refresh_session`). Backed by a new pure helper
  `utils.host_identity() -> (hostname, ipv4, ipv6)` built on `utils._route_source_ip(family,
  probe)`, a connected-UDP-socket route lookup that puts NO packet on the wire (never
  disturbs capture) and degrades to `"-"` when a family has no route. Deliberately NOT added
  to the repro report or the NDJSON schema (privacy - the tool sends no data anywhere). New
  i18n keys `session.host`, `session.private_ipv4`, `session.private_ipv6` in both langs.
  New test `tests/test_core.py::test_host_identity` (asserts a 3-tuple of non-empty strings).
- Connections table split traffic into `down`/`up`/total (`gui/pages/conns.py`,
  `views.py`). The engine already recorded `bytes_in`/`bytes_out` per flow in `_log_conn`;
  this is presentation-only, nothing touches the capture thread. `views.DERIVED` gained
  `down` (`bytes_in`/1024) and `up` (`bytes_out`/1024) and both are in the numeric sort set;
  the existing `kb` column id is kept as the TOTAL column (unchanged semantics, only the
  label/tooltip), so the persisted default sort (`ui_state.py` `conn_sort=kb`) and its guard
  (`test_validators_settings.py`) keep working with no migration. New i18n keys `conns.down`,
  `conns.up`, `tips.col_down`, `tips.col_up` in both langs; `conns.kb`/`tips.col_kb` reworded.
- Connection table gained the per-flow columns backed by the engine work above:
  `pid`, `scoped` ("impaired?"), `dropped`, plus derived `avg` (`gui/pages/conns.py`,
  `views.py`). `views.DERIVED` gained `avg` (`bytes`/`packets`) and `scoped` (1/0 so the
  column sorts numerically); `dropped`/`pid` added to the numeric sort set. The search
  predicate was extracted to `views._filter_connections`/`_connection_blob` (one source), so
  the new `views.traffic_totals(conns, query, proc_map)` sums download/upload/total bytes
  over the SAME filtered set - computed in the worker (`_build_model`) over the whole filtered
  set, not the limited `shown`, and shown in a footer label (`conns.totals`). In-scope rows
  carry a `tag_of` -> `theme.CONN_COLORS["impaired"]` highlight. The `_render` tuple grew to
  15 values to match COLUMNS (guarded so it cannot drift). New i18n keys `conns.pid`,
  `conns.scoped`, `conns.dropped`, `conns.avg`, `conns.yes`, `conns.no`, `conns.totals`,
  `tips.col_pid`/`col_scoped`/`col_dropped`/`col_avg` in both langs.
- Connection-table CSV export: `App.export_connections_csv` (`gui/app.py`), button on
  `gui/pages/conns.py`. Reuses `views.filter_sort_connections` with the page's current
  `conn_query`/`conn_sort` and `limit=0` (the display row-limit is a render cap, not part
  of the export), so the file mirrors the visible order over the whole filtered set. Raw
  byte columns (`download_bytes`/`upload_bytes`/`total_bytes` = `bytes_in`/`bytes_out`/`bytes`)
  rather than the table's KB. Atomic overwrite (tmp + `os.replace`) to a snapshot file
  `paths.CONNECTIONS_CSV_FILE` (also exported from the package `__init__`), not an append
  log like the stats CSV. New i18n keys `buttons.export_conns`, `tips.export_conns`,
  `log.conns_saved_to` in both langs. `CONN_CSV_HEADER` now MIRRORS the table's columns:
  added `pid`, `impaired` ("yes"/"no", English like the headers - the CSV is
  language-independent), `dropped` and `avg_bytes`, so the export no longer lagged the new
  columns.

### Engine / core

- Blocking (firewall). New pipeline step 2c in `core.decide()` (documented in the module
  docstring), placed AFTER the targeting gate next to LAN mode, so a process/destination
  target scopes it. `BeanCore` gained `block_active`/`block_ip`/`block_port` + two matchers
  and `set_block(active, ip, port)` (mirrors `set_dest`); the gate is `block_ip_matcher OR
  block_port_matcher` where each side takes part only when the matcher is non-empty (an empty
  `Matcher` is falsy and would otherwise match everything - that is the OR skip-empty rule, and
  the reason blocking is NOT modelled as AND like destination targeting). Drops carry
  `reason="block"`, `scoped=True`. Two registry fields `block_ip`/`block_port` (`fields.py`,
  section `block`, kinds `KIND_IP`/`KIND_INT`+`PORT_BOUNDS`, flags `--block-ip`/`--block-port`)
  - so `MATCH_FIELDS`, `build_matchers`, form, live validation and profile scope derive
  themselves. `settings.py`: `DEFAULT_SETTINGS` gained `block_ip`/`block_port`, `apply_settings`
  calls `engine.set_block` (tolerant `try/except` like destination), `setting_expression`
  normalises `block_port`. `engine.py`: counter `drop_block` in `st`, `_bump` map entry, and a
  `set_block` delegate. Surfaced additively (no contract break): CSV column `dropped_block`
  (`gui/app.py::CSV_COLUMNS`), live stat row `stats.block_cut` (`gui/pages/stats.py`), one-line
  `summary.block`, NDJSON `sample.drop_block` and the `[bean]` text line, repro metric
  `blocked`, and the reproduce command (`repro.settings_to_cli` emits `--block-ip`/`--block-port`
  - it is a hand-maintained emitter, not registry-driven, so a missing field silently drops from
  the copy-paste repro command; guarded by the round-trip test below). New i18n keys `frames.block`, `tips.block`, `stats.block_cut`, `tips.stat_block`,
  `summary.block` in both langs; field labels reuse `fields.ip`/`fields.port`.

- Per-flow impairment bookkeeping behind the upcoming "impaired?"/"dropped" connection
  columns. `core.Decision` gained `scoped: bool = True`; the three targeting early-returns
  (process step 1, destination ip/port step 2) now pass `scoped=False`, so `scoped` marks
  whether a packet cleared the targeting gate - i.e. the flow is in scope for impairment, not
  merely observed. Every impairment path (loss, LAN, rst, nat, flap, mtu, syn, rate) keeps
  `scoped=True`. Zero added cost: same early returns. In `engine.py`, `_log_conn` now records
  `dropped` (per-flow drop count), `scoped` (latest packet's scope) and `pid`
  (`_pid_for` -> `portmap.pid_for`, resolved once at flow creation like the process name); the
  connection dict carries `dropped`/`scoped`/`pid`. The capture loop was REORDERED so
  `core.decide()` runs before `_log_conn` (decide reads none of the connection log, so the
  order is free) - one lock acquisition still records the packet plus its drop/scope. No new
  O(n) work on the capture thread. These fields flow through `connections_snapshot` into the
  repro report automatically (additive, backward-compatible).

- Bounded link buffer for the speed limit: `buffer` field (`fields.py::FIELD_DEFS`, section
  `speed_limit`, flag `--buffer`, default 2000 ms, 0 = unbounded). The token bucket can no
  longer run unbounded ahead; offered load above the cap is dropped once the buffer fills,
  which bounds the added latency to ~`buffer` ms and lets a mid-session cap increase take
  effect within that window. New counter `drop_rate` (CSV `dropped_rate_limit`), kept
  separate from `drop_flap`, from loss, and from the queue's own `drop_overflow`. A sub-byte/s
  cap now floors at 1 B/s instead of rounding to 0 ("unlimited").
- RST injection and SYN dropping are exercised off Windows: `--simulate` now carries a real
  TCP/UDP/ICMP protocol mix and the RST packet is built through the traffic source, so
  `rst_sent` moves in tests and simulation instead of only on Windows with WinDivert.

### Tests

- `tests/test_engine.py::test_packets_queued_at_stop_are_counted_as_drop_shutdown`: a 60 s latency
  parks 200 packets in the delay queue; after `stop()` it asserts `drop_shutdown == 200`, nothing
  delivered, and `seen == delivered + drop_shutdown` (the balance closes to the end of the session).

- `tests/test_gui_layout.py`: `test_only_filter_expressions_get_the_syntax_cheat_sheet` renamed to
  `test_fields_with_a_help_sheet_get_the_question_mark_button` and now asserts `buffer` is present
  in `ControlForm.helps` alongside the five expression fields (guards the generalised "?" help
  wiring from `Field.help_body`).

- `tests/test_failsafe.py::test_start_and_stop_run_off_the_ui_thread`: a slow `engine.start`/
  `engine.stop` (0.4 s sleep) proves `_start()`/`_stop()` return in < 0.2 s (do not block the UI
  thread), the button keeps showing START/STOP with no transitional label, and
  `_settle_transition()` drives the async result to `running` True/False.
  `test_the_gui_starts_the_session_with_its_duration` gained the matching `_settle_transition()`
  call now that start is asynchronous.

- Release-polish pass:
  - `tests/test_crashlog.py`: `test_launch_creates_no_crash_folder_until_a_capture_arms_it` and
    `test_arm_native_is_a_noop_when_native_was_not_requested` guard the lazy `arm_native`; plus
    `test_cleanup_removes_the_empty_native_file_and_dir` and `test_cleanup_keeps_a_non_empty_native_file`
    for `_cleanup_native` (empty file + empty dir removed on clean exit; a written report is preserved).
  - `tests/test_virtual_tables.py::test_clicking_a_blank_slot_selects_nothing` guards the
    `_on_select` blank-slot fix (clicking a blank slot clears it; a real+blank click keeps only
    the real key). `tests/fake_tk.py` `Treeview` gained `selection_remove`.
  - `tests/test_windows.py::test_a_window_is_dark_and_hidden_before_it_is_shown` gained a
    `maxsize` assertion (every window is capped, not just given a minsize).
  - `tests/test_gui_release_fixes.py::test_tooltip_is_suppressed_while_a_dropdown_is_open` guards
    the tooltip grab-guard: `_grab_active` is false with no grab, true after `grab_set()`, and
    `_show_bubble` returns `None` (short-circuits before rendering) while a grab is held.
  - `tests/test_gui_release_fixes.py`: `test_short_dropdowns_do_not_spawn_a_popdown_scrollbar`
    (filter/language comboboxes carry `height == len(values)`),
    `test_profile_menu_has_no_indicator_gutter` (every profile `add_command` has `hidemargin`),
    `test_scenario_dialog_defaults_to_the_bundled_scenarios_dir` (`paths.scenarios_dir()` exists and
    is named `scenarios`), `test_shortcut_buttons_advertise_their_key` (START/Apply tooltips carry
    `F5`/`Ctrl+Enter`), `test_profile_picker_uses_the_combobox_field_style` (Menubutton uses
    `Profile.TMenubutton`). Combobox focus-drop (#7) verified live on real Tk, not in the fake
    (fake `focus_set` is a no-op).
  - `tests/test_conns_columns.py::test_connection_columns_tag_and_footer` rewritten for live scope:
    it sets `engine.core.set_target(True, {5000})` and gives the out-of-scope svchost row a STALE
    `scoped=True`, asserting the column and tag follow the current target (svchost -> "no", no tag)
    rather than the stored flag.
- Blocking: `tests/test_core.py` gained six tests for pipeline step 2c - block by IP drops
  matching only (reason `block`, `scoped=True`), block by port ignores an empty IP field (the
  OR skip-empty rule), IP and port combine with OR (not AND like destination targeting), block
  sits after the process-targeting gate (a non-target flow passes even when its destination is
  on the block list), inactive block passes everything, and a malformed expression raises
  `ValueError`. `block_ip`/`block_port` added to `IMPAIRMENT_OFF` and `drop_block` to
  `DAMAGE_COUNTERS` in `tests/test_passthrough.py` (a new default-harm field would otherwise slip
  through). Registry-guard sets updated for the two new expression fields:
  `test_field_registry.py`, `test_settings_config_scenario.py` (MATCH_FIELDS view),
  `test_gui_layout.py` (filter fields get the syntax cheat sheet), and the hand-written fake
  engine in `test_cli_runtime.py` gained a `set_block` stub.
  `test_summary_repro_views.py::test_settings_to_cli_roundtrip` extended with `block_ip`/
  `block_port` so the reproduce command is proven to round-trip them.
- Engine and settings coverage: `test_engine.py::test_block_integration` (block drops matching
  IP and port through a real `BeanEngine`+`FakeDivert`, `drop_block == 2`, OR of the two
  fields); `test_settings_config_scenario.py` gained `test_apply_settings_bad_expression_disables_blocking`
  (tolerant path), `test_apply_settings_with_block_expressions`, `test_scenario_block_step_applies_and_clears`,
  and extends `test_apply_settings_maps_engine`, `test_config_roundtrip_keeps_expressions` and
  `test_validate_settings_rejects_bad_expressions` with block fields; `test_summary_repro_views.py::test_summary_shows_blocking`.
- `scenarios/blocked-endpoint.json` shipped (loops a backend/API outage via `block_ip` on a
  TEST-NET-3 range, then clears it) - auto-validated by `test_shipped_scenarios.py`.
- `tests/test_conns_columns.py` - drives the real `ConnsPage` on fake-tk: the 15-column
  render tuple lines up with COLUMNS, `pid`/`scoped`/`dropped` cells render, the in-scope row
  gets the `impaired` tag and the observed-only row does not, and the footer sums the filtered
  traffic. `tests/test_views.py` gained `test_traffic_totals_sum_filtered_bytes` (footer sum
  honours the search), `test_derived_avg_and_scoped` and `test_sort_by_every_new_numeric_column`
  (down/up/dropped/pid each actually order the table). `tests/test_conns_export.py` now also
  covers the connection export's new columns (pid/impaired/dropped/avg_bytes) and adds
  `test_export_csv_stats_appends_then_rotates_on_a_column_change` - the FIRST test of the stats
  CSV export at all (append, and the roll-aside-on-header-change branch).
- `tests/test_core.py::test_decision_scoped_reflects_targeting` - `Decision.scoped` is False
  only when process/destination targeting excludes the packet, True with no targeting, on a
  matching target, and on an impairment drop (LAN). `tests/test_engine.py::test_connection_records_scope_and_dropped`
  - with targeting on one port and 100% loss, only the targeted flow is `scoped` and counts
  its `dropped`; the other is merely observed; every row carries a `pid` field.
- `tests/test_engine.py::test_lan_mode_integration` strengthened: now also feeds an INBOUND
  packet from a public `src_addr`, so LAN mode is proven to cut the internet both ways
  (`remote_ip` = `dst_addr` outbound / `src_addr` inbound), not only outbound. Expected
  `drop_lan` 2 -> 3, with a LAN-bound packet still passing.
- `tests/test_conns_export.py` - guards `App.export_connections_csv`: the CSV header, the
  raw `download_bytes`/`upload_bytes`/`total_bytes` split, sort order carried into the file,
  the atomic overwrite leaving no `.tmp`, and that the current search narrows the export.
  First test to exercise a CSV export at all (the stats export was never covered).
- `tests/test_bandwidth_buffer.py` - bounded queueing delay (added latency capped by
  `buffer`), recovery after a mid-session rate increase, `drop_rate` counting on a full
  buffer, and the legacy unbounded behaviour. Locks in the fix for the old token bucket that
  ran seconds ahead at a low rate and swallowed every later high-rate step.
- Reminder (convention "new impairment"): every traffic-damaging field must also be added to
  `IMPAIRMENT_OFF` in `tests/test_passthrough.py`, or a harmful default slips through unseen.

### Build / packaging

- `BeanNetworkTester.spec`: two size trims, neither touching startup or runtime (onedir does not
  unpack at launch - PROJECT_NOTES "performance > size").
  (1) Drop Tcl's bundled IANA timezone database (`_tcl_data/tzdata`) and msgcat catalogs
  (`_tcl_data/msgs`, `_tk_data/msgs`) from `a.datas` after Analysis - the tool uses Python's
  `time` (never Tcl `[clock]`) and its own `lang/*.json` i18n, so ~750 files were dead weight.
  (2) `excludes` now also drops `ssl`, `_ssl`, `_hashlib` -> OpenSSL (libcrypto ~6 MB + libssl
  ~1.3 MB) is no longer collected. The app has no network TLS (convention 36: no telemetry) and
  `import bean_network_tester` never pulls in `ssl`; its only hashing is crashlog's sha1
  fingerprint, and `hashlib` falls back to the built-in `_sha1` module when `_hashlib` is absent
  (verified: `sys.modules['_hashlib']=None; hashlib.sha1(...)` still works on this CPython, and
  `_sha1` is built into python314.dll, not a separate excluded .pyd).
  Measured `dist/BeanNetworkTester/_internal`: 1020 -> 262 files, 27.9 -> 19.2 MB. Encodings are
  KEPT (Tk needs them). Verified on the rebuilt exe: `--version`, `--simulate --loss 10
  --duration 2` (exit 0), and the GUI window opens; `libcrypto*`/`libssl*`/`_hashlib*`/`_ssl*` are
  absent from `_internal`.

### CI / tooling

- `.github/workflows/ci.yml`: pinned actions moved to their Node 24 majors
  (`checkout@v5`, `setup-python@v6`, `upload-artifact@v6`); fixed the coverage-artifact name
  (`matrix.python` -> `matrix.python-version`, previously empty and colliding across the two
  Python versions); added `concurrency` (cancel superseded runs), least-privilege
  `permissions: contents: read`, per-job `timeout-minutes`, a weekly `schedule` run (catches
  drift in unpinned `pydivert`/`psutil`), and `CHANGELOG.md` to the required-release-files
  check. New headed GUI render check under Xvfb (`tools/ci_gui_render.py`) that builds the
  real Tk `App` at 1366x768 in both languages and fails on truncated key widgets - catches
  layout regressions the fake-tk smoke cannot see.
- `.github/dependabot.yml`: weekly updates for the `github-actions` and `pip` ecosystems.

## [0.2.0] - 2026-07 - first public release

First tagged release. See `CHANGELOG.md` for the user-facing summary. Internally this is the
package-refactor baseline: the pure decision core (`core.py`), the threaded engine
(`engine.py`), the field/filter/exit-code/preset/window/page registries as single sources of
truth, the virtualized tables, and the pytest suite (engine, i18n, CLI, fail-safe, property
based, concurrency chaos, GUI on the fake-tk harness).
