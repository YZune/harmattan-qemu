#!/bin/sh
# Separate, opt-in entry for original call-ui with synthetic calls.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
export HARMATTAN_UI_CALL_SIMULATION=on
export HARMATTAN_UI_AUDIO=${HARMATTAN_UI_AUDIO:-pulse}
case ${1:-interactive} in
    interactive) test "$#" -le 1 ;;
    --locked)
        test "$#" -eq 1
        export HARMATTAN_UI_CALL_LOCKSCREEN=on HARMATTAN_UI_LOCKSCREEN=on ;;
    --headless-diagnostic|--locked-headless-diagnostic)
        if [ "$1" = --locked-headless-diagnostic ]; then
            export HARMATTAN_UI_CALL_LOCKSCREEN=on HARMATTAN_UI_LOCKSCREEN=on
        fi
        test "$#" -eq 1
        export HARMATTAN_UI_CALL_SIMULATION_TEST=on
        exec sh "$repo_root/scripts/harmattan-qemu/run-arm64-ui.sh" --startup-headless-diagnostic ;;
    *) echo 'Usage: run-call-simulation.sh [--locked | --headless-diagnostic | --locked-headless-diagnostic]' >&2; exit 2 ;;
esac
exec sh "$repo_root/scripts/harmattan-qemu/run-arm64-ui.sh"
