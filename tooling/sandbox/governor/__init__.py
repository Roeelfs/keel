"""Machine governor (phase 1, keel side). docs/specs/2026-09-29-machine-governor.md.

Every module here defaults to shadow behavior: decisions and reclaim actions are computed and
logged, but nothing kills or deletes unless the caller explicitly passes enforce=True/--live, and
`governor-act` additionally checks `Policy().governor_mode == 'enforce'` before any live side effect.
"""
