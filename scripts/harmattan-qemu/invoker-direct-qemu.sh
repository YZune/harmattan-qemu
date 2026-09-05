#!/bin/sh
# HARMATTAN_QEMU_DIRECT_INVOKER

# QEMU-only fallback for the PR1.3-on-PR1.0 rescue environment.  Stock
# applauncherd requires an Aegis credential that this kernel/userspace pairing
# cannot grant.  Preserve the desktop Exec contract while starting the target
# as the existing unprivileged user; this is not an Aegis replacement.

set -u

original=/usr/local/libexec/harmattan-qemu/invoker.applauncherd
app_type=
single_instance=0
splash_portrait=
splash_landscape=

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help|-c|--creds)
            exec "$original" "$1"
            ;;
        -t|--type)
            shift
            [ "$#" -gt 0 ] || exit 2
            app_type=$1
            shift
            ;;
        --type=*)
            app_type=${1#*=}
            shift
            ;;
        -S|--splash|-L|--splash-landscape)
            splash_option=$1
            shift
            [ "$#" -gt 0 ] || exit 2
            case "$splash_option" in
                -S|--splash) splash_portrait=$1 ;;
                *) splash_landscape=$1 ;;
            esac
            shift
            ;;
        --splash=*) splash_portrait=${1#*=}; shift ;;
        --splash-landscape=*) splash_landscape=${1#*=}; shift ;;
        -d|--delay|-r|--respawn)
            shift
            [ "$#" -gt 0 ] || exit 2
            shift
            ;;
        --delay=*|--respawn=*)
            shift
            ;;
        -s|--single-instance)
            single_instance=1
            shift
            ;;
        -w|--wait-term|-n|--no-wait|-G|--global-syms|-D|--deep-syms|-o|--daemon-mode)
            shift
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "invoker-direct-qemu: unsupported option: $1" >&2
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

if [ "$#" -eq 0 ]; then
    echo "invoker-direct-qemu: application path is missing" >&2
    exit 2
fi

application=$1
shift

if [ "$single_instance" -eq 1 ]; then
    process_name=${application##*/}
    if pidof "$process_name" >/dev/null 2>&1; then
        exit 0
    fi
fi

export DISPLAY=${DISPLAY:-:0}
export DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=/tmp/session_bus_socket}

# Explicit opt-in, installed only in the new launcher's disposable snapshot.
# exec below preserves this shell PID; do not publish a helper/booster PID.
case ${N00_UI_SPLASH:-0} in
    0) ;;
    1)
        if [ -n "$splash_portrait" ]; then
            /usr/bin/perl /tmp/n00-ui-helpers/splash-screen-guest.pl \
                "$$" "$splash_portrait" "$splash_landscape" \
                >>/tmp/n00-splash-screen.log 2>&1 || {
                echo 'invoker-direct-qemu: splash publication failed' >&2
                # Keep the actual application available if its optional image
                # is missing. Diagnostics reject the recorded helper failure.
            }
        fi
        ;;
    *) echo 'invoker-direct-qemu: invalid splash mode' >&2; exit 2 ;;
esac

case "$app_type" in
    m)
        exec "$application" -local-theme -graphicssystem raster "$@"
        ;;
    q|qt|d)
        exec "$application" -graphicssystem raster "$@"
        ;;
    *)
        exec "$application" "$@"
        ;;
esac
