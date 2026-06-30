#!/usr/bin/env python3
"""
Work Report Data Extractor
Queries OpenCode SQLite, Claude Code JSONL, and git to produce structured JSON
for billable hours calculation and report generation.

Incremental by default: reads last report's "until" date and continues from there.

Usage:
  python3 extract-data.py --project /path/to/project                    # auto since=last report, until=today
  python3 extract-data.py --project /path/to/project --since 2026-03-13 # explicit start, until=today
  python3 extract-data.py --project /path/to/project --since 2026-03-01 --until 2026-03-14
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ── Constants ──────────────────────────────────────────────────────────────────

OPENCODE_DB = Path.home() / ".local/share/opencode/opencode.db"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude/projects"
CLAUDE_TRANSCRIPTS_DIR = Path.home() / ".claude/transcripts"
CLAUDE_HISTORY = Path.home() / ".claude/history.jsonl"
REPORTS_BASE = Path.home() / "code/work-reports"

GAP_BUCKETS = [
    (30,    0.0),    # <30s: automated/system
    (120,   1.0),    # 30s-2m: quick approval while watching
    (600,   2.5),    # 2-10m: reviewing output, deciding
    (1800,  7.0),    # 10-30m: manual testing, UI inspection, config
    (7200,  4.0),    # 30m-2h: context switch back after break
]
# >2h: session break = 0 min

# Streak-continuity parameters — credit wall-clock time of sustained message streaks
STREAK_BREAK_SEC = 1800         # 30 min gap = new streak (session break)
STREAK_MIN_MESSAGES = 3         # need 3+ msgs to qualify for wall-clock credit
STREAK_MIN_WALLCLOCK_MIN = 10   # need 10+ min of wall-clock to qualify
STREAK_UTILIZATION = 0.70       # 70% of wall-clock credited (30% idle allowance)


# ── Hours Calculator (Streak + Gap Hybrid) ─────────────────────────────────────

def calc_gap_hours(timestamps):
    """
    Calculate human engagement hours using streak-continuity model.

    Per streak (no gap >30 min):
      - If streak qualifies (3+ msgs, 10+ min wall-clock):
          credit = max(gap_sum, wall_clock × STREAK_UTILIZATION)
      - Otherwise: credit = gap_sum (bucket-based)

    This credits sustained focus sessions at wall-clock rate while
    preserving the parallel-work constraint (30m+ breaks → new streak).

    Returns (hours, gap_distribution_dict).
    """
    if len(timestamps) < 2:
        return round(1.0 / 60, 4), {}

    # Build streaks: contiguous messages with no gap >STREAK_BREAK_SEC
    streaks = [[timestamps[0]]]
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i - 1]
        if gap > STREAK_BREAK_SEC:
            streaks.append([timestamps[i]])
        else:
            streaks[-1].append(timestamps[i])

    total_minutes = 0.0
    gap_distribution = defaultdict(int)

    for streak in streaks:
        if len(streak) < 2:
            total_minutes += 1.0  # single message = 1 min credit
            continue

        # Gap-sum for this streak (always compute as floor)
        gap_sum_min = 0.0
        for i in range(1, len(streak)):
            gap = streak[i] - streak[i - 1]
            credited = 0.0
            bucket_name = ">2h"
            for threshold, credit in GAP_BUCKETS:
                if gap < threshold:
                    credited = credit
                    bucket_name = f"<{threshold}s"
                    break
            gap_sum_min += credited
            gap_distribution[bucket_name] += 1

        # Wall-clock of streak
        wall_clock_min = (streak[-1] - streak[0]) / 60

        # Apply streak wall-clock credit if qualifying
        if len(streak) >= STREAK_MIN_MESSAGES and wall_clock_min >= STREAK_MIN_WALLCLOCK_MIN:
            total_minutes += max(gap_sum_min, wall_clock_min * STREAK_UTILIZATION)
        else:
            total_minutes += gap_sum_min

    return round(total_minutes / 60, 4), dict(gap_distribution)


# ── OpenCode Extractor ─────────────────────────────────────────────────────────

def extract_opencode(project_path, since_ts, until_ts):
    """Extract session data from OpenCode SQLite database."""
    if not OPENCODE_DB.exists():
        return {"available": False, "reason": "OpenCode DB not found"}

    db = sqlite3.connect(str(OPENCODE_DB))
    db.row_factory = sqlite3.Row

    # Find project IDs matching this path
    projects = db.execute(
        "SELECT id, worktree FROM project WHERE worktree LIKE ?",
        (f"%{os.path.basename(project_path)}%",)
    ).fetchall()

    if not projects:
        db.close()
        return {"available": False, "reason": "Project not found in OpenCode"}

    project_ids = [p["id"] for p in projects]
    placeholders = ",".join(["?"] * len(project_ids))

    # Detect timestamp format (seconds vs milliseconds)
    sample = db.execute("SELECT time_created FROM message LIMIT 1").fetchone()
    ts_div = 1000 if sample and sample[0] > 1e12 else 1

    since_unix = int(since_ts.timestamp())
    until_unix = int(until_ts.timestamp())

    # User messages with timestamps
    rows = db.execute(f"""
        SELECT m.time_created/{ts_div} as ts,
               date(m.time_created/{ts_div}, 'unixepoch', 'localtime') as day
        FROM message m
        JOIN session s ON m.session_id = s.id
        WHERE s.project_id IN ({placeholders})
        AND json_extract(m.data, '$.role') = 'user'
        AND m.time_created/{ts_div} >= ?
        AND m.time_created/{ts_div} < ?
        ORDER BY m.time_created
    """, (*project_ids, since_unix, until_unix)).fetchall()

    # Assistant messages count per day
    asst_rows = db.execute(f"""
        SELECT date(m.time_created/{ts_div}, 'unixepoch', 'localtime') as day,
               COUNT(*) as cnt
        FROM message m
        JOIN session s ON m.session_id = s.id
        WHERE s.project_id IN ({placeholders})
        AND json_extract(m.data, '$.role') = 'assistant'
        AND m.time_created/{ts_div} >= ?
        AND m.time_created/{ts_div} < ?
        GROUP BY day
    """, (*project_ids, since_unix, until_unix)).fetchall()
    asst_per_day = {r["day"]: r["cnt"] for r in asst_rows}

    # Screenshots/file attachments per day
    screenshot_rows = db.execute(f"""
        SELECT date(p.time_created/{ts_div}, 'unixepoch', 'localtime') as day,
               COUNT(*) as cnt
        FROM part p
        JOIN message m ON p.message_id = m.id
        JOIN session s ON m.session_id = s.id
        WHERE s.project_id IN ({placeholders})
        AND json_extract(p.data, '$.type') = 'file'
        AND p.time_created/{ts_div} >= ?
        AND p.time_created/{ts_div} < ?
        GROUP BY day
    """, (*project_ids, since_unix, until_unix)).fetchall()
    screenshots_per_day = {r["day"]: r["cnt"] for r in screenshot_rows}

    # User message text length classification per day
    length_rows = db.execute(f"""
        SELECT date(p.time_created/{ts_div}, 'unixepoch', 'localtime') as day,
               CASE
                 WHEN length(json_extract(p.data, '$.text')) < 50 THEN 'short'
                 WHEN length(json_extract(p.data, '$.text')) < 200 THEN 'medium'
                 ELSE 'long'
               END as bucket,
               COUNT(*) as cnt
        FROM part p
        JOIN message m ON p.message_id = m.id
        JOIN session s ON m.session_id = s.id
        WHERE s.project_id IN ({placeholders})
        AND json_extract(m.data, '$.role') = 'user'
        AND json_extract(p.data, '$.type') = 'text'
        AND p.time_created/{ts_div} >= ?
        AND p.time_created/{ts_div} < ?
        GROUP BY day, bucket
    """, (*project_ids, since_unix, until_unix)).fetchall()

    length_per_day = defaultdict(lambda: {"short": 0, "medium": 0, "long": 0})
    for r in length_rows:
        length_per_day[r["day"]][r["bucket"]] = r["cnt"]

    # Session count per day
    session_rows = db.execute(f"""
        SELECT date(time_created/{ts_div}, 'unixepoch', 'localtime') as day,
               COUNT(*) as cnt
        FROM session
        WHERE project_id IN ({placeholders})
        AND time_created/{ts_div} >= ?
        AND time_created/{ts_div} < ?
        GROUP BY day
    """, (*project_ids, since_unix, until_unix)).fetchall()
    sessions_per_day = {r["day"]: r["cnt"] for r in session_rows}

    db.close()

    # Group timestamps by day and calculate gap hours
    daily_ts = defaultdict(list)
    for row in rows:
        daily_ts[row["day"]].append(row["ts"])

    daily_data = {}
    total_gap_hours = 0.0
    total_user_msgs = 0
    total_screenshots = 0
    all_gap_dist = defaultdict(int)

    for day in sorted(daily_ts):
        ts_list = sorted(daily_ts[day])
        hours, gap_dist = calc_gap_hours(ts_list)
        sc = screenshots_per_day.get(day, 0)
        total_gap_hours += hours
        total_user_msgs += len(ts_list)
        total_screenshots += sc
        for k, v in gap_dist.items():
            all_gap_dist[k] += v

        daily_data[day] = {
            "user_messages": len(ts_list),
            "assistant_messages": asst_per_day.get(day, 0),
            "sessions": sessions_per_day.get(day, 0),
            "screenshots": sc,
            "message_lengths": dict(length_per_day.get(day, {})),
            "gap_hours": hours,
        }

    return {
        "available": True,
        "projects": [{"id": p["id"][:8], "worktree": p["worktree"]} for p in projects],
        "daily": daily_data,
        "totals": {
            "user_messages": total_user_msgs,
            "screenshots": total_screenshots,
            "gap_hours": round(total_gap_hours, 2),
            "gap_distribution": dict(all_gap_dist),
            "active_days": len(daily_data),
        },
    }


# ── Claude Code Extractor ──────────────────────────────────────────────────────

def extract_claude_code(project_path, since_ts, until_ts):
    """Extract session data from Claude Code JSONL files."""
    # Build the project directory key (dashes replacing slashes)
    project_key = project_path.replace("/", "-")
    if project_key.startswith("-"):
        project_key = project_key  # keep leading dash
    project_dir = CLAUDE_PROJECTS_DIR / project_key

    if not project_dir.exists():
        return {"available": False, "reason": f"Claude Code project dir not found: {project_dir}"}

    since_iso = since_ts.strftime("%Y-%m-%dT00:00:00")
    until_iso = until_ts.strftime("%Y-%m-%dT00:00:00")

    daily_ts = defaultdict(list)
    daily_screenshots = defaultdict(int)
    daily_lengths = defaultdict(lambda: {"short": 0, "medium": 0, "long": 0})
    daily_asst = defaultdict(int)
    session_count = 0

    for fname in os.listdir(project_dir):
        if not fname.endswith(".jsonl"):
            continue

        fpath = project_dir / fname
        has_messages_in_range = False

        try:
            for line in open(fpath, "r", errors="replace"):
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                ts_str = obj.get("timestamp", "")
                if not ts_str or ts_str < since_iso or ts_str >= until_iso:
                    continue

                msg_type = obj.get("type", "")
                day = ts_str[:10]

                if msg_type == "user":
                    has_messages_in_range = True
                    # Parse to unix timestamp
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        daily_ts[day].append(dt.timestamp())
                    except (ValueError, TypeError):
                        continue

                    # Measure content length and count screenshots
                    content = obj.get("message", {}).get("content", "")
                    if isinstance(content, str):
                        text_len = len(content)
                    elif isinstance(content, list):
                        text_len = sum(
                            len(b.get("text", ""))
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                        daily_screenshots[day] += sum(
                            1
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "image"
                        )
                    else:
                        text_len = 0

                    if text_len < 50:
                        daily_lengths[day]["short"] += 1
                    elif text_len < 200:
                        daily_lengths[day]["medium"] += 1
                    else:
                        daily_lengths[day]["long"] += 1

                elif msg_type == "assistant":
                    has_messages_in_range = True
                    daily_asst[day] += 1

        except (OSError, IOError):
            continue

        if has_messages_in_range:
            session_count += 1

    # Calculate gap hours per day
    daily_data = {}
    total_gap_hours = 0.0
    total_user_msgs = 0
    total_screenshots = 0

    for day in sorted(daily_ts):
        ts_list = sorted(daily_ts[day])
        hours, gap_dist = calc_gap_hours(ts_list)
        sc = daily_screenshots.get(day, 0)
        total_gap_hours += hours
        total_user_msgs += len(ts_list)
        total_screenshots += sc

        daily_data[day] = {
            "user_messages": len(ts_list),
            "assistant_messages": daily_asst.get(day, 0),
            "screenshots": sc,
            "message_lengths": dict(daily_lengths.get(day, {})),
            "gap_hours": hours,
        }

    return {
        "available": True,
        "sessions": session_count,
        "daily": daily_data,
        "totals": {
            "user_messages": total_user_msgs,
            "screenshots": total_screenshots,
            "gap_hours": round(total_gap_hours, 2),
            "active_days": len(daily_data),
        },
    }


# ── Git Extractor ──────────────────────────────────────────────────────────────

def extract_git(project_path, since_str, until_str):
    """Extract git commit data across all repos (main + submodules)."""

    def git_log(repo_path, since, until):
        """Get per-day commit data for a repo."""
        try:
            # Per-day commit messages
            result = subprocess.run(
                ["git", "log", "--all", f"--since={since}", f"--until={until}",
                 "--no-merges", "--format=%ad|%s", "--date=short"],
                capture_output=True, text=True, cwd=repo_path, timeout=30
            )
            commits_raw = [l for l in result.stdout.strip().split("\n") if l]

            # Per-day stats
            result2 = subprocess.run(
                ["git", "log", "--all", f"--since={since}", f"--until={until}",
                 "--no-merges", "--shortstat", "--format=__DATE__%ad", "--date=short"],
                capture_output=True, text=True, cwd=repo_path, timeout=30
            )

            # Parse per-day LOC
            daily_loc = defaultdict(lambda: {"insertions": 0, "deletions": 0, "commits": 0})
            current_day = None
            for line in result2.stdout.split("\n"):
                line = line.strip()
                if line.startswith("__DATE__"):
                    current_day = line.replace("__DATE__", "")
                elif "files changed" in line and current_day:
                    parts = line.split(",")
                    ins = del_ = 0
                    for p in parts:
                        p = p.strip()
                        if "insertion" in p:
                            ins = int(p.split()[0])
                        elif "deletion" in p:
                            del_ = int(p.split()[0])
                    daily_loc[current_day]["insertions"] += ins
                    daily_loc[current_day]["deletions"] += del_
                    daily_loc[current_day]["commits"] += 1

            # Total diff
            result3 = subprocess.run(
                ["git", "diff", "--stat", f"HEAD@{{{since}}}..HEAD"],
                capture_output=True, text=True, cwd=repo_path, timeout=30
            )
            diff_summary = result3.stdout.strip().split("\n")[-1] if result3.returncode == 0 else "unavailable"

            # Commit type breakdown
            type_counts = defaultdict(int)
            commits_by_day = defaultdict(list)
            for line in commits_raw:
                if "|" in line:
                    day, msg = line.split("|", 1)
                    commits_by_day[day].append(msg)
                    prefix = msg.split(":")[0].split("(")[0].strip() if ":" in msg else "other"
                    type_counts[prefix] += 1

            return {
                "total_commits": len(commits_raw),
                "daily": {d: dict(v) for d, v in daily_loc.items()},
                "commits_by_day": {d: v for d, v in commits_by_day.items()},
                "commit_types": dict(type_counts),
                "diff_summary": diff_summary,
            }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"total_commits": 0, "error": "git command failed"}

    repos = {}

    # Main workspace
    repos["workspace"] = git_log(project_path, since_str, until_str)

    # Detect submodules
    try:
        result = subprocess.run(
            ["git", "submodule", "status"],
            capture_output=True, text=True, cwd=project_path, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                parts = line.strip().split()
                if len(parts) >= 2:
                    submodule_path = parts[1]
                    full_path = os.path.join(project_path, submodule_path)
                    if os.path.isdir(full_path):
                        repos[submodule_path] = git_log(full_path, since_str, until_str)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return repos


# ── Combine & Calculate ────────────────────────────────────────────────────────

def combine_results(opencode, claude_code, git_data, since_str, until_str):
    """Combine all data sources and calculate final billable hours."""

    # Merge daily gap hours from both tools
    all_days = set()
    if opencode.get("available"):
        all_days.update(opencode.get("daily", {}).keys())
    if claude_code.get("available"):
        all_days.update(claude_code.get("daily", {}).keys())

    combined_daily = {}
    for day in sorted(all_days):
        oc = opencode.get("daily", {}).get(day, {})
        cc = claude_code.get("daily", {}).get(day, {})
        combined_daily[day] = {
            "opencode_gap_hours": oc.get("gap_hours", 0),
            "claude_code_gap_hours": cc.get("gap_hours", 0),
            "total_gap_hours": round(oc.get("gap_hours", 0) + cc.get("gap_hours", 0), 4),
            "opencode_user_msgs": oc.get("user_messages", 0),
            "claude_code_user_msgs": cc.get("user_messages", 0),
            "total_user_msgs": oc.get("user_messages", 0) + cc.get("user_messages", 0),
            "screenshots": oc.get("screenshots", 0) + cc.get("screenshots", 0),
            "opencode_msg_lengths": oc.get("message_lengths", {}),
            "claude_code_msg_lengths": cc.get("message_lengths", {}),
        }

        # Add git data for this day
        day_commits = 0
        day_ins = 0
        day_del = 0
        day_commit_msgs = []
        for repo_name, repo_data in git_data.items():
            repo_daily = repo_data.get("daily", {}).get(day, {})
            day_commits += repo_daily.get("commits", 0)
            day_ins += repo_daily.get("insertions", 0)
            day_del += repo_daily.get("deletions", 0)
            day_commit_msgs.extend(repo_data.get("commits_by_day", {}).get(day, []))

        combined_daily[day]["commits"] = day_commits
        combined_daily[day]["loc_added"] = day_ins
        combined_daily[day]["loc_deleted"] = day_del
        combined_daily[day]["commit_messages"] = day_commit_msgs

    # Calculate totals
    total_gap = sum(d["total_gap_hours"] for d in combined_daily.values())
    total_screenshots = sum(d["screenshots"] for d in combined_daily.values())
    total_user_msgs = sum(d["total_user_msgs"] for d in combined_daily.values())
    total_commits = sum(d["commits"] for d in combined_daily.values())
    active_days = len(combined_daily)

    # Apply overhead — 5% on top of streak-based hours (calibrated for
    # planning/review work not captured by streak wall-clock: off-keyboard
    # thinking, short breaks between sessions, startup context loading).
    overhead_hours = round(total_gap * 0.05, 2)
    billable_hours = round(total_gap + overhead_hours, 1)

    return {
        "period": {"since": since_str, "until": until_str},
        "daily": combined_daily,
        "totals": {
            "active_days": active_days,
            "gap_hours": round(total_gap, 2),
            "overhead_hours": overhead_hours,
            "billable_hours": billable_hours,
            "total_user_messages": total_user_msgs,
            "total_screenshots": total_screenshots,
            "total_commits": total_commits,
        },
        "sources": {
            "opencode": {
                "available": opencode.get("available", False),
                "gap_hours": opencode.get("totals", {}).get("gap_hours", 0),
                "user_messages": opencode.get("totals", {}).get("user_messages", 0),
                "screenshots": opencode.get("totals", {}).get("screenshots", 0),
            },
            "claude_code": {
                "available": claude_code.get("available", False),
                "gap_hours": claude_code.get("totals", {}).get("gap_hours", 0),
                "user_messages": claude_code.get("totals", {}).get("user_messages", 0),
                "screenshots": claude_code.get("totals", {}).get("screenshots", 0),
            },
        },
        "git": {
            repo: {
                "total_commits": data.get("total_commits", 0),
                "commit_types": data.get("commit_types", {}),
                "diff_summary": data.get("diff_summary", ""),
            }
            for repo, data in git_data.items()
        },
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def find_last_report_date(project_name):
    """Find the 'until' date from the most recent extracted-data.json."""
    internal_dir = REPORTS_BASE / project_name / "internal"
    if not internal_dir.exists():
        return None

    json_files = sorted(internal_dir.glob("*-extracted-data.json"), reverse=True)
    for f in json_files:
        try:
            data = json.loads(f.read_text())
            until_date = data.get("period", {}).get("until")
            if until_date:
                print(f"  Found previous report ending {until_date} ({f.name})", file=sys.stderr)
                return until_date
        except (json.JSONDecodeError, KeyError):
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description="Extract work report data")
    parser.add_argument("--project", required=True, help="Project root path")
    parser.add_argument("--since", default=None, help="Start date (YYYY-MM-DD). Default: last report end date")
    parser.add_argument("--until", default=None, help="End date exclusive (YYYY-MM-DD). Default: tomorrow")
    parser.add_argument("--output", default=None, help="Output JSON path (default: auto to work-reports/)")
    args = parser.parse_args()

    project_path = os.path.abspath(args.project)
    project_name = os.path.basename(project_path)
    today = datetime.now(timezone.utc)
    tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # Auto-detect --since from last report
    if args.since is None:
        last_date = find_last_report_date(project_name)
        if last_date:
            args.since = last_date
            print(f"  Auto --since={args.since} (from last report)", file=sys.stderr)
        else:
            print("ERROR: No previous report found. Provide --since explicitly.", file=sys.stderr)
            sys.exit(1)

    # Default --until to tomorrow
    if args.until is None:
        args.until = tomorrow
        print(f"  Auto --until={args.until} (tomorrow)", file=sys.stderr)

    # Auto-detect --output
    if args.output is None:
        out_dir = REPORTS_BASE / project_name / "internal"
        out_dir.mkdir(parents=True, exist_ok=True)
        args.output = str(out_dir / f"{today.strftime('%Y-%m-%d')}-extracted-data.json")
        print(f"  Auto --output={args.output}", file=sys.stderr)

    since_ts = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    until_ts = datetime.strptime(args.until, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"Extracting data for: {project_path}", file=sys.stderr)
    print(f"Period: {args.since} to {args.until}", file=sys.stderr)

    print("  Querying OpenCode...", file=sys.stderr)
    opencode = extract_opencode(project_path, since_ts, until_ts)

    print("  Querying Claude Code...", file=sys.stderr)
    claude_code = extract_claude_code(project_path, since_ts, until_ts)

    print("  Querying git...", file=sys.stderr)
    git_data = extract_git(project_path, args.since, args.until)

    print("  Combining results...", file=sys.stderr)
    result = combine_results(opencode, claude_code, git_data, args.since, args.until)

    output = json.dumps(result, indent=2, default=str)

    # Ensure both output directories exist
    customer_dir = REPORTS_BASE / project_name / "customer"
    customer_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output)
        print(f"  Written to {args.output}", file=sys.stderr)
    else:
        print(output)

    print(f"\n  Billable hours: {result['totals']['billable_hours']}h", file=sys.stderr)
    print(f"  ({result['totals']['gap_hours']}h gaps + {result['totals']['overhead_hours']}h overhead)", file=sys.stderr)
    print(f"  Customer report dir: {customer_dir}", file=sys.stderr)
    print(f"  Internal report dir: {REPORTS_BASE / project_name / 'internal'}", file=sys.stderr)


if __name__ == "__main__":
    main()
