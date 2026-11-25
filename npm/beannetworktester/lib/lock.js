'use strict';

// One session at a time.
//
// Two sessions that see the same traffic add up: two of 100 ms each slowed a server by
// 200 ms (measured 2026-11-25). Playwright's workers would then slow each other's
// tests, so a session holds this lock while it runs, and a second one waits.
//
// Node has no file lock the system drops with the process, so the lock is a file that
// names the process holding it: a holder that died is noticed by its process ID and
// the file is taken over. The file is in the temporary folder: on Linux that is the
// machine's, shared by every user, and on Windows it is the user's own. The Python
// package uses a lock of the system's own, in another file, so a pytest run and a
// Playwright run at the same time are not kept apart.

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { BadNetworkError } = require('./program');

const LOCK_NAME = 'beannetworktester-node.lock';

function lockPath() {
  return path.join(os.tmpdir(), LOCK_NAME);
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

function holder(where) {
  try {
    return Number.parseInt(fs.readFileSync(where, 'utf8'), 10);
  } catch {
    return NaN;
  }
}

function create(where) {
  try {
    const fd = fs.openSync(where, 'wx');
    fs.writeSync(fd, String(process.pid));
    fs.closeSync(fd);
    return true;
  } catch (err) {
    if (err.code !== 'EEXIST') {
      throw new BadNetworkError(`The lock file ${where} cannot be made: ${err.message}`);
    }
    return false;
  }
}

function tryTake(where) {
  if (create(where)) return true;
  const pid = holder(where);
  if (alive(pid) || holder(where) !== pid) return false;
  try {
    fs.unlinkSync(where);           // its holder is gone
  } catch (err) {
    // A file another user's run left (one under sudo, say) cannot be removed from
    // Linux's shared /tmp, and waiting would only end in the wrong sentence. On Windows
    // the folder is the user's own, and a refusal there is a reader holding it a moment.
    if (process.platform !== 'win32' && (err.code === 'EPERM' || err.code === 'EACCES')) {
      throw new BadNetworkError(`The lock file ${where} was left by process ${pid}, which has ` +
        `ended, and this user may not remove it. Remove it (on Linux: sudo rm ${where}).`);
    }
    // ENOENT: another waiter took it over first
  }
  return create(where);
}

async function acquire(wait, { where = lockPath(), sleep, now = Date.now } = {}) {
  const pause = sleep || ((ms) => new Promise((done) => setTimeout(done, ms)));
  const deadline = now() + Math.max(0, wait) * 1000;
  while (!tryTake(where)) {
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
    if (holder(where) === process.pid) {
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

module.exports = { LOCK_NAME, acquire, alive, lockPath };
