#!/usr/bin/env bash
# H6 (improve-harness 2026-07-06): compaction wipes file read-state — 15
# "File has not been read yet" errors clustered right after compaction boundaries.
# SessionStart(source=compact) additive context; never blocks.
cat <<'MSG'
<system-reminder>
Compaction wiped file read-state: Read any file (even one you edited minutes ago)
before its first Edit/Write this segment — batch the Reads. Also re-read the last
standing mandate in the transcript before asking the user anything.
</system-reminder>
MSG
exit 0
