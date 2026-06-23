# Quickstart

From zero to running the spec → review → test flow in your own repo.

## 1. Install into your repo

```bash
git clone https://github.com/Roeelfs/keel.git ~/keel
cd /path/to/your/project          # a git repo
~/keel/install.sh .
```

`install.sh` copies `.claude/skills`, `.claude/agents`, `.claude/hooks`, and
`tooling/` into your repo, and scaffolds the template files **only if they don't
already exist**. It never overwrites your `CLAUDE.md`, `settings.json`, or docs.

## 2. Fill in the three files that make it yours

The harness needs to know your project to be useful. Fill these (the scaffolded
copies are templates with `{{PLACEHOLDERS}}`):

| File | What it drives |
|------|----------------|
| `CLAUDE.md` | The engineering rules every agent follows. Fill the placeholders. |
| `docs/security-policy.md` | The policy `spec-review`'s security miner audits against. |
| `docs/testing-config.md` | How the test skills run real tests here (commands, staging URLs, accounts). |

See [`examples/filled-in/`](examples/filled-in/) for a fully populated set you can
copy from.

## 3. Wire up settings

If you had no `.claude/settings.json`, the installer created one from the example —
open it and confirm the hooks block and the permission allow/deny lists look right
for you. If you already had one, the installer left it alone and dropped
`.claude/settings.example.json` beside it; merge the `hooks` block in by hand.

The hooks do the following at session start: capture `$CLAUDE_SESSION_ID`, warn if
you launched from a worktree, register your session in the shared workflow state,
and inject the in-flight work registry into context. At session end they release
your claims. The `PreToolUse` hook enforces the heavy-op lock.

**Restart Claude Code in the repo** so the SessionStart hooks load.

## 4. Install the optional bits (recommended for parallel work)

```bash
# Let the serialize-heavy-ops hook enforce the lock by putting the wrapper on PATH:
sudo cp tooling/sandbox/with-heavy-lock /usr/local/bin/ && sudo chmod +x /usr/local/bin/with-heavy-lock

# (macOS / Linux) install the crashed-session reaper timer — see:
cat tooling/workflow/install/README.md
```

If you don't have `flock` (macOS): `brew install flock`.

## 5. Run the flow

### Review a spec

Write a spec under `docs/specs/` (or try the bundled
[`examples/filled-in/docs/specs/0001-task-sharing.md`](examples/filled-in/docs/specs/0001-task-sharing.md)),
then in Claude Code:

> Run spec-review on docs/specs/0001-task-sharing.md

The `spec-review` skill mines your session's decisions, dispatches the 9 reviewers
in parallel, cross-examines any Claude↔Codex disagreements, and reports findings —
applying only real design fixes to the spec prose. (No Codex CLI installed? It runs
the Claude lanes and skips the Codex ones.)

### Plan and execute tests

> Generate a test plan for docs/specs/0001-task-sharing.md

then

> Execute the test plan

`spec-test-plan` produces an E2E-first plan grounded in your `docs/testing-config.md`;
`spec-test-execute` runs it tier by tier, triaging failures with parallel
diagnostician agents.

### Coordinate parallel agents

When you run more than one session (one per worktree), have each claim its lane
before editing:

```bash
tooling/workflow/workflow claim-scope 'src/routes/sharing/**'
tooling/workflow/workflow status        # see who owns what
```

A second session that tries to claim an overlapping path is refused. Run heavy
commands under the lock:

```bash
with-heavy-lock pnpm test
```

## Troubleshooting

- **Hooks didn't run** — confirm `.claude/settings.json` has the `hooks` block and
  you restarted Claude Code. Hook paths use `$CLAUDE_PROJECT_DIR`.
- **`claim-scope` says CLAUDE_SESSION_ID is not set** — the `capture-session-id.sh`
  SessionStart hook sets it; if you're running the CLI outside a session, export one:
  `export CLAUDE_SESSION_ID=$(uuidgen)`.
- **`flock: command not found`** — `brew install flock` (macOS). The tooling degrades
  to best-effort without it, but the locks won't serialize.
- **Codex lanes skipped** — that's expected without the Codex CLI; the review still
  runs Claude-only.
