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
