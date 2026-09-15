#!/usr/bin/env python3
"""Install the opt-in resource governor without replacing unrelated hook config."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone

SOURCE_ROOT = Path(__file__).resolve().parent
HOOK_SOURCE = SOURCE_ROOT.parents[1] / ".claude" / "hooks"
CLAUDE_HOOKS = ("serialize-heavy-ops.py", "heavy_command.py")
RUNTIME_FILES = ("with-heavy-lock", "heavy_resources.py", "heavy_runner.py", "heavy_node.cjs", "heavy_child.py")
RESOURCE_SCRIPT = "serialize-heavy-ops.py"

def load_json(path, default):
    if not path.exists(): return default
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error: raise ValueError(f"invalid JSON: {path}: {error}")
    if not isinstance(value, dict): raise ValueError(f"expected JSON object: {path}")
    return value

def command_for(python, script, runtime):
    """Preserve stdin, name the runtime, and map an unavailable/broken launcher to hook denial (2)."""
    return ("/bin/sh -c 'py=$1; script=$2; shift 2; if [ ! -x \"$py\" ] || [ ! -f \"$script\" ]; then "
            "echo \"resource guard unavailable: interpreter or script is missing\" >&2; exit 2; fi; "
            "\"$py\" \"$script\" \"$@\"; rc=$?; if [ \"$rc\" -eq 0 ] || [ \"$rc\" -eq 2 ]; then exit \"$rc\"; fi; "
            "echo \"resource guard unavailable: launcher failed\" >&2; exit 2' resource-hook "
            + shlex.quote(str(python)) + " " + shlex.quote(str(script)) + " --runtime " + shlex.quote(runtime))

def hook_entry(command):
    return {"matcher": "^Bash$", "hooks": [{"type": "command", "command": command, "timeout": 3,
                                                  "statusMessage": "Checking machine-heavy command"}]}

def matcher_applies_to_bash(value):
    try: return isinstance(value, str) and re.fullmatch(value, "Bash") is not None
    except re.error: return False

def resource_handler(handler):
    if not isinstance(handler, dict):
        return False
    try:
        words = shlex.split(str(handler.get("command", "")), comments=True)
    except ValueError:
        return False
    names = [Path(word).name for word in words]
    scripts = {RESOURCE_SCRIPT, "serialize-heavy-ops.sh"}
    return bool(names and (names[0] in scripts or
                (names[0] in {"python", "python3", "sh", "bash", "zsh", "_run.sh"}
                 and any(name in scripts for name in names[1:]))))

def applicable_resource_handlers(groups):
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or not matcher_applies_to_bash(group.get("matcher")): continue
        for handler in group.get("hooks", []) if isinstance(group.get("hooks"), list) else []:
            if resource_handler(handler): yield group, handler

def mutate_codex(config, command):
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise ValueError("Codex hooks must be an object")
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list): raise ValueError("Codex hooks.PreToolUse must be an array")
    for group in groups:
        if not isinstance(group, dict) or group.get("matcher") != "^Bash$" or not isinstance(group.get("hooks"), list): continue
        for handler in group["hooks"]:
            if resource_handler(handler):
                changed = handler.get("command") != command
                if changed: handler["command"] = command
                return changed
    groups.append(hook_entry(command)); return True

def mutate_claude(config, command):
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise ValueError("Claude hooks must be an object")
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list): raise ValueError("Claude hooks.PreToolUse must be an array")
    existing = next(applicable_resource_handlers(groups), None)
    if existing:
        _, handler = existing
        changed = handler.get("command") != command or handler.get("async", False)
        if changed:
            handler["command"] = command
            handler["async"] = False
        return bool(changed)
    for group in groups:
        if isinstance(group, dict) and matcher_applies_to_bash(group.get("matcher")) and isinstance(group.get("hooks"), list):
            group["hooks"].append({"type": "command", "command": command, "async": False}); return True
    groups.append({"matcher": "Bash", "hooks": [{"type": "command", "command": command, "async": False}]}); return True

def backup(path):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = path.with_name(path.name + ".resource-hooks." + stamp + ".bak")
    if path.is_symlink(): destination.symlink_to(os.readlink(path))
    else: shutil.copy2(path, destination)
    return destination

def atomic_bytes(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name); handle.write(content)
    temporary.chmod(0o700 if executable else 0o600); os.replace(temporary, path)

def file_current(source, destination, executable=False):
    mode = 0o700 if executable else 0o600
    return (destination.is_file() and not destination.is_symlink()
            and destination.read_bytes() == source.read_bytes()
            and stat.S_IMODE(destination.stat().st_mode) == mode)

def replace_file(source, destination, plan, executable=False):
    content = source.read_bytes()
    if file_current(source, destination, executable): return False
    if destination.exists() or destination.is_symlink(): plan.setdefault("backups", []).append(str(backup(destination)))
    atomic_bytes(destination, content, executable); return True

def validate_sources():
    files = [*(HOOK_SOURCE / name for name in CLAUDE_HOOKS), *(SOURCE_ROOT / name for name in RUNTIME_FILES)]
    missing = [str(path) for path in files if not path.is_file()]
    if missing: raise ValueError("source files are missing: " + ", ".join(missing))

def valid_wrapper_target(wrapper, runtime):
    if not wrapper.is_symlink() or not os.access(wrapper, os.X_OK): return False
    try: target = wrapper.resolve(strict=True)
    except OSError: return False
    return target in {SOURCE_ROOT.joinpath("with-heavy-lock").resolve(), runtime.joinpath("with-heavy-lock").resolve()}

def install(home, apply):
    validate_sources(); home = home.resolve()
    claude_dir, runtime_dir = home / ".claude" / "hooks", home / ".keel" / "resource-hooks"
    codex_path, claude_path = home / ".codex" / "hooks.json", home / ".claude" / "settings.json"
    python, script = Path(sys.executable).resolve(), claude_dir / RESOURCE_SCRIPT
    codex, claude = load_json(codex_path, {}), load_json(claude_path, {})
    codex_changed = mutate_codex(codex, command_for(python, script, "codex"))
    claude_changed = mutate_claude(claude, command_for(python, script, "claude"))
    wrapper = home / ".local" / "bin" / "with-heavy-lock"; wrapper_valid = valid_wrapper_target(wrapper, runtime_dir)
    plan = {"home": str(home), "apply": apply, "codex_changed": codex_changed, "claude_changed": claude_changed,
            "wrapper_changed": not wrapper_valid, "copy_claude_hooks": list(CLAUDE_HOOKS), "copy_runtime": list(RUNTIME_FILES),
            "trust_required": "Codex hook trust is not changed. Review, trust, and enable it in Codex before relying on it."}
    plan["stale_files"] = [str(claude_dir / name) for name in CLAUDE_HOOKS
                           if not file_current(HOOK_SOURCE / name, claude_dir / name, True)]
    plan["stale_files"] += [str(runtime_dir / name) for name in RUNTIME_FILES
                            if not file_current(SOURCE_ROOT / name, runtime_dir / name, name == "with-heavy-lock")]
    if not apply: return plan
    for name in CLAUDE_HOOKS: replace_file(HOOK_SOURCE / name, claude_dir / name, plan, executable=True)
    for name in RUNTIME_FILES: replace_file(SOURCE_ROOT / name, runtime_dir / name, plan, executable=name == "with-heavy-lock")
    for path, value, changed in ((codex_path, codex, codex_changed), (claude_path, claude, claude_changed)):
        if changed:
            if path.exists() or path.is_symlink(): plan.setdefault("backups", []).append(str(backup(path)))
            atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    if not wrapper_valid:
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        if wrapper.exists() or wrapper.is_symlink(): plan.setdefault("backups", []).append(str(backup(wrapper)))
        temporary = wrapper.with_name(wrapper.name + ".resource-hooks.new"); temporary.unlink(missing_ok=True)
        temporary.symlink_to(runtime_dir / "with-heavy-lock"); os.replace(temporary, wrapper)
    return plan

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home()); parser.add_argument("--apply", action="store_true"); parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.apply and args.check: parser.error("--apply and --check cannot be combined")
    try: print(json.dumps(install(args.home, args.apply), indent=2, sort_keys=True))
    except (OSError, ValueError) as error:
        print("install-resource-hooks: " + str(error), file=sys.stderr); return 2
    return 0

if __name__ == "__main__": raise SystemExit(main())
