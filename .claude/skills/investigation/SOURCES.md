# Sources

The grounding channels for an investigation run. Each is a place to find *grounded* facts.
**Prefer primary sources** (official docs, changelogs, source repos, the vendor's own API) over the top
SEO result — agents measurably drift toward content farms otherwise.

**This file is the canonical catalog.** `DEEP-WORKFLOW.md` carries a *delivered digest* of it in the
`SOURCE_TIERS` constant, because a research lane starts cold and never reads this file on its own
(measured 2026-08-18: SOURCES.md reached 2 of 29 generated scripts and 2 of 602 lane transcripts).
**When you edit a row here, update the digest in the same change** — that is the only path by which a row
reaches a lane. Divergence probe:
`grep -c 'hn.algolia.com/api/v1/search\|api.deps.dev\|endoflife.date/api/v1' DEEP-WORKFLOW.md` → 3.

**Pick sources by topic-fit.** Each research lane draws on whichever rows fit its one question — start
primary, widen to the tier that fits *this* question. A version-currency question opens at Currency &
lifecycle; an idioms question at Code & impl; a "does one exist" question at Agent ecosystem. There is no
tier budget and no lean-vs-deep mode: the run is always the Workflow, sized by width.

## Admission bar — adding a source

A source is admissible when it is **primary** (the project / vendor / author / registry, not a recap)
**AND** reachable by **either**:

- **arm A** — a `site:`-scoped WebSearch of a stable, **server-rendered** host; or
- **arm B** — a plain **unauthenticated HTTP GET** that WebFetch itself can hit, returning JSON or
  server-rendered HTML.

**Disqualifier, both arms: a JS-only shell is not admissible.** It returns HTTP 200 with a body that says
"enable JavaScript" and reads to a lane as a real but empty answer. This is not hypothetical — it is what
killed two rows already in this catalog (see the fixes at `hn.algolia` and Sourcegraph below).

Every row carries two required fields beyond the recipe:

- **Hand-hit date** — the day the recipe was actually exercised. This repo has no CI, so the date is the
  only staleness signal a future reader gets.
- **Proven transport** — `WebFetch`, `curl`, or both. **They disagree in both directions**: crates.io
  403s a bare curl and serves WebFetch; api.stackexchange.com serves curl and is refused by WebFetch.
  A row proven on one transport says nothing about the other.

A row that earns zero citations across 10 runs after it is actually delivered gets **deleted**, not
defended. A source no agent reaches is fake coverage.

## Tier: Standards & docs

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| **`llms.txt` / `llms-full.txt`** | `https://<docs-host>/llms.txt` (index) or `/llms-full.txt` (full) — try **FIRST** for any vendor with dev docs | machine-readable, agent-targeted docs map — beats guessing doc URLs | — | WebFetch |
| Official docs | `site:docs.<vendor>.com <topic>` | canonical current behavior — the ground truth | — | both |
| MDN | `site:developer.mozilla.org <topic>` | web-platform standards | — | both |
| RFCs / specs | `site:rfc-editor.org <topic>` | protocol / format ground truth | — | both |
| awesome-* lists | `site:github.com awesome <topic>` | curated landscape of the options | — | both |

## Tier: Code & impl

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| GitHub repo search | `https://api.github.com/search/repositories?q=topic:<topic>+<terms>&sort=updated&order=desc&per_page=5` → `items[].{full_name,pushed_at,archived,stargazers_count}` | prior art **plus** the health tuple (freshness + archived + traction) | 2026-08-18 | WebFetch |
| GitHub code search | `gh search code "<symbol>"` — **Bash + auth only** | real API shapes in the wild | — | Bash/`gh` |
| Stack Overflow | `site:stackoverflow.com <error / topic>` | concrete errors, gotchas, idioms | — | both |
| Sourcegraph | `https://sourcegraph.com/search?q=<symbol>` — **arm A only** (`site:`-scoped search). The web app is a JS shell (200, 7,215 B, body ends "You need to enable JavaScript to run this app") and `.api/search/stream` returns `text/event-stream` at 3.9 MB — **never WebFetch either** | cross-repo usage patterns | 2026-08-18 | WebSearch only |

> **GitHub code search caps** (unchanged, and they bite): default branch ONLY (`branch:` otherwise);
> **login required** — a logged-out not-found is an *access* artifact, and the REST code-search endpoint is
> **401 unauthenticated**; only files <384 KB and the first 500 KB of a file are indexed; forks indexed only
> if they out-star the parent. A no-result is **never** proof a symbol is unused.
> Repo search is **10 req/minute** (separate bucket); `/repos/` lookups eat the **60/hr** core quota.

## Tier: Industry pulse

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| Hacker News | `https://hn.algolia.com/api/v1/search?query=<topic>&tags=story` → JSON `hits[]` | what the field flagged — launches, deprecations, sentiment | 2026-08-18 | WebFetch |
| TLDR | `site:tldr.tech <topic>` | newsletter-level signal | — | WebSearch |
| Lobsters / dev.to / changelog.com | `site:lobste.rs <topic>`, `site:dev.to <topic>`, `site:changelog.com <topic>` | higher-signal discussion, release commentary | — | WebSearch |

> The old `https://hn.algolia.com/?q=<topic>` row was a **JS shell** — 200 at 2,383 B whose entire body is
> "This page will only work with JavaScript enabled". It is why the Industry-pulse tier showed ~0 citations.

## Tier: Agent ecosystem — MCP servers, skills, plugins

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| Official MCP Registry | `https://registry.modelcontextprotocol.io/v0/servers?search=<q>&version=latest&limit=10` | does an MCP server exist for X, is it current, where does it live | 2026-08-18 | WebFetch |
| Smithery | `https://registry.smithery.ai/servers?q=<q>&pageSize=10` → `useCount`, `verified`, `inactive` | the only cross-registry adoption number + an abandonment flag | 2026-08-18 | WebFetch |
| Glama | `https://glama.ai/api/mcp/v1/servers?query=<q>&first=10` | breadth of MCP discovery | 2026-08-18 | WebFetch |
| skills.sh | `https://skills.sh/api/search?q=<q>` → `skills[].{id,name,installs,source}` | which agent skills already exist, with install counts | 2026-08-18 | WebFetch |
| Plugin marketplaces | `https://raw.githubusercontent.com/<owner>/<repo>/main/.claude-plugin/marketplace.json` — anchors: `anthropics/claude-plugins-official` (286 plugins), `anthropics/claude-code` | plugin prior art | 2026-08-18 | WebFetch |
| GitHub topics (health backstop) | `?q=topic:mcp-server` (24,769) · `topic:claude-skills` (7,108) · `topic:claude-code-plugin` (5,309) | the freshness/archived signal no dedicated registry carries | 2026-08-18 | WebFetch |

> **`?version=latest` is not optional** — without it the registry's default listing returns rows with
> `isLatest:false` (the `?limit=1` head row on 2026-08-18 was a stale 2026-04-13 version reading as current).
> **Smithery's keyless 200 and skills.sh `/api/search` are UNDOCUMENTED** (vendor docs say bearer-gated;
> skills.sh self-labels `"searchVersion":"legacy"` while every `/api/v1/*` route returns 401) — **dated
> re-check rows, not stable ones.** Glama carries no date/version/count field: discovery only, never a
> currency claim — join `repository.url` to `api.github.com/repos` for `pushed_at`/`archived`.
> Marketplace manifests are awesome-lists in disguise: no dates, no health field, a dead upstream stays
> listed forever. `claude plugin marketplace` has **no search verb**.

## Tier: Community & discussion

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| Discourse forums | detect `https://<host>/site.json`; then `https://<host>/search.json?q=<terms>+order%3Alatest+after%3A<YYYY-MM-DD>`; body at `/t/<id>.json`. Host guess-loop: `community.` / `discuss.` / `forum.` + domain | real error text, maintainer answers, current-version pain that never reaches docs | 2026-08-18 | WebFetch |
| GitHub Discussions | `https://github.com/<owner>/<repo>/discussions?discussions_q=<query>`; global `https://github.com/search?q=<query>&type=discussions`. Qualifiers inside `q=`: `repo:`, `is:answered`, `updated:>YYYY-MM-DD` | design debates and maintainer rationale that never become issues | 2026-08-18 | WebFetch |
| Conference talks | InfoQ `https://www.infoq.com/presentations/<slug>/` (**arrive only via a WebSearch result URL**); USENIX `https://www.usenix.org/conference/<nsdi26\|osdi26\|atc26\|fast26\|sec26>/technical-sessions` | what practitioners say about *operating* a system | 2026-08-18 | WebFetch |
| Podcast transcripts | `https://itunes.apple.com/search?media=podcast&term=<terms>&limit=3` → `feedUrl`; find `<podcast:transcript type="text/html" url="...">` and GET that URL | long-form practitioner reasoning, keyless end to end | 2026-08-18 | WebFetch |

> **`order:latest` is load-bearing.** Without it Discourse returns *relevance* order and buries this
> month's threads under 2022's — fatal for a version-currency question.
> A quoted phrase or stacked operators returns **200 with every array empty**, indistinguishable from
> absence: retry loosened before claiming a source is silent. A WAF 403 on `/site.json` means
> *inconclusive*, not "not a forum". Anonymous limit 50 req/10s. `/t/<id>.json` returns only the first ~20
> posts. No `search.rss` exists.
> **A `repo:` Discussions query returning 0 may mean Discussions are DISABLED**, not that nothing matched —
> confirm by fetching `/<owner>/<repo>/discussions` directly. There is no `discussions.atom` (404, unlike
> `releases.atom`) and GraphQL is POST+token, so the HTML pages are the only keyless surface.
> **InfoQ's 404 is a 120,840-byte soft page** that reads as a real article to anything judging by length —
> never construct an InfoQ slug. Podcast feeds run 6–9 MB (truncated by WebFetch) and most carry **zero**
> `podcast:transcript` tags; prefer the per-episode transcript page.

## Tier: Currency & lifecycle

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| endoflife.date v1 | `https://endoflife.date/api/v1/products/<product>` → `releases[].{isEol,eolFrom,isMaintained,latest}` + envelope `generated_at` / `last_modified`. Ids: `/api/all.json` (464) | when a version dies **and** how stale that answer is | 2026-08-18 | WebFetch |
| GitHub Releases | stable: `https://api.github.com/repos/<o>/<r>/releases/latest` → `tag_name`, `published_at`. Quota-free: `https://github.com/<o>/<r>/releases.atom` | current version; is the project still shipping | 2026-08-18 | WebFetch |
| Statuspage JSON | `https://status.<vendor>/api/v2/summary.json` → `page.updated_at`, `status.indicator`, `components[]`. Cheaper: `/api/v2/status.json` (215 B) | live operational state, incident history | 2026-08-18 | WebFetch |
| Raw CHANGELOG.md | `https://raw.githubusercontent.com/<o>/<r>/<main\|master\|canary>/CHANGELOG.md` | narrative change notes for feed-less vendors; no quota, no auth | 2026-08-18 | WebFetch |

> **Use v1, never the legacy `/api/<product>.json`** — v0 is still live but carries no `generated_at` and no
> `last_modified`, so its staleness is unmeasurable.
> `/releases/latest` is the **only** surface with non-prerelease, non-draft semantics: tags return alphas,
> the plain `/releases` list is `created_at`-ordered not semver-ordered, and `releases.atom` applies no
> prerelease filter (next.js led with a canary while stable was v16.3.1). `api.github.com` is **60 req/hr per
> shared egress IP** — measured 0 remaining mid-session on 2026-08-18, after which catalogued recipes
> returned 403. **That 403 is the quota, not the endpoint.** The atom feed and raw.githubusercontent are
> unmetered.
> **The `/api/v2/` Statuspage shape is not universal** — Stripe `/current`, Google Cloud `/incidents.json`,
> AWS `public/currentevents` (UTF-16), Azure RSS-only, Instatus does not answer `/summary.json`. Host
> discovery by convention hit 8/10 vendors and **both failures returned 200 with HTML** — validate on
> content-type. Cross-host hops WebFetch will not follow: `status.anthropic.com`→`status.claude.com`,
> `status.slack.com`→`slack-status.com`, `status.vercel.com`→`www.vercel-status.com`.
> **WebFetch truncates HEAD-FIRST** with a literal `[Content truncated due to length...]` marker: a 521,601 B
> CHANGELOG delivered only the newest ~30 entries. Newest-first (Keep-a-Changelog) files survive truncation;
> oldest-first files lose the answer entirely.

## Tier: Registries & health

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| **deps.dev v3** | `https://api.deps.dev/v3/systems/<npm\|pypi\|cargo\|maven\|go\|nuget\|rubygems>/packages/<name>/versions/<version>` → `isDeprecated`, `deprecatedReason`, `advisoryKeys[]`, `publishedAt`, `licenses` | **one keyless GET** answers deprecated / vulnerable / published-when across **seven** ecosystems — and it is the GET-shaped replacement for OSV's POST-only query API | 2026-08-18 | WebFetch |
| npm | `https://registry.npmjs.org/<pkg>/latest` → `version`, `deprecated` (absent when healthy), `repository.url`. Downloads: `https://api.npmjs.org/downloads/point/last-week/<pkg>` | npm currency, deprecation prose, upstream pointer | 2026-08-18 | WebFetch |
| PyPI | `https://pypi.org/pypi/<pkg>/<version>/json` → `info.{version,yanked,yanked_reason,requires_python}` | Python currency, per-release yank status | 2026-08-18 | WebFetch |
| crates.io | `https://crates.io/api/v1/crates/<crate>` → `crate.max_stable_version`, `recent_downloads`; per-version `yanked`, `rust_version` (MSRV) | Rust currency, MSRV | 2026-08-18 | WebFetch |
| Go | `https://proxy.golang.org/<module>/@latest` (187 B) → `Version`, `Time`; docs `https://pkg.go.dev/<module>`; vulns `https://vuln.go.dev/ID/GO-YYYY-NNNN.json` | Go currency, importer counts, deprecation banners | 2026-08-18 | WebFetch |
| Maven Central | `https://repo1.maven.org/maven2/<group-with-slashes>/<artifact>/maven-metadata.xml` → `<release>`, `<lastUpdated>` | authoritative JVM version currency | 2026-08-18 | WebFetch |
| NuGet / RubyGems | `https://azuresearch-usnc.nuget.org/query?q=packageid:<id>&prerelease=false` → `data[0].{version,deprecation}` · `https://rubygems.org/api/v1/gems/<gem>.json` → `version`, `yanked`, `source_code_uri` | .NET and Ruby currency, deprecation, downloads | 2026-08-18 | WebFetch |
| Docker Hub | `https://hub.docker.com/v2/repositories/<ns>/<repo>/tags?page_size=3` (`ns=library` for official) | container image currency | 2026-08-18 | WebFetch |
| GitHub Advisory DB | `https://api.github.com/advisories?ecosystem=<eco>&affects=<pkg>&per_page=5` → `ghsa_id`, `severity`, `vulnerable_version_range`, `first_patched_version` | CVE/GHSA by package, keyless | 2026-08-18 | WebFetch (quota-shadowed) |
| Snyk (key-free fallback) | `https://security.snyk.io/package/<eco>/<pkg>` — server-rendered | vulnerability roll-up + health score without a key | 2026-08-18 | WebFetch |

> **Never fetch a bare packument.** `registry.npmjs.org/express` is 804,975 B and WebFetch's truncated read
> reported express as **DEPRECATED** — harvested from 0.x entries. Always pin: `/latest` is 3,508 B.
> Same asymmetry: PyPI 11,872 B pinned vs 192,973 B; deps.dev 969 B vs 56,377 B.
> **crates.io is an INVERTED TRANSPORT TRAP** — 403s a bare curl with an API-policy body, but serves
> WebFetch and a curl with a contact UA. Never mark it dead on a curl 403. Use `max_stable_version`, not
> `newest_version`.
> **`search.maven.org` is ~4 MONTHS STALE** — it reported guava 33.4.8-jre (April 2025) while
> `maven-metadata.xml` reported `<release>33.7.1-jre</release>`. A currency question answered from the
> search tier is answered wrong, silently.
> NuGet's flat-container index **includes prereleases** (`versions[-1]` for Newtonsoft.Json is a beta).
> Maven coordinates encode `:` as `%3A`; Go module paths encode `/` as `%2F` and lowercase capitals with
> `!`-escaping (`gitHub` → `git!hub`). PyPI has **no package-level deprecated flag** — absence of `yanked`
> is not evidence of maintenance.

## Tier: Structured knowledge & comparison

| Source | Query it with | Best for | Hit | Transport |
|--------|---------------|----------|-----|-----------|
| Wikipedia / Wikidata | summary `https://en.wikipedia.org/api/rest_v1/page/summary/<Title>` → `extract`, `revision`, `timestamp`; search `/w/api.php?action=query&list=search&srsearch=<q>&format=json`; Wikidata: resolve QID via `action=wbsearchentities` **first**, then `https://query.wikidata.org/sparql?format=json&query=<sparql>` | neutral dated definition, canonical naming, CC0 structured facts | 2026-08-18 | WebFetch |
| Standards pipelines | W3C `https://api.w3.org/specifications/<shortname>/versions/latest?format=json` · TC39 `https://raw.githubusercontent.com/tc39/proposals/main/README.md` · IETF `https://datatracker.ietf.org/api/v1/doc/document/?name__startswith=draft-ietf-<wg>&format=json&limit=5` · IANA `https://www.iana.org/assignments/<registry>/<registry>.xhtml` | is this shipped, a draft, or a stage-2 proposal — what the RFC row cannot see | 2026-08-18 | WebFetch |
| Web-platform availability | `https://api.webstatus.dev/v1/features?q=<feature>&page_size=3` → `baseline.status`, per-browser `{status,version,date}` · `https://chromestatus.com/api/v0/features?q=<free text>&num=3` | "can I use this yet", with every fact dated | 2026-08-18 | WebFetch |
| Pricing & leaderboards | `https://openrouter.ai/api/v1/models` → per-model `pricing`, `context_length`, `knowledge_cutoff` · `https://prices.azure.com/api/retail/prices?$filter=<odata>&$top=5` · HF `https://datasets-server.huggingface.co/rows?dataset=<enc>&config=default&split=train&length=5` | real numbers with dates instead of a marketing page | 2026-08-18 | WebFetch |
| arXiv | `site:arxiv.org <topic>` | novel algorithms, primary research — reach for it on genuinely novel/algorithmic questions | — | WebSearch |

> **Two-step entity resolution is the general pattern here.** A SPARQL query against a *guessed* QID returns
> an empty `bindings` array indistinguishable from a genuine absence — the same silent-zero class as a
> `site:` miss. Resolve the identifier first (`wbsearchentities` → QID; api.w3.org listing → shortname;
> datasets-server `/splits` → config+split), then query.
> `www.w3.org/TR/tr.json` returns **HTTP 300** and is not JSON; the machine-readable index is `api.w3.org`.
> chromestatus prefixes its body with the XSSI guard `)]}'` so a naive `JSON.parse` fails, and it rejects
> `field:"value"` syntax with 400 — free-text `q` only.
> **openrouter's full list is 675,700 B** — far past one WebFetch window; narrow to one model, never ask for
> a cross-model comparison in one call. HF `/filter` and `/search` fail on lazy indexing; only `/rows` is
> reliable. Wikipedia is CC BY-SA (attribute if quoted); Wikidata is CC0.

## DEAD CHANNELS — do not spend a retry

Recorded so no future lane re-derives them. **Each row names the transport that produced the status** —
different transports give different answers, and conflating them is how a live channel gets condemned.

| Channel | Status | Transport that produced it | Substitute |
|---------|--------|---------------------------|------------|
| **Reddit** (all routes) | "unable to fetch" (harness denylist, not an HTTP status); `/search.json` 403 + 189,908 B HTML; r.jina.ai relays Reddit's own block page; api.pullpush.io 429 | WebFetch (denylist) · browser-UA curl (403) · WebSearch returned **zero** reddit.com URLs scoped *or* unscoped | Discourse forums + GitHub Discussions |
| **OSV query API** | `GET /v1/query` → **405** ("http method is not allowed"); `/v1/querybatch` likewise | curl + WebFetch | deps.dev `advisoryKeys` or GitHub Advisory DB. Only `/v1/vulns/<id>` is GET-able — and needs the id you were looking for. Bulk zips are GET-able at **219 MB**: never from a lane |
| **web.archive.org** | globally refused by this harness (24 hits). Note `/wayback/available` returns **404 to curl** — a different predicate from the harness refusal | WebFetch (refusal) · curl (404) | none — the standard dead-page recovery move does not exist here |
| **GHCR** | `/v2/.../tags/list` 401; the anonymous token from `ghcr.io/token` must be spent as an `Authorization` header on a **second** request, which WebFetch cannot set | WebFetch | Docker Hub |
| **PulseMCP** | 410, with a randomized 1%→100% sunset running through Sept 2026 — so a **dead channel reads as flakiness** | WebFetch | official MCP registry, Smithery, Glama |
| **mcp.so / mcpservers.org / mcpmarket.com** | SPA shells and 403 | WebFetch | as above |
| **Socket.dev · Snyk REST API · Artificial Analysis · GCP Billing** | 401 / 403 — keys required | WebFetch | deps.dev, security.snyk.io HTML page |
| **openai.com/api/pricing** | **hard 403 to BOTH** — not a WebFetch limitation | WebFetch **and** curl | openrouter `/api/v1/models` |
| **StackShare** | 429 | WebFetch | — |
| **swebench.com** | 4.19 MB JS shell | WebFetch | the `swe-bench/experiments` repo |
| **YouTube transcripts** | silent empty body | WebFetch | InfoQ / USENIX / podcast transcript pages |
| **Libraries.io** | inverts the credential rule — **no** key returns 200, an **invalid** key returns 403 — and `x-ratelimit-limit` is 10, too tight for a fan-out | curl | deps.dev |
| **Google Scholar · Papers with Code** | deleted from this catalog 2026-08-18: **zero** events of any kind corpus-wide (0 queries, 0 fetches, 0 citations across 155 briefs); Scholar's recipe was a bot-blocked bare URL | — | arXiv |

## Search gotchas — these silently un-ground a brief

- **Never pass `allowed_domains` / `blocked_domains` to WebSearch — put the host in the query as
  `site:<host>`.** This is **52 of 52** of all WebSearch hard failures in the corpus. The observed failure
  form is an unquoted bareword (64 of 78 occurrences, 0 well-formed) →
  `InputValidationError: WebSearch was called with input that could not be parsed as JSON`.
- **Never guess a `raw.githubusercontent.com` path** — 51 of 211 WebFetch 404s are guessed raw paths. List
  the tree first (`gh api /repos/<o>/<r>/contents/<dir>`).
- **A `site:` miss is inconclusive, not absence.** `site:` doesn't rank and may omit indexed URLs — retry
  the query unscoped before concluding "no docs exist". (Measured: 0 of 2,922 search payloads returned
  empty links, including all 78 containing a `site:` operator — a silent `site:` failure is *not* the
  problem; not searching is.)
- **WebFetch and redirects.** It *returns* a **cross-host** redirect's new URL instead of following it —
  re-issue WebFetch on the target (100 occurrences). A **same-host** trailing-slash 301 can be wrongly
  rejected ("Redirect not allowed") — retry **with** the trailing slash. It cannot render JS-only pages: a
  near-empty SPA-docs fetch is a tooling limit, not missing content.
- **WebFetch truncates HEAD-FIRST**, with a literal `[Content truncated due to length...]` marker. Prefer
  the smallest document that answers the question — pin the version, use `/latest`, use `/api/v2/status.json`
  over `summary.json`.
- **WebSearch's "US-only" note is a false geo-restriction.** It works fine outside the US — never let that
  note deter or deprioritize a grounding search.
- **Date-check fast-moving facts.** Prefer an endpoint that carries its **own** freshness field, so a claim
  reads "current as of `<timestamp from the payload>`" rather than "as of my fetch": endoflife.date v1
  `generated_at`, Statuspage `page.updated_at`, Wikipedia REST `revision`+`timestamp`, GitHub releases
  `published_at`.
