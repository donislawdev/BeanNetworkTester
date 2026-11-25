import type {
  PlaywrightTestArgs, PlaywrightTestOptions, PlaywrightWorkerArgs, PlaywrightWorkerOptions,
  TestType,
} from '@playwright/test';
import type { BadNetwork, BadNetworkOptions } from './index';

export declare const test: TestType<
  PlaywrightTestArgs & PlaywrightTestOptions & {
    /** Starts a session for this test; every session is stopped when the test ends. */
    badNetwork: (options: BadNetworkOptions) => Promise<BadNetwork>;
  },
  PlaywrightWorkerArgs & PlaywrightWorkerOptions
>;

export { expect } from '@playwright/test';
