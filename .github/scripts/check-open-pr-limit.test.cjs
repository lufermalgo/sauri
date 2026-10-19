const test = require('node:test');
const assert = require('node:assert/strict');
const { getOpenPullRequestLimitError } = require('./check-open-pr-limit.cjs');

test('allows a repository at the three-open-PR limit', () => {
  const openPullRequests = Array.from({ length: 3 }, (_, index) => ({ number: index + 1 }));

  assert.equal(getOpenPullRequestLimitError(openPullRequests), null);
});

test('rejects an opening or reopening when the repository exceeds the limit', () => {
  const openPullRequests = Array.from({ length: 4 }, (_, index) => ({ number: index + 1 }));

  assert.equal(
    getOpenPullRequestLimitError(openPullRequests),
    'This repository has 4 open pull requests; the maximum is 3.',
  );
});

test('reports an already-over-cap repository without blocking unrelated PR updates', () => {
  const openPullRequests = Array.from({ length: 11 }, (_, index) => ({ number: index + 1 }));

  assert.equal(
    getOpenPullRequestLimitError(openPullRequests),
    'This repository has 11 open pull requests; the maximum is 3.',
  );
});
