/** Where a session aims: a URL such as 'http://localhost:3000', 'host:port', or { host, port }. */
export type Server = string | { host: string; port: number };

export interface BadNetworkOptions {
  /** Every connection to this server's addresses and port, from any program. */
  server?: Server;
  /** 'self' (this process and everything it started), a process ID, or a program name. */
  process?: 'self' | number | string;
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
  /** Starts the program and resolves once it is capturing. */
  start(): Promise<BadNetwork>;
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
