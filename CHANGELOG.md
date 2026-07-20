# Changelog

All notable changes to Bean Network Tester.
The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.

## [0.3.0]

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
