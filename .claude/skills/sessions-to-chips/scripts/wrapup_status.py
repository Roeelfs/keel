#!/usr/bin/env python3
"""Wrap-up mode: one-shot convergence snapshot. Which sessions have written their note?

Reads the same roster as wrapup_roster.py and checks ~/.claude/sessions-to-chips/wrapup/
for <date>-<slug>.md per manager (unmanaged sessions write <date>-<slug-of-title>.md).
Prints a table and the before/after session counts. Read-only; run it once per check,
never in a loop.

Usage: wrapup_status.py [--date YYYY-MM-DD] [--recent-hours 72]
"""
import argparse, datetime, glob, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--recent-hours", type=int, default=72)
    a = ap.parse_args()
    out = subprocess.run([sys.executable, "-I", os.path.join(HERE, "wrapup_roster.py"), "--date", a.date,
                          "--recent-hours", str(a.recent_hours)], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(out.stderr)
    roster = json.loads(out.stdout)
    notes = {os.path.basename(p) for p in glob.glob(os.path.expanduser(f"~/.claude/sessions-to-chips/wrapup/{a.date}-*.md"))}

    def have(slug):
        return f"{a.date}-{slug}.md" in notes

    done = 0
    print(f"{'STATE':8} {'KIND':10} TITLE")
    for m in roster["managers"]:
        ok = have(m["slug"])
        done += ok
        print(f"{'NOTE' if ok else 'WAITING':8} {'manager':10} {m['title']} ({m['liveChildren']} children)")
    for u in roster["unmanaged"]:
        ok = any(n.startswith(f"{a.date}-") and slugify(u["title"])[:20] in n for n in notes)
        done += ok
        print(f"{'NOTE' if ok else 'WAITING':8} {'unmanaged':10} {u['title']}")
    total = len(roster["managers"]) + len(roster["unmanaged"])
    print(f"\n{done}/{total} notes written. Superseded managers not messaged: {len(roster['superseded'])}.")
    print("Notes on disk:", ", ".join(sorted(notes)) or "none")


if __name__ == "__main__":
    main()
