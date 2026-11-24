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
sys.path.insert(0, str(SOURCE_ROOT))
from governor.broker import shim_sources  # noqa: E402 - needs SOURCE_ROOT on sys.path

HOOK_SOURCE = SOURCE_ROOT.parents[1] / ".claude" / "hooks"
CLAUDE_HOOKS = ("serialize-heavy-ops.py", "heavy_command.py")
GOVERNOR_MODULES = tuple(
    "governor/" + name for name in
    ("__init__.py", "state.py", "snapshot.py", "admission.py", "jev_client.py", "broker.py",
     "act.py", "context.py", "registry.py", "inventory.py"))  # docs/specs/2026-09-29-machine-governor.md phase 1
RUNTIME_FILES = ("with-heavy-lock", "heavy_resources.py", "heavy_runner.py", "heavy_node.cjs",
                  "heavy_child.py", "keel_test_tmpdir.py", *GOVERNOR_MODULES)
RESOURCE_SCRIPT = "serialize-heavy-ops.py"
LAUNCHER = "with-heavy-lock"
SHIM_DIR = "shims"  # heavy_runner's broker puts <runtime>/shims first on a wrapper's PATH

def load_json(path, default):
    if not path.exists(): return default
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error: raise ValueError(f"invalid JSON: {path}: {error}")
    if not isinstance(value, dict): raise ValueError(f"expected JSON object: {path}")
    return value

def command_for(python, script, runtime=None):
    """Preserve stdin and map an unavailable/broken launcher to hook denial (2).

    Without a runtime the string is byte-identical to earlier installs, which Codex trust is keyed on.
    """
    shift, forward, suffix = ("shift 2; ", " \"$@\"", " --runtime " + shlex.quote(runtime)) if runtime else ("", "", "")
    return ("/bin/sh -c 'py=$1; script=$2; " + shift + "if [ ! -x \"$py\" ] || [ ! -f \"$script\" ]; then "
            "echo \"resource guard unavailable: interpreter or script is missing\" >&2; exit 2; fi; "
            "\"$py\" \"$script\"" + forward + "; rc=$?; if [ \"$rc\" -eq 0 ] || [ \"$rc\" -eq 2 ]; then exit \"$rc\"; fi; "
            "echo \"resource guard unavailable: launcher failed\" >&2; exit 2' resource-hook "
            + shlex.quote(str(python)) + " " + shlex.quote(str(script)) + suffix)

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

def mutate_codex(config, command, rewrite=False):
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict): raise ValueError("Codex hooks must be an object")
    groups = hooks.setdefault("PreToolUse", [])
    if not isinstance(groups, list): raise ValueError("Codex hooks.PreToolUse must be an array")
    for group in groups:
        if not isinstance(group, dict) or group.get("matcher") != "^Bash$" or not isinstance(group.get("hooks"), list): continue
        for handler in group["hooks"]:
            if resource_handler(handler):
                # Codex trusts the exact command; rewriting it unguards Codex until re-trusted, so it
                # happens only on an explicit --codex-rewrite, never as a side effect of --apply.
                if not rewrite or handler.get("command") == command: return False
                handler["command"] = command; return True
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

def backup(path, home):
    # Backups go to ~/.keel/backups, mirroring the path under home — never beside the live
    # file, where a .bak is loaded by nothing and globbed by everything (19 had piled up in
    # four live dirs by 2026-09-23). A symlink is re-pointed absolutely: a relative target
    # would resolve somewhere else from the backup's directory.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    try: rel = path.parent.relative_to(home)
    except ValueError: rel = Path("_outside_home") / path.parent.relative_to(path.parent.anchor)
    destination = home / ".keel" / "backups" / "resource-hooks" / rel / (path.name + ".resource-hooks." + stamp + ".bak")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink(): destination.symlink_to(os.path.normpath(path.parent / os.readlink(path)))
    else: shutil.copy2(path, destination)
    return destination

def atomic_bytes(path, content, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name); handle.write(content)
    temporary.chmod(0o700 if executable else 0o600); os.replace(temporary, path)

def file_current(source, destination, executable=False, content=None):
    """`content` is a rendered file (the launcher, a shim): only a regular copy of exactly those bytes is current."""
    if content is None:
        # A destination linked to this very source is the intended state (one owner, consumed by symlink):
        # replacing it with a copy would recreate the second copy the link exists to remove.
        if destination.is_symlink() and destination.resolve() == source.resolve(): return True
        content = source.read_bytes()
    mode = 0o700 if executable else 0o600
    return (destination.is_file() and not destination.is_symlink()
            and destination.read_bytes() == content
            and stat.S_IMODE(destination.stat().st_mode) == mode)

def replace_file(source, destination, plan, executable=False, content=None):
    if file_current(source, destination, executable, content): return False
    if destination.exists() or destination.is_symlink(): plan.setdefault("backups", []).append(str(backup(destination, Path(plan["home"]))))
    atomic_bytes(destination, source.read_bytes() if content is None else content, executable); return True

def launcher_bytes(python):
    """The installed launcher: the source with its shebang pinned to `python`, the hook's interpreter.

    `#!/usr/bin/env python3` would pick whatever python3 leads PATH, so the launcher and the hook
    could run under different interpreters.
    """
    first, _, rest = (SOURCE_ROOT / LAUNCHER).read_bytes().partition(b"\n")
    body = rest if first.startswith(b"#!") else first + b"\n" + rest
    return b"#!" + str(python).encode() + b"\n" + body

def rendered_runtime(python):
    """{name: (source, rendered bytes or None)} for every runtime file; None means a byte copy of the source."""
    files = {name: (SOURCE_ROOT / name, launcher_bytes(python) if name == LAUNCHER else None) for name in RUNTIME_FILES}
    files.update({SHIM_DIR + "/" + name: (SOURCE_ROOT / "governor" / "broker.py", text.encode())
                  for name, text in shim_sources().items()})
    return files

def runtime_executable(name):
    return name == LAUNCHER or name.startswith(SHIM_DIR + "/")

def validate_sources():
    files = [*(HOOK_SOURCE / name for name in CLAUDE_HOOKS), *(SOURCE_ROOT / name for name in RUNTIME_FILES)]
    missing = [str(path) for path in files if not path.is_file()]
    if missing: raise ValueError("source files are missing: " + ", ".join(missing))

def valid_wrapper_target(wrapper, runtime):
    """The wrapper must link to the rendered launcher copy in the runtime root, never to the source."""
    if not wrapper.is_symlink() or not os.access(wrapper, os.X_OK): return False
    try: target = wrapper.resolve(strict=True)
    except OSError: return False
    return target == runtime.joinpath(LAUNCHER).resolve()

def stable_python():
    """An interpreter path that survives a patch-level `brew upgrade` (opt/ symlink, not Cellar/)."""
    executable = Path(sys.executable).absolute()
    parts = executable.parts
    if "Cellar" in parts:
        i = parts.index("Cellar")
        formula = parts[i + 1]
        candidate = Path(*parts[:i], "opt", formula, "bin", executable.name)
        if os.access(candidate, os.X_OK): return candidate
    return executable

def install(home, apply, codex_rewrite=False):
    validate_sources(); home = home.resolve()
    claude_dir, runtime_dir = home / ".claude" / "hooks", home / ".keel" / "resource-hooks"
    codex_path, claude_path = home / ".codex" / "hooks.json", home / ".claude" / "settings.json"
    # Never .resolve() the interpreter: that pins a versioned Cellar path a `brew upgrade` deletes,
    # after which the launcher denies EVERY guarded Bash call ("interpreter or script is missing").
    python, script = stable_python(), claude_dir / RESOURCE_SCRIPT
    codex, claude = load_json(codex_path, {}), load_json(claude_path, {})
    codex_changed = mutate_codex(codex, command_for(python, script, "codex"), rewrite=codex_rewrite)
    claude_changed = mutate_claude(claude, command_for(python, script, "claude"))
    wrapper = home / ".local" / "bin" / LAUNCHER; wrapper_valid = valid_wrapper_target(wrapper, runtime_dir)
    runtime = rendered_runtime(python)
    plan = {"home": str(home), "apply": apply, "codex_changed": codex_changed, "claude_changed": claude_changed,
            "wrapper_changed": not wrapper_valid, "copy_claude_hooks": list(CLAUDE_HOOKS), "copy_runtime": list(runtime),
            "trust_required": ("Codex hook command REWRITTEN: the resource guard is OFF in Codex until you re-trust and enable it in Codex /hooks." if codex_changed and codex_rewrite else "Codex hook trust is not changed. Review, trust, and enable it in Codex before relying on it.")}
    plan["stale_files"] = [str(claude_dir / name) for name in CLAUDE_HOOKS
                           if not file_current(HOOK_SOURCE / name, claude_dir / name, True)]
    plan["stale_files"] += [str(runtime_dir / name) for name, (source, content) in runtime.items()
                            if not file_current(source, runtime_dir / name, runtime_executable(name), content)]
    if not apply: return plan
    for name in CLAUDE_HOOKS: replace_file(HOOK_SOURCE / name, claude_dir / name, plan, executable=True)
    for name, (source, content) in runtime.items():
        replace_file(source, runtime_dir / name, plan, executable=runtime_executable(name), content=content)
    for path, value, changed in ((codex_path, codex, codex_changed), (claude_path, claude, claude_changed)):
        if changed:
            if path.exists() or path.is_symlink(): plan.setdefault("backups", []).append(str(backup(path, home)))
            atomic_bytes(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    if not wrapper_valid:
        wrapper.parent.mkdir(parents=True, exist_ok=True)
        if wrapper.exists() or wrapper.is_symlink(): plan.setdefault("backups", []).append(str(backup(wrapper, home)))
        temporary = wrapper.with_name(wrapper.name + ".resource-hooks.new"); temporary.unlink(missing_ok=True)
        temporary.symlink_to(runtime_dir / LAUNCHER); os.replace(temporary, wrapper)
    return plan

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home()); parser.add_argument("--apply", action="store_true"); parser.add_argument("--check", action="store_true")
    parser.add_argument("--codex-rewrite", action="store_true", help="rewrite an existing Codex resource hook to the current command; Codex then needs a manual re-trust")
    args = parser.parse_args(argv)
    if args.apply and args.check: parser.error("--apply and --check cannot be combined")
    try: print(json.dumps(install(args.home, args.apply, args.codex_rewrite), indent=2, sort_keys=True))
    except (OSError, ValueError) as error:
        print("install-resource-hooks: " + str(error), file=sys.stderr); return 2
    return 0

if __name__ == "__main__": raise SystemExit(main())
