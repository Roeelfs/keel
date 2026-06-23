#!/usr/bin/env bash
# install.sh — drop keel into a target repository.
#
# Copies keel's .claude/ (skills, agents, hooks) and tooling/ into a target repo,
# scaffolds the rules + policy templates if they don't already exist, and prints
# the few manual steps that remain. It NEVER overwrites a file you already have —
# your CLAUDE.md, settings.json, and docs are safe.
#
# Usage:
#   ./install.sh [TARGET_REPO]      # defaults to the current directory
#
# After it runs, see QUICKSTART.md for wiring up settings and running the flow.

set -euo pipefail

KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$PWD}"

# ---------------------------------------------------------------------------
# Validate target
# ---------------------------------------------------------------------------
TARGET="$(cd "$TARGET" 2>/dev/null && pwd)" || { echo "❌ target not found: $1" >&2; exit 1; }
if [ "$TARGET" = "$KEEL_DIR" ]; then
  echo "❌ target is the keel repo itself. Pass the repo you want to install INTO:" >&2
  echo "   ./install.sh /path/to/your/project" >&2
  exit 1
fi
if ! git -C "$TARGET" rev-parse --git-dir >/dev/null 2>&1; then
  echo "⚠️  $TARGET is not a git repo. keel's workflow tooling needs git (it stores" >&2
  echo "    shared state under the repo's .git/). Run 'git init' there first, or pick" >&2
  echo "    a different target." >&2
  exit 1
fi

echo "Installing keel → $TARGET"
echo ""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
copied=0; skipped=0

# copy_tree <relative-dir> — copy a directory from keel into target, file by file,
# never overwriting an existing file. Reports each action.
copy_tree() {
  local rel="$1"
  local src="$KEEL_DIR/$rel" dst="$TARGET/$rel"
  [ -d "$src" ] || return 0
  # Walk files so we can skip individually-existing ones.
  while IFS= read -r f; do
    local relf="${f#"$src"/}"
    local out="$dst/$relf"
    mkdir -p "$(dirname "$out")"
    if [ -e "$out" ]; then
      echo "  skip (exists): $rel/$relf"; skipped=$((skipped+1))
    else
      cp "$f" "$out"; echo "  + $rel/$relf"; copied=$((copied+1))
    fi
  done < <(find "$src" -type f)
}

# scaffold <src-template> <dst-path> — copy a template only if dst doesn't exist.
scaffold() {
  local src="$KEEL_DIR/$1" dst="$TARGET/$2"
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ]; then
    echo "  skip (exists): $2"; skipped=$((skipped+1))
  else
    cp "$src" "$dst"; echo "  + $2  (template — fill it in)"; copied=$((copied+1))
  fi
}

# ---------------------------------------------------------------------------
# 1. Copy the harness
# ---------------------------------------------------------------------------
echo "Harness files:"
copy_tree ".claude/skills"
copy_tree ".claude/agents"
copy_tree ".claude/hooks"
copy_tree "tooling/workflow"
copy_tree "tooling/sandbox"

# Make scripts executable
find "$TARGET/.claude/hooks" "$TARGET/tooling" -type f \( -name "*.sh" -o -name "workflow" -o -name "with-heavy-lock" \) -exec chmod +x {} + 2>/dev/null || true

echo ""
echo "Templates (only created if missing):"
scaffold "templates/CLAUDE.md.template"        "CLAUDE.md"
scaffold "templates/AGENTS.md.template"        "AGENTS.md"
scaffold "templates/security-policy.example.md" "docs/security-policy.md"
scaffold "templates/testing-config.example.md" "docs/testing-config.md"

# Settings: never clobber an existing settings.json — drop the example beside it.
echo ""
echo "Settings:"
mkdir -p "$TARGET/.claude"
if [ -e "$TARGET/.claude/settings.json" ]; then
  cp "$KEEL_DIR/.claude/settings.example.json" "$TARGET/.claude/settings.example.json"
  echo "  you already have .claude/settings.json — merge the hooks block from"
  echo "  .claude/settings.example.json by hand (don't lose your existing config)."
else
  cp "$KEEL_DIR/.claude/settings.example.json" "$TARGET/.claude/settings.json"
  echo "  + .claude/settings.json  (from example — review it)"
  copied=$((copied+1))
fi

# ---------------------------------------------------------------------------
# 2. Optional: put with-heavy-lock on PATH
# ---------------------------------------------------------------------------
echo ""
echo "Optional: 'with-heavy-lock' on your PATH lets the serialize-heavy-ops hook"
echo "enforce the machine-global lock. To install it:"
echo "    sudo cp \"$TARGET/tooling/sandbox/with-heavy-lock\" /usr/local/bin/ && sudo chmod +x /usr/local/bin/with-heavy-lock"

# ---------------------------------------------------------------------------
# 3. Optional: reaper timer
# ---------------------------------------------------------------------------
echo ""
echo "Optional: the heartbeat reaper cleans up state from crashed sessions."
echo "See tooling/workflow/install/README.md to install the macOS/Linux timer."

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "Done. $copied file(s) installed, $skipped skipped (already present)."
echo ""
echo "Next:"
echo "  1. Fill in CLAUDE.md, docs/security-policy.md, docs/testing-config.md."
echo "  2. Review .claude/settings.json (hook wiring + permissions)."
echo "  3. Restart Claude Code in this repo so the SessionStart hooks load."
echo "  4. See QUICKSTART.md for running the spec-review / spec-test flow."
