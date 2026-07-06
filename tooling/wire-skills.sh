#!/usr/bin/env bash
#
# wire-skills.sh — keep every runtime's skill root in sync with keel's canonical set,
# AND mirror the Claude Code root's machine-local skills into the other runtimes.
#
# keel is consumed by symlink: one canonical clone, and each runtime's *global* skill
# root holds one symlink per skill pointing back into it. This tool creates the symlink
# for every keel skill missing from a root and prunes skill-symlinks whose target was
# deleted — so a newly-added skill (e.g. root-cause-analysis) appears in EVERY runtime
# with zero manual wiring. That is the drift this fixes: roots wired by hand, once, go
# stale the moment a new skill lands, hiding it from that whole runtime.
#
# Two sources are synced by default:
#   1. keel's canonical set (`<clone>/.claude/skills`) → every runtime root.
#   2. the Claude Code root's own *machine-local* skills (real dirs that live only in
#      `~/.claude/skills`, e.g. transcribe-audio) → the OTHER runtime roots (Codex,
#      agents.md). Claude Code discovers those natively; Codex and agents.md read only
#      their one global root, so without this mirror a machine-local skill added after
#      the root was first wired is invisible to them — the same drift, one source over.
# Pass an explicit --src to sync ONLY that dir (skips the machine-local mirror) — e.g.
# when opting a single project's skills into one runtime.
#
# It is idempotent and SAFE: it only ever creates symlinks into a source and prunes its
# own dangling skill-symlinks. It NEVER touches real skill copies, other vendors' skills,
# or a runtime's own built-ins (e.g. Codex's `~/.codex/skills/.system/`).
#
# Usage:
#   tooling/wire-skills.sh                      # sync keel + machine-local into all roots
#   tooling/wire-skills.sh --dry-run            # show what would change; mutate nothing
#   tooling/wire-skills.sh --src <dir>          # sync ONLY <dir> (no machine-local mirror);
#                                               #   e.g. a project's .claude/skills — see
#                                               #   docs/cross-runtime-skills.md for scoping
#   KEEL_SKILL_ROOTS=/a:/b tooling/wire-skills.sh   # override the target roots (colon-separated)
#
# Skills load at invocation time — a newly-wired skill is available on its next use; no
# restart needed. Runtimes whose home dir is absent (not installed) are skipped.
set -euo pipefail

KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$KEEL_DIR/.claude/skills"
SRC_OVERRIDDEN=""
CLAUDE_ROOT="$HOME/.claude/skills"   # machine-local skills live here; mirror into the rest
DRY=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --src) SRC="${2:?--src needs a directory}"; SRC_OVERRIDDEN=1; shift ;;
    --src=*) SRC="${1#--src=}"; SRC_OVERRIDDEN=1 ;;
    -h|--help) sed -n '2,37p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
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

# Link every skill dir in $1 that is missing from root $2. Increments globals added/shadowed.
# An existing symlink at the destination is left as-is; a real dir there is a shadow the
# owner must resolve. Symlinked source entries (e.g. keel skills already in the Claude
# root) resolve fine and are skipped at the destination when already wired.
link_missing() {
  local src="$1" root="$2" s name dest
  for s in "$src"/*/; do
    [ -e "$s" ] || continue                 # no skill dirs — glob stayed literal
    name="$(basename "$s")"
    dest="$root/$name"
    if [ -L "$dest" ]; then
      continue                              # already a symlink — leave it (resolves fine)
    elif [ -e "$dest" ]; then
      echo "  ! shadow  $dest is a real dir, not a symlink — left as-is"
      shadowed=$((shadowed + 1)); continue  # a real copy shadows the canonical skill; owner decides
    fi
    echo "  + link    $dest -> $src/$name"
    [ -n "$DRY" ] || ln -s "$src/$name" "$dest"
    added=$((added + 1))
  done
}

total_added=0; total_pruned=0
for ROOT in "${ROOTS[@]}"; do
  if [ ! -d "$(dirname "$ROOT")" ]; then
    echo "· skip  $ROOT  (runtime not installed)"
    continue
  fi
  [ -d "$ROOT" ] || { [ -n "$DRY" ] || mkdir -p "$ROOT"; }
  added=0; pruned=0; shadowed=0

  # 1. Add a symlink for every source skill missing from this root.
  link_missing "$SRC" "$ROOT"

  # 1b. Mirror the Claude Code root's machine-local skills into the OTHER roots. Default
  #     mode only (an explicit --src means "just this dir"); never mirror the Claude root
  #     into itself. keel skills already linked in step 1 are skipped as already-wired, so
  #     only the real machine-local dirs (which live nowhere else) get added.
  if [ -z "$SRC_OVERRIDDEN" ] && [ -d "$CLAUDE_ROOT" ] && [ "$ROOT" != "$CLAUDE_ROOT" ]; then
    link_missing "$CLAUDE_ROOT" "$ROOT"
  fi

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

  echo "= $ROOT: +$added added, -$pruned pruned, $shadowed real-copy"
  total_added=$((total_added + added)); total_pruned=$((total_pruned + pruned))
done

echo ""
echo "done: +$total_added symlinks, -$total_pruned pruned across ${#ROOTS[@]} root(s)${DRY:+ (dry-run)}"
