# Testing Config — {{PROJECT_NAME}}

> The `spec-test-plan` and `spec-test-execute` skills read this file to learn **how
> to run real tests in THIS project**. Their whole philosophy is E2E-first: prove a
> feature works the way a customer experiences it, on real staging, not just in
> unit tests. To do that they need your project's actual commands, URLs, and
> accounts. Fill this in. If it's missing, the skills fall back to inferring from
> the codebase and will tell you to create it.
>
> Copy this to `docs/testing-config.md` (or wherever your `CLAUDE.md` points) and
> keep it accurate — it's the source of truth for "how do I actually verify here".

## Commands

| Purpose | Command |
|---------|---------|
| Unit / integration tests | `{{TEST_CMD}}` |
| Run a single test file | `{{SINGLE_TEST_CMD e.g. npx vitest run path/to.test.ts}}` |
| Typecheck | `{{TYPECHECK_CMD}}` |
| Lint | `{{LINT_CMD}}` |
| Deploy to staging | `{{DEPLOY_STAGING_CMD — or "N/A, staging auto-deploys on push to <branch>"}}` |
| Run the E2E suite | `{{E2E_CMD}}` |
| Tail staging logs | `{{LOGS_CMD — how to read real logs after exercising a feature}}` |

> Run heavy commands (tests, builds) under `with-heavy-lock` when multiple agent
> sessions are active, so they queue instead of overloading the machine.

## Staging environment

- **Staging URL(s):** {{https://staging.example.com — UI, API base, etc.}}
- **How a deploy reaches staging:** {{push to `<branch>` / run `<cmd>` / CI job}}
- **How long a deploy takes:** {{~N min — so the skill knows how long to wait}}

## Test accounts & data

- **Test org / tenant:** {{e.g. `acme-e2e` — the dedicated org E2E runs against}}
- **Test user(s):** {{login(s) the E2E flow uses; where the credentials come from}}
- **Seed / fixtures:** {{how to get the system into a known state, if needed}}

## Observing success (how you KNOW it worked)

For a real feature, name the concrete signal the test should assert on:
- **UI surface:** {{which screen/selector shows the result}}
- **Log line:** {{the exact log string that proves the path ran}}
- **Data result:** {{the row/record/automation result that should appear}}
- **External effect:** {{the message/email/webhook/file the system should produce}}

## Known limitations / blocking dependencies

- {{Things that genuinely need human setup — third-party dashboard credentials,
  hardware, a paid sandbox — that the agent cannot provision itself. List them so
  the skill marks them BLOCKED instead of guessing.}}
- {{Anything that can't be tested on staging and why.}}
