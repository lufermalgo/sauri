'use strict';

const MAX_OPEN_PULL_REQUESTS = 3;

function getOpenPullRequestLimitError(openPullRequests) {
  if (openPullRequests.length <= MAX_OPEN_PULL_REQUESTS) {
    return null;
  }

  return `This repository has ${openPullRequests.length} open pull requests; the maximum is ${MAX_OPEN_PULL_REQUESTS}.`;
}

module.exports = { getOpenPullRequestLimitError };
