# Native dispatch tail

Every native `Agent`/`Task` prompt ends with the three lines below, copied verbatim after a `---`
line. Every Workflow `agent()` prompt gets them from the script's own `CONTRACT_TAIL` constant.

Why: `agent-prompt-normalizer.py` appends these same lines to any prompt that lacks them. In auto
mode a rewritten input is not the input the classifier reviewed, so the call is refused ("gave no
verdict ... a hook changed this call's input"). In auto mode the hook therefore denies a prompt
that is missing them and names the lines to add. A prompt that already carries them passes
untouched. An untyped or `general-purpose` dispatch also passes `model` explicitly (`sonnet` for
mechanical work). The hook would otherwise set it, and that rewrite trips the same refusal.

```text
---
You are a leaf agent: do NOT spawn sub-agents or Workflows; do the work inline and return.

Return a CONDENSED SUMMARY of conclusions (target 1,000-2,000 tokens), never a transcript, raw tool output, or file bodies - the caller re-reads your return on every subsequent turn. Ground-truth identifiers (exact error text, file:line anchors, commit SHAs, ticket IDs, command strings) are quoted VERBATIM and are never compressed away to hit that target. If the full detail matters, write it to a file and return the path.

If you write scratch files, create your OWN uniquely-named subdirectory first - the scratchpad is shared by every lane of this session, not per-lane, and sibling lanes silently overwrite same-named files.
```
