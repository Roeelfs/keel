# Optional external fixture rule for the machine-local disk-keeper.
# AFTER its existing internal cleanup rules, source this file and call:
#   disk_keeper_external_fixtures
# Keep the normal internal rules: DK_LEAK_ROOT replaces one legacy root.
# This focused extra rule adds the external root and all three fixture prefixes
# without rerunning unrelated cleanup. Compatible with /bin/bash 3.2.
# This fragment does not install/reload launchd or enable external TMPDIR.
# Do not create the root here: the test resolver owns its creation and probes.
DK_LEAK_ROOT="${DK_LEAK_ROOT:-/Volumes/T9/keel-test-tmp-$(id -u)}"

disk_keeper_external_fixtures() {
  local pat
  [ -d "$DK_LEAK_ROOT" ] && [ ! -L "$DK_LEAK_ROOT" ] || return 0
  case "$DK_LEAK_ROOT" in
    /Volumes/T9/*)
      python3 -c 'import os, sys; sys.exit(not os.path.ismount("/Volumes/T9"))' || return 0
      ;;
  esac
  for pat in 'cdk-real-app-*' 'synth-det-*' 'lambda-asset-size-*'; do
    # Bounded depth, owner check and two-hour floor protect other/live fixtures.
    # find does not follow directory symlinks.
    find "$DK_LEAK_ROOT" -mindepth 1 -maxdepth 1 -type d \
      -user "$(id -u)" -name "$pat" -mmin +120 -exec rm -rf {} + || return 1
  done
}
