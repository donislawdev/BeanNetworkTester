# Changelog

All notable changes to Bean Network Tester.
The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [Unreleased]

### Added

- **A run that would break everything now says so first.** Start with impairment on, nothing to
  aim it at and no time limit, and both the command line and the window say: this affects every
  connection on this machine, set a target or a time limit to narrow it. A warning, not a
  refusal. Silent in `--simulate`, and once the run is aimed or timed. The same line appears when
  a running session becomes unbounded, and in `--dry-run`. "LAN mode" counts as impairment here:
  on its own it cuts every connection that leaves the local network.
- **Ctrl+F, and the row menu from the keyboard.** Ctrl+F brings Connections forward and puts the
  caret in its search box, and does the same inside the event-log window. Shift+F10, or the menu
  key, opens the row menu on the selected connection. Nothing in the table needed a mouse before.
- **An empty table says why it is empty.** "0 of N" under the table was the only sign that a
  search had simply matched nothing, which reads the same as something being broken. It tells the
  two cases apart: nothing captured yet, or nothing matching what you typed.
- **`--help` starts with worked examples.** It used to open with 24 lines listing every flag,
  before a single readable sentence. Four examples now come first - a safe trial run, one aimed
  at an application, one aimed at a destination, and one for a pipeline - and the flag list
  follows. A mistyped flag shows the error instead of burying it under the same wall.
- **Numbers in the tables line up on the right.** Packets, bytes, ports, PIDs and times were
  anchored left, so 9 and 1000000 began at the same pixel and a column of numbers could not be
  scanned down. Addresses stay on the left where they read properly, and the short columns beside
  a number - protocol, "impaired?", the timestamp - sit centred so the two never touch. Applies to
  Connections and to both views of the event log.
- **An impaired row no longer relies on colour alone.** It is shown in bold as well as in orange,
  so it stays recognisable whichever columns you have chosen to show - including with the
  "impaired?" column hidden.
- **Connections: the search box can search one column at a time.** Plain text works as before,
  and now a term can name its column: `port:443`, `ip:10.0.0.0/8`, `pid:>4000`, `scoped:yes`,
  `dropped:>0`. Values use the same notation as the Control page fields, and several terms narrow
  together. A new "?" button lists the column names with examples. The search used to look at 6 of
  the table's 17 columns, so a PID was on screen and could not be searched for.
- **Connections: you can choose which columns the table shows.** Right-click, "Choose
  columns...", tick what you need. The choice is remembered for next time, and at least one
  column always stays. The table has seventeen of them, which is more than fits comfortably
  on a 1366x768 screen.
- **Connections: two new right-click actions on a row.** "Block this IP address" adds it to the
  blocking field, and "Leave this process alone" excludes that process from impairment. Both ADD
  to what is already in the field, so you can build a list one row at a time, and a repeat is
  ignored rather than duplicated. Like every other row action they fill the form only - press
  "Apply changes" to put them into a running session.

### Docs

- **The buffer help sheet no longer promises more lag than the buffer can give.** It told you to
  enter how many ms of lag you want, which is right for a small buffer and optimistic for a large
  one: the number is the most the queue can add, and one small download may never fill it.
  Measured against a real link, 2000 ms gives a single ordinary download about a quarter of that,
  and several downloads at once nearly all of it. The sheet now says so in one added line.
- **`--help` reads like ordinary writing.** Six flags described themselves with a semicolon
  joining two halves of a sentence: `--preset`, `--filter`, `--buffer`, `--dst-ip`, `--block-ip`
  and `--block-port`. They now use a full stop or a comma, like the rest of the program's text.
- Both READMEs now say in the licence section that **what you make with the tool is yours**.
  Scenarios you write, saved profiles and config files, reproduction reports, CSV exports, logs
  and screenshots are your own work: the GPL covers the program, not its output, and using the
  tool does not oblige you to publish anything. The example scenarios shipped in `scenarios/`
  are part of the project and stay GPLv3.

### Fixed

- **A run with several bad values now names them all at once.** `--loss 500 --latency -5
  --dup 900` reported the latency and stopped, so you fixed one, ran again, and met the next.
  All of them come back in one message. The window still reports the field you are typing in and
  nothing else, which is what you want while typing.

- **A mistyped preset suggests the one you probably meant.** It used to answer with the full list
  of seventeen ids and leave you to find the difference. The tool already did this for a mistyped
  setting in a config file, so preset names were the odd one out.

- **A target that means "everything" no longer counts as aiming at something.** Start with
  impairment on and a target of `*`, and the tool stayed quiet, because a target was set - to
  every program on the machine. The warning about affecting every connection now appears for any
  expression that does not narrow anything: `*`, a regular expression matching all, a PID range
  covering all, or a destination of `0.0.0.0/0`. A real target is unaffected and still silences
  it, and so does a real target with an exclusion beside it.

- **The "process" column now says when its answer was taken.** The name is read once, when the
  connection first shows up, and never again - which is why a row can still name a program that
  has since closed. The tooltip said none of that, so a name that outlived its program looked
  like a mistake.

- **Two unsafe things the window did while closing.** A tooltip could build a new, invisible
  window at the exact moment its own window was being taken apart, and the tool kept a reference
  to every tooltip window it had ever made, including the closed ones. Neither has been shown to
  cause the crash they were found while looking for - both are simply wrong, and both are gone.

- **A crash of the window itself used to leave nothing behind.** Some crashes happen below
  Python, and the file that catches those was only switched on once a capture started - so the
  window could die with nothing running and leave no record anywhere. It is switched on when the
  window opens now, and beside it the tool keeps a short note of what it was doing: which tab was
  open, whether a session was running, which extra windows. A normal exit still removes both.

- **A connection could be handed to "System" in the middle of its life.** Windows announces some
  connections twice - once for the program that opened it, once for the system itself - and the
  tool believed the second one. From that moment the connection belonged to "System": it stopped
  being impaired even though your target opened it, and that is the name the Connections tab
  showed for it. It happened to two to four connections out of every twelve here.
- **Short connections of the process you target are no longer missed.** A browser opens a new
  connection for almost every page, often from a brand new process, and many of them are over in
  well under a second. The tool used to notice them a fraction too late, so the shortest ones
  finished untouched - listed with the right process name and "impaired? no" beside it. It now
  learns each new connection the moment it appears. Measured with 12 fresh processes opening one
  short connection each: 4 escaped before, 1 out of 96 after.
- **Closing one copy of the tool no longer breaks the one that is still running.** The WinDivert
  driver is shared by the whole machine, and the copy that closed was unloading it out from under
  the copy that was working - which is why a second window could not start any more, and said
  "run as Administrator" while doing it. Whoever leaves last now does the unloading, and a copy
  that leaves early says so in its log. The driver still gets unloaded, so the program's folder
  can still be deleted afterwards.
- **A start that arrives a moment too early now waits instead of failing.** If another program
  using WinDivert is still shutting the driver down, START waits up to half a second for it
  rather than reporting an error you would fix by trying again.
- **`--doctor` no longer calls a machine healthy while nothing can start.** A driver caught
  mid-unload was reported as fine - the one state in which every start fails. It is now a warning
  that says what it means and what to wait for.
- **A failed START now tells you what actually went wrong.** Whatever the reason, the window said
  "Run as Administrator" - including to people who already were. The commonest case is not about
  rights at all: close one copy of the tool while another still runs, and Windows reports that the
  device does not exist, because the shared driver is still shutting down. That case now says so,
  and says to try again in a few seconds. A rejected traffic filter, a missing driver file and a
  blocked driver each get their own sentence too.
- **The licence notices now point at the files that are actually there.** The instructions for
  replacing WinDivert with your own build named `WinDivert.dll` in `_internal\pydivert\`; the
  program ships `WinDivert64.dll` in `_internal\pydivert\windivert_dll\`. Replacing the library
  is a right the LGPL gives you, and directions you cannot follow are not much of one.
- **The PyDivert replacement instructions were wrong, and quietly so.** They said you could drop a
  modified `pydivert` package into `_internal\`. Measured against a real build: the copy inside
  the executable wins, and the replaced module even reports the path you used, so it looks like it
  worked. The notices now give the two routes that do work - rebuild the application against your
  version, or run it from source - and the written offer of source now lasts the three years the
  licence asks of an offer.
- **"About" now carries the no-warranty notice.** The GPL defines a legal notice as four things
  together: copyright, no warranty, your right to pass the program on, and where to read the
  licence. The window had three of them.
- **Error messages say what to do instead of who is at fault.** A config file with an unusable
  number answered "Invalid value for 'loss'". It now says the setting needs a number between 0
  and 100, and quotes back what it got. A misspelled setting in a scenario file gets the same
  "did you mean" suggestion config files have always had, an unknown scenario action lists the
  ones that exist, and saving a profile names the field instead of "Values must be numbers".
- **A skipped expression no longer names the wrong feature.** The line about an expression that
  could not be read claimed targeting was switched off, even when the expression was a blocking
  rule.
- **A broken scenario file no longer starts the session first.** `--scenario` with a file the tool
  cannot read used to open the capture, impair traffic and only then report the problem. The file
  is now read before anything starts, exactly as `--dry-run` already checked it. Same exit code as
  before.
- In the Settings window, "Capture only the targeted traffic" stayed clickable after you pressed
  START, if the window was already open at the time. Ticking it did nothing until the next
  session. It now greys out for as long as the session runs, with the same "locked while running"
  note as every other option that is only read at start.

## [0.4.0] - 2026-08-01

**The short version.** This release is about numbers you can trust and targeting that catches what
you aimed at. If you read nothing else:

- **Aiming at a process now catches a connection from its first packet**, TCP and UDP alike.
  "Drop SYN" combined with a process target previously did nothing at all, and DNS and QUIC walked
  past untouched.
- **"Effective loss" was wrong and is now right.** It counts every impairment, over the traffic you
  aimed at. A session losing 90% of its traffic to a speed limit used to report 0.0%.
- **Presets and the shipped scenarios were recalculated** against published measurements. Latency
  was applied twice, and three presets were eight times too fast.
- **A session moves about 1.3x more packets a second**, and a delay you ask for arrives without the
  old few-millisecond surcharge.
- **New: "Capture only the targeted traffic".** On a real run without it, the driver threw away 43%
  of the traffic you had aimed at before this tool ever saw it.
- **New: "Show only the targeted traffic"**, five new presets, a "Driver queue wait" reading, and a
  warning when your target shares a port with another program.
- **Config and scenario files now reject a typo** instead of ignoring it.
- Plus a long list of fixes to the counters, the Connections table and session start/stop.

**If you script this tool, read the BREAKING section**: presets, "Effective loss", profiles, the
statistics CSV, the connections CSV and the reproduction report all changed shape or meaning.

### BREAKING

- **A misspelled setting in a config file is now an error.** `"latancy": 300` used to load in
  silence, so `--dry-run` said *"Configuration is valid"* and the run went out with no latency at
  all. Unknown settings now fail with code `3`, naming the key and suggesting the near miss. Files
  this tool saved keep loading. A hand-written file with an unknown name will not.

- **A mistake in a scenario file now says so instead of doing nothing.** `"duraton"` used to leave a
  reset at its default and `"lop"` used to turn looping off, both silently, so the tool looked like
  it was ignoring your file. Unknown keys, in a step or at the top level, are now an error naming
  the key. A correct file keeps working.

- **A scenario that ends now ends the run.** A non-looping scenario with a timeline used to print
  "Scenario finished." and then run forever, which in a pipeline is a job that hangs to its own
  timeout and writes no `summary`. Such a run now stops with `stop_reason: "scenario_done"` and says
  so at the start. `--duration` still wins wherever you pass it.

- **The old `reset_now` scenario action is gone.** `reset_tcp` does the same thing and is now the
  only action. A file still using `reset_now` will not load and says which step to fix. The
  "Reset TCP now" button is unaffected.

- **The presets were wrong and are now checked against published measurements.** Latency was set as
  if it were a ping, but it is added in both directions, so "Satellite link" at 600 ms delivered a
  1200 ms ping. Three presets held kilo**bits** where the field wants kilo**bytes**, making them
  eight times too fast. **If you scripted `--preset`, your traffic changes.** Ids are unchanged, but
  `--preset "Satellite link"` is now "Satellite (geostationary)".

- **The shipped scenarios in `scenarios/` were recalculated** the same way, so a scenario and a
  preset describe the same network with the same numbers. The ping you get is now the number written
  in the file.

- **"Effective loss" now means what its name says, and your numbers will change.** It used to be the
  configured Loss percentage over every packet seen, ignoring speed limits, blocking, LAN cut, link
  outages, resets, dropped SYNs and expired NAT. It now counts every impairment, over the traffic you
  aimed at. `effective_loss_pct` and `effective_corruption_pct` moved with it, so reports from before
  and after are not comparable.

- **"Duplicated" counts packets actually sent twice, not packets the tool decided to duplicate.**
  Under load the copy was thrown away while the counter rose anyway: 40 packets in, "Duplicated"
  read 40, nothing reached the wire. This matches "Corrupted", which always counted only real
  changes. Reports from before and after are not comparable on that field.

- **Profiles now remember more of the link:** latency spikes, link outages (flapping) and the buffer,
  on top of the original seven fields. Outages are why it was worth doing - a profile can finally
  describe a link that cuts out. Old profiles load exactly as before. Picking a preset now clears
  all of these, so "Perfect network" really does clear everything, and `--preset` finally does what
  the window does.

- **The Connections table now shows what arrived AND what was offered.** "down", "up" and "total"
  held *captured* bytes under headings meaning delivered, so a row could read 5 MB while the
  application got 0.4 MB. Those three are now delivered, and new **"down seen"** / **"up seen"**
  hold what was captured. **The connections CSV changed shape**: the three old byte columns are
  replaced by six `delivered_*` and `captured_*` ones, renamed rather than reused.

- **The reproduction report's "connections reset" counted packets, not connections.** One reset
  connection could report itself as 50. The report now carries three keys that answer three
  questions: `connections_reset`, `rst_packets_dropped` and `rst_sent`. The statistics CSV gained a
  matching `connections_reset` column. Nothing on screen changed.

- **The statistics CSV gained `capture_narrowed` and `packets_in_scope` columns.** The first records
  whether "Capture only the targeted traffic" was in effect, without which two rows under one header
  can count completely different traffic. Your existing file is moved aside with a timestamp and a
  fresh one started, as it already is whenever columns change, so no row misaligns. A script reading
  by column position needs the new offsets.

- **`--gui` no longer accepts any other option.** `--gui --loss 30 --duration 600` used to open no
  window and quietly impair in the background, with no STOP button anywhere. It now stops with a
  usage error (code `2`) and says what to do instead. If a script relied on this, delete `--gui`
  from it.

### Added

- **Five new presets:** Satellite (low orbit), Distant server (another continent), Congested home
  link (bufferbloat), Train / metro (tunnels) and In-flight Wi-Fi. Two are worth a note: bufferbloat
  only bites once you really saturate the link, and Train / metro is the only preset that takes the
  connection fully down, so your application has to reconnect rather than just slow down.

- **"Show only the targeted traffic"** (Settings, off by default) points the counters, the chart, the
  Connections table and the connections CSV at your target alone. It changes what you **see**, never
  what is captured or impaired. Three things deliberately do not follow it: "Queue overflow",
  "Dropped at stop" and "Send failed" always cover everything, because they count the tool's own
  losses. The statistics CSV carries both totals instead. Reports and `--format json` are unchanged.

- **"Capture only the targeted traffic"** (`--narrow-filter`) pushes your destination IP and port
  into WinDivert, so traffic that could never be impaired is not handed over at all. It is a
  correctness fix, not just a speed one: measured on a real run, without it the driver threw away
  **43% of the traffic you aimed at** before the tool saw it. It applies at START, and does nothing
  for a process target, a wildcard or an `re:` pattern - the run says which.

- **"Driver queue wait (peak)"** in the Session tab shows how long packets waited inside WinDivert
  before the tool saw them. That is the one delay the tool adds and counted nowhere. It is measured,
  not estimated. Expect a fraction of a millisecond when idle; above 50 ms the log says so. Blank
  under `--simulate`.

- **A session now records the WinDivert queue it ran behind** (length, time and size) in the log and
  in the reproduction report, so a report from a machine you do not have in front of you says which
  queue produced its numbers.

- **The tool now warns when your target shares a port with another program.** Windows lets several
  programs hold one local port - that is how mDNS, SSDP and DHCP work - and this tool decides what to
  break from the port number. On this machine four ports out of 127 were shared, one of them by five
  programs. Applying a target now names the port and who holds it, so you know that part of the
  result is a coin toss.

- **The command line says when your target stops matching**, instead of finishing green in silence.
  Measured: aiming by process id and restarting the program left five out of five new connections
  untouched with nothing in the output. Aiming by **name** recovers on its own and costs only the
  first connection. Aiming by **process id** never recovers. If the program under test restarts, aim
  by name.

- **Every run with a process target ends by saying how much of the captured traffic was yours** -
  "In scope: 40 of 500 captured packets" - and calls it out when that is zero. A run where your
  target caught nothing looks exactly like a run where your application coped. It is a warning, not
  a failure, because a quiet target is perfectly ordinary.

### Changed

- **The checkbox is now called "Capture only the targeted traffic"**, not "Narrow the driver filter
  to the target". The old name described the machinery. The `--narrow-filter` flag is unchanged, and
  its tooltip was rewritten to say what it does and when it will not apply.

- **A session moves about a third more packets a second.** The tool handles packets on two threads,
  and Python left one waiting up to 5 ms for its turn - that waiting, not the work, was the limit. A
  session now asks for shorter turns and hands the setting back at STOP. Measured on loopback and a
  real card: **1.33x to 1.36x, in 24 comparisons out of 24**, at slightly less processor time per
  packet.

- **A packet you did not ask to change goes back on the wire exactly as it arrived**, and the session
  moves about 12% more traffic for it. Checksums used to be recomputed for every packet, including
  untouched ones, which also meant a session with nothing configured did not quite pass traffic
  through unchanged. Measured: **1.12x more packets a second, 8 comparisons out of 8**, and 24 MiB of
  TCP arrived byte for byte over a real card.

- **Targeting a process no longer competes with the traffic it is measuring.** Working out which
  sockets belong to your target used to happen on the thread handling your packets, dozens of times a
  second. It now runs on its own thread. A freshly opened connection is still impaired within tens of
  milliseconds and STOP stays immediate.

- **Semicolons are gone from the interface texts and both READMEs.** Twenty-one tooltips and about
  eighty lines of documentation used them to join sentences, which is not how people write. Code
  samples keep theirs, where a semicolon is syntax.

- **"Spike chance" and "Spike size" moved to "Latency (ping)"** from "Advanced (NAT / connections)",
  because a spike is latency. Nothing about how they work changed, nor their flags, nor their place
  in a profile.

- **"Blocking (firewall)" starts collapsed** on a fresh install, like the other advanced panels. If
  you have used the tool before, your own choices are remembered.

- **The Latency and Jitter tooltips say the thing that was easy to get wrong:** ping rises by about
  twice the latency you set, because both the request and the reply are delayed, while jitter widens
  the wobble by about 1.4x rather than doubling it. Both READMEs explain it too.

### Fixed

- **Aiming at a process missed the first packet of every new connection.** Measured: 20 fresh
  connections with "Drop SYN" at 100% produced 20 successful connections and not one dropped SYN, so
  **"Drop SYN" plus a process target did nothing at all**. The first packet is now checked against
  the live socket map.
  **What changes for you:** connections aimed at a process now take longer to open and a minority
  fail outright, which is what a bad network does. If a test measured "time to first byte" under
  impairment, expect it to move.

- **Aiming at a process did not touch the first packet of a UDP exchange** - and DNS and QUIC take a
  fresh port every time, so it did not touch them at all. If you tested a game, a video call or a
  browser over QUIC and the impairment seemed weaker than configured, this is why. Ordinary TCP data
  is deliberately still not re-checked: measuring showed it would cost throughput for nothing.

- **The live "which app owns this port" map could be dragged backwards by a stale reading**, so a
  connection was briefly credited to the wrong application. A periodic sweep of the socket table,
  always a little behind, was applied on top of the live signal from the driver. Measured over 25
  seconds of ordinary traffic: **919 times**. Readings are now weighed by when they were taken.

- **Targeting could follow a process id after the process was gone**, and Windows hands those numbers
  out again. A restarted target could come back under a remembered number and **not be impaired**,
  while an unrelated program inheriting that number **was**. The tool now checks the process is still
  the same one, and forgets it when it closes its last connection.

- **Three fixes to short-lived and freshly opened connections.** Targeting now follows the system's
  socket events instead of scanning a few times a second, so a connection that opens and closes
  between two scans is no longer missed. The Connections table fills in the owning program from the
  first packet instead of leaving the row blank. And setting a process target no longer makes the
  first START pause for a second or two.

- **The "impaired?" column now reflects the whole session, not just this instant.** It asked whether
  the port was in the target *right now*, so a row flipped to "no" the moment its connection closed
  and a run impairing all of Chrome looked like it caught almost nothing. The column, the row
  highlight, the sort and the CSV now read one record, so they cannot disagree.

- **The tool kept pausing itself and then blaming WinDivert.** Every so often it spent up to half a
  second working out which program owns which connection, stopped collecting packets while it did,
  and then told you the driver's queue was backing up and to narrow your filter. The delay was its
  own. Measured over 95 seconds with programs constantly starting: the worst pile-up dropped from
  **508 ms to 17 ms** and the warning stopped appearing.

- **The "driver held a packet" warning described lost accuracy when what you were losing was
  traffic.** Measured on a deliberately overloaded run: at 138,000 packets a second offered, the tool
  moved about 14,000 and **91.75% was thrown away by the driver before the tool saw it**, while every
  drop counter on screen read zero. The warning now says a full driver queue means dropped packets,
  not just late ones.

- **With "Capture only the targeted traffic" on, the Statistics and Connections tabs said the exact
  opposite of the truth**, keeping their "counters cover ALL captured traffic" line while the driver
  had been told to hand over nothing else. The checkbox tooltip promised the opposite and both
  READMEs contradicted themselves. Both notes, the chart caption and the READMEs now describe what
  the figures actually cover, including the case where a process target is set as well.

- **Four fixes to the Scope settings.** The two "only the targeted traffic" switches now sit in one
  **Scope** card instead of separate panels a few rows apart, with a line that tells you **before
  START** whether your destination can actually be narrowed. The Settings window scrolls, so no group
  falls off the bottom. Starting a session logs which of the two outcomes you got. And the Session
  panel gained a **"Capture"** row, so a saved run says which traffic it counted.

- **Three counters were lying about how much was lost.** "Buffer overflow" and "Dropped at stop"
  charged for duplicate copies as well as packets, so a run duplicating everything reported nearly
  twice as many dropped as captured. A connection's "dropped" count ignored packets its own queue
  threw away. And packets the tool failed to re-inject left the arithmetic entirely - those now have
  a **"Send failed"** counter, a banner and an event-log entry, throttled so they cannot flood the
  log.

- **Three tooltips were telling you things that were not true.** "Dropped" claimed to count link
  outages, which have had their own counter for a while. "Downloaded (MB)" promised a figure that
  never appeared. And "Effective loss" read as "never reached the far end" when it measures damage
  done on this machine - loss out in the network never arrives here, so nothing here can count it.
  No numbers changed.

- **The delay you set is the delay you get.** Windows rounds up the wait used to hold a packet back,
  and it was a fixed surcharge rather than a percentage, so it barely showed at 100 ms and swamped
  small settings. Measured with a plain `ping`: asking for 10 ms used to cost 12.6 ms extra and now
  costs 1 ms, the same 1 ms as at 50 ms. Jitter below about 15 ms used to vanish into the noise.

- **Long cut-offs and NAT blackouts now last as long as you set them.** The tool forgets a connection
  it has not seen for a while, and a forgotten connection looks brand new - so a reset cooldown above
  about half a minute resumed after roughly 30 seconds however long you asked for, and "NAT mapping
  expiry" at 30 seconds never blocked a single packet.

- **"NAT mapping expiry" now really cuts the incoming direction.** The packet rejected for "the
  mapping has expired" was itself counted as activity, so the mapping reopened on the spot: an app
  that never sent a keep-alive lost about one packet every five seconds and otherwise worked, passing
  a test it should have failed. Incoming traffic now stays cut until the application sends something.

- **"Reset connections" now works where it claimed to.** It no longer fires on a connection that is
  still opening, where the forged reset carries no acknowledgement number and Windows is entitled to
  ignore it - measured, the connection hung until its own timeout. And it now really resets **local
  (loopback) connections**, which previously just went quiet for the cooldown while the tool reported
  an RST as sent. Connections to other machines were never affected.

- **Ping traffic never appeared in the Connections tab**, which claims to list all of them - anything
  without ports was silently left out. Thirty seconds of pinging left the tab empty while the
  counters ticked up beside it. Portless traffic is now listed as one row per address with the port
  cells empty.

- **The Connections tab could empty itself instead of dropping its oldest rows.** When many rows
  carried the same timestamp they all fell on the same side of the "old" estimate, so far more went
  than intended - in the extreme, everything. It now refuses to drop below the level it is trimming
  to.

- **When the capture could not start, the tool told you the wrong reason.** A handle that failed to
  open produced `WinDivert handle is not open` - a symptom naming nothing - while the real cause went
  to a diagnostic file nobody reads. The helpful messages both interfaces already had, including the
  window's "run as Administrator" hint, could therefore never appear. Starting now fails immediately,
  with the reason.

- **Four ways a session mishandled its own start and stop.** A failed start could leave the tool
  holding your traffic without impairing it, refusing every later START. Ending a session kept hold
  of your traffic for a moment while tidying up, so a connection could stall. STOP could take two
  seconds in two different races. And the log could print a fault above its own "Start" line.

- **An unforeseen error during a run is now an exit code, not a stack trace.** A failure inside the
  reporting loop escaped as a raw traceback with code `1`, which is also "the session could not
  start", so a pipeline could not tell an internal bug from a driver that would not open. It is now
  `runtime` (`1`) with a line saying what happened, **and the run still writes its complete
  `summary`** - a `--format json` file no longer ends mid-stream.

- **Three fixes to `--dry-run` and `--doctor` claiming more than they checked.** `--dry-run` said
  "Configuration is valid" about a command that then exits `7`, so it now says which half it checked
  and points at `--doctor`. It also reads your `--scenario` file now, which it never opened.
  `--doctor` no longer calls a driver "not loaded" when Windows simply refused to let it look.

- **Three fixes to the shared-port warning.** It listed your own target among the strangers, because
  a program like Chrome runs several processes. It offered two possible outcomes when the socket
  table already decides which one applies. And it printed bare numbers, so `5353` read like a fault
  rather than mDNS. It now says `5353 (mDNS)`, names the program, and states the one outcome that is
  true.

- **Three files could stop the program from starting, and no longer do.** A translation file with a
  malformed header, a window-layout file with an entry in the wrong shape, and a `--config` file that
  was valid JSON but not a set of settings - the last one reported the tool as having crashed. Each
  is now skipped or reported clearly, and the rest of your setup is kept.

- **Four smaller interface fixes.** The throughput chart could be squeezed until it vanished on a
  narrow window (the Live tab now scrolls). "Close" was cut in half at the bottom of the Settings
  window. The profile picker cut long names off at 24 characters. And "Save profile..." opens with
  the cursor already in the name box.

- **Two things left litter behind.** A failed "Export connections CSV" left a stray `.tmp` file next
  to the real one, and stopping a session could file a crash report in `crashes/` for an ordinary
  STOP. Neither happens now.

- **Starting a second scenario without stopping the first is no longer possible.** The engine
  replaced the running one and left the old one going in the background, so two scenarios fought over
  the same settings. Nothing in the program does this today, so it is a guard rather than a bug you
  could have hit.

### Docs

- **Both READMEs now document the scenario file format, the seven shipped scenarios, both CSV exports
  and all 17 Connections columns** - none of which were written down anywhere. The column meanings
  existed only as tooltips, and the CSV headers only in the code.

- **Three corrections to what the READMEs claimed.** A connection is in scope "the moment it opens"
  only for a program the tool already recognises, not for that program's *first* connection. An
  exclusion like `!chrome` also covers every connection whose owner could not be identified, so do
  not use one to protect an application - name the one you *do* want broken. And both files explained
  greyed-out fields with an "Enable" checkbox that no longer exists.

- **The Requirements and Tests sections now match reality.** `psutil` is not what makes process
  targeting work on Windows - the socket table and process names come from the OS, and targeting
  keeps working without it. Source installs work on Python 3.10 and newer while CI tests and builds
  on 3.14 only, which is the version frozen into the released `.exe`. The Tests section also now
  covers the GUI render check and how a release is produced.

## [0.3.0] - 2026-07-20

### Changed

- **Bean Network Tester is now free and open-source software under the GNU GPL v3.** It was
  previously released under a proprietary "free to use, no resale" licence; it is now the GNU
  General Public License, version 3, so you may also study the source, change it, and redistribute
  it - including modified versions - as long as you pass it on under the same terms. The "About"
  window and the `--license` command show the new licence.

### Added

- **New "Settings" window (gear icon, top-right).** App preferences now live in one place,
  reached from a gear button in the header where the language box used to be. The language box is
  no longer in the header, and the row limit is no longer on the Control page. It holds:
  - **Interface language** and the **table row limit** (moved here).
  - **Chart history** - how many seconds of throughput the graph keeps (default 120 s).
  - **Log lines kept** - how many lines the log strip at the bottom holds (default 500).
  - **Ask before closing while running** - turn the close confirmation on or off.
  - **Restore the last profile on startup** - reopen with your last picked profile already filled
    in (it does not start a capture - you still press START).
  - **Reset window layout** - forget the remembered window size/position, collapsed sections and
    table sorting, and recentre the window (your settings and session are kept).

  Chart history, log length and the switches are remembered across restarts.

- **New "Dropped at stop" statistic.** Packets that were still waiting in the delay queue
  when you press STOP are now counted (and shown in Statistics) instead of quietly disappearing
  from the totals. They were not lost in the network - the session just ended before they were
  sent. Expect a small nonzero value whenever you stop a run that uses latency or a speed limit.

- **A "?" help button next to the speed-limit "Buffer" field.** Hovering it shows a short
  description; clicking it opens a plain-language guide to what the buffer does and which value
  to pick for which kind of test (capping speed, faking a laggy link, or seeing packet loss).

- **The window shows at a glance when a capture is running.** While a session is live the
  title bar gains a "● RUNNING" tag and the app icon (title bar and taskbar) switches to a
  bean with a red recording dot, so it is obvious the tool is working even when the window is
  minimised. It reverts the moment you press STOP.

- **New "Loopback only (127.0.0.1/::1)" traffic filter.** A new choice in "Traffic to modify"
  (and `--filter loopback` on the command line) captures only loopback traffic, for testing
  communication between processes on the same machine. Covers IPv4 and IPv6, like every filter.

- **Buttons now show their keyboard shortcut in the tooltip.** Hovering START/STOP, "Apply
  changes", "Save file..." or "Load file..." shows its shortcut (`F5`, `Ctrl+Enter`, `Ctrl+S`,
  `Ctrl+O`) on a second line, so the shortcuts stop being hidden.

- **This machine's name and private IP shown in Statistics -> Session.** The Session
  sub-page now lists the computer name and this machine's private IPv4 and IPv6 addresses,
  so you can tell at a glance which machine and network a capture is running on. Nothing is
  sent anywhere to find them (no public-IP lookup) - an address that does not exist on this
  box, for example IPv6 on an IPv4-only network, shows as "-".
- **Block traffic to chosen ports and IP addresses** - a firewall inside the tool. A new
  "Blocking (firewall)" section on the Control page, and `--block-ip` / `--block-port` on the
  command line, drop all traffic to the destinations you list. Blocking triggers on IP OR port
  (leaving one field empty means "any"), accepts the same syntax as targeting (lists, ranges,
  CIDR, wildcards, `!` to exclude, IPv4 and IPv6), and respects process targeting - point the
  tool at your app and only its traffic to those destinations is cut. A new "Blocked" counter
  (CSV column `dropped_block`, NDJSON `drop_block`) reports how many packets a block dropped.
  Ships with a new example scenario, `scenarios/blocked-endpoint.json` (a backend/API endpoint
  goes dark, then recovers), and blocking examples in both READMEs.
- **Separate download and upload columns in the Connections table.** Each connection
  now shows received traffic ("down[KB]") and sent traffic ("up[KB]") side by side,
  each sortable on its own. The old "KB" column, which was already the sum of both, is
  relabelled "total[KB]" so it is clear it means the combined traffic.
- **More per-connection detail in the Connections table.** New columns: **impaired?**
  (whether the connection is in your targeting scope - being broken, not just watched -
  with those rows subtly highlighted), **dropped** (packets dropped on that connection by
  the active impairments), **PID** (process id, so two instances of the same program are
  told apart) and **avg** (average packet size in bytes). A footer under the table sums
  download, upload and total traffic across every connection your search matches - not just
  the rows shown under the display limit.
- **Export the connection list to CSV.** A new "Export connections CSV" button on the
  Connections page saves the current view (honouring your search and sort) to
  `bean_network_tester_connections.csv`. The file mirrors the table: a column for every
  field on screen - process, PID, impaired?, dropped, download/upload/total as separate raw
  byte columns, and average packet size - for analysis in a spreadsheet.
- **Link buffer for the speed limit** (`buffer` field / `--buffer`, default 2000 ms,
  0 = unlimited). The rate limiter now models a finite link buffer: offered traffic
  above the limit is dropped once the buffer fills, which bounds the added latency to
  ~`buffer` ms and lets a mid-session rate INCREASE take effect within that window.
- **"Rate-limit drop" counter** (`drop_rate`, CSV `dropped_rate_limit`) for packets
  dropped by a full speed-limit buffer - counted separately from "Loss" and from the
  tool's own "Buffer overflow".

### Changed

- **The default link buffer for the speed limit is now 1000 ms (was 2000 ms).** It only affects
  runs that use a download/upload limit or a schedule; it halves the extra latency a rate-limited
  link can build up and lets throughput schedules with ~1 s steps track more closely. Set
  `--buffer` (or the Buffer field) to any value to override.

- **Clearer "Corrupted" tooltip.** It now explains that packets without a payload (e.g. bare
  ACKs) cannot be corrupted, so the count can sit below the corruption percentage you set.

- **The interface was reworked for clarity and everyday use (GUI overhaul).** A pass over
  the whole GUI from earlier development: it now scales crisply on high-DPI and mixed
  multi-monitor setups, the Statistics tab is split into Live / Session / Events sub-pages
  so panels are no longer clipped on smaller screens, the Control page groups settings into
  collapsible sections, disabled controls now clearly look disabled, and the window remembers
  its size, position and layout between runs.
- **Secondary windows (About, and any future one) can no longer be maximised or stretched
  without bound.** They now have a maximum size and no maximise button, matching the main
  window. The profile dropdown was also cleaned up: it is now a plain, crisp list (presets,
  then your own profiles, divided by a line) with no washed-out "-- presets --" headings and
  no awkward tick mark - the current profile is shown on the button itself.

### Fixed

- **"Chart history" and "Log lines kept" now say what went wrong, not just turn red.** Typing a
  value they do not accept outlined the box in red and left it at that, so the only way to find
  the allowed range was to guess - while "Row limit", one card above in the same window, has
  always spelled it out. Both now show the same sentence under their card, naming the field and
  the range it accepts, and it disappears as soon as the value is good again. As before, a value
  that is not accepted is never saved.
- **The app icon now shows the red dot while a capture is running.** The dot was only ever
  reaching windows opened after you pressed START - which is why it turned up on the "close the
  app?" box and nowhere else. The icon in the title bar and on the taskbar stayed the resting
  bean for the whole session, so a minimised window gave no sign the tool was still touching
  your traffic. It now switches on START and back on STOP, and going back drops you on the
  original crisp icon rather than a blurrier copy of it.
- **Making the chart history longer now widens the chart immediately.** Setting "Chart history"
  to a bigger number left the graph on its old span: the label under the left edge still read
  "-28 s" and crawled towards the new value one tick at a time, taking minutes to get there,
  while the caption above the graph already said "last ~250 s". The graph now covers the full
  span at once, with the time you have not recorded yet drawn as a flat zero line - exactly how
  it looks right after the app starts. Shortening the history was never affected.
- **The window menu is now dark, like the rest of the app.** Clicking the bean icon in the title
  bar (or pressing Alt+Space) opened a bright white "Minimise / Maximise / Close" menu in every
  window, and the right-click menu on the Connections table had a light rim around it. Both now
  match the dark interface. The file pickers ("Save file...", "Load file...") are dark too.
- **The "About" window no longer cuts off its text.** The licence sentence and the "sends no
  data anywhere" line ran off the right edge and were simply chopped - in Polish, where the
  sentences are longer than the English they were translated from. They now wrap to the width
  of the window, at any size and any display scaling.
- **A button no longer stays lit after you close the window it opened.** Clicking "About" or the
  settings gear left the button looking as if the mouse were still hovering over it, for the rest
  of the session.
- **Keyboard focus and mouse hover no longer look the same.** Every button lit up in exactly the
  same way whether the mouse was over it or the keyboard had landed on it, so you could not tell
  the two apart - and a button that kept focus looked as if the cursor were parked on it. Hover
  still fills the button; keyboard focus now draws a thin outline inside it instead.
- **Tooltips no longer pop up far away from the text they explain.** The summary line under the
  title ("Active: ...") stretched across the whole window even when it was one short sentence, so
  hovering the empty space beside it - halfway across the header - still brought up its tooltip.
  The same went for the notes above the Statistics counters and the Connections table. Those
  tooltips now appear only over the text itself.

- **"Restore the last profile on startup" now works for your own profiles.** Saving a profile
  makes it the one you are using, but the tool remembered only profiles picked from the list -
  so after "Save...", closing and reopening the app brought back whichever ready-made profile you
  had picked before saving. Your choice is also written to disk the moment you make it, so it
  survives even if the app is killed rather than closed. Deleting a profile no longer leaves the
  setting pointing at it, and a profile that disappears while the app is closed is simply
  ignored on the next start, as before.

- **Secondary windows now open with the dark title bar right away.** The About, Settings and
  Event-log windows briefly showed a white Windows title bar until you clicked them; they now
  paint dark from the moment they open.

- **The Control page no longer jumps when you start or stop a session.** Starting a capture
  shows a "locked while running" note under the traffic filter, and stopping hides it again.
  That note used to be added to and removed from the layout, so the whole form shifted up and
  down by a line on every START/STOP (and briefly smeared as it repainted). Its space is now
  always reserved, so nothing moves.

- **The profile picker now matches the traffic-filter dropdown.** Its drop-down arrow was drawn
  as a raised, light-grey button that stood out oddly next to the flat filter box, and its open
  list was a paler shade. The picker is now a flat dark field with a plain arrow, and its list
  uses the same dark colour as the other dropdowns.

- **Faster startup.** Launching the interface no longer loads the graphical toolkit twice.
  When the app asks for Administrator rights it briefly starts a second, elevated copy of
  itself; the first copy used to build up the whole interface before handing over, only for the
  elevated copy to load it all again. It now hands over immediately, so the window appears sooner.

- **START and STOP no longer freeze the window.** Starting a session loads the WinDivert
  driver, and stopping it waits for the capture threads to finish; both used to run on the
  interface thread, so the window locked up for up to a second on every click. They now run in
  the background - the window stays responsive and the button flips between START and STOP as
  soon as the work completes.

- **The Connections table and its CSV export now agree on the "avg" column.** The average
  bytes-per-packet was rounded on screen but floored in the exported file, so a flow could show
  768 in the table and 767 in the CSV. Both now round to the same number.

- **Tooltips no longer cover an open dropdown.** A field's tooltip could pop up on top of the
  list you had just opened (for example the presets/profile picker), hiding the very options
  you were about to choose. Tooltips now stay hidden while any dropdown is open.
- **The scenario picker opens in the bundled scenarios folder.** "Load scenario..." used to open
  wherever the system last left it, so the example scenarios that ship with the tool (under
  `_internal/scenarios`) were effectively impossible to find. It now opens straight to them.
- **The traffic-filter dropdown no longer keeps a highlight after you pick a value.** The
  combobox held keyboard focus after a selection, leaving it outlined as if still active.
- **Short dropdowns no longer show a stray scrollbar.** Lists that already fit (traffic filter,
  profiles, language) used to draw a light scrollbar strip down the side for nothing.
- **The profile list now looks exactly like the traffic-filter list.** It was built differently
  under the hood, so it opened as a pale, system-drawn list with a light border, a width of its
  own and no highlight on the profile you are using. It is now the same kind of dropdown as
  every other one in the app: same dark colours, same width as the box above it, and your
  current profile highlighted when it opens.
- **The profile list no longer has "Presets" and "My profiles" rows.** They were headings you
  could click and get nothing from. The list is now just the profiles themselves - the ready-made
  ones first, your own saved ones after them.
- **The Connections highlight follows the current target, not a flow's last packet.** A connection
  that was in scope before you narrowed the target (e.g. to `chrome`) kept its amber highlight and
  "yes" in the scope column while sitting idle, so unrelated apps like `firefox` looked like they
  were being hit. The highlight and that column are now recomputed against the target as it stands.
- **Connection rows are highlighted only when a target is actually narrowing the traffic.**
  With no target set, every connection is in scope, so the whole table used to be
  highlighted for nothing. The highlight now appears only when some connections are targeted
  and some are not, and uses a cleaner amber instead of the muddy brown tint.
- **Empty rows in the Connections table can no longer be selected.** Clicking below the last
  row used to leave a blank row looking selected.
- **The throughput chart reads cleanly at any window size.** An idle chart used to stack
  duplicate "1 1 0 0" numbers up the Y axis; the axis labels are now distinct, the chart
  drops to two labels when the window is short, and the caption tracks the chosen history
  length (e.g. "last ~120 s") so it always matches the axis.
- **No `crashes/` folder appears just from launching the tool.** The `crashes/native-crash.txt`
  file used to be created on every launch, which looked as if something had crashed. Native
  crash capture is now armed only when a real capture starts (the only moment a hard crash can
  happen), and the empty file is removed again on a clean exit - so opening the app, or a
  `--simulate` run, leaves no `crashes/` folder at all.

- **A rate increase is no longer swallowed.** The old token bucket could run tens of
  seconds ahead at a low rate and keep gating every later high-rate step, so a
  variable-throughput schedule (or "Apply changes" raising the cap) never recovered
  to the higher rate. The bounded buffer caps how far the bucket can run ahead.
- **Bounded queueing delay.** A speed limit below the offered load no longer injects
  unbounded latency (100 s+ was possible); it is capped by the buffer.
- **A tiny positive speed limit no longer becomes "unlimited"** - a sub-byte/s value
  now floors at 1 B/s instead of rounding to 0.
- **RST injection and SYN dropping are now exercised off Windows.** Synthetic traffic
  (`--simulate`) carries a real protocol mix (TCP/UDP/ICMP), and the RST packet is
  built through the traffic source, so `rst_sent` moves in tests and simulation
  instead of only on Windows with WinDivert.

### Docs

- Documented that corruption only affects payload-bearing packets, that jitter
  reorders packets and clips negative swings at zero (so jitter above latency raises
  the mean delay), and the new buffer behaviour, in both READMEs.

## [0.2.0] - 2026-07 - first public release

First public release of Bean Network Tester: a Windows tool for simulating poor
network conditions (latency, jitter, packet loss, corruption, duplication,
bandwidth limits, link flapping, TCP resets, MTU black holes and more), built on
WinDivert, with a windowed interface and a full command-line mode for CI/CD.

Highlights:

- **GUI and CLI in one executable.** Double-click for the interface; run it with
  flags for scripted, reproducible test runs. Every CLI outcome has a documented
  exit code, and machine-readable NDJSON output is available for pipelines.
- **Target what you test.** Filter by traffic direction and protocol, by
  destination IP or port, or by process (including a process and its children),
  using a compact expression language (lists, ranges, wildcards, regex, CIDR,
  IPv4 and IPv6).
- **Presets, profiles and timeline scenarios.** Start from a named preset, save
  your own link profiles, or drive changing conditions over time from a JSON
  scenario. Six example scenarios ship in `scenarios/`.
- **Reproducible.** A seed makes randomised impairment repeatable, and a
  reproduction report captures exactly what happened so a bug can be re-run.
- **Built to stay out of your way when it fails.** Fail-open design: nothing is
  allowed to leave your connection broken with the UI claiming it is running.
- **No telemetry.** The tool sends no data anywhere. It captures traffic on your
  own machine, and that data never leaves it.
- Bilingual interface (English and Polish), dark theme, DPI-aware down to
  1366x768.
