// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict';

// One session at a time.
//
// Two sessions that see the same traffic add up: two of 100 ms each slowed a server by
// 200 ms (measured 2026-11-25). Playwright's workers would then slow each other's
// tests, so a session holds this lock while it runs, and a second one waits.
//
// Node has no file lock the system drops with the process, so the lock is a file that
// names the process holding it: a holder that died is noticed by its process ID and
// the file is taken over. The file is in /tmp on Linux, the machine's own and not
// $TMPDIR, so every user shares it, and on Windows in the user's temporary folder. The
// Python package uses a lock of the system's own, in another file, so a pytest run and a
// Playwright run at the same time are not kept apart.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { BadNetworkError } = require('./program');

const LOCK_NAME = 'beannetworktester-node.lock';

// A file with no process ID in it is being written this moment, or was left by a run
// that died between making it and writing it. Only an old one is taken over.
const UNWRITTEN_GRACE_MS = 5000;
// A waiter that died while taking a lock over leaves its turn behind.
const TURN_STALE_MS = 10000;
// Never a link or a FIFO: on Linux the path is the same for every user, a link planted
// there would point the read elsewhere, and a FIFO would block it. Windows has neither.
const SAFE_READ = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0) |
  (fs.constants.O_NONBLOCK || 0);

function lockPath() {
  return path.join(process.platform === 'win32' ? os.tmpdir() : '/tmp', LOCK_NAME);
}

function notALock(where) {
  return new BadNetworkError(`${where} is not a plain file, so it is not a lock this package ` +
    'made. Remove it, and run the tests again.');
}

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM';        // it exists, and belongs to someone else
  }
}

// The process ID the lock file names: NaN when there is no file, or none written in it.
function holder(where) {
  let fd;
  try {
    fd = fs.openSync(where, SAFE_READ);
  } catch (err) {
    if (err.code === 'ELOOP') throw notALock(where);
    return NaN;
  }
  try {
    if (!fs.fstatSync(fd).isFile()) throw notALock(where);
    return Number.parseInt(fs.readFileSync(fd, 'utf8'), 10);
  } finally {
    fs.closeSync(fd);
  }
}

function create(where) {
  let fd;
  try {
    fd = fs.openSync(where, 'wx');
  } catch (err) {
    if (err.code === 'EEXIST') return false;
    throw new BadNetworkError(`The lock file ${where} cannot be made: ${err.message}`);
  }
  try {
    fs.writeSync(fd, String(process.pid));
  } catch (err) {
    // An empty file would hold every later session up for UNWRITTEN_GRACE_MS.
    fs.closeSync(fd);
    try {
      fs.unlinkSync(where);
    } catch {
      // gone already
    }
    throw new BadNetworkError(`The lock file ${where} cannot be written: ${err.message}`);
  }
  fs.closeSync(fd);
  return true;
}

function unwrittenAndOld(where) {
  try {
    return Date.now() - fs.statSync(where).mtimeMs > UNWRITTEN_GRACE_MS;
  } catch {
    return false;                   // gone: the next round makes it
  }
}

// Whether the lock is still the one seen abandoned: a dead holder, or no holder written
// in a file that has been there too long for a run still writing it.
function abandoned(where, seen) {
  const now = holder(where);
  if (Number.isNaN(seen)) return Number.isNaN(now) && unwrittenAndOld(where);
  return now === seen && !alive(now);
}

function tryTake(where) {
  if (create(where)) return true;
  const seen = holder(where);
  if (!abandoned(where, seen)) return false;
  // Two waiters can see the same abandoned lock. Without a turn, the second could remove
  // the file the first has just made, and both would run. The turn is a folder, which only
  // one of them can make.
  const turn = `${where}.takeover`;
  try {
    fs.mkdirSync(turn);
  } catch (err) {
    if (err.code !== 'EEXIST') {
      throw new BadNetworkError(`The lock file ${where} cannot be taken over: ${err.message}`);
    }
    try {
      if (Date.now() - fs.statSync(turn).mtimeMs > TURN_STALE_MS) fs.rmdirSync(turn);
    } catch {
      // another waiter cleared it, or it is not ours to clear: wait
    }
    return false;
  }
  try {
    if (!abandoned(where, seen)) return false;     // another waiter took it over first
    removeAbandoned(where, seen);
    return create(where);
  } finally {
    try {
      fs.rmdirSync(turn);
    } catch {
      // gone already
    }
  }
}

function removeAbandoned(where, pid) {
  try {
    fs.unlinkSync(where);
  } catch (err) {
    // A file another user's run left (one under sudo, say) cannot be removed from
    // Linux's shared /tmp, and waiting would only end in the wrong sentence. On Windows
    // the folder is the user's own, and a refusal there is a reader holding it a moment.
    if (process.platform !== 'win32' && (err.code === 'EPERM' || err.code === 'EACCES')) {
      const who = Number.isNaN(pid) ? 'a run that ended before it wrote its process ID'
        : `process ${pid}, which has ended`;
      throw new BadNetworkError(`The lock file ${where} was left by ${who}, and this user may ` +
        `not remove it. Remove it (on Linux: sudo rm ${where}).`);
    }
    // ENOENT: it is gone already
  }
}

function calledOff() {
  return new BadNetworkError('the test ended while this session waited for another one, so ' +
    'it did not start.');
}

// `signal` calls the wait off: the test that asked for the session has ended.
async function acquire(wait, { where = lockPath(), sleep, now = Date.now, signal } = {}) {
  const pause = sleep || ((ms) => new Promise((done) => setTimeout(done, ms)));
  const deadline = now() + Math.max(0, wait) * 1000;
  for (;;) {
    if (signal && signal.aborted) throw calledOff();
    if (tryTake(where)) break;
    if (now() >= deadline) {
      throw new BadNetworkError(`Another badNetwork session has been running on this machine for ` +
        `the ${wait} s this one waited. Sessions run one at a time, because two would add up: ` +
        'with parallel Playwright workers, the tests that slow the network wait for each other. ' +
        `Give a longer wait, or run those tests in one worker. The lock is ${where}.`);
    }
    await pause(200);
  }
  let held = true;
  const release = () => {
    if (!held) return;
    held = false;
    process.removeListener('exit', release);
    let mine = false;
    try {
      mine = holder(where) === process.pid;
    } catch {
      // not a lock any more, so not ours to remove
    }
    if (mine) {
      try {
        fs.unlinkSync(where);
      } catch {
        // already gone
      }
    }
  };
  process.on('exit', release);
  return release;
}

module.exports = { LOCK_NAME, acquire, alive, calledOff, lockPath };
