const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const workflow = fs.readFileSync('.github/workflows/open-pr-limit.yml', 'utf8');
const scriptMatch = workflow.match(/^          script: \|\n([\s\S]*)$/m);
assert.ok(scriptMatch, 'workflow must define an inline github-script');
const script = scriptMatch[1]
  .split('\n')
  .map((line) => (line.startsWith('            ') ? line.slice(12) : line))
  .join('\n');

async function runGuard(openPullRequestCount) {
  const results = { failures: [], info: [], request: null };
  const openPullRequests = Array.from({ length: openPullRequestCount }, (_, index) => ({ number: index + 1 }));
  const github = {
    rest: { pulls: { list: 'pulls.list' } },
    paginate: async (endpoint, request) => {
      results.request = { endpoint, ...request };
      return openPullRequests;
    },
  };

  await vm.runInNewContext(`(async () => {\n${script}\n})()`, {
    context: { repo: { owner: 'summan', repo: 'sauri' } },
    core: {
      setFailed: (message) => results.failures.push(message),
      info: (message) => results.info.push(message),
    },
    github,
  });
  return results;
}

test('allows a repository at the three-open-PR limit', async () => {
  const result = await runGuard(3);

  assert.deepEqual(result.failures, []);
  assert.deepEqual(result.info, ['Open pull request limit respected (3/3).']);
  assert.deepEqual(result.request, {
    endpoint: 'pulls.list',
    owner: 'summan',
    repo: 'sauri',
    state: 'open',
    per_page: 100,
  });
});

test('fails when the repository exceeds the limit', async () => {
  const result = await runGuard(4);

  assert.deepEqual(result.failures, ['This repository has 4 open pull requests; the maximum is 3.']);
});

test('reports an already-over-cap repository without blocking unrelated PR updates', async () => {
  const result = await runGuard(11);

  assert.deepEqual(result.failures, ['This repository has 11 open pull requests; the maximum is 3.']);
});
