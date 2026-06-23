# Test Infrastructure Detector

Scans the project for existing test setup AND runtime/infrastructure divergence points so the generated plan tests against realistic production conditions, not local mocks.

**Agent type:** `Explore` | **Model:** default (sonnet)

```
description: "Detect test infrastructure, conventions, AND production runtime divergence"
prompt: |
  Scan this project for ALL test infrastructure AND production runtime boundaries.
  Report exactly what exists — and where local dev diverges from prod.

  Project root: {{PROJECT_ROOT}}

  ## Part A: Test Infrastructure

  1. **Test config files**: playwright.config.*, vitest.config.*, jest.config.*,
     pytest.ini, pyproject.toml [tool.pytest], bun test config, etc.

  2. **Test directories**: tests/, __tests__/, e2e/, test/, spec/
     List with file counts.

  3. **Test utilities**: fixtures, factories, helpers, page objects, test data seeders.
     List file paths.

  4. **CI/CD**: .github/workflows/, cloudbuild.yaml, etc.
     How are tests run in CI? Which tiers? What commands? Which test modules are imported into the gated entrypoint (e.g., a single release-gate test module)?

  5. **E2E patterns**: Playwright page objects, browser setup, auth helpers,
     Chrome extension test patterns.

  6. **Test runner + assertion library**: what's used per language/tier.

  7. **Naming conventions**: test file naming, test function naming, describe block style.

  ## Part B: Production Runtime Divergence (CRITICAL for blast-radius)

  Probe every boundary where local dev differs from production. These divergences
  are where bugs hide. For each, report current config and flag divergence risks.

  1. **Storage backend**
     - Local: FileSystemStorage? In-memory mocks? Empty MEDIA_ROOT?
     - Prod: S3? GCS? Which bucket? What credentials? Signed URL mechanism (mounted SA key vs cloud-IAM credential signing vs pre-signed)?
     - Divergence risk: `os.path.exists` and similar paths work locally but not on cloud object storage.
     - Check: `DEFAULT_FILE_STORAGE`, `STATICFILES_STORAGE`, `GS_*` / `AWS_*` settings.

  2. **Cloud runtime**
     - Local: Django dev server? `bun dev`? Hot-reload? Single-process?
     - Prod: serverless container? Function? Managed compute? K8s?
     - Cold-start characteristics (function layers, warm-min-instances)?
     - Ephemeral vs persistent filesystem (function `/tmp` is small + ephemeral, container is in-memory)?
     - Concurrent request model: single-threaded per pod (function) vs multi-threaded (container default)?
     - Check: deployment manifests (`cloudbuild.yaml`, `cdk.ts`, `serverless.yml`, `fly.toml`), `Dockerfile`.

  3. **IAM / credentials**
     - Local: .env file? mounted key? hardcoded placeholder?
     - Prod: metadata server? Secret Manager? KMS? IAM role?
     - Propagation delays: IAM grants on some clouds can take several minutes to propagate — does the readiness probe handle this?
     - Check: `GOOGLE_APPLICATION_CREDENTIALS`, IAM bindings in Terraform / CDK, secret-manager calls.

  4. **Dependencies & version pins**
     - Scan `requirements.txt`, `package.json`, `Gemfile.lock`, `go.mod` for pinned versions.
     - For every library the spec assumes a feature of (e.g., a storage library that needs a minimum version for cloud-IAM credential signing), verify the pin supports it.
     - Flag upgrades between local dev state and what prod CI builds.

  5. **Database / connection pooling**
     - Local: SQLite? Local Postgres? No connection limit?
     - Prod: Cloud SQL? RDS? Aurora? max_connections?
     - `CONN_MAX_AGE`, pool size, pgbouncer configured?
     - Divergence risk: local tests never stress connection limits; prod 200 concurrent requests can exhaust 300 max_connections.

  6. **Secrets & rotation**
     - Where are secrets stored (env file, Secret Manager, KMS)?
     - Is there a rotation window (SECRET_KEY can cause session MAC failures during rotation)?
     - Are ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS set from env vars? What's the default if they drop?

  7. **Observability**
     - Logging library (structlog, django.util.logging, winston, etc.)?
     - Log levels per event class — is there a style guide?
     - Alerting thresholds (ERROR log count per minute)?
     - Is there a known noise source (bot scanners) already consuming the ERROR budget?

  8. **Consumers of this codebase's APIs**
     - Is there a mobile app (iOS/Android) consuming the API? Which serializers does it parse?
     - Are there partner webhooks? Downstream cron jobs? ETL pipelines?
     - Any contract test suite (Pact, schema snapshot)?

  9. **Tenant / org model**
     - Multi-tenant? Per-tenant config tables? Per-tenant integrations?
     - What's the test org setup — single happy-path org, or multiple variants?
     - Are there "missing-integration" test orgs (e.g., org without OAuth, org without SMS)?

  10. **Known production failure modes**
      - Scan `docs/specs/`, `docs/plans/`, CHANGELOG, recent
        commit messages for prior reliability post-mortems, incident reports, adversarial
        failure modes.
      - If a prior spec-test-plan documents ADV failure modes, surface them so the new
        plan can reuse / extend them.

  ## Output

  ```
  ## Test Infrastructure Report

  ### Runners
  - Unit: <runner> (e.g., bun test, pytest, vitest)
  - Integration: <runner>
  - Chain: <runner or N/A>
  - Deploy validation: <commands / health probes>
  - E2E: <runner> (Playwright / Chrome / both)

  ### Directories
  - <path>: <count> files, <purpose>

  ### Utilities
  - <path>: <what it provides>

  ### CI Commands
  - Unit: <command>
  - Integration: <command>
  - E2E: <command>
  - Which test module gates merge (e.g., only one release-gate module runs in CI)?

  ### Conventions
  - File naming: <pattern>
  - Function naming: <pattern>
  - Assertion style: <library/pattern>

  ## Production Runtime Report

  ### Storage
  - Local: <config>
  - Prod: <backend, bucket, credential mechanism>
  - Divergence risk: <list>

  ### Runtime
  - Local: <dev server>
  - Prod: <serverless container / function / etc>
  - Cold start: <yes/no, mitigation>
  - Concurrency model: <per-pod, per-request>

  ### IAM & Secrets
  - Credentials mechanism: <env / SA key / metadata server / Secret Manager>
  - Rotation: <yes/no, window>
  - Propagation delays: <list>

  ### Dependencies (pinned versions supporting spec)
  - <library>: <version> — supports feature X: yes/no/unverified

  ### DB
  - Connection pooling: <config>
  - max_connections: <value>
  - Known saturation point: <if any>

  ### Observability
  - Log library: <name>
  - Log-level style: <per class>
  - ERROR budget / baseline noise: <rate>

  ### Consumers (API contracts)
  - Mobile: <platforms, decoder library, serializers consumed>
  - Partners: <webhooks>
  - Downstream jobs: <crons, ETL>

  ### Tenancy
  - Single / multi-tenant: <answer>
  - Test org variants available: <list>

  ### Prior Failure Modes (from past specs/plans)
  - <list with source refs>
  ```
```
