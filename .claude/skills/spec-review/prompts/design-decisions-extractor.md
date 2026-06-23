# Design Decisions Extractor

Dispatch this agent to mine the structured-decisions JSON for design context the fresh-eyes reviewer needs.

**Agent type:** `general-purpose` (needs Read for JSON parsing; Bash optional for `jq`)
**Model:** `haiku` (extraction task, not reasoning)

**Cross-runtime input.** The `{{DECISIONS_JSON_PATH}}` is the output of either:
- `python3 .claude/skills/claude-sessions/sessions.py extract-decisions --sid <SID> --output <path>` (when `{{RUNTIME}}` is `claude`; the path is repo-relative and also works if the skill is installed globally — use `~/.claude/skills/claude-sessions/sessions.py` in that case)
- Your Codex session equivalent (when `{{RUNTIME}}` is `codex`). keel ships only the Claude session miner; if you drive this from Codex, produce the same JSON schema with your Codex session tooling, or skip decision-mining entirely (the reviewers still run).

Both miners emit the **same JSON schema** so the prompt below is runtime-agnostic. The schema is structured walk over the session, not keyword heuristics:

```json
{
  "session_id": "...",
  "runtime": "claude" | "codex",
  "session_meta": {
    "cwd": "/path/to/project",
    "git_branch": "feat/X",                  // claude only
    "started_at": "ISO-8601",
    "model": "gpt-5.5",                      // codex only
    "approval_policy": "never",              // codex only
    "sandbox_policy": {"type": "..."}        // codex only
  },
  "user_turns": [
    {
      "ts": "ISO-8601",
      "content": "verbatim user text (truncated to 4000 chars)",
      "tools_after": [
        "Edit: file.ts",                     // claude
        "Bash: npm test",                    // claude
        "exec_command: { cmd: ... }",        // codex
        "exec: git status (exit=0)",         // codex
        "apply_patch: ..."                   // codex
      ],
      "files_edited_after": ["a/b/c.ts", ...]
    }
  ],
  "assistant_summary": [
    { "ts": "...", "text": "substantive assistant message (>=40 chars), capped at 1200 chars" }
  ],
  "commits_during_session": [
    { "line": "<sha> <subject> (<date>)" }
  ],
  "files_touched": ["sorted, deduped list of every file the session edited"],
  "tool_call_distribution": { "Bash": 446, "Edit": 35, ... }
}
```

The miner already cracked the runtime-specific JSONL. Your job is purely synthesis.

```
description: "Extract design decisions from structured session JSON"
prompt: |
  You are the design-decisions extractor for spec-review. Your output goes to a
  DIFFERENT reviewer who has never seen this session. They need the WHAT and
  WHY of decisions — not the back-and-forth that led to them.

  ## Inputs
  - Decisions JSON file: {{DECISIONS_JSON_PATH}}
  - Runtime: {{RUNTIME}}   ("claude" or "codex")

  ## How to read it

  Read the file once with the Read tool. The schema is documented above. Walk:
  1. **`user_turns`** — every entry is a discrete user message. The `content`
     field is the verbatim ask. The `tools_after` and `files_edited_after`
     arrays are everything the assistant did BEFORE the next user turn. That's
     your evidence: "User said X, then these tools/files happened" tells you
     whether the decision actually landed.
  2. **`commits_during_session`** — git commits made by this session (mined
     from `Session-Id:` trailer for Claude, or commits in cwd for Codex).
  3. **`files_touched`** — global set of files edited across the whole session.
     Useful for the spec-review reviewer to spot overreach (decision says one
     scope, files say another).
  4. **`assistant_summary`** — last ~30 substantive assistant replies. Use this
     ONLY to fill gaps when the user turn is terse ("yes", "ok", "do it") and
     the previous assistant message defined what they were agreeing to.

  ## Categorization rules

  Classify each meaningful user turn into one of:
  - **Decision** — user picked an option, said "yes do that", "let's go with X",
    or accepted a proposal. Cross-check against `tools_after` to confirm work
    landed; cross-check against `commits_during_session` for stronger evidence.
  - **Rejected alternative** — user said "no", "don't", "too complex",
    "delete that", "revert", or after assistant proposed several options the
    user picked one (the others are rejected).
  - **Correction** — user said "that's wrong", "you misunderstood",
    "no no no", "revert", or any reversal of a prior step. Capture the
    implication: what requirement does the correction reveal?
  - **Scope boundary** — user said "out of scope", "later", "defer", "not now",
    "not in this PR".
  - **Open concern** — user expressed uncertainty: "not sure about", "might
    break", "risky", "could fail if". Mark severity as high/medium/low based
    on what they said, not what you'd guess.
  - **Requirement** — strong statement: "must have", "we need", "it should",
    "critical that", "always", "never".
  - **Gap or ambiguity** — user turns where the response was tool-heavy but
    `commits_during_session` shows nothing landed for that line of work, OR
    where the user asked for something the spec doesn't cover.

  Use the structured `tools_after` to verify "actually shipped" vs "just
  discussed". If `tools_after` for a user-turn is empty AND no commit subject
  matches the topic, that decision is *unverified* — flag it as a gap.

  ## Output Format (max 60 lines)

  ```markdown
  ## Design Decisions Dossier

  ### Session Snapshot
  - Runtime: <claude|codex> | model: <if codex> | branch: <if claude> | cwd: <project>
  - Turns: <N user turns> | Commits during session: <M> | Files touched: <K>

  ### Key Decisions
  - Decision: [what]. Reason: [why]. Evidence: [files-edited or commit subject, if any].
  - ...

  ### Rejected Alternatives
  - Rejected: [what]. Reason: [why it was rejected].
  - ...

  ### User Corrections
  - User corrected: "[short quote]". Implication: [what requirement this reveals].
  - ...

  ### Scope Boundaries
  - In scope: [what]
  - Out of scope: [what]. Deferred to: [when, if stated].

  ### Open Concerns
  - "[quote or paraphrase]" — risk level: [high/medium/low]

  ### Requirements (verbatim user quotes)
  - "[verbatim user quote, max 200 chars]"
  - ...

  ### Gaps & Ambiguities (decisions without landed work)
  - [topic] — discussed but no commit/file evidence. Reviewer should verify the spec
    actually addresses this.
  - ...
  ```

  ## Rules
  - Max 60 lines total. Be ruthlessly concise.
  - Only include items with clear evidence from the JSON.
  - Quote text comes from `user_turns[i].content` — never paraphrase a quote.
  - Do NOT include implementation details, raw code, or full file paths
    (basenames in evidence are fine).
  - Do NOT editorialize — extract and categorize, nothing more.
  - If a category has 0 items, omit the section entirely.
  - "Evidence" should be 1-3 short markers (e.g. `apps/X.ts edited`, commit
    subject, exec cmd). Skip evidence for items where it would be noise.
```
</content>
