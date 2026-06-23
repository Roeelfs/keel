# Worked example — "Acme Tasks API"

This directory shows keel's templates **filled in** for a fictional project: a
multi-tenant task-management API written in TypeScript on Node + Postgres. It's
here so you can see what a populated `CLAUDE.md`, security policy, and testing
config look like before you write your own — and so the `spec-review` /
`spec-test-*` skills have a real spec to run against.

Nothing here is wired into a real system; it's illustrative. Files:

| File | What it shows |
|------|---------------|
| [`CLAUDE.md`](./CLAUDE.md) | The engineering-rules template, filled for a real-ish stack |
| [`docs/security-policy.md`](./docs/security-policy.md) | A concrete policy the `security-miner` can cite |
| [`docs/testing-config.md`](./docs/testing-config.md) | Real-shaped commands/URLs the test skills read |
| [`docs/specs/0001-task-sharing.md`](./docs/specs/0001-task-sharing.md) | A small spec to try `spec-review` on |

To see the spec flow in action, copy keel's `.claude/` into a checkout of this
example (or your own repo) and run the `spec-review` skill against
`docs/specs/0001-task-sharing.md`.
