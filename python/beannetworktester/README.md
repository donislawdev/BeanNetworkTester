# beannetworktester

Slow down, break or cut the **real network** in your tests: latency, packet loss, jitter,
bandwidth limits, outages. For one server or one process, on Windows and Linux, with pytest,
Playwright for Python or any Python code.

It runs [Bean Network Tester](https://beannetworktester.donislawdev.com/)'s own program, which
this package carries: on Windows the same signed program as the release. Nothing is mocked:
your app, your browser and your server talk over a network that is really slow.

```python
def test_the_page_survives_a_slow_api(bad_network, page):
    bad_network(server="http://localhost:8000", latency=300, loss=2)
    page.goto("http://localhost:3000")
    ...
```

## Install

```
pip install beannetworktester
```

Windows x64 and Linux x64 (glibc 2.39 or newer, such as Ubuntu 24.04), Python 3.10 or newer.
On other systems the package installs without the program and says so when a test asks for a
slow network.

## Rights

Changing the network needs **administrator rights on Windows** and **root on Linux**.

- **Windows:** run the tests from a terminal opened with *Run as administrator*. GitHub's
  Windows runners already run elevated.
- **Linux:** run the tests as root, or as a user who may run `sudo` without a password, as on
  GitHub's Ubuntu runners. The program then runs under `sudo`, and your tests do not.

Without the rights, the test fails with a sentence that says which of these is missing.

## In pytest

The `bad_network` fixture starts a session when you call it, and stops it when the test ends:

```python
def test_checkout_retries_when_the_api_is_slow(bad_network):
    bad_network(server="https://localhost:8443", latency=500, jitter=100)
    assert place_order().status == "paid"
```

The session's summary goes into the test's `user_properties`, and from there into a JUnit XML
report: the packets seen, how many of them were in scope, the seed, and the command that repeats
the same conditions with the program on its own.

## Anywhere else

```python
from beannetworktester import bad_network

with bad_network(server="http://localhost:3000", loss=5, duration=120) as session:
    run_my_client()
print(session.summary["counters"]["scoped_seen"], "packets were slowed")
```

`bad_network(...)` starts the session and returns it, and `with` stops it at the end. Without
`with`, call `session.stop()`, which returns the summary.

## Playwright for Python

Playwright for Python runs on pytest, so the fixture is the same:

```python
def test_the_spinner_shows_on_a_slow_network(bad_network, page):
    bad_network(server="http://localhost:3000", latency=800)
    page.goto("http://localhost:3000")
    expect(page.get_by_role("progressbar")).to_be_visible()
```

Chromium, Firefox and WebKit are all slowed the same way, and so are WebSockets: the network
itself is slow, not the browser's idea of it.

## What a session aims at

A session always aims at something. Without an aim it would slow every connection of the
machine, the test runner's own included, so `bad_network` refuses to start.

- `server="http://localhost:3000"`, `server="db.local:5432"` or `server=("10.0.0.5", 443)`:
  every connection to that address and port, from any program. This is exact on Windows and on
  Linux, and the first choice.
- `process="self"`: this test process and every program it started, such as the browser of
  Playwright for Python. Or a process ID, or a program name such as `"node"`. On Linux a new
  connection of the process is reached up to about 0.2 seconds after it opens, so its first
  packets can go through untouched. Aim at the server when the first request counts.
- `target`, `dst_ip` and `dst_port` are the program's own aims, in its own syntax.

`server=` and `process=` together slow only that process's connections to that server.

## What a session can do

Every setting is one of the program's flags, written with `_` instead of `-`:

| Setting | What it does |
|---|---|
| `latency=300` | adds 300 ms to every packet |
| `jitter=100` | varies the delay by up to 100 ms either way |
| `loss=5` | drops 5% of the packets |
| `down=256`, `up=64` | limits download and upload to so many KB/s |
| `flap_period=10, flap_down=30` | the link goes down for 30% of every 10 seconds |
| `rst_prob=2` | tears 2% of TCP connections down with a reset |
| `loss=100` | cuts the connections to the aim off completely |
| `preset="presets.3g"` | a named link profile, such as 3G or a satellite link |
| `scenario="steps.json"` | settings that change over time |
| `seed=42` | the same random choices on every run |

The program checks the settings itself, so a misspelled one fails the test with its message. The
full list is on [the command-line page](https://beannetworktester.donislawdev.com/command-line/) and
in `BeanNetworkTester --help`.

## Safety

- `duration` (300 seconds unless you give another) is the most a session may run. It ends then,
  even if nothing stops it, and the test gets a warning that the rest of it ran on a normal
  network.
- If the test process dies, the program sees its input close and stops at once.
- One session runs at a time on a machine, because two would add up. With parallel workers
  (pytest-xdist), the tests that slow the network wait for each other, for up to `wait` seconds
  (600 unless you give another).
- When a session slowed nothing, because nothing reached its aim, the test gets a
  `BadNetworkWarning`.

## Other options

- `simulate=True` runs the program on made-up traffic: no rights needed and nothing on the
  network changes. For trying the helper out.
- `BEANNETWORKTESTER_PROGRAM` in the environment points at another copy of the program, such as
  one installed with WinGet, or `bean_network_tester.py` from a checkout.

## Licence

GPL-3.0-only, like the program it carries. The program's third-party notices are inside the
package, next to it. Source, issues and the changelog:
[github.com/donislawdev/BeanNetworkTester](https://github.com/donislawdev/BeanNetworkTester).
