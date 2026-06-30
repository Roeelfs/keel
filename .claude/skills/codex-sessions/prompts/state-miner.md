# Codex State Miner

Goal
- Mine current Codex sessions and produce the newest orchestration-safe state.
- Focus on active sessions, latest final answers, stage changes, and hard constraints from recent commits.

Instructions
1. Read the JSON cache from `state-miner-*.json` and keep it as the primary timeline input.
2. Confirm latest session revisions by checking each session `tail` and `task_complete` details.
3. Prioritize sessions whose title or recent content match your project's active workstreams (pass these as a `--filter` to the `list`/`survey`/`mine` commands, or adjust the priority terms here to your domain).
4. Capture any explicit scope shifts, blockers, and unresolved follow-up decisions.
5. Do not infer PR merge status unless provided by explicit GitHub JSON.

Expected Output
- Active Lanes: current live workstreams and owners.
- Cross-Lane State: integration risks and shared-file conflicts.
- Latest Revisions: session -> latest meaningful statement/action.
- Next Moves (ranked): what should run next.
- Cache JSON: include `next_actions` and `open_questions`.

Format
Return one compact markdown artifact with those exact sections, followed by a JSON code block labelled `json`.
