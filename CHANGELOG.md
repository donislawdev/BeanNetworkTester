# Changelog

All notable changes to Bean Network Tester.
The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [Unreleased]

### BREAKING

- **BREAKING:** **A mistake in a scenario file now says so instead of doing nothing.** A misspelled
  key used to be accepted and ignored, which is the worst possible outcome: `"duraton"` quietly left
  a reset at its 3-second default, `"lop"` quietly turned looping off, and in both cases the tool
  looked like it was ignoring your file. Unknown keys - in a step and at the top level - are now an
  error naming the key, the same way an unknown *setting* name has always been. `duration` is
  validated too: it has to be a number of seconds and it only means something next to an `action`.
  A file that was correct keeps working; one that was quietly half-working will now tell you where.

### Changed

- **The checkbox is now called "Capture only the targeted traffic"** instead of "Narrow the driver
  filter to the target". The old name described the machinery rather than what you get, and
  "driver filter" means nothing unless you already know how the tool works. The `--narrow-filter`
  flag is unchanged.

- **Semicolons are gone from the interface texts and both READMEs.** Twenty-one tooltips and about
  eighty lines of documentation used them to join sentences, which is not how people write. They
  are now full stops or commas. Code samples keep theirs, since there a semicolon is syntax.

- **The "Narrow the driver filter to the target" tooltip was rewritten.** It explained how the
  option works rather than what it does, and it left out the part people most need: the option has
  **no effect at all** if you target a process, or use a wildcard or an `re:` pattern in the
  destination. It now says what it does, what changes in the Statistics and Connections tabs, and
  when it will not apply.

- **"Blocking (firewall)" now starts collapsed** on a fresh install, like the other advanced
  panels. If you have used the tool before, your own collapsed/expanded choices are remembered and
  nothing moves.

- **"Spike chance" and "Spike size" moved from "Advanced (NAT / connections)" to
  "Latency (ping)".** A spike is latency - an occasional large one - so it now sits next to the
  steady value and the jitter around it, instead of among the NAT and connection knobs. Nothing
  about how it works changed, and neither did its `--spike-prob` / `--spike-ms` flags or its place
  in a saved profile.

### Added

- **The README documents three things it never did**, in both languages:
  - **The scenario file format** - the file and step keys, what may go in `settings`, the two
    actions there are, the 1000-step limit, how looping restarts, and the 0.1 s tick.
  - **The seven shipped scenarios**, a line each: what each one reproduces and what it is for
    (which one kills the network mid-request, which one only touches DNS, which one is a one-shot).
  - **Both CSV exports and all 17 Connections columns.** The two exports behave differently on
    purpose - the statistics one appends and ignores the "targeted traffic only" switch, the
    connections one overwrites and follows your search, sorting and that switch - and the
    connections CSV does not reuse the table's labels, so there is a column-by-column map between
    them.

## [0.4.0] - 2026-07-30

### BREAKING

- **BREAKING:** **The presets were wrong, and they are now checked against published measurements.**
  Two mistakes ran through the whole list. Every latency was set as if it were a ping, but the delay
  is added to each packet in **both** directions - so "Satellite link" at 600 ms was handing you a
  1200 ms ping, against the ~680 ms a real geostationary link has. And three presets held speeds in
  kilo**bits** where the field wants kilo**bytes**, which made them eight times too fast: "3G
  network" delivered 3 Mbit/s, which is not what anybody picks that preset to feel. Both are fixed
  throughout, and every value now carries a source (or an honest note that no measurement exists,
  as for "weak Wi-Fi") in `beantester/presets.py`. **If you scripted `--preset`, the traffic you get
  will change.** Two names changed with them: "Satellite link" is now "Satellite (geostationary)",
  and "Home DSL" says VDSL. The ids did not change, so saved configs and profiles are unaffected -
  but `--preset "Satellite link"` no longer resolves.

- **BREAKING:** **The shipped scenarios in `scenarios/` were recalculated** the same way, so a
  scenario and a preset finally describe the same network with the same numbers. A pleasant side
  effect: the ping you get is now the number written in the file.

### Added

- **Five new presets**, each for a situation the old list could not describe:
  - **Satellite (low orbit)** - Starlink-like. Fast and low-ping in the steady state; what marks it
    out is the reconfiguration every 15 seconds, which briefly halts transmission and turns up as
    an occasional ping spike rather than as lost packets.
  - **Distant server (another continent)** - a fast, healthy link that is simply far away
    (~120 ms of ping). The one that catches code written as if the server were in the next room.
  - **Congested home link (bufferbloat)** - looks perfect when idle; the queue is the problem. Note
    that **it only bites once your application really saturates the link** - send a trickle and you
    will see an ordinary 8/1 Mbit/s link. Saturate the upload and watch ping climb towards two
    seconds, which is the "the video call dies when somebody starts a backup" case.
  - **Train / metro (tunnels)** - takes the connection fully down for 3 seconds out of every 30, so
    your application has to reconnect rather than just slow down. Nothing else in the list does
    that.
  - **In-flight Wi-Fi** - the satellite kind: about 750 ms of ping and 7% loss, which is a measured
    median rather than a worst case.

### Fixed

- **The profile picker cut long names off.** It was a fixed 24 characters wide, so
  "Congested home link (bufferbloat)" showed up as "Congested home link (bufferb" with nothing on
  screen saying the name went on - in both languages. It now sizes itself to its longest entry, and
  regrows when you save a profile with a long name.

### Changed

- The Latency and Jitter tooltips now say the thing that was easy to get wrong: **ping rises by
  about twice the latency you set** (both the request and the reply are delayed), while jitter
  widens the wobble by about 1.4x rather than doubling it. Both READMEs explain it too.

- **BREAKING:** **Profiles now remember more of the link.** A profile used to store seven things
  about a connection: loss, corruption, duplication, latency, jitter and the two speed limits. It
  now also stores the latency spikes, the link outages (flapping) and the buffer. The outages are
  the reason this was worth doing: they repeat on a fixed cadence, so a profile can finally describe
  a link that cuts out every so often - a satellite handover, a flaky uplink - which none of the
  other fields could say. Four things follow from it:
  - **Profiles you saved with an earlier version load exactly as before.** The fields they never had
    are simply off, and the buffer keeps its normal 1000 ms instead of quietly becoming unlimited.
  - **Picking a preset or a profile now sets all of those fields at once.** None of the twelve
    built-in presets mentions a spike, an outage or a buffer, so those go back to their defaults
    rather than keeping whatever was left in the form: "Perfect network" now really does clear
    everything. If you had dialled the buffer yourself, picking a preset resets it to 1000 ms.
  - **`--preset` on the command line now does the same thing the window does.** It applied only the
    original seven values, so the same preset name could produce different traffic depending on
    which one you started it from.
  - If you open a profile saved by this version in an older build, the new fields are ignored.

- **BREAKING:** **The reproduction report's "connections reset" counted packets, not connections.**
  It held the number of packets a reset connection swallows while it is held down, which for a
  30 second cooldown on a busy connection is thousands against a handful of actual resets - one
  reset connection could report itself as 50. The report now carries the three RST numbers as three
  keys, because they answer three different questions: `connections_reset` (how many connections
  were torn down), `rst_packets_dropped` (how much traffic that cost while they were held down) and
  `rst_sent` (how many RST packets actually reached the network stack). The last two can differ
  from the first - a connection is held down whether or not an RST could be built for it - and that
  gap is worth seeing. The statistics CSV gained a `connections_reset` column to match. Nothing on
  screen changed: the live "RST reset" tile always said "packets" in its tooltip and was right.

- **BREAKING:** **The Connections table now tells you what arrived AND what was offered.** The
  "down", "up" and "total" columns held the bytes the tool *captured* - under headings the session
  panel uses for what actually arrived. Those are the same number only while you are impairing
  nothing: with a speed limit in place a row could read 5 MB received while its application had
  received 0.4 MB. Those three columns are now the **delivered** bytes, agreeing with "Downloaded
  (MB)" in the session panel, and two new columns - **"down seen"** and **"up seen"** - hold what
  was captured. The gap between the pairs is the damage done to that connection, which is the
  number you were probably trying to read off this table in the first place. Every one of them has
  a tooltip saying which is which, because the headings alone cannot carry it. The footer sums the
  delivered columns, and says so. **The connections CSV changed shape**: `download_bytes`,
  `upload_bytes` and `total_bytes` are replaced by `delivered_down_bytes`, `delivered_up_bytes`,
  `delivered_total_bytes`, `captured_down_bytes`, `captured_up_bytes` and `captured_total_bytes` -
  renamed rather than reused, because a column that quietly changes meaning is worse than one that
  disappears.

- **BREAKING:** **"Effective loss" now means what its name says, and your numbers will change.**
  It used to be the configured Loss percentage divided by every packet the tool saw, and both
  halves of that were wrong. It ignored every other way the tool destroys traffic - a speed limit,
  blocking, LAN cut, a link outage, a connection reset, a dropped SYN, an expired NAT mapping - so
  a session losing 90% of its traffic to a bandwidth cap reported **0.0%**. And when you targeted
  one application it still divided by the whole machine's traffic, so impairing that application
  by 50% showed as **16.7%** while the application itself measured 50.1%. The figure now counts
  every impairment, over the traffic you aimed at. `effective_loss_pct` and
  `effective_corruption_pct` in the reproduction report moved the same way, so a report from
  before this release is not comparable with one from after; the report also gained
  `packets_in_scope`, and the session's NDJSON summary carries the same count. Packets the tool
  itself threw away stay out of the figure on purpose: "Buffer overflow" and "Dropped at stop" are
  the tool failing, not the link behaving badly, and they have their own counters. The number in
  the session panel now has a tooltip saying exactly this - it had none before, which is part of
  why it could be wrong for so long without anyone noticing.
- **BREAKING:** the statistics CSV gained a `packets_in_scope` column. An existing `stats.csv`
  from an older version is moved aside automatically and a fresh one started, exactly as it
  already is whenever the columns change, so no row is ever silently misaligned against the
  wrong header.

- **BREAKING:** **`--gui` no longer accepts any other option.** Combining it with settings -
  for example `--gui --loss 30 --duration 600` - used to open no window at all and quietly run
  the impairment in the background instead, with no STOP button anywhere and only Ctrl+C in a
  console you may not have been watching. It now stops immediately with a usage error (exit
  code 2) and says what to do: launch the GUI with no arguments, or drop `--gui` to run those
  settings from the command line. If a script of yours relied on the old behaviour, delete
  `--gui` from it and it behaves exactly as before.

### Changed

- **A packet you did not ask to change now goes back on the wire exactly as it arrived - and the
  session moves about 12% more traffic because of it.** The tool used to recompute every packet's
  checksums before re-injecting it, including packets it had not touched at all. That was wasted
  work, and it also meant a session with nothing configured did not quite pass traffic through
  unchanged: modern network cards leave the checksum for the hardware to finish, so recomputing it
  put different bytes on the wire than the ones that came in. Checksums are now recomputed only
  when the tool actually edited the packet - which today means corruption - and for the reset (RST)
  packets it builds itself. Measured comparing both behaviours inside the same session:
  **1.12x more packets a second, in 8 comparisons out of 8**. Verified over a real network card,
  not just loopback: 24 MiB of TCP through the tool arrived byte for byte, with a matching SHA-256.

- **A session now moves noticeably more traffic - about a third more packets a second.** The tool
  handles your packets on two threads: one takes them from the driver, the other puts them back on
  the wire. Python makes those two take turns, and by default a thread that is ready to work can be
  left waiting up to 5 milliseconds for its turn. That waiting, not the work itself, was the limit:
  putting a packet back took 57 microseconds while the same call takes 27 with nothing else in the
  way. A session now asks Python for shorter turns while it runs, and hands that setting back when
  it stops. Measured on a real capture, comparing both settings inside the same session, on
  loopback and over a real network card: **1.33x to 1.36x more packets a second, in 24 comparisons
  out of 24** - and with slightly *less* processor time per packet, not more. The queue of packets
  waiting to be re-injected stops backing up, which is what that number looks like from the other
  side. **Nothing changes in what you configure or see**, and the delay you ask for is delivered
  just as accurately as before: against a configured 10 ms, packets were late by 0.73 ms before
  and 0.76 ms after, which is the same number twice.

- **Targeting a process no longer competes with the traffic it is measuring.** Working out which
  connections belong to your target means asking Windows about its sockets, and that used to
  happen on the same thread that handles your packets - dozens of times a second, because every
  packet from every *other* application prompted another look. On a busy machine that stole time
  from the capture itself, which is how a tester ends up measuring the tool instead of their
  application. The lookup now runs on its own thread. Nothing changes in what you set or see;
  a freshly opened connection still starts being impaired within tens of milliseconds, and STOP
  stays immediate even while a lookup is in progress.

### Docs

- **Both READMEs claimed slightly more than the tool does about brand-new connections.** They said
  a connection is in scope "the moment it opens", which holds for a program the tool already
  recognises but not for that program's *first* connection: until it owns at least one socket there
  is nothing to recognise it by, so that one connection goes through untouched. Measured, so the
  exception is now stated rather than implied, next to a new note on what to do about it - if the
  program under test restarts, aim by **name** rather than by process id.

- **The process field's exclusions are now documented properly.** Writing `!chrome` means "impair
  everything except chrome" - and "everything" includes any connection whose owning process could
  not be identified yet, which every brand-new connection passes through. If you want one
  application left alone, name the one you *do* want broken instead; then anything unidentified
  passes through untouched. Both READMEs say so next to the equivalent note for `!53` on ports.

### Added

- **You can now point Statistics, the chart and Connections at your target alone.** Settings gains
  **"Show only the targeted traffic"** (off by default, so nothing changes unless you ask). With it
  on, the counter grid, the throughput chart, the Connections table and the connections CSV export
  all cover just the traffic your process / IP / port targeting selected - useful when the machine
  is busy and the numbers you care about are buried in everything else. It changes what you **see**,
  never what is captured and never what is impaired. Three things deliberately do not follow it, and
  each says so where you would look:
  - **"Queue overflow", "Dropped at stop" and "Send failed" always cover the full traffic**, because
    they count packets *this tool* lost - including traffic you never targeted. Hiding those would
    hide the tool's own damage, which is the opposite of the point.
  - **The statistics CSV keeps both totals** in separate columns instead of following the switch: it
    is an append log, and a column that means one thing in some rows and another in the rest cannot
    be charted.
  - **The reproduction report and `--format json` are unchanged** - they have always carried both
    the captured and the in-scope numbers, so a saved run never depends on how the window was set
    when it was made.
  The note above the counters and above the Connections table re-words itself to say which of the
  two you are looking at, and the chart caption names it too - so a screenshot cannot be misread.

- **A new option lets the driver do the filtering, for when you are testing at high packet rates.**
  Normally the tool receives every packet on the machine and hands almost all of them straight
  back - measured on a real run, 1944 packets taken in and none of them even eligible to be
  impaired. With **"Narrow the driver filter to the target"** (`--narrow-filter`) the destination
  IP and port are pushed into WinDivert itself, so traffic that could never be impaired is not
  handed over at all. Worth knowing before you switch it on: it takes effect **when a session
  starts**, the destination fields are then fixed until you stop, and Statistics and Connections
  cover only the narrowed traffic. It does nothing for a **process** target (Windows does not offer
  the tool a process name at that level) and falls back silently-but-loudly to capturing everything
  if your destination uses a wildcard or a `re:` pattern - the run says which of the two happened.
  **It turned out to be more than a speed option, and this is the part worth reading twice.**
  Measured on a real run with other traffic on the machine: without it, the driver was so busy
  handing over traffic the tool was never going to touch that it **threw away 43% of the traffic
  you actually aimed at, before the tool could see it** - so the session impaired less than it
  reported, and worked out its percentages from what survived. With the option on, all of it
  arrived and nothing was lost. If you test at high packet rates against a specific address or
  port, this is the setting that makes your numbers mean what they say.

- **The command line now says when the process you aimed at stops matching, instead of running on
  in silence.** If your target exits - it crashed, or your test harness restarted it and Windows
  gave it a new process id - everything from that moment on is left untouched. The run used to
  carry on and finish green, with the only mention of your target being one line printed at the
  start. Measured here against a real capture: aiming at a process id and then restarting that
  program left five out of five of its new connections completely untouched, and nothing in the
  output said so. The run now says it the moment it notices, and says so again if the target comes
  back. Worth knowing which form to use: aiming by **name** recovers on its own within about half a
  second of the restarted program opening its first connection, and only that first connection
  escapes; aiming by **process id** never recovers, because that id no longer exists. If the
  program under test restarts, aim by name.

- **Every run with a process target now ends by saying how much of the captured traffic was
  actually yours** - "In scope: 40 of 500 captured packets" - and calls it out when that number is
  zero. A run in which your target caught nothing looks exactly like a run in which your
  application coped, and those are opposite results. The existing `--min-packets` check cannot see
  this: it catches a traffic filter that matched nothing, which is a different mistake. This is a
  warning rather than a failure, because aiming at a program that happens to be quiet is a
  perfectly ordinary thing to do.

- **The session panel now shows how long packets waited inside the driver before the tool saw
  them.** This is the one delay the tool adds and counted nowhere: it happens in WinDivert's queue,
  ahead of the tool's own, so a tester measuring latency puts it down to their application or to
  the network. It is not an estimate - the driver stamps every packet with a capture time, and the
  tool now reads it 20 times a second. **"Driver queue wait (peak)"** in the Session tab holds the
  worst one, and it goes into the reproduction report with everything else. On an idle machine
  expect a fraction of a millisecond (measured here: 0.05-0.16 ms). Above 50 ms the log and the
  event list say so, at most once every five seconds. It stays blank under `--simulate`, which has
  no driver to wait in.

- **A session now records the WinDivert queue it is running behind.** WinDivert has its own buffer,
  ahead of this tool's, and nothing here ever read it - so a packet could sit in the driver for up
  to two seconds (the default queue time), land on your measured latency, and appear in no counter
  at all. The three values (length, time, size) are read when a session starts, written to the log,
  and stored in the reproduction report as `session.driver_queue`, so a report from a machine you
  do not have in front of you says which queue produced its numbers. Read on this machine:
  4096 packets / 2000 ms / 4 MiB - and note the size limit binds first for full-size packets,
  4 MiB / 1500 B = 2796 packets, not 4096. Nothing is changed about how the queue behaves; this is
  about being able to see it. `--doctor` deliberately does not read them: the values need an open
  handle, and opening one loads the driver, which would falsify the "windivert driver" line printed
  in the same report.

### Fixed

- **The live "which app owns this port" map could be dragged backwards by a stale reading, so a
  connection was briefly credited to the wrong application.** The tool learns who owns a socket
  two ways: from the driver, the instant a socket opens or closes, and from a periodic sweep of
  the system's socket table. The sweep is complete but always a little behind - it is taken up to
  0.3 s before it is used - and it was being applied on top of the live signal, so it could undo
  what the driver had just reported: put back a port that had already been closed, or name the
  previous owner of a port that had just changed hands. Measured over 25 seconds of ordinary
  traffic on a test machine, that happened **919 times**. Each one is a short window (up to about
  0.4 s) in which the Connections table shows the wrong process for a flow - and, if you are aiming
  at a process, in which a brand-new UDP exchange or a fresh connection can be judged against the
  wrong application: either your target's traffic slips through, or somebody else's gets impaired.
  Readings are now weighed by when they were actually taken, so the older one no longer wins. The
  sweep still corrects the map when it genuinely is the newer of the two, which is what recovers
  from a socket event lost under heavy load.

### BREAKING

- **BREAKING:** **"Duplicated" now counts packets that were actually sent twice, not packets the
  tool decided to duplicate.** With duplication on and the tool under enough load to fill its
  internal queue, the copy was quietly thrown away while the counter went up anyway. Measured on a
  deliberately tiny queue: 40 packets in, **"Duplicated" read 40 while nothing at all reached the
  wire**. The tile sits next to "Corrupted", which has always counted only the packets it really
  changed, so this brings the two into line. Reports and NDJSON output from before and after this
  change are not comparable on that field. Nothing else moved: the same packets are duplicated,
  and the "Buffer overflow" tile already told you when the queue was the bottleneck.

### Added

- **The tool now warns when your target shares a port with another program.** Windows lets several
  programs hold the same local port at once - that is how mDNS, SSDP and DHCP work - and this tool
  decides what to break from the port number, so on those ports it genuinely cannot tell whose
  traffic it is looking at. On this machine, four port numbers out of 127 were like that, and one
  of them (5353, used for local device discovery) had **five** owners at the same time. The
  consequence is real in both directions: aiming at one program could leave its own traffic on such
  a port untouched, or sweep three other programs' traffic in with it. Nothing about that changed -
  it cannot be fixed, because the port number simply does not say who sent the packet - but the
  tool no longer keeps it to itself. Applying a target now says which port is shared and with whom,
  so you know that part of the result is a coin toss. Ports that are not shared, which is where
  your application's own traffic lives, are unaffected.

### Fixed

- **When the capture could not start, the tool told you the wrong reason.** If the WinDivert handle
  failed to open - no Administrator rights, a driver blocked or held at a different version by
  another tool, a filter the driver rejects - the tool went ahead and started the session anyway,
  then reported `WinDivert handle is not open`. That is a symptom, and it names nothing. The actual
  reason (for example `[WinError 5] Access is denied`) was written only to a diagnostic file nobody
  is asked to read. Worse, the *helpful* messages both interfaces already had could never appear:
  the command line has an error that quotes the real cause, and the window has a dialog with a "run
  as Administrator" hint - which is exactly what a non-elevated user needed and never saw. Starting
  now fails immediately, with the reason, and both of those work.

- **The log could read backwards when a session died right after starting.** The "Start. Filter:
  ..." line was written after the capture had already begun, so a session that failed in its first
  moments printed the error and the fault *above* its own start line. Anyone reading the log to work
  out what happened when was reading it out of order. It is now announced first.

- **Turning NAT expiry off did not fully turn it off.** Switching it on tells the tool to remember
  every connection for as long as the session lasts - it has to, or an expired mapping would quietly
  reopen. Switching it back off was supposed to restore the normal "forget idle connections after
  half a minute" behaviour, and did not: the tool kept every record for the rest of the run and only
  released them when it ran out of room. Since every "Apply changes" re-sends all your settings, one
  round trip through the NAT field was enough. Memory only - nothing was impaired differently.

- **The Connections tab could empty itself instead of dropping its oldest rows.** Once the table is
  full the tool discards roughly the oldest tenth, working from a sampled estimate of "old". If a
  lot of rows carried the same timestamp, they all fell on the same side of that estimate and far
  more went than intended - in the extreme, everything. It now refuses to drop below the level it
  is trimming to, whatever the estimate says.

- **Stopping a session could file a crash report for nothing.** If STOP landed inside the
  half-second housekeeping pass that keeps the socket map fresh, the tool tripped over its own
  shutdown and wrote an entry into `crashes/`. Nothing was broken - the session stopped correctly
  and traffic returned to normal - but anyone checking that folder after a run would find a report
  for an ordinary STOP. It no longer happens.

- **Aiming at a process did not touch the first packet of a UDP exchange - and for DNS and QUIC
  that meant it did not touch them at all.** Working out which connections belong to your target
  means keeping a set of its ports, rebuilt in the background, and a brand-new port is not in it
  yet. TCP had a way around this: a connection starts with a SYN, so one packet per connection was
  checked against the live socket map. UDP has no SYN, so nothing was checked - and the traffic
  where it matters takes a **fresh port every time**: every DNS query, every QUIC connection. Those
  went past your target untouched, every one of them. They no longer do. If you have tested a game,
  a video call or a browser over QUIC and the impairment seemed weaker than you configured, this is
  why. Ordinary TCP data is deliberately still not re-checked - it does not need to be, and
  measuring showed it would cost real throughput for nothing.

- **The "the driver held a packet" warning told you about lost accuracy when what you were losing
  was traffic.** It said the wait lands on the delay you are measuring - true, and not the half
  that matters. Measured here on a deliberately overloaded run: with 138,000 packets a second
  offered, the tool moved about 14,000 of them and **91.75% of the traffic was thrown away by the
  driver before this tool ever saw it** - while every drop counter on screen still read zero,
  because the tool cannot count what never reaches it. (The same load with the tool switched off
  lost nothing at all, so that loss is the tool's presence, not the machine.) The warning now says
  that a full driver queue means dropped packets, not just late ones, and tells you to narrow the
  traffic filter. The session-start line about the queue says the same. If you have ever run a test
  through this tool at a high packet rate and trusted the counters, this is the entry to read
  twice.

- **Aiming at a process missed the first packet of every new connection - and your test results
  will change because of it.** Working out which connections belong to your target means keeping a
  set of its ports, and that set is rebuilt in the background. A connection opened a moment ago was
  not in it yet, so its very first packet was waved through untouched, every time. Measured here:
  20 fresh connections against a targeted process with "Drop SYN" at 100% produced 20 successful
  connections and not one dropped SYN. **"Drop SYN" combined with process targeting therefore did
  nothing at all** - the SYN is by definition the first packet, so it always escaped. The first
  packet is now checked against the live socket map, so it is caught like any other.

  What changes for you: with loss (or blocking, or a link outage) aimed at a process, **connections
  will now take noticeably longer to open**, because the SYN can be lost and TCP has to retransmit
  it - and a minority will fail to open at all, which is what a bad network does. Before, every
  connection opened at full speed and only then started suffering. If a test of yours measured
  "time to first byte" under impairment, expect it to move.

  Two limits worth knowing, both measured rather than guessed. The tool recognises your target by
  the connections it currently has open, so **a program that has none open at the moment the tool
  looks is invisible again**: over 20 fresh connections with "Drop SYN", a program keeping its
  connections open was caught **19 times out of 20** (only the very first escaped, before it had
  opened anything), while the same program closing each connection before starting the next was
  caught **6 times out of 20**. So a browser or an app under test is covered; a script that opens
  one connection, closes it and pauses will keep slipping through. And a program using UDP has no
  SYN, so its first packet is not covered by any of this.

- **"Reset connections" no longer fires on a connection that is still opening.** It could not have
  worked there anyway: the reset packet the tool forges from a connection request carries no
  acknowledgement number, and Windows is entitled to ignore exactly that - measured, the connection
  hung until its own timeout instead of being reset. That combination was unreachable before the
  change above; it would have become the normal case. Resets now fire on established connections,
  where they were measured to work.

- **"Reset connections" did nothing to local (loopback) connections - it just made them go
  quiet.** Aim the tool at `127.0.0.1` traffic with resets switched on and the connection was not
  reset: it stopped carrying anything for the length of the cooldown, so the application sat there
  until its own timeout expired, while the tool reported an RST as sent. Anything talking to a
  service on your own machine - a local server, a database, a dev proxy - was affected. It now
  resets for real, which for a test that expects a broken connection is the difference between
  "failed as designed" and "hung". Connections to other machines were never affected, and are
  unchanged: that path was measured working (a connection reset 6.6 s after the tool was pointed
  at it).

- **A connection's "dropped" count ignored the packets the tool's own queue threw away.** The
  figure was recorded a step too early - before the packet was even queued - so a session that
  dropped 5 500 packets to a full delay queue could show `dropped = 0` on the very row it happened
  to, and packets still waiting when you pressed STOP were never counted against their connection
  at all. Both now land on the row they belong to.

- **A failed "Export connections CSV" left a stray `.tmp` file next to the real one.** The export
  writes to a temporary file and renames it, which is what makes it safe to overwrite the previous
  export - but when the write failed, the half-written temp file stayed on disk. Nothing cleaned
  it up, and the next export silently overwrote it, so it was litter you could find but not
  explain. It is now removed on failure, exactly as the profile and config files already do, and a
  failed export leaves the previous one untouched.

- **STOP could take two seconds if a capture error happened to land at the same moment.** If the
  capture side failed for its own reason a fraction of a second before you pressed STOP, the two
  waited on each other until a two-second safety timeout expired. Nothing was lost or stuck - the
  session did stop - but the button felt broken. The capture side now waits only for a session
  that is still starting up, never for a stop that is already under way. Related: when two
  failures land together, the report keeps the first one, which is the actual cause; it used to be
  overwritten by the follow-up "a worker thread died", which says nothing useful on its own.

- **Starting a second scenario without stopping the first is no longer possible.** The engine
  replaced the running scenario with the new one and left the old one running in the background,
  unreachable: two scenarios then fought over the same settings with nothing on screen to say why.
  Nothing in the program did this today - it starts one scenario per session - so this is a guard
  rather than a bug you could have hit.

- **Packets the tool failed to put back on the wire vanished from the numbers.** When re-injecting
  a packet fails - the connection went down mid-session, the driver refused it - the packet is
  gone. It had been counted as seen, it was never delivered, and nothing recorded it as lost, so
  it simply left the arithmetic: a session could show packets climbing while the delivered total
  stood still, with no counter explaining the gap. Every other way a packet can die here has had a
  counter for a while; this one only had a line in the log. There is now a **"Send failed"**
  counter next to "Buffer overflow" and "Dropped at stop", a warning banner when it happens, and
  an entry in the event log so the reproduction report carries it too. Like the other two, it is
  the tool failing rather than the link you asked it to simulate, so it stays out of "Effective
  loss" - but it is in the seen/delivered/dropped arithmetic, where it belongs.

- **A run of send failures no longer floods the log (and freezes the window with it).** The
  message was written once per failed packet, and the window applies every queued line to the log
  strip on the interface thread, so a burst of failures could lock up the window on top of losing
  the packets. It is now written at most once every five seconds, carrying the running count and
  the last error, exactly like the queue-overflow warning that has worked this way for a while.

- **"Effective loss" now says whose loss it is.** The number counts what this tool broke, and the
  tooltip said "how much of the traffic you aimed at never arrived" - which reads as "never
  reached the far end". Those are different things, and the difference shows up the first time you
  compare the tool against a real run: ping 30 packets, lose one reply out on the network, and the
  connection row reads 59 packets with zero drops. Both numbers are right - 30 requests went out,
  29 replies came back, and the tool broke none of them - but nothing on screen said so. The
  tooltip and both READMEs now spell out that the figure measures damage done on this machine, and
  that loss happening somewhere out in the network never reaches this machine, so nothing here can
  count it. No numbers changed.

- **Ping traffic never appeared in the Connections tab, which claims to list all of them.** The
  note under the tab says "All captured connections" and the README says the same, but anything
  without ports was silently left out - and ping (ICMP) has none. Thirty seconds of pinging with
  the "Ping (ICMP)" traffic filter selected left the tab completely empty while the packet
  counters ticked up beside it, which reads as a broken tool. Portless traffic is now listed as
  one row per address, with the two port cells left empty. The process column usually stays empty
  on those rows as well: a ping has no socket to trace back to an application, which is how ICMP
  works rather than something missing here. In the command line, `--log-conns` prints `-` where
  such a row has no port.

- **"Buffer overflow" and "Dropped at stop" counted up to twice the packets they lost.** With
  "Duplicate packets" switched on, the tool puts a second copy of the packet in its delay queue,
  and both counters were charging for the copy as well as for the packet. A run that duplicated
  everything reported nearly twice as many dropped as it ever captured, so the "Buffer overflow"
  tile could show a bigger number than the "Packets" tile right beside it, and the overload
  warning in the log quoted that inflated figure back at you. Both now count packets that never
  arrived. A dropped copy is not one of them: your application receives one packet instead of
  two, and one packet is what it would have received without the tool, so a copy that does not
  fit no longer counts and no longer raises the overload warning on its own. Runs without
  duplication are unaffected; figures from earlier runs with duplication are not comparable with
  these, because the old ones were too high.

- **Two tooltips were telling you things that were not true.** "Dropped" said it also counted
  link outages - those have had their own counter for a while, so the tooltip was sending you to
  the wrong number when working out where your packets went. "Downloaded (MB)" promised that
  hovering would also show how much the app tried to download; nothing of the sort ever appeared.
  Both now describe what the counter actually holds.

- **Long connection cut-offs and NAT blackouts now last as long as you set them.** Two impairments
  quietly stopped early, because the tool forgets a connection it has not seen for a while and a
  forgotten connection looks brand new. "Reset connections" with a cooldown above about half a
  minute resumed traffic after roughly 30 seconds however long you had asked for - a scenario
  written as "the connection is down for two minutes" simply did not happen. "NAT mapping expiry"
  was worse: at a 30 second timeout it never blocked a single packet, because the connection was
  forgotten just before the incoming traffic arrived. Both now hold for exactly as long as
  configured - a 120 second cooldown resets every 120 seconds, and an expired NAT mapping stays
  shut until the application sends something, which is the behaviour the setting describes. The
  tool's memory limits are unchanged.

- **The delay you set is the delay you get.** Every configured delay used to arrive with several
  milliseconds of padding on top, because of how Windows rounds up the wait the tool uses to hold
  a packet back. It was a fixed surcharge rather than a percentage, so it barely showed at 100 ms
  and swamped the small settings: with the tool asked for 10 ms, a ping measured about 12.6 ms of
  extra round trip on top of the expected amount, and asking for 1 ms produced roughly seven times
  that. Simulating a fast LAN, a game server or a VoIP hop is exactly where that hurt. The tool now
  asks Windows for a fine-grained timer while a session runs, and gives it back at STOP. Measured
  with a plain `ping`, 40 packets per setting: asking for 10 ms of delay now costs 1 ms more than
  it should instead of 12.6 ms, and asking for 50 ms costs the same 1 ms more - the surcharge is
  gone rather than merely smaller. Jitter benefits the same way: variation below about 15 ms used
  to disappear into the timer's own noise.

- **"NAT mapping expiry" now really cuts the incoming direction, instead of losing one packet
  every few seconds.** This impairment is there to answer one question: does the application
  notice its mapping is gone and send something to re-open it? It could not answer that. The
  packet the tool rejected for "the mapping has expired" was itself counted as activity on that
  connection, so the mapping came back on the spot and traffic flowed again for another whole
  timeout - then one more packet was dropped, and so on. With `--nat-timeout 5` an app that never
  sent a keep-alive lost about one packet every five seconds and otherwise carried on working, so
  it passed a test it should have failed. Now incoming traffic stays cut until the application
  actually sends something outbound, which is what re-opens the mapping on a real NAT. Nothing
  changes when you leave the setting at 0 (off, the default).

- **Short-lived connections now show which program they belong to.** The Connections table works
  out the owning program by asking Windows which application holds each socket, and that answer
  used to come from a list refreshed a few times a second. A connection that opened and finished
  in between two of those refreshes was never on the list, so its row stayed blank in the Process
  and PID columns - and brief connections like that are exactly what you get when a browser, or an
  app you are testing, opens hundreds of them a minute. The tool is now told who owns a connection
  the moment it is created, so the row is filled in from its very first packet. The program's name
  can still appear a moment after its process number, because names are looked up in the
  background, but the row no longer stays empty.

- **A window you have moved now keeps its place when you switch language.** Changing the language
  rebuilds the whole main window, and a smaller window open at the time - Settings, for example -
  was torn down with it. It came back at the size and position it had the last time you closed it,
  quietly throwing away wherever you had just dragged it. It now stays where you put it.

- **Setting a process target no longer makes the first start pause.** Working out which process
  owns each connection could take a second or two the first time, because it fell back to scanning
  every process on the system. It now resolves only what it needs, so starting - and typing a
  target - is quick, and the connections it catches settle in almost immediately instead of after
  that pause.

- **Targeting a process now catches its connections as they open, including short-lived ones.**
  Working out which connections belong to your target used to mean scanning the system's socket
  table a few times a second - so a connection that opened and closed between two scans (a browser
  makes many) could slip through unimpaired, and pointing the tool at a busy app like Chrome caught
  only some of its traffic. On Windows the tool now follows the system's socket events as they
  happen, so a connection is impaired from the moment it opens - for outbound connections, before
  its first packet even leaves. Without real WinDivert it falls back to the old scan. Nothing
  changes in how you set a target.

- **The "impaired?" column now reflects the whole session, not just this instant.** When you
  targeted a process, the column asked "is this connection's port in the target *right now*" -
  so the moment a connection closed (a browser closes hundreds a minute) its row flipped to
  "no", and a run that was impairing all of Chrome looked like it was catching almost nothing.
  The column now records whether a connection was in impairment scope at any point this session
  and keeps saying "yes" after it closes. The row highlight, the column, the sort and the CSV
  export all read that one record, so they can never disagree - a row is coloured exactly when
  its column says "yes".

- **One bad translation file no longer stops the whole program.** Language files are plain JSON
  next to the program, and you can add your own. If one of them had a malformed `_meta` header -
  the little block naming the language - the program refused to start at all, with a technical
  error and no hint that a language file was to blame. Even asking it for its version failed. A
  header it cannot read is now simply ignored: the translations in that file are still used, and
  the language is named after the file.
- **`--dry-run` now checks your scenario file as well.** That option exists to tell you whether a
  run will work before you start it - but it never actually opened the scenario file, so a damaged,
  empty or half-written scenario passed the check with "Configuration is valid" and then failed the
  real run moments later. It now reads the scenario too and tells you straight away what is wrong
  with it. A check that passes everything is worse than no check at all.
- **A settings file in the wrong form now gives a clear message instead of crashing.** If you
  pointed `--config` at a JSON file that was readable but not a set of settings - a list, say, or
  a single value, which is what some tools produce - the program stopped with a raw Python error
  and reported itself as having crashed. It now says what it expected and stops with the "bad
  configuration" code, so a script running it can tell the difference between "your file is wrong"
  and "the tool broke".
- **A damaged window-layout file no longer stops the program from starting.** The program
  remembers your window size, the page you were last on and which sections you had collapsed, in a
  small file next to it. That file is yours to edit, and it also gets copied between machines - and
  if an entry in it ended up the wrong shape, the program could fail to open at all, with an error
  that gave no hint which file was to blame. Anything it cannot make sense of is now ignored, that
  one setting goes back to its default, and the log tells you which entries were skipped. The rest
  of your layout is kept.
- **Ending a session now hands your network back at once, instead of a moment later.** When a run
  finished - whether you pressed STOP or its time ran out - the tool stopped looking at packets
  immediately, but kept its grip on your network traffic for a moment longer while it tidied up
  after itself. In that moment Windows was still handing packets to something that was no longer
  reading them, so a connection or two could stall right at the end of a run. The moment was
  usually far too short to notice; if the tool happened to be busy working out which process you
  were targeting, it stretched to about a quarter of a second. Your traffic is now let go first,
  and the tidying up happens afterwards.
- **Targeting could follow a process ID after the process was gone - and Windows hands those
  numbers out again.** Two things went wrong once that happened, both silently. Restart the
  application you are targeting and it could come back with a number the tool still remembered
  under the old name, so **it was no longer impaired** - the run looked like the app coping when
  really nothing was being done to it. And in the other direction, a completely different program
  that happened to inherit the number **was impaired instead**, so an application you never named
  had its network broken. The tool now checks that the process behind a number is still the same
  one before it trusts what it remembers, and forgets a process the moment it closes its last
  connection.
- **`--doctor` could report a WinDivert driver as "not loaded" when it simply was not allowed
  to look.** Windows refuses full access to some services even for an Administrator, and the
  check treated that refusal as "the service is not there" - in the one command whose whole job
  is to tell you the truth about your machine. It now asks only for permission to read the
  state, which also means the driver line is accurate **without** running as Administrator. If
  the state genuinely cannot be read, the line now says so and warns, instead of quietly
  reporting a clean machine.
- **`--cleanup-driver` explains a refusal instead of calling it "not installed".** Being told
  "access denied - the service exists but this account may not remove it" points somewhere;
  being told the service was never there does not.
- **A session that fails to start now hands your network back and lets you try again.** Starting a
  run sets up several background workers, and if your machine could not spare the resources for one
  of them - most likely while you are already running the heavy load you are testing against - the
  start failed halfway. The tool could be left holding your traffic without actually impairing it,
  showing an error while quietly keeping its grip, and every later START was refused until you
  killed the program. A failed start now releases your network immediately and leaves the tool
  ready to start again, exactly as if you had never pressed START.
- **STOP is immediate again when you press it just as a timed run ends.** If you hit STOP at the
  same moment a run reached its set duration, the tool could sit on "stopping" for about two seconds
  before the window went back to normal. Your network was already handed back at once - it was only
  the button that lagged - but a STOP that looks stuck is exactly the wrong thing in a tool whose
  whole job is undoing what you did to your own connection. It now finishes right away either way.

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
