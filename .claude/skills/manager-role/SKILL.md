---
license: MIT
name: manager-role
description: Load a manager's role from disk - the first thing every [Manager] session does at every wake, session start, compaction and account switch, and whenever it is told its role changed. Invoked as "/manager-role <slug>" (the program slug). Prints the current role card, the changes since the version this manager last loaded, the rulings, the wake steps and the program's context brief, and records the load so the Stop guard can check it.
---

# manager-role

Run this, with your program slug, and nothing else first:

```bash
python3 -I ~/.claude/skills/sessions-to-chips/scripts/role_brief.py --program <slug>
```

Read its output top to bottom and do its wake steps in order. Everything it says comes from the
files on disk at this moment, so this body never goes stale: it only points.

- The output's header names the role version; write `Role: v<version>` in your next `## AT-WAKE` block.
- A `!!!` line (keel checkout behind origin, overlay ledger missing) is reported once to the Harness
  manager; keep working from what was printed.
- The load is recorded in `~/.claude/orchestrator/programs/<slug>.role.json` by the script. Never
  edit that file.

The role's owner is `~/.claude/skills/sessions-to-chips/references/role.md`; the depth behind each
line is `manager-contract.md` in the same directory.
