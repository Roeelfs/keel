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

- 2026-11-04 | Already-approved PRs: never restart their reviews or ask for merge approval again; one in-session approval covers the PR until it lands | founder 2026-10-31T14:58Z and 2026-11-01T07:27Z, standing-rulings-2026-11-01.md #1
- 2026-11-04 | Merge hold: no merge to main until the current main tip has green CI; pr-merge arms and waits, never force past a red tip (a fix-forward owner excepted) | founder 2026-10-26, standing-rulings-2026-11-01.md #2
- 2026-11-04 | Test persona password = its own email, never random | founder 2026-10-25, standing-rulings-2026-11-01.md #3
- 2026-11-04 | Codex threads read the non-docs merge rule as a per-PR named approval; a blanket auto-approval is rejected (#5004, #5007); Claude managers read it PR by PR too, one approval per PR is enough | founder, standing-rulings-2026-11-01.md #4
- 2026-11-04 | No Codex fan-out cap: dispatch every qualifying lane at once; the provider quota wall is the only limit | founder 2026-11-04, ~/.claude/CLAUDE.md Token & Context Economy
- 2026-11-04 | A qualifying lane (self-contained prompt, document deliverable or one-worktree commit, read-only or confined to one worktree) goes to Codex first; `codex-headroom.sh` picks the model and always dispatches | founder 2026-10-22, re-ruled 2026-11-04
- 2026-11-04 | Opus 5.5 is the Claude ceiling; fable is retired; security, final-gate and adversarial work run on opus or Codex astra | founder 2026-10-24, hook-denied
- 2026-11-04 | Managers run sonnet/medium and never write spec prose or a code diff; specs and all implementation are opus lanes or Codex lanes | founder 2026-11-01
- 2026-11-04 | A wrap_up/AskUserQuestion approval whose question names the exact PR and action, clicked Approve, IS an in-session merge go; a generic Done/Continue button never is | founder 2026-11-04
- 2026-11-04 | Docs-only PRs (diff lists only docs/ or .md docs files) merge with no approval, every session and lane | founder 2026-10-26, ~/.claude/CLAUDE.md Development Flow
- 2026-11-04 | Operator sessions under ~/CynapOperator/<org> are exempt from spec-review, wayfinder and the ship gate | founder 2026-10-28, CYN-3238
- 2026-11-04 | Grill every open item at turn end, recommended answer first; never end on open items | founder 2026-10-23
- 2026-11-04 | The founder's main Chrome is roee@cynap.ai only; never sign a test identity in there | founder 2026-10-19, CYN-2891
