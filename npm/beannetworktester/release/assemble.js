'use strict';

// Lays out the packages a release puts on npm: beannetworktester itself, and one
// package per system carrying the release's own program, unchanged (on Windows the
// signed exe). .github/workflows/npm.yml runs it on the archives it downloaded from the
// release, checked and unpacked, and nothing here fetches or publishes anything. It is
// not part of the package: "files" in package.json leaves it out.
//
//   node assemble.js build <version> <windows-dir> <linux-dir> <out>
//       the packages, each a folder in <out>; prints the folders, the systems first
//   node assemble.js tag <version>
//       the dist-tag a version goes under: latest, or next for a release candidate

const fs = require('node:fs');
const path = require('node:path');
const { PACKAGES } = require('../lib/program');

const PACKAGE = path.resolve(__dirname, '..');
const REPO = path.resolve(PACKAGE, '..', '..');
const TOP = 'BeanNetworkTester';
const PROGRAMS = { 'win32-x64': `${TOP}/BeanNetworkTester.exe`, 'linux-x64': `${TOP}/BeanNetworkTester` };
const VERSION = /^v?(\d+\.\d+\.\d+(?:-rc\.\d+)?)$/;

function fail(message) {
  throw new Error(`assemble: ${message}`);
}

function checkedVersion(version) {
  const found = VERSION.exec(version || '');
  if (!found) fail(`${JSON.stringify(version)} is not a release version, such as 1.1.0 or 1.1.0-rc.1`);
  return found[1];
}

function distTag(version) {
  return checkedVersion(version).includes('-') ? 'next' : 'latest';
}

function writeJson(where, data) {
  fs.writeFileSync(where, JSON.stringify(data, null, 2) + '\n');
}

function platformPackage(system, version, from, out) {
  const [os, cpu] = system.split('-');
  const dir = path.join(out, system);
  const program = path.join(from, ...PROGRAMS[system].split('/'));
  if (!fs.existsSync(program)) fail(`${from} holds no ${PROGRAMS[system]}`);
  fs.mkdirSync(path.join(dir, 'program'), { recursive: true });
  // cpSync keeps each file's mode, so the Linux program keeps its execute bit as long
  // as this runs on Linux: npm.yml packs there for that reason.
  fs.cpSync(path.join(from, TOP), path.join(dir, 'program', TOP), { recursive: true,
    verbatimSymlinks: true, errorOnExist: true });
  for (const entry of fs.readdirSync(path.join(dir, 'program', TOP), { recursive: true })) {
    const where = path.join(dir, 'program', TOP, entry);
    if (fs.lstatSync(where).isSymbolicLink()) fail(`${where} is a link, and a package cannot hold one`);
  }
  fs.copyFileSync(path.join(REPO, 'LICENSE'), path.join(dir, 'LICENSE'));
  fs.writeFileSync(path.join(dir, 'README.md'),
    `# ${PACKAGES[system]}\n\nThe Bean Network Tester program for ${os === 'win32' ? 'Windows' : 'Linux'} ` +
    `x64, unchanged from release ${version}, for the [beannetworktester](https://www.npmjs.com/package/` +
    'beannetworktester) package. npm installs it with that package on this system. It is not ' +
    'meant to be installed on its own.\n');
  writeJson(path.join(dir, 'package.json'), {
    name: PACKAGES[system], version, description: `The Bean Network Tester program for ` +
      `${os === 'win32' ? 'Windows' : 'Linux'} x64, for the beannetworktester package.`,
    license: 'GPL-3.0-only', author: 'DonislawDev', homepage: 'https://beannetworktester.donislawdev.com/',
    repository: { type: 'git', url: 'git+https://github.com/donislawdev/BeanNetworkTester.git' },
    os: [os], cpu: [cpu], files: ['program/', 'LICENSE', 'README.md'], preferUnplugged: true,
  });
  return dir;
}

function mainPackage(version, out) {
  const source = JSON.parse(fs.readFileSync(path.join(PACKAGE, 'package.json'), 'utf8'));
  const dir = path.join(out, 'beannetworktester');
  fs.mkdirSync(dir, { recursive: true });
  for (const entry of source.files) {
    const from = entry === 'LICENSE' ? path.join(REPO, 'LICENSE') : path.join(PACKAGE, entry);
    fs.cpSync(from, path.join(dir, entry), { recursive: true });
  }
  delete source.scripts;
  source.version = version;
  source.optionalDependencies = Object.fromEntries(
    Object.values(PACKAGES).map((name) => [name, version]));
  writeJson(path.join(dir, 'package.json'), source);
  return dir;
}

function build(version, windowsDir, linuxDir, out) {
  const v = checkedVersion(version);
  if (fs.existsSync(out)) fail(`${out} exists already`);
  fs.mkdirSync(out, { recursive: true });
  const from = { 'win32-x64': windowsDir, 'linux-x64': linuxDir };
  const systems = Object.keys(PACKAGES);
  if (systems.join() !== Object.keys(from).join()) {
    fail(`lib/program.js names ${systems.join(', ')}, and assemble knows win32-x64 and linux-x64`);
  }
  return [...systems.map((system) => platformPackage(system, v, from[system], out)),
    mainPackage(v, out)];
}

function main(argv) {
  if (argv[0] === 'build' && argv.length === 5) {
    for (const dir of build(argv[1], path.resolve(argv[2]), path.resolve(argv[3]), path.resolve(argv[4]))) {
      console.log(dir);
    }
  } else if (argv[0] === 'tag' && argv.length === 2) {
    console.log(distTag(argv[1]));
  } else {
    fail('usage: assemble.js build <version> <windows-dir> <linux-dir> <out> | tag <version>');
  }
}

if (require.main === module) {
  try {
    main(process.argv.slice(2));
  } catch (err) {
    console.error(err.message);
    process.exit(1);
  }
}

module.exports = { build, checkedVersion, distTag };
