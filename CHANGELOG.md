# Changelog

All notable changes to Bean Network Tester.
The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [Unreleased]

### BREAKING

- **BREAKING:** **`--gui` no longer accepts any other option.** Combining it with settings -
  for example `--gui --loss 30 --duration 600` - used to open no window at all and quietly run
  the impairment in the background instead, with no STOP button anywhere and only Ctrl+C in a
  console you may not have been watching. It now stops immediately with a usage error (exit
  code 2) and says what to do: launch the GUI with no arguments, or drop `--gui` to run those
  settings from the command line. If a script of yours relied on the old behaviour, delete
  `--gui` from it and it behaves exactly as before.

### Changed

- **Targeting a process no longer competes with the traffic it is measuring.** Working out which
  connections belong to your target means asking Windows about its sockets, and that used to
  happen on the same thread that handles your packets - dozens of times a second, because every
  packet from every *other* application prompted another look. On a busy machine that stole time
  from the capture itself, which is how a tester ends up measuring the tool instead of their
  application. The lookup now runs on its own thread. Nothing changes in what you set or see;
  a freshly opened connection still starts being impaired within tens of milliseconds, and STOP
  stays immediate even while a lookup is in progress.

### Docs

- **The process field's exclusions are now documented properly.** Writing `!chrome` means "impair
  everything except chrome" - and "everything" includes any connection whose owning process could
  not be identified yet, which every brand-new connection passes through. If you want one
  application left alone, name the one you *do* want broken instead; then anything unidentified
  passes through untouched. Both READMEs say so next to the equivalent note for `!53` on ports.

### Fixed

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
  and keeps saying "yes" after it closes. Which connections are being impaired *right now* is
  still shown by the row highlight, which follows your current target. The connections CSV
  export already worked this way, so the table and the export now agree.

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
