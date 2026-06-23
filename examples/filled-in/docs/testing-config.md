# Testing Config — Acme Tasks API

> How to run real tests in THIS project. The `spec-test-*` skills read this.

## Commands

| Purpose | Command |
|---------|---------|
| Unit / integration tests | `pnpm test` |
| Run a single test file | `npx vitest run src/routes/sharing/share.test.ts` |
| Typecheck | `pnpm typecheck` |
| Lint | `pnpm lint` |
| Deploy to staging | auto-deploys on push to `main` (CI job `deploy-staging`, ~4 min) |
| Run the E2E suite | `pnpm e2e --env staging` |
| Tail staging logs | `acme logs --env staging --service api --since 5m` |

Run heavy commands under `with-heavy-lock` when multiple agent sessions are active.

## Staging environment

- **API base:** `https://api.staging.acme-tasks.example.com`
- **How a deploy reaches staging:** push to `main` → CI `deploy-staging` job.
- **How long a deploy takes:** ~4 minutes from green CI to live.

## Test accounts & data

- **Test org:** `acme-e2e` (a dedicated org that exists only on staging).
- **Test users:** `owner@acme-e2e.test` and `member@acme-e2e.test`; credentials in
  the CI secret `E2E_CREDS` (and in 1Password vault "Acme E2E" for local runs).
- **Seed:** `pnpm e2e:seed --env staging` resets the test org to a known state.

## Observing success

- **API result:** `POST /tasks/:id/share` returns `201` and the share appears in
  `GET /tasks/:id/shares`.
- **Log line:** `task.shared org=acme-e2e task=<id> target=<user>` in the api
  service logs.
- **Isolation check:** a request from a *different* test org for the same task ID
  returns `404` (not `403` — we don't confirm existence across orgs).

## Known limitations / blocking dependencies

- The Slack-integration share path needs a real Slack workspace token; staging has
  one wired for `acme-e2e` only. Tests outside that org mark the Slack leg BLOCKED.
- Email delivery on staging goes to a catch-all inbox; assert on the outbound
  webhook, not on a real inbox.
