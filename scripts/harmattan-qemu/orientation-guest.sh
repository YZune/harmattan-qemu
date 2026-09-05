#!/bin/sh
# Snapshot-local virtual pose. Original provider registry/cache remains intact.
set -eu
base=/tmp/n00-qemu-orientation
user_env="HOME=/home/user USER=user LOGNAME=user DISPLAY=:9 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/n00-shell-session-bus CONTEXT_PROVIDERS=$base/providers"
get_value() {
    su user -c "$user_env dbus-send --session --print-reply --reply-timeout=2000 --dest=org.harmattan.QemuOrientation /org/maemo/contextkit/$1 org.maemo.contextkit.Property.Get"
}
edge=${2:-}
case "$edge" in top|left|bottom|right) ;; *) echo 'Expected top, left, bottom or right' >&2; exit 2 ;; esac
case ${1:-} in
    start)
        test ! -e "$base"
        test -f /tmp/n00-orientation-provider
        mkdir -m 0755 "$base" "$base/providers"
        cp /usr/share/contextkit/providers/*.context "$base/providers/"
        # A private XML registry avoids modifying or invalidating cache.cdb.
        perl -0777 -i -pe 'BEGIN { $n=0; } $n += s{<key name="(?:Screen[.]TopEdge|Position[.]IsFlat)"/>}{}g; END { die "unexpected orientation declarations" unless $n == 2; }' "$base/providers/com.nokia.SensorService.context"
        printf '%s\n' '<?xml version="1.0"?>' \
            '<provider xmlns="http://contextkit.freedesktop.org/Provider" bus="session" service="org.harmattan.QemuOrientation">' \
            '  <key name="Screen.TopEdge"/>' '  <key name="Position.IsFlat"/>' '</provider>' \
            > "$base/providers/org.harmattan.QemuOrientation.context"
        chmod 0644 "$base/providers/"*.context
        cp /tmp/n00-orientation-provider "$base/provider"
        chmod 0755 "$base/provider"
        mkfifo "$base/control"
        touch "$base/provider.log"
        chown user "$base/control" "$base/provider.log"
        chmod 0600 "$base/control" "$base/provider.log"
        provider_pid=$(su user -c "$user_env sh -c 'exec 3<>$base/control; exec $base/provider $edge <&3' >$base/provider.log 2>&1 & echo \$!")
        case "$provider_pid" in ''|*[!0-9]*) exit 1 ;; esac
        printf '%s\n' "$provider_pid" > "$base/pid"
        ;;
    set)
        test -p "$base/control"
        kill -0 "$(cat "$base/pid")"
        printf '%s\n' "$edge" > "$base/control"
        ;;
    inspect) ;;
    *) echo 'Expected start, set or inspect' >&2; exit 2 ;;
esac
provider_pid=$(cat "$base/pid")
test "$(readlink "/proc/$provider_pid/exe")" = "$base/provider"
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$provider_pid"
    if get_value Screen/TopEdge > "$base/topedge.reply" 2>/dev/null && grep -q "variant.*string \"$edge\"" "$base/topedge.reply"; then
        ready=1; break
    fi
    sleep 1
done
test "$ready" = 1
printf 'N00_ORIENTATION_EXPECT edge=%s provider=org.harmattan.QemuOrientation\n' "$edge"
printf 'N00_ORIENTATION_TOP_EDGE_BEGIN\n'
get_value Screen/TopEdge
printf 'N00_ORIENTATION_TOP_EDGE_END\nN00_ORIENTATION_IS_FLAT_BEGIN\n'
get_value Position/IsFlat
printf 'N00_ORIENTATION_IS_FLAT_END\n'
provider_pid=$(cat "$base/pid")
printf 'N00_ORIENTATION_PROCESS %s\n' "$provider_pid"
sed -n '1,8p' "/proc/$provider_pid/status"
readlink "/proc/$provider_pid/exe"
md5sum "$base/provider" "/proc/$provider_pid/exe"
test ! -e "$base/providers/cache.cdb"
printf 'N00_ORIENTATION_ORIGINAL_REGISTRY\n'
md5sum /usr/share/contextkit/providers/com.nokia.SensorService.context /usr/share/contextkit/providers/cache.cdb
printf 'N00_ORIENTATION_READY %s\n' "$edge"
