// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict';

// A session: the program started on an aim, waited for, and stopped with its summary.
//
// The program writes one JSON object per line (--format json). The session waits for
// its start object before it hands control back, so the traffic a test sends next is
// already slowed, and stops it by closing its standard input (--stop-on-stdin-close):
// a normal end, with a summary. If the test process dies, its end of that pipe closes
// with it and the program stops at once, and duration stops it in any case. Closing is
// also the only clean stop there is from Node on Windows, where kill() ends a process
// without letting it write its summary.

const { spawn } = require('node:child_process');
const readline = require('node:readline');
const { sessionFlags } = require('./aim');
const { acquire, calledOff } = require('./lock');
const { BadNetworkError, programCommand, rightsPrefix, shippedScenarios } = require('./program');

const DEFAULT_DURATION = 300;
const MAX_DURATION = 86400;
const END_GRACE_S = 5;
const EXIT_MEANING = {
  2: 'the program refused the command line',
  3: 'the program refused the settings',
  4: 'the program could not read the scenario',
  5: 'the program could not write a file it was asked to write',
  7: 'the program has no right to capture',
};
const LIVE = new Set();

class BadNetwork {
  constructor(options = {}) {
    const { server, process: proc, duration = DEFAULT_DURATION, simulate = false, wait = 600,
      startTimeout = 60, ...settings } = options;
    const seconds = Number(duration);
    if (!(seconds > 0 && seconds <= MAX_DURATION)) {
      throw new BadNetworkError(`duration=${JSON.stringify(duration)}: give the most seconds the ` +
        `session may run, above 0 and at most ${MAX_DURATION}. It is the safety net if nothing ` +
        'else stops it.');
    }
    // A number that is not one would make the waits below end at once or never.
    if (typeof wait !== 'number' || !Number.isFinite(wait) || wait < 0) {
      throw new BadNetworkError(`wait=${JSON.stringify(wait)}: give the seconds to wait for ` +
        'another session to end, 0 or more.');
    }
    if (typeof startTimeout !== 'number' || !Number.isFinite(startTimeout) || startTimeout <= 0) {
      throw new BadNetworkError(`startTimeout=${JSON.stringify(startTimeout)}: give the seconds ` +
        'to wait for the program to start capturing, above 0.');
    }
    Object.assign(this, { server, proc, simulate: Boolean(simulate), duration: seconds, wait,
      startTimeout, settings });
    this.command = [];
    this.startRecord = null;
    this.summary = null;
    this.stderr = [];
    this._child = null;
    this._release = null;
    this._stopped = false;
    this._exited = null;
  }

  get running() {
    // A pid too: a program that could not be started has none, and never exits.
    return Boolean(this._child) && Number.isInteger(this._child.pid)
      && this._child.exitCode === null && this._child.signalCode === null;
  }

  // `signal` calls the start off while it still waits for another session: the
  // Playwright fixture aborts it when the test ends.
  async start({ signal } = {}) {
    if (this._child) throw new BadNetworkError('this session has already been started; make a new one');
    if (LIVE.size) {
      // It would wait for the lock this process holds itself, until `wait` ran out.
      throw new BadNetworkError('A session started in this process has not been stopped yet, and ' +
        'two at once would add up. Stop it first (await session.stop()), or change the ' +
        'conditions over time with one session and scenario.');
    }
    LIVE.add(this);             // at once: two starts awaited together are two at once
    try {
      const program = programCommand();
      const tail = ['--format', 'json', '--stop-on-stdin-close', '--duration', String(this.duration)];
      if (this.simulate) tail.push('--simulate');
      const command = async () => {
        const flags = await sessionFlags({ server: this.server, process: this.proc,
          simulate: this.simulate, settings: this.settings,
          shippedScenarios: shippedScenarios(program) });
        return [...rightsPrefix({ simulate: this.simulate }), ...program, ...flags, ...tail];
      };
      this.command = await command();          // a wrong option fails before any wait
      this._release = await acquire(this.wait, { signal });
      if (signal && signal.aborted) throw calledOff();
      // Again once the lock is ours: the wait may have lasted minutes, in which a process
      // aim may have ended and its number gone to another process, or a server's address
      // may have changed.
      this.command = await command();
    } catch (err) {
      this._finish();
      throw err;
    }
    try {
      await this._launch();
    } catch (err) {
      await this._abandon();
      throw err;
    }
    return this;
  }

  async stop({ timeout = 30 } = {}) {
    const child = this._child;
    if (!child || this._stopped) return this.summary;
    this._stopped = true;
    try {
      child.stdin.end();
      const exited = await Promise.race([this._exited, delay(timeout * 1000).then(() => false)]);
      if (exited === false) await this._end();
    } finally {
      this._finish();
    }
    if (this.running) throw this._stillRunning();
    if (!this.summary) throw new BadNetworkError(this._endedWithout(child.exitCode, false));
    this._warnAbout(this.summary);
    return this.summary;
  }

  _launch() {
    const [file, ...args] = this.command;
    const child = spawn(file, args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    this._child = child;
    // A signal that cannot be delivered is an 'error' event, and one with no listener
    // would end this process. Whether the program ended is read from its state instead.
    child.on('error', () => {});
    child.stdin.on('error', () => {});      // a program that ended first closed its input
    this._exited = new Promise((done) => child.once('close', () => done(true)));
    readline.createInterface({ input: child.stderr }).on('line', (line) => {
      this.stderr.push(line);
      if (this.stderr.length > 60) this.stderr.shift();
    });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new BadNetworkError(
        `the program did not start capturing within ${this.startTimeout} s.${this._tail()}`)),
      this.startTimeout * 1000);
      child.once('error', (err) => {
        clearTimeout(timer);
        reject(new BadNetworkError(`the program could not be started: ${err.message}`));
      });
      readline.createInterface({ input: child.stdout }).on('line', (line) => {
        let record;
        try {
          record = JSON.parse(line);
        } catch {
          return;
        }
        if (record && record.event === 'start') {
          this.startRecord = record;
          clearTimeout(timer);
          resolve();
        } else if (record && record.event === 'summary') {
          this.summary = record;
        }
      });
      this._exited.then(() => {
        clearTimeout(timer);
        if (!this.startRecord) reject(new BadNetworkError(this._endedWithout(child.exitCode, true)));
      });
    });
  }

  _finish() {
    if (this._release) this._release();
    this._release = null;
    LIVE.delete(this);
  }

  async _abandon() {
    this._stopped = true;
    try {
      if (this.running) await this._end();
    } finally {
      this._finish();
    }
  }

  _stillRunning() {
    return new BadNetworkError(`the program (process ${this._child.pid}) did not end when it ` +
      'was asked to, nor when it was forced. End it yourself: until then it still changes the ' +
      `network.${this._tail()}`);
  }

  // End the program when closing its input did not: asked to first, then forced. Asked
  // first because a forced end on Linux leaves the aim's packets with nowhere to go for
  // about 3 s (2.8 s measured 2026-10-20), while an asked one lets them through at once
  // and writes the summary. Under sudo the request reaches the program through sudo. On
  // Windows both are TerminateProcess, and the traffic comes back at once.
  async _end({ grace = END_GRACE_S } = {}) {
    const child = this._child;
    child.kill('SIGTERM');
    const exited = await Promise.race([this._exited, delay(grace * 1000).then(() => false)]);
    if (exited === false) {
      child.kill('SIGKILL');
      await Promise.race([this._exited, delay(grace * 1000)]);
    }
  }

  _tail() {
    const lines = this.stderr.filter((line) => line.trim()).slice(-8);
    return lines.length ? '\nThe program said:\n  ' + lines.join('\n  ') : '';
  }

  _endedWithout(code, starting) {
    const meaning = EXIT_MEANING[code];
    return `the program ended ${starting ? 'before it started capturing' : 'without a summary'}, ` +
      `exit code ${code}${meaning ? ` (${meaning})` : ''}.${this._tail()}`;
  }

  _warnAbout(summary) {
    if (summary.stop_reason === 'duration') {
      process.emitWarning(`the session ended by its duration (${this.duration} s) before it was ` +
        'stopped, so the rest of the test ran on a normal network. Give a longer duration.',
      'BadNetworkWarning');
    }
    const counters = summary.counters || {};
    if (!this.simulate && counters.seen && !counters.scoped_seen) {
      process.emitWarning(`the session slowed nothing: none of the ${counters.seen} packets it ` +
        'saw matched its aim. Check server or process.', 'BadNetworkWarning');
    }
  }
}

function delay(ms) {
  return new Promise((done) => setTimeout(done, ms).unref());
}
async function badNetwork(options) {
  return new BadNetwork(options).start();
}

// Leaving: every session still running is told to stop. Its pipe would close with this
// process anyway, which stops the program; this only makes it sooner.
process.on('exit', () => {
  for (const session of LIVE) {
    try {
      session._child.stdin.end();
    } catch {
      // already closed
    }
  }
});

module.exports = { BadNetwork, BadNetworkError, badNetwork, DEFAULT_DURATION, END_GRACE_S };
