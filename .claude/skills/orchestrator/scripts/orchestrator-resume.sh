#!/usr/bin/env bash
# SessionStart(source=compact) hook: re-inject the grand-project snapshot after a
# compaction so the orchestrator thread survives. Registered by the orchestrator
# skill (SKILL.md §grand-project snapshot) in the project's .claude/settings.local.json.
# Fail-open: any missing file or parse problem emits nothing and exits 0.
set -uo pipefail

# Resolve the project slug the same way the harness does: cwd → ~/.claude/projects/<slug>
slug=$(pwd | sed 's|/|-|g')
snapshot="$HOME/.claude/projects/${slug}/orchestrator-runs/grand-project-snapshot.json"

[ -f "$snapshot" ] || exit 0

cat <<EOF
<system-reminder>
Orchestrator grand-project snapshot survives compaction. Before your next routing
claim: read ${snapshot} (grand-project name/phase, user_recurring_guidance,
in_flight_decisions, pending user actions), re-run the state miner over active
lanes, and open with a one-paragraph "resumed" summary.
</system-reminder>
EOF
exit 0
