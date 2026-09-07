#!/bin/sh
# Explicit disposable SDK battery mode. Does not start full DSME/MCE/CSD.
set -eu
test "$(uname -m)" = armv7l
test "$(uname -r)" = 2.6.32.26
grep -qw 'n00.ui_sdk_power=1' /proc/cmdline
grep -q '^mtd1: 00060000 00020000 "config"$' /proc/mtd
state=/tmp/n00-ui-sdk-power
identity() {
    printf '%s\n' \
        '3656cad5df189b759639aa21bb5e00ea  /usr/sbin/bme_RX-71' \
        'd1fd1a55b816e4537e163ed09bcf39c2  /usr/lib/hwi/hw/rx71.so' \
        '4a509f812807fec894c94e4793f62374  /usr/bin/bmestat' | md5sum -c -
}
check_process() {
    pid=$(cat "$state/pid")
    case "$pid" in ''|*[!0-9]*|0|1) return 1 ;; esac
    kill -0 "$pid"
    test "$(readlink /proc/"$pid"/exe)" = /usr/sbin/bme_RX-71
    test "$(md5sum /proc/"$pid"/exe | cut -d ' ' -f 1)" = 3656cad5df189b759639aa21bb5e00ea
    test "$(cat /proc/"$pid"/stat | cut -d ' ' -f 22)" = "$(cat "$state/starttime")"
    test -S /tmp/.bmesrv
    test -f /tmp/.bmeevt
}
stats() {
    code=0
    perl -e 'alarm 3; exec "/usr/bin/bmestat"; die $!' > "$state/stats" 2>&1 || code=$?
    test "$code" = 128
}
report() {
    check_process
    stats
    printf 'N00_UI_POWER_REPORT_BEGIN %s\n' "$1"
    printf 'N00_UI_POWER_PROCESS %s\n' "$pid"
    md5sum /proc/"$pid"/exe
    printf 'N00_UI_POWER_ARGS '
    tr '\000' ' ' < /proc/"$pid"/cmdline
    printf '\nN00_UI_POWER_STATS_BEGIN\n'
    cat "$state/stats"
    printf 'N00_UI_POWER_STATS_END\n'
    if [ "$1" != startup ]; then
        printf 'N00_UI_CELLULAR_OWNER_BEGIN\n'
        dbus-send --system --print-reply --reply-timeout=2000 \
            --dest=org.freedesktop.DBus /org/freedesktop/DBus \
            org.freedesktop.DBus.NameHasOwner string:com.nokia.csd.ContextProvider
        printf 'N00_UI_CELLULAR_OWNER_END\n'
    fi
    printf 'N00_UI_POWER_REPORT_END %s\n' "$1"
}
case "${1:-}" in
    start)
        test -z "$(pidof bme_RX-71 2>/dev/null || true)"
        test ! -e /tmp/.bmesrv
        identity
        mkdir -m 0700 "$state"
        mkdir -p /dev/shm
        chmod 1777 /dev/shm
        pid=
        cleanup() {
            if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi
            cat "$state/bme.log"
        }
        trap cleanup EXIT
        /usr/sbin/bme_RX-71 -n -l stderr -v 5 -c /usr/lib/hwi/hw/rx71.so > "$state/bme.log" 2>&1 &
        pid=$!
        printf '%s\n' "$pid" > "$state/pid"
        cat /proc/"$pid"/stat | cut -d ' ' -f 22 > "$state/starttime"
        ready=0
        for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
            kill -0 "$pid"
            if [ -S /tmp/.bmesrv ] && stats; then ready=1; break; fi
            sleep 1
        done
        test "$ready" = 1
        report startup
        trap - EXIT
        ;;
    report)
        case "${2:-}" in settled|final|shutdown) report "$2" ;; *) exit 2 ;; esac
        ;;
    stop)
        report shutdown
        kill "$pid"
        stopped=0
        for attempt in 1 2 3 4 5; do
            if [ ! -e /proc/"$pid"/exe ]; then stopped=1; break; fi
            sleep 1
        done
        test "$stopped" = 1
        printf 'N00_UI_POWER_STOPPED\n'
        ;;
    *) exit 2 ;;
esac
