const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const workflowPath = path.join(__dirname, '..', 'workflows', 'open-pr-limit.yml');
const workflow = fs.readFileSync(workflowPath, 'utf8');

// The guard runs inside actions/github-script. The repository Actions policy
// requires every action to be pinned to a commit SHA (never a mutable tag) and
// to run on the Node 24 runtime, because GitHub deprecated the Node 20 runtime.
// GITHUB_SCRIPT_NODE24_SHA is the published commit of actions/github-script
// v9.0.0, whose action.yml declares `using: node24`.
const GITHUB_SCRIPT_NODE24_SHA = '3a2844b7e9c422d3c10d287c895573f7108da1b3';

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

test('runs only on pull_request opened and reopened', () => {
  const trigger = workflow.match(/^on:\n([\s\S]*?)^permissions:/m);
  assert.ok(trigger, 'workflow must declare an on: block before permissions:');
  const triggerBlock = trigger[1];

  assert.match(triggerBlock, /pull_request:/, 'workflow must trigger on pull_request');
  assert.match(triggerBlock, /types:\s*\[opened,\s*reopened\]/, 'trigger types must be exactly opened and reopened');
  assert.doesNotMatch(triggerBlock, /synchronize/, 'synchronize must not trigger the guard');
});

test('requests only read access to pull requests', () => {
  const permissions = workflow.match(/^permissions:\n([\s\S]*?)^jobs:/m);
  assert.ok(permissions, 'workflow must declare a permissions: block before jobs:');
  const block = permissions[1];

  assert.match(block, /^\s*pull-requests:\s*read\s*$/m, 'pull-requests permission must be read only');
  assert.doesNotMatch(block, /write/, 'no write permission is allowed');
  assert.doesNotMatch(block, /contents:/, 'the guard does not need contents access');
});

test('pins the github-script action to a commit SHA on the Node 24 runtime', () => {
  const uses = workflow.match(/uses:\s*actions\/github-script@(\S+)/);

  assert.ok(uses, 'workflow must use actions/github-script');
  const reference = uses[1];

  assert.match(
    reference,
    /^[0-9a-f]{40}(\s+#\s*v\d+\.\d+\.\d+)?$/,
    `github-script must be pinned to a 40-character commit SHA, got "${reference}"`,
  );
  assert.equal(
    reference.split(/\s+/)[0],
    GITHUB_SCRIPT_NODE24_SHA,
    'github-script must be pinned to the published Node 24 runtime commit',
  );
});
