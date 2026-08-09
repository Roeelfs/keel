#!/bin/bash
# chrome.sh — canonical, connection-free Chrome automation for the harness.
#
# WHY THIS EXISTS
#   "Chrome not working" has burned dozens of tool calls across sessions. There are
#   two browser-automation surfaces and each has a distinct, recurring failure mode:
#
#     • claude-in-chrome (extension MCP): richest/DOM-aware, but needs a LIVE pairing.
#       It frequently "won't connect" — nothing you can fix from a shell.
#     • Control_Chrome / osascript (this script): drives Chrome via AppleEvents.
#       It has NO live-pairing dependency, so it is the reliable FLOOR — provided two
#       one-time OS/Chrome permission gates are satisfied.
#
#   The two gates, and their exact failure signatures:
#     GATE 1  AppleEvents automation (macOS TCC). Lets us talk to Chrome at all.
#             Failure: osascript error -1743 "Not authorized to send Apple events".
#             Fix: System Settings ▸ Privacy & Security ▸ Automation ▸ allow the
#                  terminal/Claude app to control "Google Chrome".
#     GATE 2  Chrome "Allow JavaScript from Apple Events" (a per-profile Chrome toggle,
#             OFF by default). Lets AppleEvents run page JavaScript.
#             Failure: "Executing JavaScript through AppleScript is turned off."
#             (the Control_Chrome MCP mis-reports this as a bogus "Chrome not running")
#             Fix: Chrome menu ▸ View ▸ Developer ▸ Allow JavaScript from Apple Events.
#                  This is a ONE-TIME, PERSISTENT toggle — do it once, done forever.
#
#   Reads (list tabs, get title) need only GATE 1. Running page JS needs BOTH.
#
# TAB INDEPENDENCE (the reason this script is tab-scoped, not focus-scoped)
#   Driving "active tab of front window" means the agent and the human fight over one
#   tab: the agent navigates away from whatever the human was reading, and the human
#   switching tabs silently re-points the agent at the wrong page. Both directions are
#   data corruption, not just annoyance.
#
#   So every navigating/reading command here targets a SESSION-OWNED tab BY ID, and
#   never touches focus. The owned tab id is remembered per Claude session
#   ($CLAUDE_SESSION_ID), so parallel sessions each get their own tab and never
#   collide. The human's active tab is never read, never navigated, never focused.
#
#   `tab show` is the ONLY command that moves focus, and only because you asked.
#
# USAGE
#   chrome.sh check                 # diagnose both gates; exit 0 iff fully green
#   chrome.sh fix                   # try to auto-enable GATE 2; else print the 1 step
#
#   chrome.sh open '<url>' ['<js>'] # navigate THIS SESSION'S tab, await load, opt. JS
#   chrome.sh js '<javascript>'     # run JS in THIS SESSION'S tab, print the result
#   chrome.sh content               # visible text of THIS SESSION'S tab
#   chrome.sh url                   # current URL of THIS SESSION'S tab
#
#   chrome.sh tab                   # show owned tab (creates one if none)
#   chrome.sh tab new ['<url>']     # force a fresh owned tab
#   chrome.sh tab adopt <id>        # take over an existing tab (see: chrome.sh tabs)
#   chrome.sh tab show              # focus the owned tab (the ONLY focus-stealing cmd)
#   chrome.sh tab close             # close the owned tab and forget it
#   chrome.sh tab release           # forget the owned tab without closing it
#   chrome.sh tabs                  # list every open tab (id / title / url)
#
# Once `check` is green, prefer `chrome.sh js '…'` over the Control_Chrome MCP —
# it has zero connection dependency, cannot flake, and will not steal the human's tab.

set -uo pipefail

CHROME_APP="Google Chrome"

# Runtime state. ~/.claude/.gitignore denies '/*' by default, so this dir is
# untracked without touching .gitignore.
STATE_DIR="${HOME}/.claude/run/chrome"
SESSION_KEY="${CLAUDE_SESSION_ID:-default}"
STATE_FILE="${STATE_DIR}/${SESSION_KEY}.tab"

_c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
_c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
_c_yel()   { printf '\033[33m%s\033[0m\n' "$*"; }

chrome_running() { pgrep -f "/${CHROME_APP}.app/Contents/MacOS/${CHROME_APP}" >/dev/null 2>&1; }

# ---------------------------------------------------------------- gate probes

# GATE 1 probe: read the active tab title. Read-only; does NOT change focus.
_gate1() {
  osascript -e "tell application \"${CHROME_APP}\" to get title of active tab of front window" 2>&1
}

# GATE 2 probe: run JS in the active tab. Probe only — real work uses _tab_js.
_probe_js() {
  osascript - "$1" <<'APPLESCRIPT' 2>&1
on run argv
  set js to item 1 of argv
  tell application "Google Chrome"
    return (execute active tab of front window javascript js)
  end tell
end run
APPLESCRIPT
}

# ------------------------------------------------------- tab-targeted helpers
#
# Chrome tab ids exceed AppleScript's 536870911 integer-coercion ceiling
# (`as integer` silently overflows and the id never matches), so every id
# comparison below is done as TEXT. Do not "simplify" these to integers.

# Run JS in a specific tab by id. Never changes focus.
_tab_js() { # $1=tabId  $2=javascript
  osascript - "$1" "$2" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  set js to item 2 of argv
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if ((id of t) as text) is tid then
          return (execute t javascript js)
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

# Print "<title>\t<url>" for a tab id, or __NO_SUCH_TAB__. GATE 1 only.
_tab_info() { # $1=tabId
  osascript - "$1" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  -- NOTE: `tab` inside a `tell application "Google Chrome"` block resolves to
  -- Chrome's tab CLASS, not the tab character, and silently concatenates the
  -- literal word "tab". Bind the separator outside the tell block.
  set sep to (ASCII character 9)
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if ((id of t) as text) is tid then
          return (title of t) & sep & (URL of t)
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

# Run navigation JS in a tab and wait for the load to settle. Does NOT activate Chrome.
_tab_nav_js() { # $1=tabId  $2=javascript
  osascript - "$1" "$2" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  set theJS to item 2 of argv
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if ((id of t) as text) is tid then
          -- Navigate by running location.href IN THE PAGE, not by `set URL of t`.
          -- Measured on macOS: `set URL of t` ACTIVATES Chrome (steals the human's
          -- keyboard focus mid-typing); `execute t javascript` does NOT. Same
          -- navigation, no focus theft. Do not "simplify" this back to set URL.
          execute t javascript theJS
          delay 0.3
          repeat 120 times
            if (loading of t) is false then exit repeat
            delay 0.25
          end repeat
          return "loaded"
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

# Navigate a tab by id without activating Chrome. Falls back to `set URL` (which DOES
# activate) only when the page refuses JS — e.g. chrome:// pages, where execute is denied.
_tab_nav() { # $1=tabId  $2=url
  local esc r
  esc="${2//\\/\\\\}"; esc="${esc//\'/\\\'}"     # single-quote-safe for the JS literal
  r="$(_tab_nav_js "$1" "location.href='${esc}'")"
  case "$r" in
    loaded|__NO_SUCH_TAB__) printf '%s' "$r"; return 0 ;;
  esac
  # JS refused (chrome:// page, or GATE 2 off). Accept the activation rather than fail.
  _c_yel "note: page refused JS navigation — falling back to set URL (this focuses Chrome once)." >&2
  _tab_nav_seturl "$1" "$2"
}

# Legacy navigator. ACTIVATES Chrome — fallback only, never the default path.
_tab_nav_seturl() { # $1=tabId  $2=url
  osascript - "$1" "$2" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  set theURL to item 2 of argv
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if ((id of t) as text) is tid then
          set URL of t to theURL
          delay 0.3
          repeat 120 times
            if (loading of t) is false then exit repeat
            delay 0.25
          end repeat
          return "loaded"
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

# The frontmost application name, in the form `open -a` accepts. Read-only: reading it
# does NOT activate anything, and lsappinfo needs no Accessibility grant (System Events
# does, and this process usually lacks it).
_front_app() {
  lsappinfo info -only name "$(lsappinfo front 2>/dev/null)" 2>/dev/null | sed 's/.*=//; s/"//g'
}

# Create a tab, then give the human back BOTH the app focus and the active tab.
#
# `make new tab` activates Chrome — measured, and unavoidable through AppleScript (unlike
# navigation, which we do via page JS precisely to dodge this). So we snapshot the
# frontmost app first and re-activate it after. That costs one brief flash on the FIRST
# command of a session; every later navigate/read/JS is silent because the tab already
# exists. Never remove the snapshot: without it Chrome simply keeps the focus.
_tab_create() { # $1=url
  local before after id
  before="$(_front_app)"
  id="$(_tab_create_raw "$1")"
  after="$(_front_app)"
  if [ -n "$before" ] && [ "$before" != "$after" ] && [ "$after" = "Google Chrome" ]; then
    open -a "$before" 2>/dev/null || true
  fi
  printf '%s' "$id"
}

# Raw creator. ACTIVATES Chrome — always call it through _tab_create, never directly.
_tab_create_raw() { # $1=url
  osascript - "$1" <<'APPLESCRIPT' 2>&1
on run argv
  set theURL to item 1 of argv
  tell application "Google Chrome"
    if (count of windows) is 0 then
      set w to (make new window)
      set t to active tab of w
      set URL of t to theURL
      return (id of t) as text
    end if
    set w to front window
    -- Remember the human's tab by ID, not index: if they close a tab while we work,
    -- indices shift underneath us and an index-restore lands on the wrong page.
    set beforeId to ((id of active tab of w) as text)
    set beforeIdx to active tab index of w
    set t to (make new tab at end of tabs of w with properties {URL:theURL})
    -- `make new tab` focuses the new tab; hand focus straight back to the human.
    try
      set restored to false
      set idx to 0
      repeat with ot in tabs of w
        set idx to idx + 1
        if ((id of ot) as text) is beforeId then
          set active tab index of w to idx
          set restored to true
          exit repeat
        end if
      end repeat
      -- their tab is gone entirely; fall back to the old position
      if restored is false then set active tab index of w to beforeIdx
    end try
    return (id of t) as text
  end tell
end run
APPLESCRIPT
}

_tab_close() { # $1=tabId
  osascript - "$1" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if ((id of t) as text) is tid then
          close t
          return "closed"
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

_tab_focus() { # $1=tabId — the ONLY function that moves the human's focus
  osascript - "$1" <<'APPLESCRIPT' 2>&1
on run argv
  set tid to item 1 of argv
  tell application "Google Chrome"
    repeat with w in windows
      set idx to 0
      repeat with t in tabs of w
        set idx to idx + 1
        if ((id of t) as text) is tid then
          set active tab index of w to idx
          set index of w to 1
          activate
          return "focused"
        end if
      end repeat
    end repeat
  end tell
  return "__NO_SUCH_TAB__"
end run
APPLESCRIPT
}

# ------------------------------------------------------------ owned-tab state

_state_read()  { [ -f "$STATE_FILE" ] && cat "$STATE_FILE" || true; }
_state_write() { mkdir -p "$STATE_DIR"; printf '%s' "$1" > "$STATE_FILE"; }
_state_clear() { rm -f "$STATE_FILE"; }

# Echo this session's owned tab id, creating/healing it as needed.
# A stale id (human closed the tab) is silently replaced — we NEVER fall back to
# the active tab, because that is the exact focus-stealing bug this file fixes.
_owned_tab() { # $1=optional url for a fresh tab
  local url="${1:-about:blank}" id info
  id="$(_state_read)"
  if [ -n "$id" ]; then
    info="$(_tab_info "$id")"
    if [ "$info" != "__NO_SUCH_TAB__" ]; then printf '%s' "$id"; return 0; fi
    _c_yel "note: owned tab $id is gone (closed?) — opening a fresh one." >&2
  fi
  id="$(_tab_create "$url")"
  case "$id" in
    ""|*"error"*|*"not authorized"*)
      _c_red "✗ could not create a tab: $id" >&2; return 1 ;;
  esac
  _state_write "$id"
  printf '%s' "$id"
}

_require_green_js() { # guard: turn the GATE-2 message into an actionable one
  case "$1" in
    *"turned off"*) _c_red "GATE 2 off — run 'chrome.sh fix' first."; printf '%s\n' "$1"; return 2 ;;
    "__NO_SUCH_TAB__") _c_red "owned tab vanished mid-command; re-run."; return 3 ;;
  esac
  return 0
}

# ------------------------------------------------------------------- commands

cmd_check() {
  if ! chrome_running; then
    _c_red "✗ Chrome is not running."
    echo "  → Launch Google Chrome, then re-run: chrome.sh check"
    return 3
  fi
  _c_green "✓ Chrome running"

  local g1; g1="$(_gate1)"
  if printf '%s' "$g1" | grep -qi -E "not authorized|-1743|assistive|-600|isn.t running"; then
    _c_red "✗ GATE 1 (AppleEvents automation) blocked:"
    echo "    $g1"
    echo "  → System Settings ▸ Privacy & Security ▸ Automation ▸ enable your terminal/Claude → \"${CHROME_APP}\"."
    return 1
  fi
  _c_green "✓ GATE 1 (AppleEvents automation)"

  local g2; g2="$(_probe_js "1+1")"
  if [ "$g2" = "2" ]; then
    _c_green "✓ GATE 2 (Allow JavaScript from Apple Events) — page JS works"
    echo
    _c_green "ALL GREEN. Canonical surface: chrome.sh js '<code>'  (own tab, no pairing, no focus theft)."
    return 0
  fi
  _c_red "✗ GATE 2 (Allow JavaScript from Apple Events) is OFF:"
  echo "    $g2"
  echo
  _c_yel "  ONE-TIME FIX (persists forever): in Chrome's menu bar →"
  _c_yel "      View ▸ Developer ▸ Allow JavaScript from Apple Events"
  echo "  Then re-run: chrome.sh check    (or try: chrome.sh fix)"
  return 2
}

# Attempt to flip GATE 2 without a human, via System Events UI scripting.
# Requires an Accessibility grant; if absent (error -1719) we print the manual step.
cmd_fix() {
  if [ "$(_probe_js "1+1")" = "2" ]; then _c_green "GATE 2 already on — nothing to do."; return 0; fi
  local out
  out="$(osascript <<'APPLESCRIPT' 2>&1
tell application "Google Chrome" to activate
delay 0.5
with timeout of 8 seconds
  tell application "System Events" to tell process "Google Chrome"
    set devMenu to menu 1 of menu item "Developer" of menu 1 of menu bar item "View" of menu bar 1
    set itm to menu item "Allow JavaScript from Apple Events" of devMenu
    if (value of attribute "AXMenuItemMarkChar" of itm) is missing value then click itm
  end tell
end timeout
return "clicked"
APPLESCRIPT
)"
  if [ "$(_probe_js "1+1")" = "2" ]; then
    _c_green "✓ Auto-enabled GATE 2 via System Events. Page JS now works."
    return 0
  fi
  if printf '%s' "$out" | grep -qi -E "-1719|assistive access"; then
    _c_red "✗ Can't auto-toggle: this process lacks Accessibility (UI-scripting) permission."
    echo "  Pick ONE one-time action:"
    _c_yel "    (a) SIMPLEST — Chrome menu ▸ View ▸ Developer ▸ Allow JavaScript from Apple Events."
    _c_yel "    (b) Or grant Accessibility to your terminal/Claude (System Settings ▸ Privacy &"
    _c_yel "        Security ▸ Accessibility) so 'chrome.sh fix' can self-heal on its own."
  else
    _c_red "✗ Auto-toggle failed:"
    echo "    $out"
    _c_yel "  Do it manually: Chrome menu ▸ View ▸ Developer ▸ Allow JavaScript from Apple Events."
  fi
  return 2
}

cmd_js() {
  [ $# -ge 1 ] || { _c_red "usage: chrome.sh js '<javascript>'"; return 64; }
  local id r; id="$(_owned_tab)" || return 1
  r="$(_tab_js "$id" "$1")"
  _require_green_js "$r" || return $?
  printf '%s\n' "$r"
}

cmd_open() {
  [ $# -ge 1 ] || { _c_red "usage: chrome.sh open '<url>' ['<js>']"; return 64; }
  local id r; id="$(_owned_tab "$1")" || return 1
  r="$(_tab_nav "$id" "$1")"
  [ "$r" = "__NO_SUCH_TAB__" ] && { _c_red "owned tab vanished; re-run."; return 3; }
  if [ "${2:-}" != "" ]; then
    r="$(_tab_js "$id" "$2")"
    _require_green_js "$r" || return $?
    printf '%s\n' "$r"
  else
    echo "loaded [tab $id]: $1"
  fi
}

cmd_content() {
  local id r; id="$(_owned_tab)" || return 1
  r="$(_tab_js "$id" "document.body ? document.body.innerText : ''")"
  _require_green_js "$r" || return $?
  printf '%s\n' "$r"
}

cmd_url() {
  local id info; id="$(_owned_tab)" || return 1
  info="$(_tab_info "$id")"
  [ "$info" = "__NO_SUCH_TAB__" ] && { _c_red "owned tab vanished; re-run."; return 3; }
  printf '%s\n' "${info#*$'\t'}"
}

cmd_tab() {
  local sub="${1:-status}"; shift || true
  case "$sub" in
    status)
      local id info; id="$(_owned_tab)" || return 1
      info="$(_tab_info "$id")"
      _c_green "owned tab [session ${SESSION_KEY}]: $id"
      printf '  title: %s\n  url:   %s\n' "${info%%$'\t'*}" "${info#*$'\t'}"
      ;;
    new)
      local id old; old="$(_state_read)"
      [ -n "$old" ] && _c_yel "releasing previous owned tab $old (left open)"
      _state_clear
      id="$(_owned_tab "${1:-about:blank}")" || return 1
      _c_green "new owned tab: $id"
      ;;
    adopt)
      [ $# -ge 1 ] || { _c_red "usage: chrome.sh tab adopt <id>   (see: chrome.sh tabs)"; return 64; }
      local info; info="$(_tab_info "$1")"
      [ "$info" = "__NO_SUCH_TAB__" ] && { _c_red "no tab with id $1 — run: chrome.sh tabs"; return 4; }
      _state_write "$1"
      _c_green "adopted tab $1"
      printf '  title: %s\n' "${info%%$'\t'*}"
      ;;
    show)
      local id; id="$(_state_read)"
      [ -z "$id" ] && { _c_red "no owned tab yet — run: chrome.sh tab"; return 4; }
      local r; r="$(_tab_focus "$id")"
      [ "$r" = "__NO_SUCH_TAB__" ] && { _c_red "owned tab $id is gone."; return 4; }
      _c_green "focused tab $id"
      ;;
    close)
      local id; id="$(_state_read)"
      [ -z "$id" ] && { _c_yel "no owned tab to close."; return 0; }
      _tab_close "$id" >/dev/null
      _state_clear
      _c_green "closed and forgot tab $id"
      ;;
    release)
      local id; id="$(_state_read)"
      _state_clear
      _c_green "forgot tab ${id:-<none>} (left open)"
      ;;
    *) _c_red "usage: chrome.sh tab {status|new [url]|adopt <id>|show|close|release}"; return 64 ;;
  esac
}

# Emit "<id>\t<title>\t<url>" for every open tab. Kept as its own function because a
# heredoc nested directly inside $( ) is re-scanned by bash: a backtick or apostrophe
# in an AppleScript comment there silently breaks the whole script.
_all_tabs() {
  osascript <<'APPLESCRIPT' 2>&1
-- The bare word "tab" inside a Chrome tell block resolves to the tab CLASS, not the
-- tab character, and concatenates the literal word. Bind the separator outside it.
set sep to (ASCII character 9)
tell application "Google Chrome"
  set out to ""
  repeat with w in windows
    repeat with t in tabs of w
      set out to out & (id of t) & sep & (title of t) & sep & (URL of t) & linefeed
    end repeat
  end repeat
  return out
end tell
APPLESCRIPT
}

cmd_tabs() {
  local owned raw; owned="$(_state_read)"
  raw="$(_all_tabs)"
  printf '%s\n' "$raw" | while IFS=$'\t' read -r id title url; do
    [ -z "${id:-}" ] && continue
    if [ "$id" = "$owned" ]; then printf '\033[32m* %s\t%s\t%s\033[0m\n' "$id" "$title" "$url"
    else printf '  %s\t%s\t%s\n' "$id" "$title" "$url"; fi
  done
}

case "${1:-check}" in
  check)   cmd_check ;;
  fix)     cmd_fix ;;
  js)      shift; cmd_js "$@" ;;
  open)    shift; cmd_open "$@" ;;
  content) cmd_content ;;
  url)     cmd_url ;;
  tab)     shift; cmd_tab "$@" ;;
  tabs)    cmd_tabs ;;
  *) echo "usage: chrome.sh {check|fix|open <url> [js]|js '<code>'|content|url|tab [sub]|tabs}"; exit 64 ;;
esac
