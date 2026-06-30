---
name: work-report
description: Use when generating development reports, calculating billable hours, reviewing work done in a period, or when the user asks for a project status summary. Triggers on keywords like report, billable, hours, invoice, timesheet, work summary.
---

# Work Report Generator

Generate customer-facing and internal development reports with data-driven billable hours.

## Output Structure

```
~/code/work-reports/{project-name}/
  customer/
    YYYY-MM-DD-report.html          # Polished HTML for the customer
  internal/
    YYYY-MM-DD-report.md            # Full data + insights
    YYYY-MM-DD-report.html          # Internal HTML summary
    YYYY-MM-DD-extracted-data.json   # Raw extraction output
```

## Workflow

### Step 1: Extract Data

Run the extraction script to query all data sources:

```bash
python3 ~/.claude/skills/work-report/extract-data.py \
  --project /path/to/project \
  --since YYYY-MM-DD \
  --until YYYY-MM-DD \
  --output ~/code/work-reports/{project}/internal/YYYY-MM-DD-extracted-data.json
```

This queries:
- **OpenCode SQLite** (`~/.local/share/opencode/opencode.db`) — sessions, user messages, screenshots, message lengths
- **Claude Code JSONL** (`~/.claude/projects/`) — sessions, user messages, screenshots
- **Git** (all repos + submodules) — commits, LOC, types, per-day breakdown

### Step 2: Analyze Git History for Features

The extraction script gives you commits grouped by day. You must now:

1. **Read all commit messages** in the extracted data
2. **Group commits into logical features** (F1, F2, ...) by analyzing:
   - Conventional commit prefixes (feat, fix, refactor, docs, etc.)
   - Related subject areas (same module, same feature area)
   - Temporal clustering (commits on same day touching same area)
3. **For each feature**, summarize:
   - Feature name and date range
   - Bullet list of what was built/changed
   - Commit count and approximate LOC
4. **Read key source files** to verify feature descriptions are accurate (never trust commit messages alone)

### Step 3: Calculate Billable Hours

The extraction script uses the **streak-continuity model** (as of April 2026).

**Per streak** (a sequence of messages with no gap >30 min):
```
1. Compute gap_sum_min using bucket credits:
   gap < 30s:     0 min    (automated/system message)
   gap 30s-2m:    1.0 min  (quick approval while watching)
   gap 2m-10m:    2.5 min  (reviewing AI output, deciding)
   gap 10m-30m:   7.0 min  (manual testing, UI inspection, config)
   gap 30m-2h:    4.0 min  (context switch back after break)

2. Compute wall_clock_min = last_msg_ts - first_msg_ts of streak

3. If streak qualifies (≥3 messages AND ≥10 min wall-clock):
       credit = max(gap_sum_min, wall_clock_min × 0.70)
   Otherwise:
       credit = gap_sum_min

Total = Σ(streak credits across OpenCode + Claude Code) × 1.05
                                                          ^^^^
                                      5% overhead for off-keyboard
                                      planning/review time not in streaks
```

**Why streak-continuity?**

Gap-based alone under-credits sustained focus. Ten messages every 5 min for 45 min = gap sum of ~18 min, but wall-clock was 45 min of dedicated work. The streak model credits the wall-clock when activity is sustained.

**Parallel-work safety:**

Each streak breaks on a 30+ min gap. Gaps that span other projects break the streak — they won't get wall-clock credit. The formula is credit-biased toward the project with continuous activity.

**70% utilization factor:**

Within a qualifying streak, 70% of wall-clock is credited. The 30% allowance covers short breaks, context switches within the project, reading long AI responses, and brief checks on other work. This matches the implicit utilization in the gap buckets (10-30m gap = 7 min credit ≈ 23% utilization).

**5% overhead:**

On top of streak hours, 5% is added for:
- Daily startup/context loading
- Out-of-band 3rd party config (dashboards, cloud consoles)
- Off-keyboard planning and review not captured by streaks

**Calibration history:**
- Phase 1 (Mar 1-13) gap formula: 37.38h raw → 42.5h actual (10% overhead used then)
- April 2026 recalibration: bucket credits bumped, streak-continuity added, overhead reduced to 5%

### Step 4: Generate Customer Report

Create the HTML report at `customer/YYYY-MM-DD-report.html`.

**Required sections:**
1. **Header**: Project name, report date, period, developer name
2. **Executive Summary**: 1-2 sentences + 4 stat cards (commits, LOC added, work days, billable hours)
3. **Per-Day Breakdown**: Table with date, day#, commits, LOC +/-, hours, key work description
4. **Repository Breakdown**: Card per repo with commits, files changed, insertions, deletions, net LOC
5. **Verification Results**: If E2E or test results exist in evidence files, show pass/fail cards
6. **Features Developed**: One card per feature with bullet list + commit/LOC stats
7. **Hours Methodology**: Brief explanation of gap-based formula

**Design rules** (match your existing customer-report style, if you have one):
- Font: Inter (Google Fonts), 14px base
- Colors: #111 headings, #444 body, #888 labels, #f8f8f8 stat cards
- Tables: #111 header bg, white text, alternating row stripes
- Feature cards: 1px #e8e8e8 border, 3px #111 left border
- Print-friendly: page-break-inside: avoid on features

**Do NOT include**: Development tooling details, AI tool names, internal process info.

### Step 5: Generate Internal Report

Create the MD report at `internal/YYYY-MM-DD-report.md` and HTML summary.

**Required sections** (everything in customer report PLUS):

1. **Hours Calculation Breakdown**:
   - Per-day table: OpenCode streak hours, Claude Code streak hours, combined, overhead
   - Gap distribution histogram (how many gaps in each bucket)
   - Streak stats: total streaks, qualifying streaks, wall-clock vs gap-sum breakdown
   - Total formula: `streak_hours × 1.05 = billable_hours`

2. **Session Analytics**:
   - Message counts per tool per day
   - Message length distribution (short/medium/long)
   - Screenshot count and distribution
   - Sessions per day per tool

3. **Workflow Insights** (analyze the extracted data to produce):

   **Productivity Patterns**:
   - Which days had highest/lowest output (commits per gap-hour)
   - Peak productivity windows (from message timestamp clustering)
   - Tool switching patterns (when did work shift from OpenCode to Claude Code?)

   **Message Efficiency**:
   - Ratio of short to long messages per tool (indicates interaction style)
   - Screenshots-per-feature ratio (indicates UI verification load)
   - User-to-assistant message ratio (indicates autonomy level)

   **Time Distribution**:
   - % of gap-hours in each bucket (<30s, 30s-2m, 2m-10m, 10m-30m, 30m-2h)
   - What this means: high % in 2-10m = lots of review time; high % in 10-30m = lots of manual testing

4. **Improvement Suggestions** (generate based on data patterns):

   | Pattern Detected | Suggestion |
   |-----------------|------------|
   | High % of gaps in 10-30m bucket | Heavy manual testing — consider adding automated E2E tests to reduce verification time |
   | Many screenshots on specific days | UI-heavy work — consider a live preview setup to reduce screenshot-verify cycles |
   | Long messages dominate (>60%) | Detailed prompting — consider creating reusable prompt templates for common tasks |
   | Short messages dominate (>80%) | Rapid-fire interaction — agent autonomy is high, workflow is efficient |
   | Large gap between tools (e.g., OpenCode ends, Claude starts days later) | Context loss between tools — consider a shared state/handoff document |
   | Single day has >30% of all commits | Workload concentration — consider smaller, more frequent sessions |
   | Many >2h gaps within a day | Fragmented attention — consider blocking dedicated focus time |
   | High assistant-to-user ratio (>10:1) | Agent running autonomously — verify output quality hasn't degraded |
   | Screenshots clustered on specific features | Those features need visual QA — prioritize automated visual regression |

5. **Comparison to Previous Reports** (if prior reports exist):
   - Hours trend (increasing/decreasing)
   - Commits-per-hour trend
   - Feature complexity trend
   - Tool usage shift

## Quick Reference

| Input | Source |
|-------|--------|
| User message timestamps | OpenCode SQLite `message` table, Claude Code JSONL `type: "user"` |
| Screenshots | OpenCode `part` table `type: "file"`, Claude Code image content blocks |
| Message lengths | OpenCode `part` text length, Claude Code content length |
| Commits | `git log` across workspace + submodules |
| LOC changes | `git log --shortstat` and `git diff --stat` |
| Planning docs | Scan for `.md` files in docs/, .sisyphus/plans/, .superpowers/ |
| Evidence/test results | Scan .sisyphus/evidence/, test-results/ |

## Common Mistakes

- **Trusting commit messages for feature descriptions**: Always read key source files to verify
- **Double-counting submodule commits**: Workspace repo includes submodule pointer bumps; don't count the same work twice
- **Including binary file LOC**: Exclude image/video file changes from LOC counts
- **Inflating hours with overhead**: The 5% overhead is calibrated; don't add additional multipliers
- **Including AI tool names in customer report**: Customer sees "Development Report", not "OpenCode + Claude Code Report"
