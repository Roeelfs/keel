CHECKPOINT MODE ({{DATE}}). The founder is about to switch accounts. This is NOT a full stop: finish what is in flight, start nothing new, and leave a clean checkpoint. Session history will not be readable from the other account, so state must live in git, Linear and a note.

You are "{{TITLE}}". In your own session:
1. Let any running build, verify or lane finish to its next checkpoint. Do not start new work.
2. Push your own feature branch once if it has unpushed commits, or record its worktree path, branch and PR. A merge, deploy or prod mutation needs the human's explicit in-session go-ahead; do not do one to finish.
3. Update Linear: one comment per ticket you touched (shipped with PR and mergedAt, parked and why, unproven and the exact probe) and set the state to match reality. Never write a CYN- number you did not get back from the tracker. If Linear is unavailable, put the intended comment in your note.
4. Write ~/.claude/sessions-to-chips/wrapup/{{DATE}}-<short-slug-of-your-title>.md with: state (DONE / RUNNING / PARKED / LIVE-WORK), worktree, branch, PR, the gate that blocks you (one line), what is still unproven, and the exact continuation phrase to resume you from a fresh session on the other account.
5. Your final message is one line: the note path and your state. No reply is needed in the sender's session.
