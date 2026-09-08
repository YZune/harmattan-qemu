#!/bin/sh
# Explicit synthetic calls inside a disposable emulator guest only.
set -eu
umask 077
root=/tmp/n00-call-simulation
helpers=/tmp/n00-ui-helpers
address="unix:path=$root/bus"
control=/org/harmattan/CallSimulation
service=org.harmattan.CallSimulation
test "$(uname -m)" = armv7l
grep -q 'init=/sbin/preinit root=0xB302' /proc/cmdline

request() {
    DBUS_SESSION_BUS_ADDRESS="$address" dbus-send --session --print-reply \
        --reply-timeout=5000 --dest="$service" "$control" "$service.$1"
}

owned_pid() {
    pid=$(cat "$root/$1.pid") || return 1
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$pid" || return 1
    test "$(readlink "/proc/$pid/exe")" = "$2" || return 1
    actual=$(tr '\000' '\n' <"/proc/$pid/environ" | grep '^DBUS_SESSION_BUS_ADDRESS=') || return 1
    test "$actual" = "DBUS_SESSION_BUS_ADDRESS=$address" || return 1
    printf '%s\n' "$pid"
}

case ${N00_CALL_LOCKSCREEN:-off} in off|on) ;; *) exit 2 ;; esac

case ${1:-} in
    setup)
        test "$(id -u)" = 0
        case ${N00_CALL_AUDIO:-off} in off|pulse) ;; *) exit 2 ;; esac
        test "$(md5sum /usr/bin/call-ui | cut -d ' ' -f 1)" = c9d625ced99916c45464069ccedf6c03
        test "$(md5sum /usr/lib/libdbus-1.so.3.5.4 | cut -d ' ' -f 1)" = 8e1080b6ea9fe102c3983918779f0628
        test "$(md5sum /usr/lib/libgstreamer-0.10.so.0.29.0 | cut -d ' ' -f 1)" = 60e2038ef720175b84bf86aa17a25702
        test "$(md5sum /usr/lib/gconf2/gconfd-2 | cut -d ' ' -f 1)" = 3103cb2bab05954ee11de77cb2b1096c
        test ! -e "$root"
        mkdir -m 0700 "$root"
        chmod 0755 "$helpers/n00-call-simulation"
        lock_env=
        image_env=
        if [ "${N00_CALL_LOCKSCREEN:-off}" = on ]; then
            sh "$helpers/call-lockscreen-guest.sh" check
            chmod 0755 "$helpers/n00-call-lockscreen"
            lock_env='N00_CALL_LOCKSCREEN=on'
            image_env="N00_CALL_LIVE_PIXMAP=on LD_PRELOAD=$helpers/n00-call-livepixmap.so"
            touch "$root/lockscreen-enabled"
        fi
        cat >"$root/bus.conf" <<'EOF'
<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
 <type>session</type>
 <listen>unix:path=/tmp/n00-call-simulation/bus</listen>
 <auth>EXTERNAL</auth>
 <servicedir>/tmp/n00-call-simulation/services</servicedir>
 <policy context="default"><allow user="user"/></policy>
 <policy user="user">
  <allow own="org.freedesktop.Telepathy.AccountManager"/>
  <allow own="org.freedesktop.Telepathy.Connection.ring.tel.ring"/>
  <allow own="org.harmattan.CallSimulation"/>
  <allow own="com.nokia.NonGraphicFeedback1"/>
  <allow own="com.nokia.call-ui"/>
  <allow own="Com.Nokia.Telephony.CallUi"/>
  <allow own="org.freedesktop.Telepathy.Client.CallUi"/>
  <allow own="com.nokia.CallUi.Context"/>
  <allow own="org.gnome.GConf"/>
  <allow send_destination="*"/>
  <allow receive_sender="*"/>
 </policy>
</busconfig>
EOF
        if [ "${N00_CALL_LOCKSCREEN:-off}" = on ]; then
            # Only the root relay can own lock interfaces; the original user
            # call process cannot claim those names on the private bus.
            sed -i '/<policy context="default">/a\
 <policy context="default"><allow user="root"/></policy>\
 <policy user="root">\
  <allow own="com.nokia.systemui.ScreenLock"/>\
  <allow own="com.nokia.mce"/>\
  <allow own="org.harmattan.CallSimulation.LockUi"/>\
  <allow send_destination="*"/><allow receive_sender="*"/>\
 </policy>' "$root/bus.conf"
        fi
        # Original GConf's StartServiceByName needs a service file even when
        # its daemon already owns the name. Keep this bus's activation isolated.
        mkdir "$root/services" "$root/gconf-home"
        cp -R /etc/osso-af-init/gconf-dir "$root/gconf-data"
        printf 'xml:readwrite:%s/gconf-data\n' "$root" >"$root/gconf-home/.gconf.path"
        cat >"$root/services/gconf.service" <<'EOF'
[D-BUS Service]
Name=org.gnome.GConf
Exec=/bin/false
EOF
        # A failed/replaced daemon must fail, never auto-restart unnoticed.
        audio_env=
        if [ "${N00_CALL_AUDIO:-off}" = pulse ]; then
            case ${PULSE_SERVER:-} in tcp:10.0.2.2:*) ;; *) exit 2 ;; esac
            port=${PULSE_SERVER##*:}
            case "$port" in ''|*[!0-9]*) exit 2 ;; esac
            test "$port" -ge 1 && test "$port" -le 65535
            test "${PULSE_COOKIE:-}" = /tmp/n00-audio.cookie
            test -r "$PULSE_COOKIE"
            audio_env="PULSE_SERVER=$PULSE_SERVER PULSE_COOKIE=$PULSE_COOKIE"
        fi
        cat >"$root/start.sh" <<EOF
#!/bin/sh
set -eu
ulimit -l unlimited
export HOME=/home/user USER=user LOGNAME=user DISPLAY=:9
export DBUS_SESSION_BUS_ADDRESS=$address
dbus-daemon --nofork --config-file=$root/bus.conf >$root/bus.log 2>&1 &
echo \$! >$root/bus.pid
for attempt in 1 2 3 4 5; do
    test ! -S $root/bus || break
    sleep 1
done
test -S $root/bus
HOME=$root/gconf-home DBUS_SYSTEM_BUS_ADDRESS=$address GCONF_DEBUG_OUTPUT=1 \\
    /usr/lib/gconf2/gconfd-2 >$root/gconf.log 2>&1 &
echo \$! >$root/gconf.pid
for attempt in 1 2 3 4 5 6 7 8 9 10; do
    value=\$(DBUS_SYSTEM_BUS_ADDRESS=$address gconftool-2 -g /meegotouch/theme/name 2>/dev/null || true)
    test "\$value" != blanco || break
    sleep 1
done
test "\$value" = blanco
$lock_env $audio_env $helpers/n00-call-simulation ${N00_CALL_AUDIO:-off} >$root/backend.log 2>&1 &
echo \$! >$root/backend.pid
for attempt in 1 2 3 4 5; do
    grep -q '^DEMO_READY ' $root/backend.log && break
    sleep 1
done
grep -q '^DEMO_READY ' $root/backend.log
EOF
        cat >"$root/ui.sh" <<EOF
#!/bin/sh
set -eu
ulimit -l unlimited
export HOME=/home/user USER=user LOGNAME=user DISPLAY=:9
export DBUS_SESSION_BUS_ADDRESS=$address
$image_env DBUS_SYSTEM_BUS_ADDRESS=$address QT_GRAPHICSSYSTEM=raster M_FORCE_LOCAL_THEME=1 \\
    /usr/bin/call-ui -prestart -software -local-theme -graphicssystem raster >$root/call-ui.log 2>&1 &
echo \$! >$root/ui.pid
EOF
        chown -R user "$root"
        ulimit -l unlimited
        su user -c "sh $root/start.sh"
        if [ "${N00_CALL_LOCKSCREEN:-off}" = on ]; then
            sh "$helpers/call-lockscreen-guest.sh" start
        fi
        su user -c "sh $root/ui.sh"
        ready=0
        for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
            if su user -c "DBUS_SESSION_BUS_ADDRESS=$address dbus-send --session --print-reply --reply-timeout=1000 --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID string:org.freedesktop.Telepathy.Client.CallUi" >"$root/owner.log" 2>&1; then
                if [ "$(sed -n 's/^[[:space:]]*uint32 //p' "$root/owner.log")" = "$(cat "$root/ui.pid")" ]; then ready=1; break; fi
            fi
            sleep 1
        done
        cat "$root/owner.log"
        test "$ready" = 1
        # A separate entry on the original Home requests another simulated call.
        cat >/usr/share/applications/n00-call-simulation.desktop <<'EOF'
[Desktop Entry]
Type=Application
Name=Simulate call
Name[zh_CN]=模拟来电
Comment=Simulated N9 incoming call; no real telephone connection
Icon=icon-l-telephony
Exec=/bin/sh /tmp/n00-ui-helpers/call-simulation-guest.sh incoming
Terminal=false
EOF
        chmod 0644 /usr/share/applications/n00-call-simulation.desktop
        sh "$0" report
        ;;
    incoming|end|report|invalid-input|busy|stale|lock-negative)
        if [ "$(id -u)" = 0 ] && { [ "$1" != report ] || [ ! -e "$root/lockscreen-enabled" ]; }; then
            exec su user -c "sh $0 $1"
        fi
        test "$(id -u)" = 29999 || { test "$(id -u)" = 0 && test "$1" = report; }
        backend=$(owned_pid backend "$helpers/n00-call-simulation")
        ui=$(owned_pid ui /usr/bin/call-ui)
        gconf=$(owned_pid gconf /usr/lib/gconf2/gconfd-2)
        case "$1" in
            incoming) request Incoming ;;
            end) request End ;;
            lock-negative)
                test -e "$root/lockscreen-enabled"
                if DBUS_SESSION_BUS_ADDRESS="$address" dbus-send --session --print-reply --reply-timeout=5000 \
                    --dest=org.harmattan.CallSimulation.LockUi /org/harmattan/CallSimulation/LockUi \
                    org.harmattan.CallSimulation.LockUi.Begin >"$root/negative.log" 2>&1; then
                    echo 'Unexpected lock control impersonation success' >&2; exit 1
                fi
                cat "$root/negative.log"
                grep -q '^Error org.freedesktop.DBus.Error.AccessDenied:' "$root/negative.log"
                printf 'N00_CALL_NEGATIVE_OK lock-sender-identity\n'
                ;;
            invalid-input|busy|stale)
                expected=org.freedesktop.DBus.Error.InvalidArgs
                set -- "$1" --session --print-reply --reply-timeout=5000 --dest="$service" "$control" "$service.Incoming"
                case "$1" in
                    invalid-input) shift; set -- "$@" string:unexpected ;;
                    busy) expected=org.freedesktop.Telepathy.Error.NotAvailable; shift ;;
                    stale)
                        expected=org.freedesktop.DBus.Error.UnknownObject
                        set -- --session --print-reply --reply-timeout=5000 \
                            --dest=org.freedesktop.Telepathy.Connection.ring.tel.ring \
                            /org/freedesktop/Telepathy/Connection/ring/tel/ring/call1 \
                            org.freedesktop.Telepathy.Channel.Close ;;
                esac
                if DBUS_SESSION_BUS_ADDRESS="$address" dbus-send "$@" >"$root/negative.log" 2>&1; then
                    echo 'Unexpected simulation method success' >&2; exit 1
                fi
                cat "$root/negative.log"
                grep -q "^Error $expected:" "$root/negative.log"
                printf 'N00_CALL_NEGATIVE_OK %s\n' "$expected"
                ;;
            report)
                printf 'N00_CALL_BACKEND_PID %s\nN00_CALL_UI_PID %s\n' "$backend" "$ui"
                printf 'N00_CALL_GCONF_PID %s\n' "$gconf"
                md5sum "/proc/$backend/exe" "/proc/$ui/exe" "/proc/$gconf/exe"
                if [ -e "$root/lockscreen-enabled" ]; then
                    cat "$root/relay.log"
                    tail -10 /tmp/n00-shell-sysuid.log
                    relay=$(owned_pid relay "$helpers/n00-call-lockscreen")
                    printf 'N00_CALL_RELAY_PID %s\n' "$relay"
                    md5sum "/proc/$relay/exe"
                fi
                printf 'N00_CALL_STATUS_BEGIN\n'
                request Status
                printf 'N00_CALL_STATUS_END\n'
                # Full logs stay private. The host checks explicit state/error records.
                cat "$root/backend.log"
                printf 'N00_CALL_UI_LOG_BEGIN\n'
                tail -50 "$root/call-ui.log"
                printf 'N00_CALL_UI_LOG_END\n'
                ;;
        esac
        ;;
    stop)
        if [ "$(id -u)" = 0 ]; then
            su user -c "sh $0 end"
            if [ -e "$root/lockscreen-enabled" ]; then sh "$helpers/call-lockscreen-guest.sh" stop; fi
            exec su user -c "sh $0 stop"
        fi
        test "$(id -u)" = 29999
        backend=$(owned_pid backend "$helpers/n00-call-simulation")
        ui=$(owned_pid ui /usr/bin/call-ui)
        gconf=$(owned_pid gconf /usr/lib/gconf2/gconfd-2)
        bus=$(owned_pid bus /usr/bin/dbus-daemon)
        request End
        kill "$ui" "$backend"
        for attempt in 1 2 3 4 5; do
            if ! kill -0 "$ui" 2>/dev/null && ! kill -0 "$backend" 2>/dev/null; then break; fi
            sleep 1
        done
        kill "$gconf"
        kill "$bus"
        printf 'N00_CALL_STOPPED\n'
        ;;
    *) echo 'Expected setup, incoming, end, report or stop' >&2; exit 2 ;;
esac
