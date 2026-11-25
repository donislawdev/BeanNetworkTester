'use strict';

// Playwright Test with a badNetwork fixture.
//
//   import { test, expect } from 'beannetworktester/playwright';
//
//   test('the spinner shows on a slow network', async ({ page, badNetwork }) => {
//     await badNetwork({ server: 'http://localhost:3000', latency: 800 });
//     await page.goto('http://localhost:3000');
//   });
//
// Calling badNetwork starts a session and resolves once the network is slowed. Every
// session it started is stopped when the test ends, and its summary is attached to the
// test's report as "bad-network".

const { test: base, expect } = require('@playwright/test');
const { BadNetwork } = require('./lib/session');

const test = base.extend({
  // eslint-disable-next-line no-empty-pattern -- Playwright reads the fixtures it needs from this pattern
  badNetwork: async ({}, use, testInfo) => {
    const sessions = [];
    await use(async (options) => {
      const session = new BadNetwork(options);
      sessions.push(session);
      return session.start();
    });
    let failure = null;
    for (const session of sessions) {
      try {
        const summary = await session.stop();
        if (summary) {
          await testInfo.attach('bad-network', {
            body: JSON.stringify(summary, null, 2), contentType: 'application/json' });
        }
      } catch (err) {
        failure = failure || err;
      }
    }
    if (failure) throw failure;
  },
});

module.exports = { test, expect };
