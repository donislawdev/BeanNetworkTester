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

const { spawn } = require('node:child_process');
const { checkedScenario, flagOf, sessionFlags, serverAddress, serverIps, RESERVED } = require('../lib/aim');
const { acquire, alive } = require('../lib/lock');
const { BadNetworkError, PROGRAM_ENV, programCommand, rightsPrefix } = require('../lib/program');
const { BadNetwork, badNetwork } = require('../index');
const { END_GRACE_S } = require('../lib/session');
const { build, checkedVersion, distTag } = require('../release/assemble');

const lookup = (...addresses) => async () => addresses.map((address) => ({ address }));

test('a session without an aim is refused, and simulate needs none', async () => {
  await assert.rejects(sessionFlags({ settings: { latency: 300 } }), /needs an aim/);
  assert.deepEqual(await sessionFlags({ simulate: true, settings: { latency: 3 } }), ['--latency', '3']);
  // The program's own aims are an aim on their own (an API on its port, say), and they
  // narrow server and process when given with them.
  for (const own of ['target', 'dstIp', 'dstPort']) {
    assert.equal((await sessionFlags({ settings: { [own]: 'x' } }))[0], flagOf(own));
  }
  assert.deepEqual(await sessionFlags({ process: 'self', settings: { dstPort: 443 } }),
    ['--target', String(process.pid), '--dst-port', '443']);
});

test('an empty aim is refused, not passed on as no aim at all', async () => {
  // Alone it would count as an aim and reach the program as an empty flag, which aims at
  // everything. After server it would override the server's own addresses.
  for (const [key, empty] of [['dstIp', ''], ['dstIp', []], ['dstPort', ' '], ['target', ','],
    ['target', ['', '']]]) {
    await assert.rejects(sessionFlags({ settings: { [key]: empty } }), /names nothing/);
    await assert.rejects(sessionFlags({ server: 'localhost:3000', settings: { [key]: empty },
      lookup: lookup('127.0.0.1') }), /names nothing/);
  }
});

test('process is this test, or a child process it started', async () => {
  const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 60000)']);
  await new Promise((done) => child.once('spawn', done));
  try {
    assert.deepEqual(await sessionFlags({ process: child, settings: {} }), ['--target', String(child.pid)]);
  } finally {
    const exited = new Promise((done) => child.once('exit', done));
    child.kill();
    await exited;
  }
  await assert.rejects(sessionFlags({ process: child, settings: {} }), /already ended/);
  // A number may be any process (PID 1 on Linux is every one), a name every process whose
  // name contains it: neither is something this test started, and target takes them.
  for (const bad of [1, process.pid, 'node', 'chrome.exe', '*', true, {}]) {
    await assert.rejects(sessionFlags({ process: bad, settings: {} }), /use target/, JSON.stringify(bad));
  }
});

test('several servers are every address and port of them', async () => {
  const resolveBy = async (host) => (host === '10.0.0.5' ? [{ address: '10.0.0.5' }]
    : [{ address: '127.0.0.1' }, { address: '::1' }]);
  const flags = await sessionFlags({ server: ['http://localhost:3000', { host: '10.0.0.5', port: 5432 },
    'localhost:3000'], settings: {}, lookup: resolveBy });
  assert.deepEqual(flags, ['--dst-ip', '127.0.0.1,::1,10.0.0.5', '--dst-port', '3000,5432']);
  await assert.rejects(sessionFlags({ server: [], settings: {} }), /names no server/);
  assert.throws(() => serverAddress({ host: 'h', port: 'x' }), /names no host and port/);
});

test('a scenario may not change what server or process set', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-scenario-'));
  const write = (name, data, bom = '') => {
    const where = path.join(dir, name);
    fs.writeFileSync(where, bom + JSON.stringify(data));
    return where;
  };
  const portStep = [{ at: 0, settings: { latency: 50 } }, { at: 5, settings: { dst_port: '' } }];
  await assert.rejects(sessionFlags({ server: 'localhost:3000', lookup: lookup('127.0.0.1'),
    settings: { scenario: write('s.json', { steps: portStep }) } }), /step 2 changes dst_port/);
  const list = write('list.json', portStep, String.fromCharCode(0xfeff));
  assert.deepEqual((await sessionFlags({ process: 'self', settings: { scenario: list } })).slice(-2),
    ['--scenario', path.resolve(list)], 'with process, a step on the port narrows that process');
  const targetStep = write('t.json', { steps: [{ at: 0, settings: { target: '*' } }] });
  await assert.rejects(sessionFlags({ process: 'self', settings: { scenario: targetStep } }),
    /step 1 changes target/);
  assert.equal((await sessionFlags({ settings: { dstPort: 8080, scenario: targetStep } })).at(-1),
    path.resolve(targetStep), 'the program\'s own aims are the test\'s to change: no check');
  // The program's own: failing-dns aims at port 53 in its first step.
  const shippedScenarios = [path.resolve(__dirname, '..', '..', '..', 'scenarios')];
  await assert.rejects(sessionFlags({ server: 'localhost:3000', lookup: lookup('127.0.0.1'),
    shippedScenarios, settings: { scenario: 'scenarios/failing-dns.json' } }), /step 1 changes dst_port/);
  assert.equal((await sessionFlags({ process: 'self', shippedScenarios,
    settings: { scenario: 'scenarios/failing-dns.json' } })).at(-1),
  path.join(shippedScenarios[0], 'failing-dns.json'));
  assert.throws(() => checkedScenario(path.join(dir, 'missing.json'), []), /no such file/);
  assert.throws(() => checkedScenario(__filename, []), /could not be read as JSON/);
  assert.throws(() => checkedScenario(write('flat.json', { loop: true }), []), /no list of steps/);
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

test('a lock file with no process ID in it is taken over once it is old', async () => {
  const where = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-lock-')), 'test.lock');
  fs.writeFileSync(where, '');                     // a run that died before writing it
  await assert.rejects(acquire(0, { where }), /one at a time/, 'a fresh one may be being written');
  const old = new Date(Date.now() - 60000);
  fs.utimesSync(where, old, old);
  const taken = await acquire(0, { where });
  assert.equal(fs.readFileSync(where, 'utf8'), String(process.pid));
  taken();
});

test('an abandoned lock is taken over by one waiter at a time', async () => {
  const where = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-lock-')), 'test.lock');
  fs.writeFileSync(where, '999999999');
  fs.mkdirSync(`${where}.takeover`);               // another waiter is taking it over
  await assert.rejects(acquire(0, { where }), /one at a time/);
  assert.equal(fs.readFileSync(where, 'utf8'), '999999999', 'the lock was left to that waiter');
  const old = new Date(Date.now() - 60000);
  fs.utimesSync(`${where}.takeover`, old, old);    // ...which died while doing it
  await assert.rejects(acquire(0, { where }), /one at a time/, 'its old turn is cleared first');
  const taken = await acquire(0, { where });
  assert.equal(fs.readFileSync(where, 'utf8'), String(process.pid));
  assert.ok(!fs.existsSync(`${where}.takeover`), 'the turn is given back');
  taken();
});

test('a wait for another session is called off when the test ends', async () => {
  const where = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-lock-')), 'test.lock');
  const held = await acquire(0, { where });
  const testEnded = new AbortController();
  setTimeout(() => testEnded.abort(), 300);
  const began = Date.now();
  await assert.rejects(acquire(30, { where, signal: testEnded.signal }), /test ended/);
  assert.ok(Date.now() - began < 5000, 'called off at once, not at the end of its wait');
  assert.equal(fs.readFileSync(where, 'utf8'), String(process.pid), 'the holder kept its lock');
  held();
});

test('wait and startTimeout are numbers of seconds, like duration', () => {
  for (const wait of [-1, 'x', NaN, Infinity, null]) {
    assert.throws(() => new BadNetwork({ simulate: true, wait }), /wait=/);
  }
  for (const startTimeout of [0, -1, 'x', NaN, Infinity]) {
    assert.throws(() => new BadNetwork({ simulate: true, startTimeout }), /startTimeout=/);
  }
  assert.ok(new BadNetwork({ simulate: true, wait: 0, startTimeout: 1 }), 'canary: 0 s of wait is a choice');
});

test('a start called off in its wait leaves nothing behind', { skip: !process.env[PROGRAM_ENV] }, async () => {
  const held = await acquire(0);                   // another session holds the machine's lock
  const testEnded = new AbortController();
  setTimeout(() => testEnded.abort(), 300);
  try {
    await assert.rejects(new BadNetwork({ simulate: true, latency: 5, wait: 30 })
      .start({ signal: testEnded.signal }), /test ended/);
  } finally {
    held();
  }
  // Nothing counts as live: the next session of this process starts.
  const next = await badNetwork({ simulate: true, latency: 5, duration: 60 });
  await next.stop();
});

test('a link or a FIFO at the lock path is refused at once', { skip: process.platform === 'win32' }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bnt-lock-'));
  const victim = path.join(dir, 'victim');
  fs.writeFileSync(victim, '999999999');
  const link = path.join(dir, 'link.lock');
  fs.symlinkSync(victim, link);
  await assert.rejects(acquire(0, { where: link }), /not a plain file/);
  assert.equal(fs.readFileSync(victim, 'utf8'), '999999999', 'the file behind the link is untouched');
  const fifo = path.join(dir, 'fifo.lock');
  require('node:child_process').execFileSync('mkfifo', [fifo]);
  const began = Date.now();
  await assert.rejects(acquire(0, { where: fifo }), /not a plain file/);
  assert.ok(Date.now() - began < 5000, 'refused at once, not blocked');
});

test('a session waits for the capture and stops with its summary', { skip: !process.env[PROGRAM_ENV] }, async () => {
  const session = await badNetwork({ simulate: true, latency: 20, duration: 60 });
  try {
    assert.equal(session.startRecord.event, 'start');
    assert.ok(session.running);
    const began = Date.now();
    await assert.rejects(badNetwork({ simulate: true, duration: 60, wait: 30 }), /has not been stopped yet/);
    assert.ok(Date.now() - began < 5000, 'a second one here is refused at once, not after its own lock');
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

test('a stop that is not heard asks first, then forces', async () => {
  // A forced end on Linux leaves the aim's packets nowhere to go for about 3 s, so a
  // program that did not hear its input close is asked to end before it is forced.
  assert.equal(END_GRACE_S, 5);
  const ask = async (endsOn) => {
    const calls = [];
    const session = new BadNetwork({ simulate: true });
    // A running program holds the event loop, and the waits in _end do not: on Node 22
    // a fake that held nothing ended the test while _end still waited.
    const running = setInterval(() => {}, 1000);
    let exit;
    session._exited = new Promise((done) => { exit = done; });
    session._child = { kill: (signal) => { calls.push(signal); if (signal === endsOn) exit(true); } };
    try {
      await session._end({ grace: 0.05 });
    } finally {
      clearInterval(running);
    }
    return calls;
  };
  assert.deepEqual(await ask('SIGKILL'), ['SIGTERM', 'SIGKILL'], 'asked, given time, then forced');
  assert.deepEqual(await ask('SIGTERM'), ['SIGTERM'], 'canary: one that ends when asked is not forced');
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
