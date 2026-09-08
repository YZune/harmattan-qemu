#!/bin/sh
# Scoped guest-only original locked-call prerequisites and root relay lifecycle.
set -eu
root=/tmp/n00-call-simulation
helpers=/tmp/n00-ui-helpers
policy=/etc/dbus-1/session.d/n00-call-lock.conf
address=unix:path=/tmp/n00-shell-session-bus
test "$(id -u)" = 0
test "$(uname -m)" = armv7l
grep -q 'init=/sbin/preinit root=0xB302' /proc/cmdline
reload() {
    DBUS_SESSION_BUS_ADDRESS="$address" dbus-send --session --print-reply --reply-timeout=5000 \
        --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.ReloadConfig
}
case ${1:-} in
    check)
        test "${N00_CALL_LOCKSCREEN:-off}" = on
        test "$(md5sum /usr/lib/libQtMeeGoGraphicsSystemHelper.so.4.7.4 | cut -d ' ' -f 1)" = 60932237ff41f89153b68b11594fefe5
        test "$(md5sum /usr/lib/libX11.so.6.3.0 | cut -d ' ' -f 1)" = 9b9136ffeecd7bdd756a1911eb6b5169
        test "$(md5sum /usr/lib/libQtGui.so.4.7.4 | cut -d ' ' -f 1)" = 24510eddaa9ea5eda5fc4ab1150d02e9
        test -r "$helpers/n00-call-livepixmap.so"
        ;;
    start)
        test "${N00_CALL_LOCKSCREEN:-off}" = on
        test ! -e "$policy"
        cat >"$policy" <<'POLICY'
<busconfig><policy user="root">
 <allow send_destination="com.nokia.systemui.ScreenLock" send_interface="com.nokia.systemui.ScreenLock" send_member="insertEvent"/>
 <allow send_destination="com.nokia.systemui.ScreenLock" send_interface="com.nokia.systemui.ScreenLock" send_member="removeEvent"/>
</policy></busconfig>
POLICY
        chmod 0644 "$policy"
        reload
        : >"$root/relay.log"
        DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/n00-call-simulation/bus \
            "$helpers/n00-call-lockscreen" >"$root/relay.log" 2>&1 &
        echo $! >"$root/relay.pid"
        chmod 0644 "$root/relay.pid" "$root/relay.log"
        for attempt in 1 2 3 4 5 6 7 8 9 10; do
            grep -q '^LOCK_READY$' "$root/relay.log" && break
            sleep 1
        done
        grep -q '^LOCK_READY$' "$root/relay.log"
        ;;
    stop)
        pid=$(cat "$root/relay.pid")
        case "$pid" in ''|*[!0-9]*) exit 2 ;; esac
        test "$(readlink "/proc/$pid/exe")" = "$helpers/n00-call-lockscreen"
        test "$(tr '\000' '\n' <"/proc/$pid/environ" | grep '^DBUS_SESSION_BUS_ADDRESS=')" = DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/n00-call-simulation/bus
        kill "$pid"
        rm "$policy"
        reload
        ;;
    *) exit 2 ;;
esac
