# beannetworktester

Slow down, break or cut the **real network** in your tests: latency, packet loss, jitter,
bandwidth limits, outages. For one server, one API or one process, on Windows and Linux, with
pytest, Playwright for Python or any Python code.

```python
def test_the_page_survives_a_slow_api(bad_network, page):
    bad_network(server="http://localhost:8000", latency=300, loss=2)
    page.goto("http://localhost:3000")
    ...
```

Nothing is mocked: your app, your browser and your server really talk over a slow network. The
package carries [Bean Network Tester](https://beannetworktester.donislawdev.com/)'s own program
and runs it for the length of a test. On Windows it is the same signed program as the release.

## Quick start

**1. Install**

```
pip install beannetworktester
```

Windows x64 or Linux x64 (glibc 2.39 or newer, such as Ubuntu 24.04), Python 3.10 or newer.

**2. Get the rights.** Changing the network needs **administrator rights on Windows** and
**root on Linux**:

- Windows: open the terminal with *Run as administrator*. GitHub's Windows runners already run
  elevated.
- Linux: run the tests as root, or as a user who may run `sudo` without a password, as on
  GitHub's Ubuntu runners. Then only the program runs under `sudo`, and your tests do not.

**3. Save this as `test_slow.py` and run `pytest`**

```python
import subprocess
import sys
import time
import urllib.request

import pytest


@pytest.fixture
def web_server():
    server = subprocess.Popen([sys.executable, "-m", "http.server", "8000"])
    time.sleep(1)                                    # give it a moment to listen
    yield "http://localhost:8000"
    server.terminate()


def test_a_page_takes_longer_on_a_slow_network(bad_network, web_server):
    bad_network(server=web_server, latency=500)      # every connection to it, +500 ms
    started = time.monotonic()
    urllib.request.urlopen(web_server).read()
    assert time.monotonic() - started >= 0.5
```

The test passes because the page really took half a second longer. When it ends, the network
is back to normal.

No rights at hand? `bad_network(simulate=True, latency=500)` runs the program on made-up traffic,
needs no rights and changes nothing on the network. It is for checking that the package is set
up, not for slowing your app.

## In pytest

The `bad_network` fixture starts a session when you call it and returns once the network is
slow. The session stops when the test ends, whether it passed, failed or crashed:

```python
def test_checkout_retries_when_the_api_is_slow(bad_network):
    bad_network(server="https://localhost:8443", latency=500, jitter=100)
    assert place_order().status == "paid"
```

To change the conditions in the middle of a test, stop the first session before you start the
next one, or give one session a scenario (below):

```python
def test_the_app_recovers_when_the_api_comes_back(bad_network):
    outage = bad_network(server="http://localhost:8000", loss=100)
    assert app_shows_offline_banner()
    outage.stop()                                    # the network is normal again
    assert app_hides_offline_banner()
```

## Playwright for Python

Playwright for Python runs on pytest, so the fixture is the same:

```python
from playwright.sync_api import expect


def test_the_spinner_shows_on_a_slow_network(bad_network, page):
    bad_network(server="http://localhost:3000", latency=800)
    page.goto("http://localhost:3000")
    expect(page.get_by_role("progressbar")).to_be_visible()
```

Chromium, Firefox and WebKit are all slowed the same way, and so are WebSockets: the network
itself is slow, not the browser's idea of it.

## Without pytest

```python
from beannetworktester import bad_network

with bad_network(server="http://localhost:3000", loss=5, duration=120) as session:
    run_my_client()
print(session.summary["counters"]["scoped_seen"], "packets were in the aim")
```

`bad_network(...)` starts the session and returns it, and `with` stops it at the end. Without
`with`, call `session.stop()`, which returns the summary.

## What a session aims at

Every session aims at something, and only that traffic changes. Without an aim it would slow
every connection of the machine, the test runner's own included, so `bad_network` refuses to
start.

| Aim | What is slowed |
|---|---|
| `server="http://localhost:3000"` | every connection to that address and port, from any program. Also `"db.local:5432"` or `("10.0.0.5", 443)` |
| `server=["http://localhost:3000", "localhost:8080"]` | several servers: every address of them with every port of them |
| `process="self"` | this test process and every program it started, such as Playwright's browser |
| `process=proc` | a process your test started: pass the `subprocess.Popen` itself, not its number |
| `dst_port=8080` | every connection of this machine to that port, at any address: an API on a known port |
| `dst_ip="10.0.0.5"` | every connection to that address, any port. Also lists, ranges and CIDR such as `"172.18.0.0/16"` |
| `target="myapi"` | processes by name or by process ID, in the program's syntax |

`server=` is the first choice: it is exact on Windows and Linux. `dst_ip`, `dst_port` and
`target` are the program's own aims, written in [its syntax](https://beannetworktester.donislawdev.com/command-line/)
(lists, ranges, `!` to leave something out). They reach **everything that matches**, so think
about what else uses it:

- `dst_port=443` is every HTTPS connection of the machine: your browser, your editor, the CI
  runner's own connection. Aim at the server instead, or add `process="self"`.
- `target="node"` is every program whose name contains "node", your editor and the test runner
  included.
- `dst_ip="!10.0.0.5"` is everything except that address.

Aims given together narrow each other. `server=` with `process="self"` slows only this test's
connections to that server, and `process="self"` with `dst_port=8080` only this test's
connections to port 8080.

On Linux, `process=` and `target` reach a new connection up to about 0.2 seconds after it
opens, so its first packets can go through untouched. Aim at the server when the first request
counts.

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
| `loss=100` | cuts the connections in the aim off completely |
| `block_port=5432` | blocks the traffic to that port, inside the aim |
| `preset="presets.3g"` | a named link profile, such as 3G or a satellite link |
| `seed=42` | the same random choices on every run |

The program checks the settings itself, so a misspelled one fails the test with its message. The
full list is on [the command-line page](https://beannetworktester.donislawdev.com/command-line/) and
in `BeanNetworkTester --help`.

## Conditions that change over time

A scenario is a JSON file of steps, each at a second of the session:

```json
{"steps": [
  {"at": 0,  "settings": {"latency": 100}},
  {"at": 10, "settings": {"latency": 800, "loss": 10}},
  {"at": 20, "settings": {"loss": 100}}
]}
```

```python
bad_network(server="http://localhost:3000", scenario="slow-then-down.json", duration=60)
```

The program's own scenarios work by name, such as `scenario="scenarios/cafe-wifi.json"` or
`"scenarios/mobile-lte-to-3g.json"`. A step may change how the network behaves, but not what
`server=` or `process=` aim at: the helper reads the file first and refuses such a step, because
it could widen the aim to the whole machine.

## Safety

- **Never the whole machine by accident.** A session without an aim does not start.
- **It ends with the test.** The fixture stops it when the test ends. If the test process dies,
  the program sees its input close and stops at once. `duration` (300 seconds unless you give
  another) is the most a session may run in any case, and the test gets a `BadNetworkWarning`
  when it ran out first.
- **One at a time.** Two sessions over the same traffic would add up. Parallel workers
  (pytest-xdist) take turns, each waiting up to `wait` seconds (600 unless you give another). A
  second session in the same test is refused at once.
- **It says when it did nothing.** A session that slowed nothing, because nothing reached its
  aim, ends with a `BadNetworkWarning`.

## When something goes wrong

| What you see | What to do |
|---|---|
| "needs administrator rights on Windows" | open the terminal with *Run as administrator* |
| "needs root on Linux" | run as root, or allow `sudo` without a password for this user |
| `BadNetworkWarning`: "the session slowed nothing" | the app talks to another address than the aim: a container, the machine's network address instead of `localhost`, or a proxy. Aim at the address it really uses, or use `process="self"` |
| "Another bad_network session has been running" | parallel workers wait for each other: give a longer `wait=`, or run those tests in one worker |
| "has not been stopped yet" | stop the first session of the test before you start the next one |
| "runs the network on Windows x64 and Linux x64 only" | on a Mac, run the tests in a Linux x86_64 container or virtual machine, or on a CI runner |
| "has no program in it" | install with a 64-bit Python and a current `pip` |
| `BadNetworkWarning`: "ended by its duration" | give a longer `duration=` |
| "the program refused the settings" | the program's own words follow, and name the setting |

## The summary

Every session ends with the program's summary: `session.summary`, or `stop()`'s return value.
In pytest it also goes into the test's `user_properties`, and from there into a JUnit XML report.
The parts worth reading:

- `counters["seen"]`: packets the program saw. `counters["scoped_seen"]`: those in the aim.
- `stop_reason`: `"stdin"` when the test stopped it, `"duration"` when time ran out.
- `seed` and `repro_command`: the command that repeats the same conditions with the program on
  its own.

## Other options

- `duration=`: the most seconds a session may run, 300 unless given, at most 86400.
- `wait=`: seconds to wait for another session to end, 600 unless given.
- `start_timeout=`: seconds to wait for the program to start, 60 unless given.
- `BEANNETWORKTESTER_PROGRAM` in the environment points at another copy of the program, such as
  one installed with WinGet, or `bean_network_tester.py` from a checkout.

## Licence

The package's own code, the part your tests import, is under the Mozilla Public License 2.0
(MPL-2.0), in LICENSE. You can use it in the tests of any project, closed-source ones included, and
your tests stay yours. If you change one of the package's own files and pass it on, that file stays
under MPL-2.0.

The program the package carries and starts is a separate program, under GPL-3.0-only. Its licence
and third-party notices are in the package, next to it. Source, issues and the changelog:
[github.com/donislawdev/BeanNetworkTester](https://github.com/donislawdev/BeanNetworkTester).
