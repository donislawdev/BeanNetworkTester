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

### Fixed: SocketWatcher STOP no longer logs a crash; targeting resolve no longer blocks on process_iter

Follow-up to the chunk 2 rollout, from a field crash log + report (slow first target-start).

- **SocketWatcher stop recorded a spurious crash.** `_loop` caught the `WinError 995` that `stop()`
  induces - closing the SOCKET handle unblocks the parked `recv()` with "I/O aborted" - and wrote it
  to crashes/ via `crashlog.once`, so every STOP left a `socketwatch.loop` entry. Now guarded by
  `if not self._stopping.is_set()`, exactly like the capture loop's `if self._running`; a real
  socket-stream failure while running is still recorded. Test:
  `test_socketwatch.py::test_stop_does_not_record_the_close_induced_error_as_a_crash`.
- **The first target-start blocked for ~2 s.** Resolving a target expression walks every
  socket-owning PID and its process TREE; the first protected ANCESTOR (System, a protected service)
  that could not be opened individually made `portmap.info` fall back to a whole-system
  `psutil.process_iter()` - measured 2911 ms - and because the SYNCHRONOUS start/apply resolve runs
  that walk, it blocked the session (measured cold `ProcessTargeting.refresh` 2148 ms -> 371 ms,
  `apply_targeting` ~335 ms). New `allow_bulk` flag threaded through `PortTable.info` / `name_of` /
  `ancestors` and `SocketWatcher.name_of` / `ancestors`; `ProcessTargeting.refresh` passes
  `allow_bulk=False`. The bulk stays for `warm_names()` (the connection log's display column) on the
  watchdog thread. This also relieves the yes/no flicker at start: the resolver's periodic refreshes
  hit the SAME bulk, so targeting was effectively stale for ~2 s and connections opened in that
  window slipped to "not impaired"; now it is live in ~350 ms.
- Behaviour change: a PROTECTED process (one the tool cannot open individually) can no longer be
  TARGETED by name - it will not match, where the bulk scan used to name it. The connection log still
  shows its name. Targeting a system process was never a real use case; the trade is a ~6x faster
  start.
- Tests: `test_processes.py`'s fake psutil now provides `Process` (individual resolution) to match
  real psutil - it exposed only `process_iter` (the bulk path) before, so targeting's individual path
  had nothing to resolve against. Every targeting/watcher test fake gained the `allow_bulk` kwarg.

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
