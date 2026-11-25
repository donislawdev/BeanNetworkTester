'use strict';

// What a session aims at, and its settings, as the program's flags.
//
// A session always aims at something: a server, a process, or one of the program's
// own aims (target, dstIp, dstPort). Without one it would slow every connection of the
// machine, the test runner's own included.

const dns = require('node:dns');
const { BadNetworkError } = require('./program');

// Settings the helper sets itself, or that would turn the run into something else.
const RESERVED = new Set(['format', 'stopOnStdinClose', 'duration', 'simulate', 'gui', 'doctor',
  'dryRun', 'printConfig', 'saveConfig', 'license', 'installDesktop', 'removeDesktop',
  'cleanupDriver', 'version', 'help']);
const OWN_AIMS = ['target', 'dstIp', 'dstPort'];
const KEY = /^[a-z][a-zA-Z0-9]*$/;
const DEFAULT_PORTS = { 'http:': 80, 'https:': 443, 'ws:': 80, 'wss:': 443 };

function flagOf(key) {
  return '--' + key.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
}

function serverAddress(server) {
  if (server && typeof server === 'object' && !Array.isArray(server)) {
    return [String(server.host), Number(server.port)];
  }
  if (Array.isArray(server) && server.length === 2) return [String(server[0]), Number(server[1])];
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

function processAim(proc) {
  if (proc === 'self') return String(process.pid);
  if ((typeof proc === 'number' && Number.isInteger(proc)) || (typeof proc === 'string' && proc)) {
    return String(proc);
  }
  throw new BadNetworkError(`process=${JSON.stringify(proc)}: give 'self', a PID or a program name.`);
}

function given(value) {
  return value !== undefined && value !== null && value !== false && value !== '';
}

async function sessionFlags({ server, process: proc, simulate = false, settings = {},
  lookup } = {}) {
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
  const aims = OWN_AIMS.filter((key) => given(settings[key]));
  if (server === undefined && proc === undefined && !aims.length && !simulate) {
    throw new BadNetworkError('badNetwork needs an aim: server, process, or one of target, ' +
      'dstIp, dstPort. Without one it would slow every connection of this machine, the test ' +
      'runner\'s own included.');
  }
  const flags = [];
  if (server !== undefined) {
    if (aims.includes('dstIp') || aims.includes('dstPort')) {
      throw new BadNetworkError('server sets dstIp and dstPort: give one or the other.');
    }
    const [host, port] = serverAddress(server);
    flags.push('--dst-ip', (await serverIps(host, lookup ? { lookup } : {})).join(','),
      '--dst-port', String(port));
  }
  if (proc !== undefined) {
    if (aims.includes('target')) {
      throw new BadNetworkError('process sets target: give one or the other.');
    }
    flags.push('--target', processAim(proc));
  }
  for (const [key, value] of Object.entries(settings)) {
    if (value === undefined || value === null || value === false) continue;
    if (value === true) flags.push(flagOf(key));
    else flags.push(flagOf(key), Array.isArray(value) ? value.join(',') : String(value));
  }
  return flags;
}

module.exports = { OWN_AIMS, RESERVED, flagOf, serverAddress, serverIps, sessionFlags };
