#!/usr/bin/env python3
"""chrome-focus-guard — PreToolUse guard on the Control_Chrome MCP tools
(improve-harness 2026-08-09).

WHY. Control_Chrome is an installed Claude Desktop Extension whose implementation is
readable at:
  ~/Library/Application Support/Claude/Claude Extensions/
      ant.dir.ant.anthropic.chrome-control/server/index.js
Two of its tools steal the human's macOS keyboard focus mid-typing, and five more
silently operate on whatever tab the human is currently looking at.

Grounded in that source, read 2026-08-09 (line numbers verbatim):

  switch_to_tab   index.js:291-293  `set active tab index of w to tabIndex`
                                    `set index of w to 1`
                                    `activate`
                  -> tab switch + window raise + APP ACTIVATION, all three at once.

  open_url        index.js:203 (new_tab:true, the DEFAULT)
                                    `tell application "Google Chrome" to open location`
                  -> `open location` fronts Chrome.
                  index.js:204 (new_tab:false)
                                    `set URL of active tab of front window to ...`
                  -> measured 2026-08-09 to ALSO activate Chrome, AND it navigates the
                     human's own tab away from whatever they were reading. Both modes
                     are unsafe, so open_url is denied outright rather than steered to
                     new_tab:false.

  reload_tab / go_back / go_forward / execute_javascript / get_page_content
                  index.js:324, 351, 379, 406, 432 — each is the else-branch of a
                  `safeTabId ? ... : ...` ternary falling back to
                  `active tab of front window`. tab_id is NOT in their `required`
                  arrays (only close_tab:111 and switch_to_tab:123 require it), so an
                  omitted tab_id silently targets the human's tab. This one does NOT
                  move focus, which is exactly why it goes unnoticed: the agent quietly
                  reads or reloads the page the human is using.

ALLOWED unconditionally: list_tabs and get_current_tab are pure property reads
(index.js:211-217, 229-244) with no activate / no window raise. close_tab requires
tab_id already. The five fallback tools are allowed WITH an explicit tab_id.

SAFETY: fail-open on any parse error. Deny == exit 2. Anything not recognised is
allowed — this guard never denies a tool it does not have a specific source-grounded
reason to deny.

Lives in a real .py rather than an embedded `python3 -c` block: a single apostrophe in
a comment inside such a block silently darkens the whole hook.
"""
import sys, json

# Tools that steal macOS app focus on every call, regardless of arguments.
ALWAYS_DENY = {
    "switch_to_tab": (
        "activates Chrome (index.js:291-293: `set index of w to 1` + `activate`) — "
        "it raises the window AND fronts the app"
    ),
    "open_url": (
        "fronts Chrome via `open location` (index.js:203); with new_tab:false it "
        "instead navigates the human's OWN tab away (index.js:204) and still activates"
    ),
}

# Tools whose optional tab_id falls back to the human's active tab AND which MUTATE it
# (reload it, navigate it back/forward). Denied when tab_id is missing.
#
# DELIBERATELY EXCLUDED: execute_javascript (index.js:406) and get_page_content
# (index.js:432) share the same fallback, but reading the page the human is looking at
# is frequently the intent ("what's on this page?"), and neither moves focus. Denying
# them would fire on a large legitimate set for a hazard (silent re-point if the human
# switches tabs) that is a correctness issue, not the interruption this guard exists to
# stop. Measured over 464 real Control_Chrome calls in ~/.claude/projects/*/*.jsonl on
# 2026-08-09: execute_javascript already passes tab_id in 291 of 369 calls (79%), and
# all 9 get_page_content calls omitted it. Denying those 87 would have been the
# fires-on-the-negative-set failure. This set denies 51 of 464 (11%), every one of
# which genuinely steals focus or reloads the human's page out from under them.
NEEDS_TAB_ID = {
    "reload_tab": 324,
    "go_back": 351,
    "go_forward": 379,
}

ALTERNATIVE = (
    "Use chrome.sh instead — it owns a per-session tab, targets it by id, and navigates "
    "via page JS, so it never moves focus:\n"
    "  ~/.claude/scripts/chrome.sh open '<url>' ['<js>']\n"
    "  ~/.claude/scripts/chrome.sh js '<code>' | content | url\n"
    "  ~/.claude/scripts/chrome.sh tabs        # list tabs + their ids\n"
)

try:
    d = json.load(sys.stdin)
    tool = d.get("tool_name") or ""
    if not tool.startswith("mcp__Control_Chrome__"):
        sys.exit(0)
    name = tool.split("__")[-1]
    args = d.get("tool_input") or {}

    if name in ALWAYS_DENY:
        sys.stderr.write(
            "\U0001f6a6 Control_Chrome." + name + " blocked — it steals the human's "
            "keyboard focus while they are typing: " + ALWAYS_DENY[name] + ".\n"
            + ALTERNATIVE
            + "If you genuinely need to FOCUS a tab for the human, that is "
            "`chrome.sh tab show` — the one command that is allowed to.\n"
        )
        sys.exit(2)

    if name in NEEDS_TAB_ID and args.get("tab_id") in (None, ""):
        sys.stderr.write(
            "\U0001f6a6 Control_Chrome." + name + " blocked: no tab_id. Its tab_id is "
            "OPTIONAL, and omitting it silently targets the tab the HUMAN is looking at "
            "(index.js:" + str(NEEDS_TAB_ID[name]) + " falls back to "
            "`active tab of front window`). That does not move focus, which is why it "
            "goes unnoticed — the agent quietly reads or reloads their page.\n"
            "Either pass an explicit tab_id (get one from "
            "`~/.claude/scripts/chrome.sh tabs`), or use chrome.sh, which cannot make "
            "this mistake:\n" + ALTERNATIVE
        )
        sys.exit(2)

    sys.exit(0)
except SystemExit:
    raise
except Exception:
    sys.exit(0)
