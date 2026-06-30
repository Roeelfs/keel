#!/usr/bin/env python3
"""
orchestrator/bootstrap.py — discover project-specific config and cache it.

Run once when starting orchestrator work in a new repo, or whenever the cache
feels stale. The orchestrator reads the resulting cache to know which GitHub
Project to write to, which custom field IDs to use, and which labels exist.

Usage:
  python3 ~/.claude/skills/orchestrator/bootstrap.py            # discover + cache
  python3 ~/.claude/skills/orchestrator/bootstrap.py --print    # show existing cache
  python3 ~/.claude/skills/orchestrator/bootstrap.py --project "Backlog"
                                                                # disambiguate when
                                                                # multiple projects
                                                                # match

Cache lives at ~/.claude/projects/<slug>/orchestrator-cache.json — same dir as
that project's memory/, so it travels with the project context.

Read-only: NEVER creates labels, fields, or projects. Reports what's missing
and prints the gh command to create it. Idempotent.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def slug_from_cwd(cwd: str) -> str:
    """Match Claude Code's project slug derivation: leading dash + slashes→dashes."""
    return cwd.replace("/", "-")


def cache_path(slug: str) -> Path:
    return Path.home() / ".claude" / "projects" / slug / "orchestrator-cache.json"


def run_gh(args: list[str], **kwargs) -> tuple[int, str, str]:
    try:
        r = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, timeout=30, **kwargs,
        )
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)


def discover_repo(cwd: str) -> dict | None:
    rc, out, err = run_gh(
        ["repo", "view", "--json", "owner,name,nameWithOwner"], cwd=cwd
    )
    if rc != 0:
        print(f"  ✗ gh repo view failed: {err.strip()}", file=sys.stderr)
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def discover_project(repo_owner: str, project_hint: str | None) -> dict | None:
    """Try the repo owner first, then @me. Match by hint substring if given;
    otherwise auto-pick when there's exactly one project for an owner."""
    for owner in [repo_owner, "@me"]:
        rc, out, err = run_gh(["project", "list", "--owner", owner, "--format", "json"])
        if rc != 0:
            if "missing required scopes" in err.lower() or "read:project" in err.lower():
                print(
                    "  ✗ gh missing 'project' scope. Run once interactively:",
                    file=sys.stderr,
                )
                print(
                    "    gh auth refresh -s project --hostname github.com",
                    file=sys.stderr,
                )
                return None
            continue
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            continue
        projects = data.get("projects", []) if isinstance(data, dict) else []
        if project_hint:
            matches = [
                p for p in projects
                if project_hint.lower() in (p.get("title") or "").lower()
            ]
            if matches:
                p = dict(matches[0])
                p["owner"] = owner
                return p
        elif len(projects) == 1:
            p = dict(projects[0])
            p["owner"] = owner
            return p
        elif projects:
            print(
                f"  ⚠ {len(projects)} projects under '{owner}' — disambiguate with --project '<title-substring>'",
                file=sys.stderr,
            )
            for p in projects:
                print(f"    #{p.get('number')} {p.get('title')}", file=sys.stderr)
            return None
    return None


def fetch_fields(project_num: int, owner: str) -> dict:
    rc, out, err = run_gh(
        ["project", "field-list", str(project_num),
         "--owner", owner, "--format", "json"]
    )
    if rc != 0:
        print(f"  ✗ field-list failed: {err.strip()}", file=sys.stderr)
        return {}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    fields: dict[str, dict] = {}
    for f in data.get("fields", []):
        name = f.get("name", "")
        entry: dict = {"id": f.get("id"), "type": f.get("type")}
        if isinstance(f.get("options"), list):
            entry["options"] = {
                opt.get("name"): opt.get("id") for opt in f["options"] if opt.get("name")
            }
        fields[name] = entry
    return fields


def check_labels(repo_with_owner: str) -> dict:
    """Verify priority/* and effort/* labels exist on the repo."""
    rc, out, _ = run_gh(
        ["label", "list", "--repo", repo_with_owner,
         "--limit", "200", "--json", "name"]
    )
    if rc != 0:
        return {"priority": [], "effort": [], "missing": []}
    try:
        names = [l["name"] for l in json.loads(out) if isinstance(l, dict)]
    except (json.JSONDecodeError, KeyError, TypeError):
        return {"priority": [], "effort": [], "missing": []}
    pri = sorted(n for n in names if n.startswith("priority/"))
    eff = sorted(n for n in names if n.startswith("effort/"))
    expected_pri = {"priority/p0", "priority/p1", "priority/p2", "priority/p3"}
    expected_eff = {"effort/s", "effort/m", "effort/l", "effort/xl"}
    missing = sorted((expected_pri - set(pri)) | (expected_eff - set(eff)))
    return {"priority": pri, "effort": eff, "missing": missing}


def label_create_hint(label: str) -> str:
    palette = {
        "priority/p0": ("Critical — drop everything", "b60205"),
        "priority/p1": ("High — current week", "d93f0b"),
        "priority/p2": ("Medium — current month", "fbca04"),
        "priority/p3": ("Low — backlog, opportunistic", "0e8a16"),
        "effort/s": ("Small — under half a day", "c2e0c6"),
        "effort/m": ("Medium — 0.5 to 2 days", "bfd4f2"),
        "effort/l": ("Large — 2 to 5 days", "fad8c7"),
        "effort/xl": ("Extra large — over a week, multi-PR", "f9d0c4"),
    }
    desc, color = palette.get(label, ("", "ededed"))
    return f"gh label create '{label}' --description '{desc}' --color '{color}'"


def field_create_hint(num: int, owner: str, name: str) -> str:
    if name in ("Priority",):
        return (
            f"gh project field-create {num} --owner {owner} --name 'Priority' "
            f"--data-type SINGLE_SELECT --single-select-options 'P0,P1,P2,P3'"
        )
    if name in ("Effort",):
        return (
            f"gh project field-create {num} --owner {owner} --name 'Effort' "
            f"--data-type SINGLE_SELECT --single-select-options 'S,M,L,XL'"
        )
    if name == "Target Date":
        return (
            f"gh project field-create {num} --owner {owner} --name 'Target Date' "
            f"--data-type DATE"
        )
    return f"# (manual) create '{name}' on project {num}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", help="Project title hint (substring match)")
    ap.add_argument("--cwd", default=os.getcwd(), help="Working dir (default: cwd)")
    ap.add_argument(
        "--print", dest="just_print", action="store_true",
        help="Print existing cache and exit",
    )
    args = ap.parse_args()

    cwd = os.path.realpath(args.cwd)
    if not (Path(cwd) / ".git").exists():
        print(f"Not a git repo: {cwd}", file=sys.stderr)
        return 1

    slug = slug_from_cwd(cwd)
    path = cache_path(slug)

    if args.just_print:
        if path.exists():
            print(path.read_text())
            return 0
        print(f"No cache at {path} — run without --print to discover.", file=sys.stderr)
        return 1

    print(f"→ cwd: {cwd}")
    print(f"→ slug: {slug}")
    print(f"→ cache: {path}")

    print("\n[1/4] Discovering repo via gh ...")
    repo = discover_repo(cwd)
    if not repo:
        return 1
    print(f"  ✓ {repo['nameWithOwner']}")

    print("\n[2/4] Discovering GitHub project ...")
    project = discover_project(repo["owner"]["login"], args.project)
    proj_data: dict | None = None
    if not project:
        print("  ⚠ no project matched. Create one with:")
        print(
            f"    gh project create --owner {repo['owner']['login']} --title '<Title>'"
        )
        print("  Then re-run with --project '<Title>'.")
    else:
        print(f"  ✓ #{project['number']} '{project['title']}' (owner: {project['owner']})")
        proj_data = {
            "number": project["number"],
            "title": project["title"],
            "owner": project["owner"],
            "id": project.get("id"),
            "url": project.get("url"),
        }

    fields: dict = {}
    if proj_data:
        print("\n[3/4] Fetching project fields ...")
        fields = fetch_fields(proj_data["number"], proj_data["owner"])
        for fname in ["Status", "Priority", "Effort", "Target Date"]:
            if fname in fields:
                opts = fields[fname].get("options", {}) or {}
                opt_str = f" options=[{', '.join(opts)}]" if opts else ""
                print(f"  ✓ {fname}: {fields[fname]['id']}{opt_str}")
            else:
                print(f"  ⚠ {fname} missing — create with:")
                print(
                    f"    {field_create_hint(proj_data['number'], proj_data['owner'], fname)}"
                )

    print("\n[4/4] Checking priority/* + effort/* labels ...")
    labels = check_labels(repo["nameWithOwner"])
    print(f"  priority: {labels['priority'] or '(none)'}")
    print(f"  effort:   {labels['effort'] or '(none)'}")
    if labels["missing"]:
        print(f"  ⚠ missing: {labels['missing']}")
        print("  Create with:")
        for lbl in labels["missing"]:
            print(f"    {label_create_hint(lbl)}")

    cache = {
        "version": 1,
        "generated_at": subprocess.run(
            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"],
            capture_output=True, text=True,
        ).stdout.strip(),
        "cwd": cwd,
        "slug": slug,
        "repo": repo,
        "project": proj_data,
        "fields": fields,
        "labels": labels,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))
    print(f"\n✓ Wrote {path}")
    if labels["missing"] or not proj_data or any(
        f not in fields for f in ("Priority", "Effort", "Target Date")
    ):
        print(
            "  (cache written despite gaps — re-run after creating missing items)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
