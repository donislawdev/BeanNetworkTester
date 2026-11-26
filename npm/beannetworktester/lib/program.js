// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict';

// Which program a session runs, and with what rights.
//
// The program comes in a package of its own for each system, the release's own files
// unchanged (on Windows the signed exe): @beannetworktester/win32-x64 and
// @beannetworktester/linux-x64, which npm installs as optional dependencies of this
// package on the system each is for.

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

// Set it to run another copy of the program: an installed BeanNetworkTester, or
// bean_network_tester.py from a checkout (a .py file runs with BEANNETWORKTESTER_PYTHON,
// or python). PATH is never searched: a copy found there would be another version.
const PROGRAM_ENV = 'BEANNETWORKTESTER_PROGRAM';
const PYTHON_ENV = 'BEANNETWORKTESTER_PYTHON';
const PACKAGES = {
  'win32-x64': '@beannetworktester/win32-x64',
  'linux-x64': '@beannetworktester/linux-x64',
};
const NAMES = { win32: 'BeanNetworkTester.exe', linux: 'BeanNetworkTester' };

class BadNetworkError extends Error {
  constructor(message) {
    super(message);
    this.name = 'BadNetworkError';
  }
}

function isFile(where) {
  try {
    return fs.statSync(where).isFile();
  } catch {
    return false;
  }
}

function programCommand({ env = process.env, platform = process.platform, arch = process.arch,
  resolve = require.resolve } = {}) {
  const given = env[PROGRAM_ENV];
  if (given) {
    if (!isFile(given)) {
      throw new BadNetworkError(`${PROGRAM_ENV} is set to ${given}, and there is no file there. ` +
        'Point it at the program, or unset it to use the one this package installs.');
    }
    if (given.endsWith('.py')) {
      return [env[PYTHON_ENV] || (platform === 'win32' ? 'python' : 'python3'), given];
    }
    return [given];
  }
  const system = `${platform}-${arch}`;
  const pkg = PACKAGES[system];
  if (!pkg) {
    throw new BadNetworkError(`beannetworktester runs the network on Windows x64 and Linux x64 ` +
      `only, and this is ${system}. On a Mac, run the tests in a Linux x86_64 container or ` +
      'virtual machine, or on a CI runner with Windows or Linux.');
  }
  let dir;
  try {
    dir = path.dirname(resolve(`${pkg}/package.json`));
  } catch {
    throw new BadNetworkError(`${pkg}, which carries the program for this system, is not ` +
      'installed. npm installs it with beannetworktester unless optional dependencies were left ' +
      'out (--omit=optional). Install again without that, or set ' +
      `${PROGRAM_ENV} to the path of BeanNetworkTester.`);
  }
  const found = path.join(dir, 'program', 'BeanNetworkTester', NAMES[platform]);
  if (!isFile(found)) {
    throw new BadNetworkError(`The program is not at ${found}, where ${pkg} puts it: something ` +
      `removed it. Install the packages again, or set ${PROGRAM_ENV} to the path of ` +
      'BeanNetworkTester.');
  }
  if (platform !== 'win32') {
    try {
      fs.accessSync(found, fs.constants.X_OK);
    } catch {
      fs.chmodSync(found, 0o755);   // an unpacker that dropped the execute bit
    }
  }
  return [found];
}

// The folders the program keeps the scenarios it ships in: built, or a checkout.
function shippedScenarios(command) {
  const folder = path.dirname(path.resolve(command[command.length - 1]));
  return [path.join(folder, '_internal', 'scenarios'), path.join(folder, 'scenarios')];
}

function isAdmin({ run = spawnSync } = {}) {
  // `net session` answers only an elevated caller: the usual test, with no module.
  const done = run('net', ['session'], { stdio: 'ignore', windowsHide: true });
  return done.status === 0;
}

function sudoWorks({ run = spawnSync } = {}) {
  const done = run('sudo', ['-n', 'true'], { stdio: 'ignore', timeout: 30000 });
  return done.status === 0;
}

// What goes in front of the program so that it may capture: [] or sudo. Asked before
// anything starts, so a test fails with a sentence that says what to do.
function rightsPrefix({ simulate, platform = process.platform,
  getuid = process.getuid, admin = isAdmin, sudo = sudoWorks } = {}) {
  if (simulate) return [];
  if (platform === 'win32') {
    if (admin()) return [];
    throw new BadNetworkError('Slowing the network needs administrator rights on Windows. Run ' +
      'the tests from a terminal opened with Run as administrator. GitHub\'s Windows runners ' +
      'already run elevated.');
  }
  if (platform === 'linux') {
    if (getuid && getuid() === 0) return [];
    if (sudo()) return ['sudo', '-n'];
    throw new BadNetworkError('Slowing the network needs root on Linux. Run the tests as root, ' +
      'or as a user who may run sudo without a password, as on GitHub\'s Ubuntu runners. The ' +
      'program runs under sudo, and the tests themselves do not.');
  }
  throw new BadNetworkError('beannetworktester runs the network on Windows x64 and Linux x64 only.');
}

module.exports = { BadNetworkError, PACKAGES, PROGRAM_ENV, PYTHON_ENV, programCommand, rightsPrefix,
  shippedScenarios };
