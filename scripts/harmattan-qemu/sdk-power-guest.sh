#!/bin/sh
# Isolated SDK hardware/BME diagnostic, never a complete power-service startup.
set -eu
test "$(uname -m)" = armv7l
test "$(uname -r)" = 2.6.32.26
grep -q 'n00.sdk_power_probe=1' /proc/cmdline
test -z "$(pidof bme_RX-71 2>/dev/null || true)"
test ! -e /tmp/.bmesrv
printf '%s\n' \
    '3656cad5df189b759639aa21bb5e00ea  /usr/sbin/bme_RX-71' \
    'd1fd1a55b816e4537e163ed09bcf39c2  /usr/lib/hwi/hw/rx71.so' \
    '4a509f812807fec894c94e4793f62374  /usr/bin/bmestat' \
    | md5sum -c -
printf 'N00_BME_IDENTITY_OK\n'
status=0
bmestat >/tmp/n00-sdk-bmestat-absent.log 2>&1 || status=$?
test "$status" = 2 # ENOENT: no BME socket before startup.
printf 'N00_BME_ABSENT_REJECTED\n'
cat /proc/mtd
grep -q '^mtd1: 00060000 00020000 "config"$' /proc/mtd
mkdir -p /dev/shm
chmod 1777 /dev/shm
pid=
cleanup() {
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
    cat /tmp/n00-sdk-bme.log
}
trap cleanup EXIT
# -n isolates hardware and BMEIPC from the currently incomplete DSME graph.
/usr/sbin/bme_RX-71 -n -l stderr -v 5 -c /usr/lib/hwi/hw/rx71.so >/tmp/n00-sdk-bme.log 2>&1 &
pid=$!
sleep 12
kill -0 "$pid"
test "$(readlink "/proc/$pid/exe")" = /usr/sbin/bme_RX-71
test -S /tmp/.bmesrv
test -f /tmp/.bmeevt
printf 'N00_BME_STATS_BEGIN\n'
status=0
bmestat || status=$?
# This pinned bmestat returns the successful 128-byte IPC read, not zero.
# ARM main 0x9008 saves the result at 0x9024 and returns it at 0x91bc;
# the statistics request at 0xa60c asks for 0x80 bytes. Reject other exits.
test "$status" = 128
printf 'N00_BME_STATS_END\n'
kill -0 "$pid"
printf 'N00_BME_ALIVE\n'
kill "$pid"
wait "$pid"
pid=
printf 'N00_BME_STOPPED\n'
