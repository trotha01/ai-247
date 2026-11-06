// The test/dev suites drive a real `wrangler dev --local` process with several HTTP round trips and 400 ms sleeps per
// test; one took 4.6 s locally and crossed vitest's default 5 s limit on a loaded CI runner (ci run 42256969087), and
// a timed-out test leaves its R2 state behind for the next one. 30 s per test is generous for the unit suites too.
export default {
  test: {
    testTimeout: 30_000,
    hookTimeout: 180_000,
  },
};
