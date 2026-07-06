#!/usr/bin/env bash
#
# wire-skills.sh — keep every runtime's skill root in sync with keel's canonical set.
#
# keel is consumed by symlink: one canonical clone, and each runtime's *global* skill
# root holds one symlink per skill pointing back into it. This tool creates the symlink
# for every keel skill missing from a root and prunes skill-symlinks whose target was
# deleted — so a newly-added skill (e.g. root-cause-analysis) appears in EVERY runtime
# with zero manual wiring. That is the drift this fixes: roots wired by hand, once, go
# stale the moment a new skill lands, hiding it from that whole runtime.
#
# It is idempotent and SAFE: it only ever creates symlinks into the source and prunes
# its own dangling skill-symlinks. It NEVER touches real skill copies, other vendors'
# skills, or a runtime's own built-ins (e.g. Codex's `~/.codex/skills/.system/`).
#
# Usage:
#   tooling/wire-skills.sh                      # sync keel skills into all detected roots
#   tooling/wire-skills.sh --dry-run            # show what would change; mutate nothing
#   tooling/wire-skills.sh --src <dir>          # sync a different skills dir (e.g. a project's
#                                               #   .claude/skills — see docs/cross-runtime-skills.md
#                                               #   for the project-vs-global scoping rules)
#   KEEL_SKILL_ROOTS=/a:/b tooling/wire-skills.sh   # override the target roots (colon-separated)
#
# Skills load at invocation time — a newly-wired skill is available on its next use; no
# restart needed. Runtimes whose home dir is absent (not installed) are skipped.
set -euo pipefail

KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$KEEL_DIR/.claude/skills"
DRY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --src) SRC="${2:?--src needs a directory}"; shift ;;
    --src=*) SRC="${1#--src=}" ;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "wire-skills: unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -d "$SRC" ] || { echo "wire-skills: source skills dir not found: $SRC" >&2; exit 1; }
SRC="$(cd "$SRC" && pwd)"

# Runtime skill roots. Override with KEEL_SKILL_ROOTS (colon-separated). A root is synced
# only when its parent (the runtime's home) exists — an uninstalled runtime is skipped.
if [ -n "${KEEL_SKILL_ROOTS:-}" ]; then
  IFS=':' read -r -a ROOTS <<< "$KEEL_SKILL_ROOTS"
else
  ROOTS=("$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills")
fi

# A dangling symlink is ours to prune only if it pointed at a skills dir (keel-direct,
# a runtime-root hop like ~/.claude/skills/<name>, or the current --src). Real dirs and
# non-skill symlinks never match, so they are never touched.
is_skill_symlink() {
  local link="$1" tgt
  [ -L "$link" ] || return 1
  tgt="$(readlink "$link")"
  case "$tgt" in
    "$SRC"/*|*/.claude/skills/*|*/code/keel/.claude/skills/*) return 0 ;;
    *) return 1 ;;
  esac
}

total_added=0; total_pruned=0
for ROOT in "${ROOTS[@]}"; do
  if [ ! -d "$(dirname "$ROOT")" ]; then
    echo "· skip  $ROOT  (runtime not installed)"
    continue
  fi
  [ -d "$ROOT" ] || { [ -n "$DRY" ] || mkdir -p "$ROOT"; }
  added=0; pruned=0; kept=0; shadowed=0

  # 1. Add a symlink for every source skill missing from this root.
  for s in "$SRC"/*/; do
    name="$(basename "$s")"
    dest="$ROOT/$name"
    if [ -L "$dest" ]; then
      kept=$((kept + 1)); continue          # already a symlink — leave it (resolves fine)
    elif [ -e "$dest" ]; then
      echo "  ! shadow  $dest is a real dir, not a symlink — left as-is"
      shadowed=$((shadowed + 1)); continue  # a real copy shadows the canonical skill; owner decides
    fi
    echo "  + link    $dest -> $SRC/$name"
    [ -n "$DRY" ] || ln -s "$SRC/$name" "$dest"
    added=$((added + 1))
  done

  # 2. Prune our own dangling skill-symlinks (source skill was removed).
  if [ -d "$ROOT" ]; then
    for dest in "$ROOT"/* "$ROOT"/.*; do
      [ -e "$dest" ] && continue             # resolves (incl. `.`, `..`, real dirs) — keep
      is_skill_symlink "$dest" || continue   # only our dangling skill-links qualify
      echo "  - prune   $dest (source skill removed)"
      [ -n "$DRY" ] || rm -f "$dest"
      pruned=$((pruned + 1))
    done
  fi

  echo "= $ROOT: +$added added, -$pruned pruned, $kept already-wired, $shadowed real-copy"
  total_added=$((total_added + added)); total_pruned=$((total_pruned + pruned))
done

echo ""
echo "done: +$total_added symlinks, -$total_pruned pruned across ${#ROOTS[@]} root(s)${DRY:+ (dry-run)}"
