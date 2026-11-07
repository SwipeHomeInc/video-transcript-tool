#!/bin/bash
# Installs the company plugin in Claude Code cloud sessions. Cloud containers
# start fresh, and the extraKnownMarketplaces entry in settings.json is not
# applied there, so add the marketplace and install the plugin here.
# Both commands are no-ops when the company is already installed.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Output goes to stderr so it stays out of the session's context.
{
  claude plugin marketplace add SwipeHomeInc/Kitchen &&
    claude plugin install company@swipehome-kitchen
} >&2 || echo "company: install failed; run the two commands in .claude/hooks/session-start.sh by hand" >&2

exit 0
