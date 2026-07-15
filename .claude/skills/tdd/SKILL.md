---
name: tdd
description: Test-driven development. Use when the user wants to build features or fix bugs test-first, mentions "red-green-refactor", or wants integration tests.
---

# Test-Driven Development

TDD is the red → green loop. This skill is the reference that makes that loop produce tests worth keeping: what a good test is, where tests go, the anti-patterns, and the rules of the loop. Every section applies on every cycle — consult them before and during the loop, not after.

When exploring the codebase, read `CONTEXT.md` (if it exists) so test names and interface vocabulary match the project's domain language, and respect ADRs in the area you're touching.

## What a good test is

Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't. A good test reads like a specification — "user can checkout with valid cart" tells you exactly what capability exists — and survives refactors because it doesn't care about internal structure.

See [tests.md](tests.md) for examples and [mocking.md](mocking.md) for mocking guidelines.

## Seams — where tests go

A **seam** is the public boundary you test at: the interface where you observe behavior without reaching inside. Tests live at seams, never against internals.

**Test only at pre-agreed seams.** Before writing any test, write down the seams under test and confirm them with the user. No test is written at an unconfirmed seam. You can't test everything — agreeing the seams up front is how testing effort lands on the critical paths and complex logic instead of every edge case.

Ask: "What's the public interface, and which seams should we test?"

When shaping the interface behind a seam, run the `/codebase-design` skill for the deep-module vocabulary and the testability-through-interface checks.

## Anti-patterns

- **Implementation-coupled** — mocks internal collaborators, tests private methods, or verifies through a side channel (querying the database instead of using the interface). The tell: the test breaks when you refactor but behavior hasn't changed.
- **Tautological** — the assertion recomputes the expected value the way the code does (`expect(add(a, b)).toBe(a + b)`, a snapshot derived by hand the same way, a constant asserted equal to itself), so it passes by construction and can never disagree with the code. Expected values must come from an independent source of truth — a known-good literal, a worked example, the spec.
- **Horizontal slicing** — writing all tests first, then all implementation. Bulk tests verify _imagined_ behavior: you test the _shape_ of things rather than user-facing behavior, the tests go insensitive to real changes, and you commit to test structure before understanding the implementation. Work in **vertical slices** instead — one test → one implementation → repeat, each test a **tracer bullet** that responds to what the last cycle taught you.

## Rules of the loop

- **Red before green.** Write the failing test first, then only enough code to pass it. Don't anticipate future tests or add speculative features.
- **One slice at a time.** One seam, one test, one minimal implementation per cycle.
- **Refactoring is not part of the loop.** It belongs to the review stage (run `/review`), not the red → green implementation cycle.

## Test-runner & iteration conventions

- **Test runner:** if your test runner can choose a worker model and a worker cap, prefer process-isolated workers (e.g. vitest `pool: 'forks'`) with a bounded `maxWorkers` over thread-pool workers. Native addons can segfault during worker-thread teardown on some platforms, and an uncapped worker pool can saturate every core and starve the rest of the machine. Once your project settles on these values, don't change them casually.
- **Targeted-first iteration:** loop on the narrow set of tests your change touches (a single file or a single named test), and run the full project verify gate (the command your project documents) ONCE at the end, never in the inner loop. Repeatedly firing the whole suite while iterating wastes time and can pin the machine.
- **Partial mocks:** a partial `vi.mock(module)` MUST spread `...(await vi.importActual())` — see [mocking.md](mocking.md).
- **TDD is for clean seams, not runtime paths.** Use it where there's a deterministic, in-process seam you can drive directly (pure logic, classifiers/extractors behind a test double, data rollups). For runtime paths that only exhibit real behavior under live traffic (request handlers, dispatch, sandbox/worker lifecycle, webhooks, RPC), green tests are necessary but NOT sufficient — the real gate is exercising the path against real traffic and confirming the outcome in your logs and your system's actual state.
