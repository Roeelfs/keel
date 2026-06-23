# Periodic reaper install (optional)

The `SessionStart` / `SessionEnd` hooks handle the happy path: a session claims
state on start and releases it on clean exit. But a session killed by closing the
terminal, `Ctrl-C`, or a crash may never fire `SessionEnd`, leaving a stale
`sessions/<sid>.json` and path claim behind.

The **heartbeat reaper** (`.claude/hooks/heartbeat-reaper.sh`) is the safety net.
Run it on a 30-minute timer and it purges any session whose heartbeat is older
than 24h, or older than 4h with a worktree that no longer exists.

`install.sh` sets this up for you. The files here are for manual / customized
installs.

## macOS (launchd)

```bash
REPO="$(git rev-parse --show-toplevel)"
sed "s|__REPO__|$REPO|g" \
  tooling/workflow/install/keel.workflow.reaper.plist.template \
  > ~/Library/LaunchAgents/keel.workflow.reaper.plist
launchctl load ~/Library/LaunchAgents/keel.workflow.reaper.plist
```

Logs: `/tmp/keel.workflow.reaper.stdout.log` and `.stderr.log`.
Uninstall: `launchctl unload ~/Library/LaunchAgents/keel.workflow.reaper.plist`.

## Linux (systemd user timer)

```bash
REPO="$(git rev-parse --show-toplevel)"
mkdir -p ~/.config/systemd/user
sed "s|__REPO__|$REPO|g" \
  tooling/workflow/install/keel-workflow-reaper.service.template \
  > ~/.config/systemd/user/keel-workflow-reaper.service
cp tooling/workflow/install/keel-workflow-reaper.timer \
  ~/.config/systemd/user/keel-workflow-reaper.timer
systemctl --user daemon-reload
systemctl --user enable --now keel-workflow-reaper.timer
```

Status: `systemctl --user status keel-workflow-reaper.timer`.
Uninstall: `systemctl --user disable --now keel-workflow-reaper.timer`.

## Without a timer

The reaper is strictly best-effort cleanup. If you don't install a timer, run it
by hand whenever you want to tidy stale claims:

```bash
REPO="$(git rev-parse --show-toplevel)" tooling/workflow/../.claude/hooks/heartbeat-reaper.sh
# or simply:
REPO="$(git rev-parse --show-toplevel)" .claude/hooks/heartbeat-reaper.sh
```
