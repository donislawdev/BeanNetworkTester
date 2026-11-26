// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
