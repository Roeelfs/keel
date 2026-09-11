# Shared resource budget implementation plan

The approved design extends `with-heavy-lock` to constrain the complete job and enforce its use across both supported agent runtimes.

1. Add real subprocess regressions before implementation: serialization, nested ownership, bounded deferral, aggregate RSS and worker caps. Fixtures allocate only tens of MiB and own all processes they terminate.
2. Replace the shell semaphore implementation with a small Python supervisor using the existing slot file. Split policy/process observation into `heavy_resources.py`, supervision into `heavy_runner.py`, and transitive Node CLI worker caps into `heavy_node.cjs`. Preserve the wrapper command. Default to one job, two workers, a 6 GiB aggregate RSS ceiling, a 20% pressure threshold and a bounded 15-second admission wait. These are conservative initial limits.
3. Update the existing heavy-command hook and its tests, then register the same hook in the supported native Codex `PreToolUse`/`Bash` surface. Do not modify security approval settings. A missing runner must refuse a recognized heavy job. Light commands and quoted documentation remain unaffected.
4. Run the old and new bounded fixture suites, replay real command records through the classifier without executing those commands, then perform one primary review and one narrow closure review over changed seams. Fix correctness findings only.
5. Install the verified canonical files and hook registration with a reversible backup. Confirm one small real Vitest invocation sees the caps, confirm native hook execution, and verify the two existing Claude sessions remain intact. The existing VM is an optional hard-limit backend; do not disrupt its running services or claim a hard memory guarantee from native RSS sampling.

No production deployment or full product verification suite belongs to this harness change. Existing receipt reuse is retained without introducing a new result cache. Public files contain only generic mechanisms; host-specific evidence and settings remain private.
