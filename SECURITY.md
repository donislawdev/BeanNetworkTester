# Security Policy

## Supported versions

Bean Network Tester has a single active line of development. Security fixes are made
against the **latest release** and the `master` branch. Please confirm you can
reproduce an issue on the latest version before reporting it.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private vulnerability reporting: open the **Security** tab of this
repository and choose **Report a vulnerability**. This keeps the report private until
a fix is available. If you cannot use that channel, reach the author through
https://donislawdev.com/.

Please include:

- the version (`BeanNetworkTester.exe --version`) and your Windows version,
- whether you ran the GUI or the CLI, and whether it was elevated (administrator),
- a clear description and the smallest steps to reproduce,
- the impact you believe it has.

You can expect an initial response within a few days. Once a fix is ready it ships in
the next release, and the advisory is published crediting the reporter (unless you
prefer to remain anonymous).

## Scope: the nature of this tool

Bean Network Tester deliberately degrades network traffic and **loads a signed
kernel-mode driver (WinDivert)** to do so. Running it interrupts connectivity on the
machine by design - that is the tool working, not a vulnerability. Issues in the driver
itself belong upstream: https://github.com/basil00/WinDivert.

The program has **no telemetry and no network client** - it sends no data anywhere.

Reports that are in scope include, for example: a way to make the tool affect traffic
it was not told to target, a crash that corrupts a user's files (profiles, config,
CSV), or unsafe handling of the files it reads and writes.
