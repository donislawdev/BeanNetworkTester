# beannetworktester

Slow down, break or cut the **real network** in your tests: latency, packet loss, jitter,
bandwidth limits, outages. For one server or one process, on Windows and Linux, in Playwright
Test or any Node code.

Playwright's own tools can only take a page offline, or slow Chromium through DevTools. This
works below the browser, on the network itself, so Chromium, Firefox and WebKit are slowed the
same way, WebSockets and WebRTC included, and so is your API server if you aim at it.

```js
import { test, expect } from 'beannetworktester/playwright';

test('the spinner shows on a slow network', async ({ page, badNetwork }) => {
  await badNetwork({ server: 'http://localhost:3000', latency: 800 });
  await page.goto('http://localhost:3000');
  await expect(page.getByRole('progressbar')).toBeVisible();
});
```

It runs [Bean Network Tester](https://beannetworktester.donislawdev.com/)'s own program, which
npm installs with this package: on Windows the same signed program as the release.

## Install

```
npm install --save-dev beannetworktester
```

Windows x64 and Linux x64 (glibc 2.39 or newer, such as Ubuntu 24.04), Node 20 or newer. npm
installs the program for your system as an optional dependency, so do not leave optional
dependencies out (`--omit=optional`). On other systems the package installs without a program
and says so when a test asks for a slow network.

## Rights

Changing the network needs **administrator rights on Windows** and **root on Linux**.

- **Windows:** run the tests from a terminal opened with *Run as administrator*. GitHub's
  Windows runners already run elevated.
- **Linux:** run the tests as root, or as a user who may run `sudo` without a password, as on
  GitHub's Ubuntu runners. The program then runs under `sudo`, and your tests do not.

Without the rights, the test fails with a sentence that says which of these is missing.

## In Playwright Test

Import `test` and `expect` from `beannetworktester/playwright` instead of `@playwright/test`. The
`badNetwork` fixture starts a session when you call it, and resolves once the network is slowed.
Every session is stopped when the test ends, and its summary is attached to the test's report as
`bad-network`: the packets seen, how many were in scope, the seed, and the command that repeats
the same conditions with the program on its own.

```js
test('checkout retries when the API is slow', async ({ page, badNetwork }) => {
  await badNetwork({ server: 'http://localhost:8000', latency: 500, jitter: 100 });
  await page.goto('http://localhost:3000/checkout');
  await page.getByRole('button', { name: 'Pay' }).click();
  await expect(page.getByText('Paid')).toBeVisible({ timeout: 30_000 });
});
```

`@playwright/test` is a peer dependency: the one your project already has is used.

## Anywhere else

```js
const { badNetwork } = require('beannetworktester');

const session = await badNetwork({ server: 'http://localhost:3000', loss: 5, duration: 120 });
try {
  await runMyClient();
} finally {
  const summary = await session.stop();
  console.log(summary.counters.scoped_seen, 'packets were slowed');
}
```

## What a session aims at

A session always aims at something. Without an aim it would slow every connection of the
machine, the test runner's own included, so `badNetwork` refuses to start.

- `server: 'http://localhost:3000'`, `server: 'db.local:5432'` or `server: { host, port }`:
  every connection to that address and port, from any program. This is exact on Windows and on
  Linux, and the first choice.
- `process: 'self'`: this test worker and every program it started, such as its browser. Or a
  process ID, or a program name such as `'node'`. On Linux a new connection of the process is
  reached up to about 0.2 seconds after it opens, so its first packets can go through untouched.
  Aim at the server when the first request counts.
- `target`, `dstIp` and `dstPort` are the program's own aims, in its own syntax.

`server` and `process` together slow only that process's connections to that server.

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
| `loss: 100` | cuts the connections to the aim off completely |
| `preset: 'presets.3g'` | a named link profile, such as 3G or a satellite link |
| `scenario: 'steps.json'` | settings that change over time |
| `seed: 42` | the same random choices on every run |

The program checks the settings itself, so a misspelled one fails the test with its message. The
full list is on [the command-line page](https://beannetworktester.donislawdev.com/command-line/)
and in `BeanNetworkTester --help`.

## Safety

- `duration` (300 seconds unless you give another) is the most a session may run. It ends then,
  even if nothing stops it, and a `BadNetworkWarning` says the rest of the test ran on a normal
  network.
- If the test worker dies, the program sees its input close and stops at once.
- One session runs at a time on a machine, because two would add up. With parallel workers, the
  tests that slow the network wait for each other, for up to `wait` seconds (600 unless you give
  another). A pytest run of the Python package at the same time is not kept apart from them.
- When a session slowed nothing, because nothing reached its aim, a `BadNetworkWarning` says so.

## Other options

- `simulate: true` runs the program on made-up traffic: no rights needed and nothing on the
  network changes. For trying the helper out.
- `BEANNETWORKTESTER_PROGRAM` in the environment points at another copy of the program, such as
  one installed with WinGet, or `bean_network_tester.py` from a checkout, which runs with
  `BEANNETWORKTESTER_PYTHON` (or `python`).

## Licence

GPL-3.0-only, like the program it carries. The program's third-party notices are inside the
program's package, next to it. Source, issues and the changelog:
[github.com/donislawdev/BeanNetworkTester](https://github.com/donislawdev/BeanNetworkTester).
