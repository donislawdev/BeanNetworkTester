// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

'use strict';

// Slow down, break or cut the real network for a test: Playwright Test, or any Node code.
//
//   const { badNetwork } = require('beannetworktester');
//   const session = await badNetwork({ server: 'http://localhost:3000', latency: 300 });
//   ...
//   const summary = await session.stop();
//
// For Playwright Test, import { test, expect } from 'beannetworktester/playwright'.

const { BadNetwork, BadNetworkError, badNetwork } = require('./lib/session');

module.exports = { BadNetwork, BadNetworkError, badNetwork };
