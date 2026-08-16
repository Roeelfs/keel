#!/usr/bin/env python3
"""Validate a bounded procedural-worker pointer result."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


KEYS = {"schema", "pass_id", "status", "head_sha", "artifact", "unexpected_writes"}
STATUSES = {"pass", "fail", "blocked"}
SUMMARY_KEYS = {
    "schema",
    "pass_id",
    "status",
    "head_sha",
    "tracked_diff_sha256_before",
    "tracked_diff_sha256_after",
    "command_results",
    "environment",
    "blocker",
}
COMMAND_KEYS = {"id", "status", "exit_code", "log", "decisive_excerpt"}
COMMAND_STATUSES = {"pass", "fail", "blocked"}
MAX_SUMMARY_BYTES = 65_536
MAX_EXCERPT_BYTES = 2_048

# An evidence directory is named <ticket>-<pass-kind>-<short-sha> (see
# prompts/procedural-worker.md). The stem <ticket>-<pass-kind> is the budget key:
# it is what a lane rename cannot change.
EVIDENCE_DIR_RE = re.compile(r"^(?P<stem>.+)-(?P<sha>[0-9a-f]{7,40})$")
# The third FAILING pass on one stem is the treadmill. Two is a correction cycle.
MAX_FAILING_PASSES = 3


def _inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def validate_summary(path: Path, pointer: dict[str, object]) -> list[str]:
    try:
        if path.stat().st_size > MAX_SUMMARY_BYTES:
            return [f"artifact exceeds {MAX_SUMMARY_BYTES} bytes"]
    except OSError as exc:
        return [f"artifact cannot be inspected: {exc}"]
    try:
        summary = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"artifact must be readable JSON: {exc}"]
    if not isinstance(summary, dict) or set(summary) != SUMMARY_KEYS:
        return [f"artifact keys must be exactly {sorted(SUMMARY_KEYS)}"]
    errors: list[str] = []
    if summary["schema"] != "procedural-summary/v1":
        errors.append("unsupported artifact schema")
    for key in ("pass_id", "status", "head_sha"):
        if summary[key] != pointer[key]:
            errors.append(f"artifact {key} does not match pointer")
    for key in ("tracked_diff_sha256_before", "tracked_diff_sha256_after"):
        if not isinstance(summary[key], str) or not re.fullmatch(r"[0-9a-f]{64}", summary[key]):
            errors.append(f"artifact {key} must be a SHA-256 hex digest")
    if summary["tracked_diff_sha256_before"] != summary["tracked_diff_sha256_after"]:
        errors.append("tracked diff changed during the worker pass")
    command_results = summary["command_results"]
    if not isinstance(command_results, list):
        errors.append("artifact command_results must be a list")
        command_results = []
    artifact_dir = path.resolve().parent
    command_statuses: list[str] = []
    for index, result in enumerate(command_results):
        prefix = f"command_results[{index}]"
        if not isinstance(result, dict) or set(result) != COMMAND_KEYS:
            errors.append(f"{prefix} keys must be exactly {sorted(COMMAND_KEYS)}")
            continue
        if not isinstance(result["id"], str) or not result["id"].strip():
            errors.append(f"{prefix}.id is required")
        status = result["status"]
        if status not in COMMAND_STATUSES:
            errors.append(f"{prefix}.status is invalid")
        else:
            command_statuses.append(status)
        exit_code = result["exit_code"]
        if status == "pass" and exit_code != 0:
            errors.append(f"{prefix} pass requires exit_code 0")
        elif status == "fail" and (not isinstance(exit_code, int) or exit_code == 0):
            errors.append(f"{prefix} fail requires a nonzero integer exit_code")
        elif status == "blocked" and exit_code is not None:
            errors.append(f"{prefix} blocked requires a null exit_code")
        log = result["log"]
        if not isinstance(log, str) or not Path(log).is_absolute():
            errors.append(f"{prefix}.log must be an absolute path")
        else:
            resolved_log = Path(log).resolve()
            if not _inside(resolved_log, artifact_dir):
                errors.append(f"{prefix}.log must stay inside the artifact directory")
            elif not resolved_log.is_file():
                errors.append(f"{prefix}.log does not exist")
        excerpt = result["decisive_excerpt"]
        if not isinstance(excerpt, str):
            errors.append(f"{prefix}.decisive_excerpt must be a string")
        elif len(excerpt.encode("utf-8")) > MAX_EXCERPT_BYTES:
            errors.append(f"{prefix}.decisive_excerpt exceeds {MAX_EXCERPT_BYTES} bytes")
    if not isinstance(summary["environment"], str) or not summary["environment"].strip():
        errors.append("artifact environment is required")
    blocker = summary["blocker"]
    status = summary["status"]
    if status == "pass":
        if not command_results or any(item != "pass" for item in command_statuses):
            errors.append("pass requires at least one command and every command to pass")
        if blocker is not None:
            errors.append("pass requires blocker null")
    elif status == "fail":
        if "fail" not in command_statuses:
            errors.append("fail requires at least one failed command")
        if blocker is not None:
            errors.append("fail requires blocker null")
    elif status == "blocked":
        if not isinstance(blocker, dict) or set(blocker) != {"reason", "resume_key"}:
            errors.append("blocked requires exactly reason and resume_key")
        elif any(not isinstance(blocker[key], str) or not blocker[key].strip() for key in blocker):
            errors.append("blocked reason and resume_key are required")
    return errors


def validate_correction(text: str, previous_text: str) -> list[str]:
    errors: list[str] = []
    try:
        current = json.loads(text)
        previous = json.loads(previous_text)
    except json.JSONDecodeError as exc:
        return [f"correction pointers must be JSON objects: {exc.msg}"]
    if not isinstance(current, dict) or not isinstance(previous, dict):
        return ["correction pointers must be JSON objects"]
    for key in ("pass_id", "head_sha", "artifact"):
        if current.get(key) == previous.get(key):
            errors.append(f"correction must use a distinct {key}")
    return errors


def _summary_status(directory: Path) -> str | None:
    """Terminal status recorded in a sibling evidence dir, or None if unreadable.

    Legacy directories predating the naming contract, half-written passes, and
    dirs whose summary is absent or malformed all return None. An unreadable
    sibling is NOT counted as a failure — absence of evidence is not evidence of
    a failing pass.
    """
    for name in ("procedural-summary.json", "summary.json"):
        candidate = directory / name
        if not candidate.is_file():
            continue
        try:
            value = json.loads(candidate.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(value, dict):
            status = value.get("status")
            return status.lower() if isinstance(status, str) else None
    return None


def validate_pass_budget(pointer: dict[str, object], evidence_root: Path | None = None) -> list[str]:
    """Refuse a third FAILING pass against one <ticket>-<pass-kind> stem.

    This runs in the validator the root already invokes on every procedural
    result, which is downstream of all four lane-dispatch substrates (headless
    `spawn-lane.sh`, raw `codex exec`, native `Agent`/`Workflow`, native Codex
    `spawn_agent`). A preflight at any single spawn path would cover one of the
    four and be evaded by substrate choice.

    Only repeated FAILURE counts. Many passing gates on one ticket is
    convergence, or the sequential runtime carve-out where each ship is verified
    green — neither is the treadmill this bounds.
    """
    if str(pointer.get("status", "")).lower() != "fail":
        return []
    artifact = pointer.get("artifact")
    if not isinstance(artifact, str):
        return []
    current = Path(artifact).parent
    root = evidence_root or current.parent
    match = EVIDENCE_DIR_RE.match(current.name)
    if not match:
        # Non-conforming basename: the budget key does not exist, so there is
        # nothing to count. validate_text warns about the naming separately.
        return []
    stem = match.group("stem")
    try:
        siblings = sorted(p for p in root.glob(f"{stem}-*") if p.is_dir() and p != current)
    except OSError:
        return []
    failing = [p for p in siblings if _summary_status(p) == "fail"]
    if len(failing) + 1 < MAX_FAILING_PASSES:
        return []
    names = ", ".join(p.name for p in failing)
    return [
        f"pass budget: this is failing pass #{len(failing) + 1} for '{stem}' "
        f"(prior failing passes: {names}). One fix per gate run is the treadmill — "
        "each pass costs a full lane and returns one check. Batch EVERY open failure "
        "from the decisive excerpts into a single fix mission, or escalate to the "
        "operator. Re-running the gate on another single fix is not the next move."
    ]


def validate_text(text: str, expected_sha: str | None = None) -> list[str]:
    errors: list[str] = []
    if len(text.encode("utf-8")) > 1024:
        errors.append("result exceeds 1024 UTF-8 bytes")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return errors + [f"result must be one JSON object: {exc.msg}"]
    if not isinstance(value, dict):
        return errors + ["result must be a JSON object"]
    if set(value) != KEYS:
        errors.append(f"result keys must be exactly {sorted(KEYS)}")
        return errors
    if value["schema"] != "procedural-worker/v1":
        errors.append("unsupported schema")
    if not isinstance(value["pass_id"], str) or not value["pass_id"].strip():
        errors.append("pass_id is required")
    if value["status"] not in STATUSES:
        errors.append("invalid status")
    if not isinstance(value["head_sha"], str) or not re.fullmatch(r"[0-9a-f]{7,64}", value["head_sha"]):
        errors.append("head_sha must be a hexadecimal SHA")
    elif expected_sha and value["head_sha"] != expected_sha:
        errors.append("head_sha does not match the pinned SHA")
    artifact = value["artifact"]
    if not isinstance(artifact, str) or not Path(artifact).is_absolute():
        errors.append("artifact must be an absolute path")
    elif not Path(artifact).is_file():
        errors.append("artifact does not exist")
    else:
        errors.extend(validate_summary(Path(artifact), value))
    if value["unexpected_writes"] != []:
        errors.append("unexpected_writes must be empty")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--previous-result", type=Path)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        help="directory holding the <ticket>-<pass-kind>-<sha> dirs; defaults to the artifact's grandparent",
    )
    args = parser.parse_args(argv[1:])
    text = args.result.read_text()
    errors = validate_text(text, args.expected_sha)
    if args.previous_result:
        errors.extend(validate_correction(text, args.previous_result.read_text()))
    try:
        pointer = json.loads(text)
    except json.JSONDecodeError:
        pointer = None
    if isinstance(pointer, dict):
        errors.extend(validate_pass_budget(pointer, args.evidence_root))
        artifact = pointer.get("artifact")
        if isinstance(artifact, str) and not EVIDENCE_DIR_RE.match(Path(artifact).parent.name):
            print(
                f"WARN: artifact_dir '{Path(artifact).parent.name}' is not "
                "<ticket>-<pass-kind>-<short-sha>; this pass is invisible to the pass budget",
                file=sys.stderr,
            )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {args.result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
