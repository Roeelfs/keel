# Security Policy — {{PROJECT_NAME}}

> This is the rulebook the `security-miner` (in `spec-review`) and the
> `security-reviewer` agent audit against. Fill it with the rules that are TRUE
> for your system and DELETE the ones that aren't. Every rule should be specific
> enough that a reviewer can cite it and point at a concrete violation — vague
> aspirations ("be secure") give reviewers nothing to check.
>
> The reviewers cite this file by rule. If a rule isn't here (or in `CLAUDE.md`),
> they fall back to generic categories and flag it as "policy gap: undocumented".

## 1. Authentication & authorization

- {{Where authorization claims come from — e.g. "authz is derived from
  `<trusted, server-controlled claim>`, NEVER from `<user-editable field>`."}}
- {{Least privilege — e.g. "service X may read tables A, B only; no write to C."}}
- {{Which roles may call which privileged operations; what anonymous/unauthenticated
  callers may NOT reach.}}

## 2. Secrets & credentials

- No secrets in source, config committed to git, logs, error messages, or client
  bundles.
- Secrets are stored in {{your secret store / manager}}. {{Any rule about which
  store holds which kind of credential — e.g. "third-party integration tokens live
  in `<store>`, never `<other store>`."}}
- {{Key rotation / expiry expectations, if any.}}

## 3. Tenant / data isolation

- {{The isolation rule — e.g. "every query and mutation is scoped to the caller's
  `org_id`; no code path returns rows the caller doesn't own."}}
- {{How isolation is enforced — row-level policies, an enforced query layer, object
  ACLs — and what would constitute a bypass.}}

## 4. Input validation & injection

- Untrusted input ({{request bodies, query params, webhook payloads, file
  uploads, third-party API responses}}) is validated at the boundary before use.
- Guard the sinks: {{SQL / parameterized queries only, no string-built queries}};
  no shelling out with unsanitized input; path inputs are confined (no traversal);
  outbound URLs are validated (no SSRF to internal ranges).

## 5. Data boundaries

- {{Which data may live in which store, and what must NOT cross between them —
  e.g. "PII lives only in `<store>`; analytics events carry no PII."}}
- {{Encryption at rest / in transit requirements, if applicable.}}

## 6. Output & error handling

- Responses, errors, and logs never leak secrets, credentials, internal IDs the
  caller shouldn't see, or another tenant's data.
- Failures deny by default — an error in an auth/permission check denies access, it
  doesn't fall through to allow.

## 7. Project-specific tripwires

- {{Anything unusual that has bitten you and must never recur. These are the
  highest-value rules — they encode real incidents. e.g. "the `<X>` endpoint must
  never be exposed without `<Y>` check."}}
