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
const { acquire } = require('./lock');
const { BadNetworkError, programCommand, rightsPrefix } = require('./program');

const DEFAULT_DURATION = 300;
const MAX_DURATION = 86400;
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
    return Boolean(this._child) && this._child.exitCode === null && this._child.signalCode === null;
  }

  async start() {
    if (this._child) throw new BadNetworkError('this session has already been started; make a new one');
    const flags = await sessionFlags({ server: this.server, process: this.proc,
      simulate: this.simulate, settings: this.settings });
    const tail = ['--format', 'json', '--stop-on-stdin-close', '--duration', String(this.duration)];
    if (this.simulate) tail.push('--simulate');
    this.command = [...rightsPrefix({ simulate: this.simulate }), ...programCommand(), ...flags, ...tail];
    this._release = await acquire(this.wait);
    try {
      await this._launch();
    } catch (err) {
      this._abandon();
      throw err;
    }
    LIVE.add(this);
    return this;
  }

  async stop({ timeout = 30 } = {}) {
    const child = this._child;
    if (!child || this._stopped) return this.summary;
    this._stopped = true;
    child.stdin.end();
    const ended = await Promise.race([this._exited, delay(timeout * 1000).then(() => false)]);
    if (ended === false) {
      child.kill();             // the traffic comes back when the process is gone
      await this._exited;
    }
    this._finish();
    if (!this.summary) throw new BadNetworkError(this._endedWithout(child.exitCode, false));
    this._warnAbout(this.summary);
    return this.summary;
  }

  _launch() {
    const [file, ...args] = this.command;
    const child = spawn(file, args, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    this._child = child;
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

  _abandon() {
    this._stopped = true;
    if (this.running) this._child.kill();
    this._finish();
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

module.exports = { BadNetwork, BadNetworkError, badNetwork, DEFAULT_DURATION };
