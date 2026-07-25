#!/usr/bin/env bash
#
# wire-skills.sh — keep every runtime's skill AND agent root in sync with keel's
# canonical set, AND mirror the Claude Code root's machine-local skills into the
# other runtimes.
#
# keel is consumed by symlink: one canonical clone, and each runtime's *global* root
# holds one symlink per skill (a dir) or agent (a .md file) pointing back into it.
# This tool creates the symlink for every keel entry missing from a root and prunes
# symlinks whose target was deleted — so a newly-added skill or agent appears with
# zero manual wiring. That is the drift this fixes: roots wired by hand, once, go
# stale the moment a new entry lands, hiding it from that whole runtime.
#
# AGENTS were added 2026-07-24 after exactly that drift bit us: `verifier.md` merged
# to master, git showed it clean, and it existed for NO session on the machine —
# `~/.claude/agents/` is a dir of per-file symlinks with no auto-sync, so a merged
# agent was a silent no-op that read as success. Skills had this tool; agents did not.
#
# Sources synced by default:
#   1. keel's canonical skills (`<clone>/.claude/skills`) → every runtime skill root.
#   2. keel's canonical agents (`<clone>/.claude/agents`) → every runtime agent root.
#   3. the Claude Code root's own *machine-local* skills (real dirs that live only in
#      `~/.claude/skills`, e.g. transcribe-audio) → the OTHER runtime roots (Codex,
#      agents.md). Claude Code discovers those natively; Codex and agents.md read only
#      their one global root, so without this mirror a machine-local skill added after
#      the root was first wired is invisible to them — the same drift, one source over.
# Pass an explicit --src to sync ONLY that dir (skips the machine-local mirror) — e.g.
# when opting a single project's skills into one runtime.
#
# Agent roots default to `~/.claude/agents` ALONE. Codex and agents.md have no global
# agent root of that shape, and fabricating one would create a dir nothing reads.
#
# It is idempotent and SAFE: it only ever creates symlinks into a source and prunes its
# own dangling symlinks. It NEVER touches real copies, other vendors' entries, or a
# runtime's own built-ins (e.g. Codex's `~/.codex/skills/.system/`).
#
# Usage:
#   tooling/wire-skills.sh                      # sync skills + agents into all roots
#   tooling/wire-skills.sh --dry-run            # show what would change; mutate nothing
#   tooling/wire-skills.sh --kind agents        # only agents (or: skills | all — default all)
#   tooling/wire-skills.sh --src <dir>          # sync ONLY <dir> (implies --kind skills, no
#                                               #   machine-local mirror); e.g. a project's
#                                               #   .claude/skills — see docs/cross-runtime-skills.md
#   KEEL_SKILL_ROOTS=/a:/b tooling/wire-skills.sh   # override skill roots (colon-separated)
#   KEEL_AGENT_ROOTS=/a:/b tooling/wire-skills.sh   # override agent roots (colon-separated)
#
# Skills load at invocation time — a newly-wired skill is available on its next use.
# AGENTS load at session start — a newly-wired agent needs a RESTART, so this script
# says so when it links one. Runtimes whose home dir is absent are skipped.
set -euo pipefail

KEEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$KEEL_DIR/.claude/skills"
SRC_OVERRIDDEN=""
CLAUDE_ROOT="$HOME/.claude/skills"   # machine-local skills live here; mirror into the rest
DRY=""
KIND="all"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --kind) KIND="${2:?--kind needs skills|agents|all}"; shift ;;
    --kind=*) KIND="${1#--kind=}" ;;
    --src) SRC="${2:?--src needs a directory}"; SRC_OVERRIDDEN=1; shift ;;
    --src=*) SRC="${1#--src=}"; SRC_OVERRIDDEN=1 ;;
    -h|--help) sed -n '2,49p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "wire-skills: unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

case "$KIND" in
  skills|agents|all) ;;
  *) echo "wire-skills: --kind must be skills, agents or all (got: $KIND)" >&2; exit 2 ;;
esac
# An explicit --src names a skills dir; agents have no equivalent opt-in source.
[ -n "$SRC_OVERRIDDEN" ] && KIND="skills"

[ -d "$SRC" ] || { echo "wire-skills: source skills dir not found: $SRC" >&2; exit 1; }
SRC="$(cd "$SRC" && pwd)"
AGENT_SRC="$KEEL_DIR/.claude/agents"

# Runtime roots. Override with KEEL_SKILL_ROOTS / KEEL_AGENT_ROOTS (colon-separated).
# A root is synced only when its parent (the runtime's home) exists.
if [ -n "${KEEL_SKILL_ROOTS:-}" ]; then
  IFS=':' read -r -a SKILL_ROOTS <<< "$KEEL_SKILL_ROOTS"
else
  SKILL_ROOTS=("$HOME/.claude/skills" "$HOME/.codex/skills" "$HOME/.agents/skills")
fi
if [ -n "${KEEL_AGENT_ROOTS:-}" ]; then
  IFS=':' read -r -a AGENT_ROOTS <<< "$KEEL_AGENT_ROOTS"
else
  AGENT_ROOTS=("$HOME/.claude/agents")
fi

# A dangling symlink is ours to prune only if it pointed at a source of the kind we are
# syncing (keel-direct, a runtime-root hop, or the current --src). Real files/dirs and
# unrelated symlinks never match, so they are never touched.
is_managed_symlink() {
  local link="$1" kind="$2" tgt
  [ -L "$link" ] || return 1
  tgt="$(readlink "$link")"
  if [ "$kind" = "agents" ]; then
    case "$tgt" in
      "$AGENT_SRC"/*|*/.claude/agents/*|*/code/keel/.claude/agents/*) return 0 ;;
      *) return 1 ;;
    esac
  fi
  case "$tgt" in
    "$SRC"/*|*/.claude/skills/*|*/code/keel/.claude/skills/*) return 0 ;;
    *) return 1 ;;
  esac
}

# Link every entry in $1 missing from root $2, for kind $3. Increments added/shadowed.
# An existing symlink at the destination is left as-is; a real file/dir there is a
# shadow the owner must resolve.
link_missing() {
  local src="$1" root="$2" kind="$3" s name dest
  local -a entries=()
  if [ "$kind" = "agents" ]; then
    for s in "$src"/*.md; do [ -f "$s" ] && entries+=("$s"); done
  else
    for s in "$src"/*/; do [ -e "$s" ] && entries+=("$s"); done
  fi
  [ ${#entries[@]} -gt 0 ] || return 0        # nothing to link — glob stayed literal
  for s in "${entries[@]}"; do
    name="$(basename "${s%/}")"
    dest="$root/$name"
    if [ -L "$dest" ]; then
      continue                                # already a symlink — leave it (resolves fine)
    elif [ -e "$dest" ]; then
      echo "  ! shadow  $dest is a real ${kind%s}, not a symlink — left as-is"
      shadowed=$((shadowed + 1)); continue
    fi
    echo "  + link    $dest -> ${s%/}"
    [ -n "$DRY" ] || ln -s "${s%/}" "$dest"
    added=$((added + 1))
    [ "$kind" = "agents" ] && agents_linked=$((agents_linked + 1))
  done
}

# Sync one kind across its roots. $1 = kind, $2 = source dir, rest = roots.
sync_kind() {
  local kind="$1" src="$2"; shift 2
  local -a roots=("$@")
  local ROOT dest
  [ -d "$src" ] || { echo "· skip  $kind (no source dir: $src)"; return 0; }
  for ROOT in "${roots[@]}"; do
    if [ ! -d "$(dirname "$ROOT")" ]; then
      echo "· skip  $ROOT  (runtime not installed)"
      continue
    fi
    [ -d "$ROOT" ] || { [ -n "$DRY" ] || mkdir -p "$ROOT"; }
    added=0; pruned=0; shadowed=0

    # 1. Add a symlink for every source entry missing from this root.
    link_missing "$src" "$ROOT" "$kind"

    # 1b. Mirror the Claude Code root's machine-local SKILLS into the OTHER roots.
    #     Default mode only; never mirror the Claude root into itself. Skills only —
    #     agents have a single root, so there is nothing to mirror.
    if [ "$kind" = "skills" ] && [ -z "$SRC_OVERRIDDEN" ] \
       && [ -d "$CLAUDE_ROOT" ] && [ "$ROOT" != "$CLAUDE_ROOT" ]; then
      link_missing "$CLAUDE_ROOT" "$ROOT" "skills"
    fi

    # 2. Prune our own dangling symlinks (source entry was removed).
    if [ -d "$ROOT" ]; then
      for dest in "$ROOT"/* "$ROOT"/.*; do
        [ -e "$dest" ] && continue             # resolves (incl. `.`, `..`) — keep
        is_managed_symlink "$dest" "$kind" || continue
        echo "  - prune   $dest (source ${kind%s} removed)"
        [ -n "$DRY" ] || rm -f "$dest"
        pruned=$((pruned + 1))
      done
    fi

    echo "= $ROOT: +$added added, -$pruned pruned, $shadowed real-copy"
    total_added=$((total_added + added)); total_pruned=$((total_pruned + pruned))
    total_roots=$((total_roots + 1))
  done
}

total_added=0; total_pruned=0; total_roots=0; agents_linked=0
added=0; pruned=0; shadowed=0

if [ "$KIND" = "skills" ] || [ "$KIND" = "all" ]; then
  sync_kind skills "$SRC" "${SKILL_ROOTS[@]}"
fi
if [ "$KIND" = "agents" ] || [ "$KIND" = "all" ]; then
  sync_kind agents "$AGENT_SRC" "${AGENT_ROOTS[@]}"
fi

echo ""
echo "done: +$total_added symlinks, -$total_pruned pruned across $total_roots root(s)${DRY:+ (dry-run)}"
if [ "$agents_linked" -gt 0 ]; then
  echo "note: $agents_linked agent(s) newly wired — agents load at SESSION START, so restart before using them."
fi
