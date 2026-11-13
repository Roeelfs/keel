# Rulings ledger

The ONE place a standing founder ruling reaches every manager. `render_state.py --context`
(`scripts/state_brief.py`) prints, at every wake, the lines below that are newer than the program's last
`## AT-WAKE (<UTC ISO>)` stamp (all of them when the block carries no stamp), plus the commits since that
stamp to `~/.claude/CLAUDE.md`, `manager-contract.md` and this file.

**Managers: stop copying rulings into your program state file.** This ledger is their owner; a copied line goes
stale the day a ruling changes. Read them from the wake brief. Leave existing copies alone; never re-add one.

Adding a ruling: append one line, `- <date or UTC ISO> | <founder words or short rule> | <source>`. The date is
the day the line enters the ledger, so every manager waking after it sees it; the founder's own date goes in
the source. A date-only line shows to every wake stamped that day; a full ISO time is exact. A ruling that
replaces another says `replaces <date> <rule>`; never delete a line.

## Rulings

This public file carries the format and de-identified, generic rulings only. A machine keeps its private rulings in its private overlay,
`~/.claude/skills-overlay/sessions-to-chips/rulings-ledger.md`, in the same line format; `state_brief.py`
reads both files, this one first. Rulings name private tickets, accounts and files, so they never land here.

- 2026-11-13 | Every child session keeps ONE notes file under the program's relay folder (done, owed, next, decisions, paths), rewritten each turn; its manager reads that file and the PR at a wake, never the child's transcript | founder 2026-11-13, permanent
- 2026-11-13 | A child compacts in place by default (warm cache, no re-paid preamble); a fresh child, started from the notes file, only at a phase boundary with a complete notes file and a different next seam | founder 2026-11-13, permanent
- 2026-11-13 | One batched manager turn per wake: read every pending child report and event in ONE turn (children report with notify_when_idle); read state from disk, never child transcripts or lane output beyond a slice | founder 2026-11-13, permanent
