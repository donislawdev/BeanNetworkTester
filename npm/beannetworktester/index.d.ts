// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

/** A ChildProcess from node:child_process, described here so that Node's own types are
 * not needed. */
export interface ChildProcessLike {
  readonly pid?: number | undefined;
  readonly exitCode: number | null;
}

/** A server: a URL such as 'http://localhost:3000', 'host:port', or { host, port }. */
export type Server = string | { host: string; port: number };

export interface BadNetworkOptions {
  /** Every connection to this server's addresses and port, from any program. An array of
   * servers is every address of them with every port of them. */
  server?: Server | Server[];
  /** 'self' (this process and everything it started), or a ChildProcess this test started
   * and that still runs. A process ID or a program name goes in target. */
  process?: 'self' | ChildProcessLike;
  /** The program's own aim: process IDs and names (a name matches every program whose name
   * contains it), in its own syntax. Narrows server when given with it. */
  target?: string | number;
  /** The program's own aim: remote addresses, ranges, CIDR, in its own syntax. Every
   * program's connections to them are slowed. Narrows process when given with it. */
  dstIp?: string | string[];
  /** The program's own aim: remote ports, in its own syntax. Every program's connections to
   * them are slowed: 443 is all of the machine's HTTPS. Narrows process when given with it. */
  dstPort?: string | number | Array<string | number>;
  /** A scenario file: settings that change over time. Its steps may not change what server
   * or process set. */
  scenario?: string;
  /** The most seconds the session may run. 300 unless given. */
  duration?: number;
  /** Made-up traffic: no rights needed, nothing on the network changes. */
  simulate?: boolean;
  /** Seconds to wait for another session on this machine to end. 600 unless given. */
  wait?: number;
  /** Seconds to wait for the program to start capturing. 60 unless given. */
  startTimeout?: number;
  /** Any of the program's flags in camelCase: latency, jitter, loss, lossBurst, down, up, ... */
  [setting: string]: unknown;
}

/** The program's summary object (its last line in --format json). */
export interface Summary {
  event: 'summary';
  exit_code: number;
  exit_name: string;
  stop_reason: string;
  seed: number | null;
  elapsed_s: number;
  packets: number;
  counters: Record<string, number>;
  repro_command: string | null;
  [key: string]: unknown;
}

export declare class BadNetworkError extends Error {}

export declare class BadNetwork {
  constructor(options?: BadNetworkOptions);
  /**
   * Starts the program and resolves once it is capturing. An aborted `signal` calls the
   * start off while it still waits for another session.
   */
  start(options?: { signal?: AbortSignal }): Promise<BadNetwork>;
  /** Ends the session and resolves to its summary. */
  stop(options?: { timeout?: number }): Promise<Summary | null>;
  readonly running: boolean;
  readonly command: string[];
  readonly startRecord: Record<string, unknown> | null;
  readonly summary: Summary | null;
  readonly stderr: string[];
}

/** Starts a session and resolves to it once the network is slowed. */
export declare function badNetwork(options?: BadNetworkOptions): Promise<BadNetwork>;
