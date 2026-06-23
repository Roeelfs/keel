#!/bin/sh
# SessionStart hook: warn if Claude Code was launched from a linked worktree.
#
# Why: Claude Code locks the project slug to the cwd at launch and never
# re-derives it. A session launched from inside a worktree is filed under a
# separate ~/.claude/projects/<slug>/ and disappears from /resume and from the
# session survey when you look from the main checkout. The fix is to launch
# claude from the MAIN repo, then `cd` into the worktree as your first action.
#
# Limitation: SessionStart fires AFTER the slug is already chosen, so this hook
# can only WARN — it cannot abort the session.
#
# CONFIG: WORKTREE_DIR_RE is an `case`-style glob matched against the launch cwd.
# Default matches a `.../<repo>/.../worktrees/...` layout and common `*-wt-*`
# naming. Override by editing the pattern below to match your worktree paths.

WORKTREE_DIR_RE='*/worktrees/*|*-wt-*|*/.worktrees/*'

INPUT=$(cat)
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null)

# shellcheck disable=SC2254  # WORKTREE_DIR_RE is an intentional glob with alternation
case "$CWD" in
  $WORKTREE_DIR_RE)
    cat >&2 <<EOF

⚠️  SLUG MISMATCH WARNING

This session was launched from a worktree:
  $CWD

The project slug is now locked to that path. Effects:
  • This session will NOT appear in /resume from the main checkout
  • Memory/notes changes will land in a separate slug dir
  • The claude-sessions survey will list it under a different slug

Recommended: exit this session, then:
  cd <your main repo checkout>
  claude
  cd $CWD   # switch into the worktree as your first action

If you continue here, find this session later via:
  claude --resume <sid-prefix>

EOF
    ;;
esac

exit 0
