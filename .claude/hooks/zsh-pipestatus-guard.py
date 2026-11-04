#!/usr/bin/env python3
"""zsh-pipestatus-guard — PreToolUse (Bash).

WHY: this machine's shell is zsh. `$PIPESTATUS` is a BASH-ism: in zsh it expands to
EMPTY with no error, so any downstream exit-code check silently becomes a no-op —
`echo "exit: ${PIPESTATUS[0]}"` prints `exit:` and the failure is never seen.
The rule is in CLAUDE.md verbatim and was violated 3 times consecutively in one
session anyway (measured 2026-07-24). A prose rule the model "should remember" is
strictly weaker than a hook that blocks.

zsh's equivalent is ${pipestatus[1]} — lowercase, 1-INDEXED. Better still: don't
pipe, and capture rc=$? directly.

FALSE-POSITIVE CONTROL: match against a shadow with SINGLE-quoted spans and heredoc
bodies blanked — those are the only contexts where `$PIPESTATUS` does NOT expand, so
a grep pattern in 'single quotes' or a heredoc writing this very rule is safe.
DOUBLE-quoted spans are deliberately KEPT: `echo "rc=${PIPESTATUS[0]}"` is precisely
where the bug lives, and blanking them made the guard fire on nothing at all (caught
in dry-run 2026-07-24, before wiring).

Escape: PIPESTATUS_OK=1 (checked by the calling .sh before this runs). FAILS OPEN on
any parse error.

Lives in a real .py rather than an embedded `python3 -c` block: a single apostrophe in
a comment inside such a block silently darkens the whole hook, and an unheard guard is
the failure mode this layer keeps re-earning.
"""
import json, sys, re


def bail():
    sys.exit(0)


try:
    d = json.load(sys.stdin) or {}
except Exception:
    bail()

cmd = (d.get("tool_input") or {}).get("command")
if not isinstance(cmd, str) or "PIPESTATUS" not in cmd:
    bail()

# Shadow: blank out single/double-quoted spans and heredoc bodies so literals inside
# them cannot trigger. Keeps offsets irrelevant — we only test for presence.
shadow = cmd
shadow = re.sub(r"<<-?\s*(['\"]?)(\w+)\1.*?^\s*\2", " ", shadow, flags=re.S | re.M)
shadow = re.sub(r"'[^']*'", " ", shadow)

if not re.search(r"\$\{?PIPESTATUS", shadow):
    bail()

reason = (
    "BLOCKED: `$PIPESTATUS` is a bash-ism and this shell is zsh — it expands to EMPTY "
    "with NO error, so the exit-code check you are writing silently becomes a no-op "
    "(measured: `echo \"exit: ${PIPESTATUS[0]}\"` printed `exit:` and the failure went "
    "unnoticed).\n\n"
    "Use either:\n"
    "  - `${pipestatus[1]}`  (zsh: lowercase, 1-INDEXED), or\n"
    "  - better: do NOT pipe — run the command, capture `rc=$?`, then post-process.\n\n"
    "Set PIPESTATUS_OK=1 to override."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }
}))
