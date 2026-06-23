# Security Policy — Acme Tasks API

> The rulebook `security-miner` and `security-reviewer` audit against. Every rule is
> specific enough to cite and point at a concrete violation.

## 1. Authentication & authorization

- Authorization is derived from the JWT's verified `org_id` and `user_id` claims,
  signed by our auth service. NEVER from a request body, query param, or header the
  client controls.
- A user may act only within their own `org_id`. There is no "admin sees all orgs"
  path in the API tier.
- Privileged operations (deleting a task list, managing members) require the
  caller's role claim to be `owner` or `admin` for that org.

## 2. Secrets & credentials

- No secrets in source, committed config, logs, or error responses.
- `DATABASE_URL`, `JWT_PUBLIC_KEY`, and integration tokens come from the
  environment / secret manager — never hardcoded, never logged.
- Third-party integration tokens are stored encrypted in the `integrations` table,
  not in plaintext config.

## 3. Tenant / data isolation

- Every SQL query that reads or writes tenant data includes `WHERE org_id = $1`
  bound to the caller's verified `org_id`. A query without an org scope on a
  tenant table is a defect, full stop.
- Object IDs are opaque UUIDs; never trust a client-supplied `task_id` without
  confirming it belongs to the caller's org in the same query.

## 4. Input validation & injection

- Every request body, query param, and path param is parsed by a Zod schema at the
  route boundary before reaching domain logic.
- All SQL uses parameterized queries (`$1`, `$2` …). String-built SQL is forbidden.
- Outbound HTTP (webhooks, integrations) validates the target URL against an
  allowlist — no requests to internal/private IP ranges (SSRF guard).

## 5. Data boundaries

- Tenant data lives only in the primary Postgres database. Analytics events
  emitted to the event pipeline carry `org_id` but no task content or PII.

## 6. Output & error handling

- Error responses return a typed code and safe message — never a raw DB error,
  stack trace, or another org's data.
- An error in an auth or org-scope check denies the request; it never falls through
  to allow.

## 7. Project-specific tripwires

- The `/tasks/:id/share` endpoint must verify the *target* user is in the same org
  before creating a share. A past incident let a task be shared cross-org because
  the share path only checked the *sharer's* org. Never regress this.
