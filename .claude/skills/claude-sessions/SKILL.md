---
name: claude-sessions
description: Survey live Claude Code sessions — list which are running and extract their recent state (last user msg, last assistant reply, open todos), and mine a session's design decisions for downstream review. Use when the user wants to "look at all active sessions", "see what each session is doing", "find context across parallel work", or when another skill needs a session's decision history.
---

# claude-sessions

Source of truth: `~/.claude/sessions/<PID>.json`. A session is "live" iff its
`pid` is alive and `kind == "interactive"`. Conversation content lives in
`~/.claude/projects/<project-slug>/<sid>.jsonl`.

This skill is the **decision-mining backbone** for the `spec-review` and
`spec-test-*` skills: `extract-decisions` turns a long session's transcript into
a compact JSON of user-turn windows, files edited, commits, and tool
distribution — so reviewers can judge a spec against the *intent* that produced
it, not just the prose.

## Commands

```bash
# Survey live sessions (use ~/.claude/skills/... if installed globally)
python3 .claude/skills/claude-sessions/sessions.py list
python3 .claude/skills/claude-sessions/sessions.py list --filter myproject
python3 .claude/skills/claude-sessions/sessions.py survey
python3 .claude/skills/claude-sessions/sessions.py survey --filter myproject
python3 .claude/skills/claude-sessions/sessions.py survey --sid 40a2494b
python3 .claude/skills/claude-sessions/sessions.py survey --json

# Mine the design decisions of a session into structured JSON (used by spec-review)
python3 .claude/skills/claude-sessions/sessions.py extract-decisions \
  --sid "$CLAUDE_SESSION_ID" \
  --output "/tmp/decisions-${CLAUDE_SESSION_ID:0:8}.json"
```

`survey` first emits a **cross-session trunk timeline** (recent commits on `main`
+ `origin/main`), each annotated with the live session NAME (resolved by the
`Session-Id` git trailer), `<dead/orphan sid:…>` for SIDs not in the live list,
or `(no Session-Id)` for human commits. Unpushed commits are marked `*`. This
catches commits with mismatched/manually-pasted Session-Id trailers and orphan
commits from dead sessions — failure modes the per-session view (filtered by
exact SID match) silently drops.

Then per live session:
- **commits authored by this session** (mined from the `Session-Id:` git trailer, last 7d)
- **last 10 tool uses** with timestamps (Bash cmds, file edits, TaskCreate/Update, Skill, Agent — not just text)
- last user message + timestamp
- last assistant text + timestamp
- latest TodoWrite payload

Why both tool uses *and* assistant text: an earlier version pinned on the last
text-bearing assistant reply, which biases toward narrative replies and misses
sessions that just shipped via `gh`/`git` tools. Always verify attribution
against `git log` + open PRs before drafting prompts to other sessions.

> **Session-Id trailer convention.** The trunk timeline and per-session commit
> attribution both rely on each commit carrying a `Session-Id: <sid>` git
> trailer. keel's session hooks capture `$CLAUDE_SESSION_ID`; add the trailer in
> your commits (`git commit --trailer "Session-Id: $CLAUDE_SESSION_ID"`) to make
> commit→session attribution work. Without it, attribution falls back to
> `(no Session-Id)` and still works for the rest of the survey.

**Always reference sessions by NAME in narrative output, not SID prefix** — names
own the user's mental model. SID prefixes are CLI-only (`survey --sid <prefix>`).

`--sid <prefix>` works on dead sessions too — falls back to scanning
`~/.claude/projects/*/` JSONLs when the PID is gone.

`--no-git` skips Session-Id trailer mining if the cwd isn't a git repo or you
don't care.

## Notes

- Symlinks under `~/.claude/projects/` (when a project slug is aliased) are
  resolved automatically — the JSONL is found by sid match, not directory name.
- `--json` is intended for piping into another tool or LLM context.
- This is **read-only**. Survey never writes; safe to run on parallel sessions.
