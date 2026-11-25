# beannetworktester

Slow down, break or cut the **real network** in your tests: latency, packet loss, jitter,
bandwidth limits, outages. For one server, one API or one process, on Windows and Linux, in
Playwright Test or any Node code.

```js
import { test, expect } from 'beannetworktester/playwright';

test('the spinner shows on a slow network', async ({ page, badNetwork }) => {
  await badNetwork({ server: 'http://localhost:3000', latency: 800 });
  await page.goto('http://localhost:3000');
  await expect(page.getByRole('progressbar')).toBeVisible();
});
```

Playwright's own tools can only take a page offline, or slow Chromium through DevTools. This
works below the browser, on the network itself, so Chromium, Firefox and WebKit are slowed the
same way, WebSockets and WebRTC included, and so is your API server if you aim at it. The
package carries [Bean Network Tester](https://beannetworktester.donislawdev.com/)'s own program
and runs it for the length of a test. On Windows it is the same signed program as the release.

## Quick start

**1. Install**

```
npm install --save-dev @playwright/test beannetworktester
npx playwright install chromium
```

Windows x64 or Linux x64 (glibc 2.39 or newer, such as Ubuntu 24.04), Node 20 or newer. npm
installs the program for your system as an optional dependency, so do not leave optional
dependencies out (`--omit=optional`).

**2. Get the rights.** Changing the network needs **administrator rights on Windows** and
**root on Linux**:

- Windows: open the terminal with *Run as administrator*. GitHub's Windows runners already run
  elevated.
- Linux: run the tests as root, or as a user who may run `sudo` without a password, as on
  GitHub's Ubuntu runners. Then only the program runs under `sudo`, and your tests do not.

**3. Save this as `tests/slow.spec.js` and run `npx playwright test`**

```js
import http from 'node:http';
import { test, expect } from 'beannetworktester/playwright';

let server;
test.beforeAll(async () => {
  server = http.createServer((request, response) => response.end('<h1>Hello</h1>'));
  await new Promise((done) => server.listen(8000, done));
});
test.afterAll(() => server.close());

test('a page takes longer on a slow network', async ({ page, badNetwork }) => {
  await badNetwork({ server: 'http://localhost:8000', latency: 500 });   // +500 ms
  const started = Date.now();
  await page.goto('http://localhost:8000');
  await expect(page.locator('h1')).toHaveText('Hello');
  expect(Date.now() - started).toBeGreaterThanOrEqual(500);
});
```

The test passes because the page really took half a second longer. When it ends, the network
is back to normal.

No rights at hand? `badNetwork({ simulate: true, latency: 500 })` runs the program on made-up
traffic, needs no rights and changes nothing on the network. It is for checking that the package
is set up, not for slowing your app.

## In Playwright Test

Import `test` and `expect` from `beannetworktester/playwright` instead of `@playwright/test`. The
`badNetwork` fixture starts a session when you call it and resolves once the network is slow.
The session stops when the test ends, whether it passed, failed or crashed, and its summary is
attached to the test's report as `bad-network`.

```js
test('checkout retries when the API is slow', async ({ page, badNetwork }) => {
  await badNetwork({ server: 'http://localhost:8000', latency: 500, jitter: 100 });
  await page.goto('http://localhost:3000/checkout');
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page.getByText('Paid')).toBeVisible({ timeout: 30_000 });
});
```

To change the conditions in the middle of a test, stop the first session before you start the
next one, or give one session a scenario (below):

```js
test('the app recovers when the API comes back', async ({ page, badNetwork }) => {
  const outage = await badNetwork({ server: 'http://localhost:8000', loss: 100 });
  await page.goto('http://localhost:3000');
  await expect(page.getByText('Offline')).toBeVisible();
  await outage.stop();                                // the network is normal again
  await expect(page.getByText('Offline')).toBeHidden();
});
```

`@playwright/test` is a peer dependency: the one your project already has is used.

## Without Playwright

```js
const { badNetwork } = require('beannetworktester');

async function main() {
  const session = await badNetwork({ server: 'http://localhost:3000', loss: 5, duration: 120 });
  try {
    await runMyClient();
  } finally {
    const summary = await session.stop();
    console.log(summary.counters.scoped_seen, 'packets were in the aim');
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
```

## What a session aims at

Every session aims at something, and only that traffic changes. Without an aim it would slow
every connection of the machine, the test runner's own included, so `badNetwork` refuses to
start.

| Aim | What is slowed |
|---|---|
| `server: 'http://localhost:3000'` | every connection to that address and port, from any program. Also `'db.local:5432'` or `{ host: '10.0.0.5', port: 443 }` |
| `server: ['http://localhost:3000', 'localhost:8080']` | several servers: every address of them with every port of them |
| `process: 'self'` | this test worker and every program it started, such as its browser |
| `process: child` | a process your test started: pass the `ChildProcess` itself, not its number |
| `dstPort: 8080` | every connection of this machine to that port, at any address: an API on a known port |
| `dstIp: '10.0.0.5'` | every connection to that address, any port. Also lists, ranges and CIDR such as `'172.18.0.0/16'` |
| `target: 'myapi'` | processes by name or by process ID, in the program's syntax |

`server` is the first choice: it is exact on Windows and Linux. `dstIp`, `dstPort` and `target`
are the program's own aims, written in [its syntax](https://beannetworktester.donislawdev.com/command-line/)
(lists, ranges, `!` to leave something out). They reach **everything that matches**, so think
about what else uses it:

- `dstPort: 443` is every HTTPS connection of the machine: your browser, your editor, the CI
  runner's own connection. Aim at the server instead, or add `process: 'self'`.
- `target: 'node'` is every program whose name contains "node", your editor and the test runner
  included.
- `dstIp: '!10.0.0.5'` is everything except that address.

Aims given together narrow each other. `server` with `process: 'self'` slows only this worker's
connections to that server, and `process: 'self'` with `dstPort: 8080` only this worker's
connections to port 8080.

On Linux, `process` and `target` reach a new connection up to about 0.2 seconds after it opens,
so its first packets can go through untouched. Aim at the server when the first request counts.

## What a session can do

Every setting is one of the program's flags, written in camelCase:

| Setting | What it does |
|---|---|
| `latency: 300` | adds 300 ms to every packet |
| `jitter: 100` | varies the delay by up to 100 ms either way |
| `loss: 5` | drops 5% of the packets |
| `down: 256, up: 64` | limits download and upload to so many KB/s |
| `flapPeriod: 10, flapDown: 30` | the link goes down for 30% of every 10 seconds |
| `rstProb: 2` | tears 2% of TCP connections down with a reset |
| `loss: 100` | cuts the connections in the aim off completely |
| `blockPort: 5432` | blocks the traffic to that port, inside the aim |
| `preset: 'presets.3g'` | a named link profile, such as 3G or a satellite link |
| `seed: 42` | the same random choices on every run |

The program checks the settings itself, so a misspelled one fails the test with its message. The
full list is on [the command-line page](https://beannetworktester.donislawdev.com/command-line/)
and in `BeanNetworkTester --help`.

## Conditions that change over time

A scenario is a JSON file of steps, each at a second of the session. Inside the file the
settings are the program's own names, with `_`:

```json
{"steps": [
  {"at": 0,  "settings": {"latency": 100}},
  {"at": 10, "settings": {"latency": 800, "loss": 10}},
  {"at": 20, "settings": {"loss": 100}}
]}
```

```js
await badNetwork({ server: 'http://localhost:3000', scenario: 'slow-then-down.json', duration: 60 });
```

The program's own scenarios work by name, such as `scenario: 'scenarios/cafe-wifi.json'` or
`'scenarios/mobile-lte-to-3g.json'`. A step may change how the network behaves, but not what
`server` or `process` aim at: the helper reads the file first and refuses such a step, because
it could widen the aim to the whole machine.

## Safety

- **Never the whole machine by accident.** A session without an aim does not start.
- **It ends with the test.** The fixture stops it when the test ends. If the test worker dies,
  the program sees its input close and stops at once. `duration` (300 seconds unless you give
  another) is the most a session may run in any case, and a `BadNetworkWarning` says when it ran
  out first.
- **One at a time.** Two sessions over the same traffic would add up. Parallel workers take
  turns, each waiting up to `wait` seconds (600 unless you give another). A second session in the
  same test is refused at once. A pytest run of the Python package at the same time is not kept
  apart from them.
- **It says when it did nothing.** A session that slowed nothing, because nothing reached its
  aim, ends with a `BadNetworkWarning`.

## When something goes wrong

| What you see | What to do |
|---|---|
| "needs administrator rights on Windows" | open the terminal with *Run as administrator* |
| "needs root on Linux" | run as root, or allow `sudo` without a password for this user |
| `BadNetworkWarning`: "the session slowed nothing" | the app talks to another address than the aim: a container, the machine's network address instead of `localhost`, or a proxy. Aim at the address it really uses, or use `process: 'self'` |
| "Another badNetwork session has been running" | parallel workers wait for each other: give a longer `wait`, or run those tests in one worker (`--workers=1`) |
| "has not been stopped yet" | stop the first session of the test before you start the next one |
| "which carries the program for this system, is not installed" | install again without `--omit=optional` |
| "runs the network on Windows x64 and Linux x64 only" | on a Mac, run the tests in a Linux x86_64 container or virtual machine, or on a CI runner |
| `BadNetworkWarning`: "ended by its duration" | give a longer `duration` |
| "the program refused the settings" | the program's own words follow, and name the setting |

## The summary

Every session ends with the program's summary: `session.summary`, or what `stop()` resolves to.
In Playwright Test it is also attached to the test's report as `bad-network`. The parts worth
reading:

- `counters.seen`: packets the program saw. `counters.scoped_seen`: those in the aim.
- `stop_reason`: `'stdin'` when the test stopped it, `'duration'` when time ran out.
- `seed` and `repro_command`: the command that repeats the same conditions with the program on
  its own.

## Other options

- `duration`: the most seconds a session may run, 300 unless given, at most 86400.
- `wait`: seconds to wait for another session to end, 600 unless given.
- `startTimeout`: seconds to wait for the program to start, 60 unless given.
- `BEANNETWORKTESTER_PROGRAM` in the environment points at another copy of the program, such as
  one installed with WinGet, or `bean_network_tester.py` from a checkout, which runs with
  `BEANNETWORKTESTER_PYTHON` (or `python`).

## Licence

GPL-3.0-only, like the program it carries. The program's third-party notices are inside the
program's package, next to it. Source, issues and the changelog:
[github.com/donislawdev/BeanNetworkTester](https://github.com/donislawdev/BeanNetworkTester).
