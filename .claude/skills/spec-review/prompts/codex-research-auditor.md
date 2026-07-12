# Codex Industry Research Auditor (file-review mode)

Researches a SPEC FILE against real-world implementations, OSS libraries, and big-company engineering practice. Uses raw `codex exec` with **network access enabled** so Codex can actually search the web and GitHub.

This reviewer does NOT look for defects — that's what the Standard and Adversarial reviewers do. Its job is to **elevate** the spec by grounding it in proven public implementations.

## How to dispatch

Use Bash with `run_in_background: true` (no trailing `&`). You'll be notified when it completes.

```bash
cd <PROJECT_ROOT> && echo '' | codex exec --skip-git-repo-check \
  -m gpt-5.6-sol \
  --config model_reasoning_effort="high" \
  --config service_tier="fast" \
  --sandbox workspace-write \
  --config sandbox_workspace_write.network_access=true \
  --full-auto \
  "Industry-research audit of the spec at <RELATIVE_SPEC_PATH>. Your job is to elevate this spec by grounding it in real-world implementations — NOT to find defects.

Do this in order:
1. Read the spec and identify 3-6 core themes, primitives, or design patterns it introduces.
2. For EACH theme, research the web and GitHub. Find:
   - Maintained OSS libraries that already solve this problem. Prefer libraries with >1k stars, recent commits, and production adoption. Give the repo URL and one-line maturity signal.
   - Public engineering writeups from companies that have shipped this at scale (Stripe, Netflix, Google, Meta, Airbnb, Shopify, Figma, Linear, Vercel, Cloudflare, etc.). Link the blog/RFC/doc.
   - Production gotchas those companies hit that the spec hasn't accounted for. Quote the specific lesson and link the source.
3. For each theme, output:
   - The theme name (one line)
   - 1-3 OSS alternatives with repo URL and why they could replace the spec's custom code
   - 1-3 industry references with URL and the specific pattern worth copying
   - Gotchas/caveats those companies published that apply here
   - A concrete refactor suggestion grounded in what you found (not speculation)
4. If the spec is reinventing a well-maintained primitive, call it out explicitly with severity ELEVATE.
5. If any spec claim contradicts established public best practice, note it with severity CAUTION and link the authoritative source.

Rules:
- Cite URLs for every claim. No citation = drop the claim.
- Prefer primary sources (official docs, engineering blogs, RFCs) over secondary (Medium posts, random tutorials).
- Do not repeat findings that are already obvious defects — that's other reviewers' job. Focus on elevation, not defect-hunting.
- No style feedback. No generic 'consider using a linter.' Only material, sourced suggestions." \
  2>&1 | tee /tmp/codex-spec-research-$$.txt
```

## Rules

- `echo '' |` — prevents stdin hang
- `run_in_background: true` on the Bash tool — **no trailing `&`**
- `2>&1 | tee FILE` — captures output
- `--sandbox workspace-write` + `sandbox_workspace_write.network_access=true` + `service_tier="fast"` — **network access is required**. Research without web access is just the model's training data, which defeats the purpose.
- Relative spec path
- **No JSON templates, no output format examples, no markers in the prompt.** Codex echoes prompts — templates become fake output.

## Reading results

When you get the background completion notification, read `/tmp/codex-spec-research-*.txt` with the Read tool. Parse whatever Codex produced.

## Integration

Findings go into a dedicated **Industry Insights** section of the final report (Step 5c) — NOT mixed with CRITICAL/MAJOR consensus issues. Research suggestions are elevation opportunities, not defects; mixing them dilutes the severity signal.

Two severity tags are meaningful here:
- **ELEVATE** — proven public pattern the spec could adopt. Optional but recommended.
- **CAUTION** — spec contradicts established public best practice. Worth surfacing to the user for a decision.

Neither maps to CRITICAL/MAJOR/MINOR. Present them in their own section.
```

**Leaf-agent scope:** you are a leaf agent — do NOT spawn sub-agents or Workflows; do the work inline and return.
