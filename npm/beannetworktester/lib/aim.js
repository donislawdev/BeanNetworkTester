// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict';

// What a session aims at, and its settings, as the program's flags.
//
// A session always aims at something. `server` (one or more servers) and `process` (this
// test, or a process it started) are exact, and they are what the helper promises: a
// scenario may not change what they set while it runs, or it could widen the aim to the
// whole machine. The program's own aim flags (target, dstIp, dstPort) are an aim too, in
// the program's own syntax, for what those two cannot say: an API on a port, a range of
// addresses, a process by name. They reach as far as they match, which the README spells
// out (dstPort: 443 is every HTTPS connection of the machine).

const dns = require('node:dns');
const fs = require('node:fs');
const path = require('node:path');
const { ChildProcess } = require('node:child_process');
const { BadNetworkError } = require('./program');

// Settings the helper sets itself, or that would turn the run into something else.
const RESERVED = new Set(['format', 'stopOnStdinClose', 'duration', 'simulate', 'gui', 'doctor',
  'dryRun', 'printConfig', 'saveConfig', 'license', 'installDesktop', 'removeDesktop',
  'cleanupDriver', 'version', 'help']);
const OWN_AIMS = ['target', 'dstIp', 'dstPort'];
// The keys server and process set, as a scenario file names them (the program's own).
const SERVER_KEYS = ['dst_ip', 'dst_port'];
const PROCESS_KEYS = ['target'];
const KEY = /^[a-z][a-zA-Z0-9]*$/;
const DEFAULT_PORTS = { 'http:': 80, 'https:': 443, 'ws:': 80, 'wss:': 443 };
// The two shapes the program accepts for a scenario it ships (paths.shipped_scenario).
const SHIPPED_FOLDERS = ['scenarios', '_internal/scenarios'];

function flagOf(key) {
  return '--' + key.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
}

function serverAddress(server) {
  if (server && typeof server === 'object') {
    const port = Number(server.port);
    if (!server.host || !Number.isInteger(port) || port <= 0) {
      throw new BadNetworkError(`server=${JSON.stringify(server)} names no host and port. Give ` +
        '{ host, port } with a whole-number port.');
    }
    return [String(server.host), port];
  }
  let text = String(server).trim();
  if (!text.includes('://')) text = 'tcp://' + text;
  let url;
  try {
    url = new URL(text);
  } catch {
    url = null;
  }
  const host = url && url.hostname.replace(/^\[|\]$/g, '');
  const port = url && (url.port ? Number(url.port) : DEFAULT_PORTS[url.protocol]);
  if (!host || !port || !Number.isInteger(port)) {
    throw new BadNetworkError(`server=${JSON.stringify(server)} names no host and port. Give a ` +
      'URL such as \'http://localhost:3000\', a \'host:port\' pair or { host, port }.');
  }
  return [host, port];
}

// Every [host, port] that `server` names: one, or an array of them.
function servers(server) {
  if (Array.isArray(server)) {
    if (!server.length) throw new BadNetworkError('server=[] names no server.');
    return server.map(serverAddress);
  }
  return [serverAddress(server)];
}

async function serverIps(host, { lookup = dns.promises.lookup } = {}) {
  let found;
  try {
    found = await lookup(host, { all: true });
  } catch (err) {
    throw new BadNetworkError(`server host ${JSON.stringify(host)} has no address: ${err.message}`);
  }
  const out = [];
  for (const { address } of found) {
    const plain = String(address).split('%')[0];     // an IPv6 zone is not part of the aim
    if (!out.includes(plain)) out.push(plain);
  }
  if (!out.length) throw new BadNetworkError(`server host ${JSON.stringify(host)} has no address.`);
  return out;
}

// 'self', or a ChildProcess this test started while it runs. Not a number: a number may
// name any process of the machine (PID 1 on Linux, whose tree is every process), or one
// that took over the number of a process that ended. target takes numbers and names.
function processAim(proc) {
  if (proc === 'self') return String(process.pid);
  if (proc instanceof ChildProcess) {
    if (proc.exitCode !== null || proc.signalCode !== null || !Number.isInteger(proc.pid)) {
      throw new BadNetworkError('process: the child process has already ended, so there is ' +
        'nothing of it to slow, and its number may belong to another process now.');
    }
    return String(proc.pid);
  }
  throw new BadNetworkError(`process=${JSON.stringify(proc)}: give 'self' (this test and ` +
    'everything it started), or the ChildProcess your test started (process: child, not ' +
    'child.pid). For a process ID or a program name, use target, the program\'s own aim: a name ' +
    'there matches every program whose name contains it, and a process ID covers every process ' +
    'it started.');
}

function given(value) {
  return value !== undefined && value !== null && value !== false && value !== '';
}

// The file a scenario name the program ships stands for, as the program finds it.
function shipped(name, folders) {
  if (path.isAbsolute(name)) return null;
  const parts = path.normalize(name).split(/[\\/]/);
  const folder = parts.slice(0, -1).join('/');
  const caseless = process.platform === 'win32' ? folder.toLowerCase() : folder;
  if (!SHIPPED_FOLDERS.includes(caseless)) return null;
  for (const dir of folders) {
    const candidate = path.join(dir, parts[parts.length - 1]);
    if (isFile(candidate)) return candidate;
  }
  return null;
}

function isFile(where) {
  try {
    return fs.statSync(where).isFile();
  } catch {
    return false;
  }
}

const SCENARIO_ADVICE = {
  server: 'Aim with process instead, and the scenario then narrows that process\'s traffic.',
  process: 'Aim with server instead, or take target out of the scenario.',
  both: 'Take those settings out of the scenario.',
};

// The scenario's file as an absolute path, once no step of it changes aimKeys. The
// program is handed this path, so it reads the file that was checked. A file this cannot
// read is refused here: the program could not read it either.
function checkedScenario(name, aimKeys, { folders = [], advice = 'both' } = {}) {
  const given = String(name);
  const found = isFile(given) ? given : shipped(given, folders);
  if (!found) {
    throw new BadNetworkError(`scenario=${JSON.stringify(given)}: there is no such file. A ` +
      'scenario the program ships is named \'scenarios/<file>.json\'.');
  }
  let data;
  try {
    data = JSON.parse(fs.readFileSync(found, 'utf8').replace(/^\u{FEFF}/u, ''));
  } catch (err) {
    throw new BadNetworkError(`scenario=${JSON.stringify(given)} could not be read as JSON: ` +
      err.message);
  }
  const steps = data && !Array.isArray(data) && typeof data === 'object' ? data.steps : data;
  if (!Array.isArray(steps)) {
    throw new BadNetworkError(`scenario=${JSON.stringify(given)} is not a scenario: it has no ` +
      'list of steps.');
  }
  steps.forEach((step, index) => {
    const settings = step && typeof step === 'object' ? step.settings : null;
    if (!settings || typeof settings !== 'object') return;
    const changed = Object.keys(settings).filter((key) => aimKeys.includes(key)).sort();
    if (changed.length) {
      throw new BadNetworkError(`scenario=${JSON.stringify(given)}: step ${index + 1} changes ` +
        `${changed.join(', ')}, which is what this session aims at. A scenario may change how ` +
        'the network behaves, not what the session aims at, or it could widen it to the whole ' +
        `machine. ${SCENARIO_ADVICE[advice]}`);
    }
  });
  return path.resolve(found);
}

async function sessionFlags({ server, process: proc, simulate = false, settings = {},
  lookup, shippedScenarios = [] } = {}) {
  for (const key of Object.keys(settings)) {
    if (!KEY.test(key)) {
      throw new BadNetworkError(`${JSON.stringify(key)} is not a setting name. Settings are the ` +
        'program\'s flags in camelCase, such as latency or lossBurst.');
    }
    if (RESERVED.has(key)) {
      throw new BadNetworkError(`${key} is set by beannetworktester itself and cannot be passed ` +
        'as a setting.');
    }
  }
  for (const key of OWN_AIMS) {
    const value = settings[key];
    if (value === undefined || value === null || value === false || value === true) continue;
    // An empty aim reaches the program as an empty flag, which aims at nothing in
    // particular: every connection of the machine, or, after server, every address.
    const text = Array.isArray(value) ? value.join(',') : String(value);
    if (!text.replace(/,/g, '').trim()) {
      throw new BadNetworkError(`${key}: ${JSON.stringify(value)} names nothing, and an empty ` +
        'aim would reach every connection of this machine. Give an address, a port or a name, ' +
        `or leave ${key} out.`);
    }
  }
  const aims = OWN_AIMS.filter((key) => given(settings[key]));
  if (server === undefined && proc === undefined && !aims.length && !simulate) {
    throw new BadNetworkError('badNetwork needs an aim: server (a URL, \'host:port\', or an ' +
      'array of them), process (\'self\', or a process your test started), or one of the ' +
      'program\'s own target, dstIp, dstPort. Without one it would slow every connection of ' +
      'this machine, the test runner\'s own included.');
  }
  const flags = [];
  const aimKeys = [];
  if (server !== undefined) {
    if (aims.includes('dstIp') || aims.includes('dstPort')) {
      throw new BadNetworkError('server sets dstIp and dstPort: give one or the other.');
    }
    // Several servers are every address of them with every port of them: the program's
    // two aim flags are matched apart, not as pairs.
    const ips = [];
    const ports = [];
    for (const [host, port] of servers(server)) {
      for (const ip of await serverIps(host, lookup ? { lookup } : {})) {
        if (!ips.includes(ip)) ips.push(ip);
      }
      if (!ports.includes(String(port))) ports.push(String(port));
    }
    flags.push('--dst-ip', ips.join(','), '--dst-port', ports.join(','));
    aimKeys.push(...SERVER_KEYS);
  }
  if (proc !== undefined) {
    if (aims.includes('target')) {
      throw new BadNetworkError('process sets target: give one or the other.');
    }
    flags.push('--target', processAim(proc));
    aimKeys.push(...PROCESS_KEYS);
  }
  const advice = server !== undefined && proc !== undefined ? 'both'
    : (server !== undefined ? 'server' : 'process');
  for (const [key, raw] of Object.entries(settings)) {
    if (raw === undefined || raw === null || raw === false) continue;
    const value = key === 'scenario'
      ? checkedScenario(raw, aimKeys, { folders: shippedScenarios, advice }) : raw;
    if (value === true) flags.push(flagOf(key));
    else flags.push(flagOf(key), Array.isArray(value) ? value.join(',') : String(value));
  }
  return flags;
}

module.exports = { OWN_AIMS, RESERVED, checkedScenario, flagOf, serverAddress, serverIps,
  sessionFlags };
