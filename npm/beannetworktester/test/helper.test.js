'use strict';

// The npm helper. Run with `node --test test/`, and by tests/test_helper_npm.py in the
// repository's own suite. Sessions run the program named by BEANNETWORKTESTER_PROGRAM
// (the checkout's bean_network_tester.py there) with simulate: no rights, nothing on
// the network changes.

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

const { flagOf, sessionFlags, serverAddress, serverIps, RESERVED } = require('../lib/aim');
const { acquire, alive } = require('../lib/lock');
const { BadNetworkError, PROGRAM_ENV, programCommand, rightsPrefix } = require('../lib/program');
const { BadNetwork, badNetwork } = require('../index');
const { build, checkedVersion, distTag } = require('../release/assemble');

const lookup = (...addresses) => async () => addresses.map((address) => ({ address }));

test('a session without an aim is refused, and simulate needs none', async () => {
  await assert.rejects(sessionFlags({ settings: { latency: 300 } }), /needs an aim/);
  assert.deepEqual(await sessionFlags({ simulate: true, settings: { latency: 3 } }), ['--latency', '3']);
  for (const own of ['target', 'dstIp', 'dstPort']) {
    assert.equal((await sessionFlags({ settings: { [own]: 'x' } }))[0], flagOf(own));
  }
});

test('a server is its addresses and its port', async () => {
  for (const [server, port] of [['http://localhost:3000', '3000'], ['https://localhost', '443'],
    ['localhost:5432', '5432'], [{ host: 'localhost', port: 8443 }, '8443']]) {
    const flags = await sessionFlags({ server, settings: {}, lookup: lookup('127.0.0.1', '::1', '127.0.0.1') });
    assert.deepEqual(flags, ['--dst-ip', '127.0.0.1,::1', '--dst-port', port], JSON.stringify(server));
  }
  assert.throws(() => serverAddress('localhost'), /names no host and port/);
  assert.throws(() => serverAddress('http://localhost:notaport'), BadNetworkError);
  await assert.rejects(serverIps('nowhere', { lookup: lookup() }), /has no address/);
  assert.deepEqual(await serverIps('h', { lookup: lookup('fe80::1%eth0') }), ['fe80::1']);
});

test('settings become the program\'s flags', async () => {
  const flags = await sessionFlags({ process: 'self', settings: {
    latency: 300, lossBurst: 4, flapHold: true, asym: false, seed: null, blockPort: [80, 443] } });
  assert.deepEqual(flags, ['--target', String(process.pid), '--latency', '300', '--loss-burst', '4',
    '--flap-hold', '--block-port', '80,443']);
  for (const bad of [{ format: 'text' }, { Latency: 1 }, { 'latency-ms': 1 }, { loss_burst: 1 }]) {
    await assert.rejects(sessionFlags({ simulate: true, settings: bad }), BadNetworkError);
  }
  await assert.rejects(sessionFlags({ server: 'h:1', settings: { dstIp: '1.2.3.4' }, lookup: lookup('1.1.1.1') }),
    /one or the other/);
  await assert.rejects(sessionFlags({ process: 'self', settings: { target: 'x' } }), /one or the other/);
  await assert.rejects(sessionFlags({ process: true, settings: {} }), /process=/);
  assert.ok(RESERVED.has('stopOnStdinClose') && RESERVED.has('format'));
});

test('the program: another copy by the environment, the packaged one, every way it is missing', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-npm-'));
  const script = path.join(dir, 'bean_network_tester.py');
  fs.writeFileSync(script, '');
  assert.deepEqual(programCommand({ env: { [PROGRAM_ENV]: script, BEANNETWORKTESTER_PYTHON: 'py' } }),
    ['py', script]);
  assert.throws(() => programCommand({ env: { [PROGRAM_ENV]: path.join(dir, 'missing') } }), /no file there/);
  assert.throws(() => programCommand({ env: {}, platform: 'darwin', arch: 'arm64' }), /Windows x64 and Linux x64 only/);
  const unresolved = () => { throw new Error('not found'); };
  assert.throws(() => programCommand({ env: {}, platform: 'linux', arch: 'x64', resolve: unresolved }),
    /--omit=optional/);
  const pkg = path.join(dir, 'pkg');
  fs.mkdirSync(path.join(pkg, 'program', 'BeanNetworkTester'), { recursive: true });
  fs.writeFileSync(path.join(pkg, 'package.json'), '{}');
  const resolve = () => path.join(pkg, 'package.json');
  assert.throws(() => programCommand({ env: {}, platform: 'win32', arch: 'x64', resolve }), /removed it/);
  const exe = path.join(pkg, 'program', 'BeanNetworkTester', 'BeanNetworkTester.exe');
  fs.writeFileSync(exe, '');
  assert.deepEqual(programCommand({ env: {}, platform: 'win32', arch: 'x64', resolve }), [exe]);
});

test('rights are asked before anything starts', () => {
  assert.deepEqual(rightsPrefix({ simulate: true }), []);
  assert.throws(() => rightsPrefix({ simulate: false, platform: 'win32', admin: () => false }),
    /Run as administrator/);
  assert.deepEqual(rightsPrefix({ simulate: false, platform: 'win32', admin: () => true }), []);
  assert.deepEqual(rightsPrefix({ simulate: false, platform: 'linux', getuid: () => 1000, sudo: () => true }),
    ['sudo', '-n']);
  assert.throws(() => rightsPrefix({ simulate: false, platform: 'linux', getuid: () => 1000, sudo: () => false }),
    /without a password/);
  assert.deepEqual(rightsPrefix({ simulate: false, platform: 'linux', getuid: () => 0 }), []);
  assert.throws(() => rightsPrefix({ simulate: false, platform: 'darwin' }), /only/);
});

test('one session at a time, and a holder that died is taken over', async () => {
  const where = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-lock-')), 'test.lock');
  const release = await acquire(0, { where });
  const start = Date.now();
  await assert.rejects(acquire(0.5, { where }), /one at a time/);
  assert.ok(Date.now() - start >= 400, 'it waited');
  release();
  assert.ok(!fs.existsSync(where), 'released, the file is gone');
  fs.writeFileSync(where, '999999999');            // a process that cannot exist
  assert.equal(alive(999999999), false);
  const taken = await acquire(0, { where });
  assert.equal(fs.readFileSync(where, 'utf8'), String(process.pid));
  taken();
});

test('a session waits for the capture and stops with its summary', { skip: !process.env[PROGRAM_ENV] }, async () => {
  const session = await badNetwork({ simulate: true, latency: 20, duration: 60 });
  try {
    assert.equal(session.startRecord.event, 'start');
    assert.ok(session.running);
    assert.deepEqual(session.command.slice(-6),
      ['--format', 'json', '--stop-on-stdin-close', '--duration', '60', '--simulate']);
  } finally {
    const summary = await session.stop();
    assert.equal(summary.stop_reason, 'stdin');
    assert.equal(summary.exit_code, 0);
  }
  assert.equal(await session.stop(), session.summary, 'stop again gives the same summary');
  await assert.rejects(badNetwork({ simulate: true, latncy: 5 }), /unrecognized arguments: --latncy/);
  await assert.rejects(badNetwork({ simulate: true, loss: 500 }), /refused the settings/);
  const again = await badNetwork({ simulate: true, duration: 30 });
  assert.ok(again.running, 'a failed start left the lock free');
  await again.stop();
});

test('a bad duration is refused before anything starts', () => {
  for (const bad of [0, -1, null, 'x', 86401]) {
    assert.throws(() => new BadNetwork({ simulate: true, duration: bad }), /duration/);
  }
});

test('the release lays out three packages, the systems first', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-assemble-'));
  for (const [dir, name] of [['win', 'BeanNetworkTester.exe'], ['lin', 'BeanNetworkTester']]) {
    fs.mkdirSync(path.join(root, dir, 'BeanNetworkTester', '_internal'), { recursive: true });
    fs.writeFileSync(path.join(root, dir, 'BeanNetworkTester', name), 'program', { mode: 0o755 });
  }
  const dirs = build('v1.1.0', path.join(root, 'win'), path.join(root, 'lin'), path.join(root, 'out'));
  assert.deepEqual(dirs.map((d) => path.basename(d)), ['win32-x64', 'linux-x64', 'beannetworktester']);
  const main = JSON.parse(fs.readFileSync(path.join(dirs[2], 'package.json'), 'utf8'));
  assert.equal(main.version, '1.1.0');
  assert.deepEqual(main.optionalDependencies,
    { '@beannetworktester/win32-x64': '1.1.0', '@beannetworktester/linux-x64': '1.1.0' });
  assert.equal(main.scripts, undefined);
  for (const file of main.files) assert.ok(fs.existsSync(path.join(dirs[2], file)), file);
  const win = JSON.parse(fs.readFileSync(path.join(dirs[0], 'package.json'), 'utf8'));
  assert.deepEqual([win.os, win.cpu], [['win32'], ['x64']]);
  assert.ok(fs.existsSync(path.join(dirs[1], 'program', 'BeanNetworkTester', 'BeanNetworkTester')));
  if (process.platform !== 'win32') {
    fs.accessSync(path.join(dirs[1], 'program', 'BeanNetworkTester', 'BeanNetworkTester'), fs.constants.X_OK);
  }
  assert.equal(checkedVersion('v1.1.0-rc.1'), '1.1.0-rc.1');
  assert.equal(distTag('1.1.0'), 'latest');
  assert.equal(distTag('1.1.0-rc.1'), 'next');
  for (const bad of ['1.1', '1.1.0-beta.1']) assert.throws(() => checkedVersion(bad));
  assert.throws(() => build('1.1.0', path.join(root, 'empty'), path.join(root, 'lin'), path.join(root, 'out2')),
    /holds no/);
});
