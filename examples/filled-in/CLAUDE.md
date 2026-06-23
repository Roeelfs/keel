# Acme Tasks API — Engineering Rules for AI Agents

> Read by every AI agent working in this repo. The contract for how we build here,
> in priority order. When a rule here conflicts with a default behavior, this wins.

## What this project is

Acme Tasks is a multi-tenant task-management API. Every customer is an `org`; users
belong to an org and may only ever see their own org's data. The non-negotiable
quality bar is **tenant isolation** — a cross-org data leak is a Sev-1. Correctness
and data safety beat shipping speed.

**Stack:** TypeScript (strict), Node 22, Fastify, PostgreSQL (via `pg`), Zod for
validation, Vitest for tests, pnpm.
**Key directories:** `src/routes/` HTTP handlers · `src/db/` queries & migrations ·
`src/domain/` business logic · `docs/specs/` feature specs.

## How to run things

| Task | Command |
|------|---------|
| Install deps | `pnpm install` |
| Build | `pnpm build` |
| Typecheck | `pnpm typecheck` |
| Lint | `pnpm lint` |
| Unit/integration tests | `pnpm test` |
| Run locally | `pnpm dev` |

For end-to-end / staging verification, see `docs/testing-config.md`.

## Coding standards

- TypeScript strict; no `any`. Validate every external input at the boundary with a
  Zod schema before it reaches domain logic.
- **Small units.** Files 200–400 lines (800 max); functions < 50 lines.
- **Immutable by default.** Don't mutate inputs; return new objects.
- **Match the neighbors.** New routes/queries follow the structure of existing ones.
- **Errors are handled, not swallowed.** No empty `catch {}`. Domain errors throw a
  typed `AppError`; the route layer maps them to status codes.

## Change discipline

- **Delete the path you replace, in the same change.** No dead code, no dual
  old/new query paths behind a flag.
- One PR per feature; split only on a true ordering dependency, never just for size.
- No speculative abstraction — build for the requirement in front of you.

## Verification (non-negotiable)

- Verify before claiming done: run `pnpm typecheck && pnpm test` and read the
  output. "It should work" is not "it works."
- `pnpm typecheck` and `pnpm test` must pass locally before you push. CI is a
  backstop, not the first check.
- For any change touching data access, prove tenant isolation holds with a test
  that asserts an org cannot read another org's rows.

## Git & commits

- Conventional commits with a required scope: `<type>(<scope>): <description>`.
  Example scopes: `tasks`, `auth`, `sharing`, `db`, `api`.
- Add a session trailer: `git commit -m "..." --trailer "Session-Id: $CLAUDE_SESSION_ID"`.
- Branch off fresh trunk: `git fetch origin` then branch from `origin/main`.
- Don't open PRs or deploy without confirming first.

## Parallel agents

- Claim scope before editing: `tooling/workflow/workflow claim-scope 'src/routes/sharing/**'`.
- Run `pnpm test` / `pnpm build` under `with-heavy-lock` when other sessions are active.
- Worktrees live under `.worktrees/`; launch from the main checkout, then `cd` in.

## Security

See `docs/security-policy.md`. The three rules that matter most:
1. Authorization is derived from the JWT's verified `org_id` claim — never from a
   request body or query param.
2. Every query is scoped to the caller's `org_id`. No exceptions.
3. No secrets in code or logs; DB and JWT secrets come from the environment.

## Specs & review

Specs live in `docs/specs/`. Non-trivial features get a spec, a `spec-review` pass,
and a `spec-test-plan` before they're called done.
