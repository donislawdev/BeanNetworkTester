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
    const starting = new Set();
    const testEnded = new AbortController();
    await use((options) => {
      // Kept once it started: a session that failed to start has cleaned up after
      // itself, and has no summary to report.
      const start = new BadNetwork(options).start({ signal: testEnded.signal })
        .then((session) => {
          sessions.push(session);
          return session;
        });
      starting.add(start);
      start.then(() => starting.delete(start), () => starting.delete(start));
      return start;
    });
    // A start still waiting for another session when the test ended (a test that timed
    // out in the wait, or one that did not await it) would otherwise begin after the test,
    // with nobody to stop it before its duration. It is called off, and one already past
    // its wait is let finish, so the loop below stops it with the others.
    testEnded.abort();
    await Promise.allSettled([...starting]);
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
