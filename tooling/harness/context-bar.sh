#!/bin/bash

# Color theme: gray, orange, blue, teal, green, lavender, rose, gold, slate, cyan
COLOR="blue"

# Color codes
C_RESET='\033[0m'
C_GRAY='\033[38;5;245m'  # explicit gray for default text
C_BAR_EMPTY='\033[38;5;238m'
case "$COLOR" in
    orange)   C_ACCENT='\033[38;5;173m' ;;
    blue)     C_ACCENT='\033[38;5;74m' ;;
    teal)     C_ACCENT='\033[38;5;66m' ;;
    green)    C_ACCENT='\033[38;5;71m' ;;
    lavender) C_ACCENT='\033[38;5;139m' ;;
    rose)     C_ACCENT='\033[38;5;132m' ;;
    gold)     C_ACCENT='\033[38;5;136m' ;;
    slate)    C_ACCENT='\033[38;5;60m' ;;
    cyan)     C_ACCENT='\033[38;5;37m' ;;
    *)        C_ACCENT="$C_GRAY" ;;  # gray: all same color
esac

input=$(cat)

# --- Usage snapshot writer (rate_limits -> per-account JSON) ---
# Detached and fully silenced: never delays, alters, or fails the statusline output.
# Skips silently when rate_limits or an account identity is unavailable. Writes no tokens.
_usage_snapshot() {
    local rl
    rl=$(printf '%s' "$input" | jq -c '
        .rate_limits // empty
        | {five_hour: (.five_hour // null), seven_day: (.seven_day // null)}
        | map_values(if type == "object" and (.used_percentage|type) == "number"
                     then {used_percentage, resets_at: (if (.resets_at|type) == "number" then .resets_at else null end)}
                     else null end)
        | select(.five_hour != null or .seven_day != null)' 2>/dev/null) || return 0
    [[ -n "$rl" ]] || return 0

    local dir="${CLAUDE_USAGE_DIR:-$HOME/.claude/run/claude-usage}"
    umask 077
    mkdir -p "$dir" 2>/dev/null || return 0

    # Identity: the payload carries none (docs, 2026-11-19), so use `claude auth status`,
    # cached per config dir for 10 min so redraws do not spawn it each time.
    local cfg="${CLAUDE_CONFIG_DIR:-$HOME/.claude}" key cache email="" mtime now
    key=$(printf '%s' "$cfg" | cksum | cut -d' ' -f1)
    cache="$dir/.identity-$key"
    now=$(date +%s)
    if [[ -f "$cache" ]]; then
        mtime=$(stat -f %m "$cache" 2>/dev/null || stat -c %Y "$cache" 2>/dev/null)
        [[ -n "$mtime" && $((now - mtime)) -lt 600 ]] && email=$(<"$cache")
    fi
    if [[ -z "$email" ]]; then
        email=$(claude auth status --json 2>/dev/null | jq -r '.email // empty' 2>/dev/null)
        [[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || return 0
        printf '%s' "$email" > "$cache.$$" && mv -f "$cache.$$" "$cache"
    fi
    [[ "$email" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$ ]] || return 0

    local out="$dir/$email.json" tmp="$dir/.$email.json.$$"
    jq -n --arg a "$email" --argjson rl "$rl" --argjson t "$now" \
        '{account: $a, five_hour: $rl.five_hour, seven_day: $rl.seven_day, written_at: $t}' \
        > "$tmp" 2>/dev/null && mv -f "$tmp" "$out" || rm -f "$tmp"
}
( _usage_snapshot ) </dev/null >/dev/null 2>&1 &

# Extract model, directory, session name, and cwd
model=$(echo "$input" | jq -r '.model.display_name // .model.id // "?"')
session_name=$(echo "$input" | jq -r '.session.name // .session_name // empty')
cwd=$(echo "$input" | jq -r '.cwd // empty')
dir=$(basename "$cwd" 2>/dev/null || echo "?")

# Get git branch, uncommitted file count, and sync status
branch=""
git_status=""
if [[ -n "$cwd" && -d "$cwd" ]]; then
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    if [[ -n "$branch" ]]; then
        # Count uncommitted files
        file_count=$(git -C "$cwd" --no-optional-locks status --porcelain -uall 2>/dev/null | wc -l | tr -d ' ')

        # Check sync status with upstream
        sync_status=""
        upstream=$(git -C "$cwd" rev-parse --abbrev-ref @{upstream} 2>/dev/null)
        if [[ -n "$upstream" ]]; then
            # Get last fetch time
            fetch_head="$cwd/.git/FETCH_HEAD"
            fetch_ago=""
            if [[ -f "$fetch_head" ]]; then
                fetch_time=$(stat -f %m "$fetch_head" 2>/dev/null || stat -c %Y "$fetch_head" 2>/dev/null)
                if [[ -n "$fetch_time" ]]; then
                    now=$(date +%s)
                    diff=$((now - fetch_time))
                    if [[ $diff -lt 60 ]]; then
                        fetch_ago="<1m ago"
                    elif [[ $diff -lt 3600 ]]; then
                        fetch_ago="$((diff / 60))m ago"
                    elif [[ $diff -lt 86400 ]]; then
                        fetch_ago="$((diff / 3600))h ago"
                    else
                        fetch_ago="$((diff / 86400))d ago"
                    fi
                fi
            fi

            counts=$(git -C "$cwd" rev-list --left-right --count HEAD...@{upstream} 2>/dev/null)
            ahead=$(echo "$counts" | cut -f1)
            behind=$(echo "$counts" | cut -f2)
            if [[ "$ahead" -eq 0 && "$behind" -eq 0 ]]; then
                if [[ -n "$fetch_ago" ]]; then
                    sync_status="synced ${fetch_ago}"
                else
                    sync_status="synced"
                fi
            elif [[ "$ahead" -gt 0 && "$behind" -eq 0 ]]; then
                sync_status="${ahead} ahead"
            elif [[ "$ahead" -eq 0 && "$behind" -gt 0 ]]; then
                sync_status="${behind} behind"
            else
                sync_status="${ahead} ahead, ${behind} behind"
            fi
        else
            sync_status="no upstream"
        fi

        # Build git status string (compact)
        if [[ "$file_count" -eq 0 ]]; then
            git_status="(clean, ${sync_status})"
        else
            git_status="(${file_count}Δ, ${sync_status})"
        fi
    fi
fi

# Get transcript path for context calculation and last message feature
transcript_path=$(echo "$input" | jq -r '.transcript_path // empty')

# Get context window size from JSON (accurate), but calculate tokens from transcript
# (more accurate than total_input_tokens which excludes system prompt/tools/memory)
# See: github.com/anthropics/claude-code/issues/13652
max_context=$(echo "$input" | jq -r '.context_window.context_window_size // 200000')
max_k=$((max_context / 1000))
if [[ $max_k -ge 1000 ]]; then
    max_display="$((max_k / 1000))M"
else
    max_display="${max_k}k"
fi

# Calculate context bar from transcript
if [[ -n "$transcript_path" && -f "$transcript_path" ]]; then
    context_length=$(jq -s '
        map(select(.message.usage and .isSidechain != true and .isApiErrorMessage != true)) |
        last |
        if . then
            (.message.usage.input_tokens // 0) +
            (.message.usage.cache_read_input_tokens // 0) +
            (.message.usage.cache_creation_input_tokens // 0)
        else 0 end
    ' < "$transcript_path")

    # 20k baseline: includes system prompt (~3k), tools (~15k), memory (~300),
    # plus ~2k for git status, env block, XML framing, and other dynamic context
    baseline=20000
    bar_width=10

    if [[ "$context_length" -gt 0 ]]; then
        pct=$((context_length * 100 / max_context))
        pct_prefix=""
    else
        # At conversation start, ~20k baseline is already loaded
        pct=$((baseline * 100 / max_context))
        pct_prefix="~"
    fi

    [[ $pct -gt 100 ]] && pct=100

    filled=$((pct * bar_width / 100))
    [[ $filled -gt $bar_width ]] && filled=$bar_width
    bar=""
    for ((i=0; i<bar_width; i++)); do
        if [[ $i -lt $filled ]]; then
            bar+="${C_ACCENT}━${C_RESET}"
        else
            bar+="${C_BAR_EMPTY}─${C_RESET}"
        fi
    done

    ctx="${bar} ${C_GRAY}${pct_prefix}${pct}% of ${max_display}"
else
    # Transcript not available yet - show baseline estimate
    baseline=20000
    bar_width=10
    pct=$((baseline * 100 / max_context))
    [[ $pct -gt 100 ]] && pct=100

    filled=$((pct * bar_width / 100))
    [[ $filled -gt $bar_width ]] && filled=$bar_width
    bar=""
    for ((i=0; i<bar_width; i++)); do
        if [[ $i -lt $filled ]]; then
            bar+="${C_ACCENT}━${C_RESET}"
        else
            bar+="${C_BAR_EMPTY}─${C_RESET}"
        fi
    done

    ctx="${bar} ${C_GRAY}~${pct}%"
fi

# Line 1: Model | Dir | Branch (git status)
line1="${C_ACCENT}${model}${C_GRAY} | 📁${dir}"
[[ -n "$branch" ]] && line1+=" | 🔀${branch} ${git_status}"

# Line 2: Context + session name
line2="${C_GRAY}${pct_prefix:-~}${pct}% of ${max_display}"
[[ -n "$session_name" ]] && line2+=" | 📌 ${C_ACCENT}${session_name}"
line2+="${C_RESET}"

printf '%b\n' "$line1"
printf '%b\n' "$line2"
