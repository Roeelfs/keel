# Issue tracker: Linear

Issues and PRDs for this repo live in **Linear**. Use the Linear MCP tools for all
operations — there is no `gh`/CLI surface. An issue's identity is its Linear identifier
(e.g. `TEAM-123`); when narrating, wrap the identifier and its URL inside the issue's
title rather than quoting a bare id.

## Operations

- **Create an issue**: `save_issue` with `title`, a markdown `description`, and the
  target `teamId`. Capture the returned identifier.
- **Read an issue**: `get_issue` by id; `list_comments` for its thread.
- **List issues**: `list_issues` with a server-side `filter` (state, label, assignee,
  parent). Prefer the filter over fetching everything and filtering locally.
- **Comment**: `save_comment` with the issue id and a markdown body.
- **Apply / remove labels**: `save_issue` with the updated label set (resolve names via
  `list_issue_labels`; create a missing one with `create_issue_label`).
- **Set status / close**: `save_issue` with the target `stateId` (resolve via
  `list_issue_statuses` / `get_issue_status`). "Close" = move to a Done or Canceled state.
- **Publish a PRD/spec**: create the issue (or a Linear document via `save_document`) and
  apply the `ready-for-agent` label.

Linear has no separate PR surface — code review lives on the linked GitHub PR, referenced
from the Linear issue. There is no external-contributor inbound queue, so `triage`'s
external-PR mode does not apply here.

## Wayfinding operations

How this repo expresses a wayfinder map, its child tickets, blocking, and the frontier —
all in Linear:

- **Map**: a single Linear issue labelled `wayfinder:map`, holding the Destination /
  Notes / Decisions-so-far / Fog body. Create with `save_issue` + that label.
- **Child ticket**: an issue created with `save_issue` and `parentId` set to the map's id
  (a native Linear sub-issue). Label `wayfinder:<type>` (`research`/`prototype`/`grilling`/
  `task`). Once claimed, set `assigneeId` to the driving dev.
- **Blocking**: if the Linear MCP exposes issue relations, add a native `blocks` /
  `blocked-by` relation — the canonical, UI-visible edge that renders the frontier in
  Linear's own graph. Where relation-creation isn't reachable through the MCP, fall back
  to a `Blocked by: <id>, <id>` line at the top of the child body. A ticket is unblocked
  when every blocker sits in a Done/Canceled state.
- **Frontier query**: `list_issues` filtered to the map's children (`parentId` = the map)
  with an open state and no assignee; drop any whose blockers (relation or `Blocked by:`
  line) are still open; first in map order wins.
- **Claim**: `save_issue` setting `assigneeId` to the driving dev — the session's first
  write, so concurrent sessions skip a claimed ticket.
- **Resolve**: `save_comment` with the answer, move the issue to a Done state via
  `save_issue`, then append a context pointer (link) to the map's Decisions-so-far.
