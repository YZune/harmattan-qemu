#!/bin/sh
# Rendering diagnosis only, inside a disposable ARM64-port QEMU snapshot.
# No fake input device and no changes to the established PR1.3 UI launcher.
set -eu
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
user_env='HOME=/home/user USER=user LOGNAME=user DISPLAY=:9 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/n00-shell-session-bus'
if [ -n "${N00_UI_AUDIO_SERVER:-}" ]; then
    case "$N00_UI_AUDIO_SERVER" in tcp:10.0.2.2:*) ;; *) echo 'Invalid private audio address' >&2; exit 2 ;; esac
    audio_port=${N00_UI_AUDIO_SERVER#tcp:10.0.2.2:}
    case "$audio_port" in ''|*[!0-9]*) echo 'Invalid private audio server' >&2; exit 2 ;; esac
    test "$audio_port" -ge 1 && test "$audio_port" -le 65535
    test -r /tmp/n00-audio.cookie
    user_env="$user_env PULSE_SERVER=$N00_UI_AUDIO_SERVER PULSE_COOKIE=/tmp/n00-audio.cookie"
fi
compositor_env=
case ${N00_UI_READY_WAITS:-0} in 0|1) ;; *) echo 'Invalid startup wait mode' >&2; exit 2 ;; esac
case ${N00_UI_CLOCK_SYNC:-0} in
    0) ;;
    1)
        test -r "${N00_UI_TZFILE:-}"
        user_env="$user_env TZ=:${N00_UI_TZFILE}"
        ;;
    *) echo 'Invalid clock synchronization mode' >&2; exit 2 ;;
esac
case ${N00_UI_SPLASH:-0} in
    0) ;;
    1) user_env="$user_env N00_UI_SPLASH=1" ;;
    *) echo 'Invalid splash mode' >&2; exit 2 ;;
esac
case ${N00_UI_ANIMATIONS:-0} in
    0) ;;
    1) compositor_env='LD_PRELOAD=/tmp/n00-compositor-matrices.so' ;;
    *) echo 'Invalid compositor animation mode' >&2; exit 2 ;;
esac
case ${N00_UI_TOP_EDGE:-disabled} in
    disabled) ;;
    top|left|bottom|right) user_env="$user_env CONTEXT_PROVIDERS=/tmp/n00-qemu-orientation/providers" ;;
    *) echo 'Invalid virtual orientation' >&2; exit 2 ;;
esac
case ${N00_UI_KEYBOARD:-0} in
    0) ;;
    1)
        user_env="$user_env QT_IM_MODULE=MInputContext"
        . /tmp/n00-ui-helpers/input-method-guest.sh
        ;;
    *) echo 'Invalid input method mode' >&2; exit 2 ;;
esac
ulimit -l unlimited

start_audio_policy() {
    # Original ringtone previews wait for libresource grants before starting
    # GStreamer. Keep the original manager and rules in this private guest;
    # a reachable PulseAudio server alone does not satisfy that contract.
    test -z "$(pidof ohmd 2>/dev/null || true)"
    test "$(md5sum /usr/sbin/ohmd | cut -d ' ' -f 1)" = 96dc1f6be9c836dc5b2c51b54f4d74b4
    DISPLAY=:9 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/n00-shell-session-bus \
        /usr/sbin/ohmd --no-daemon >/tmp/n00-audio-policy.log 2>&1 &
    audio_policy_pid=$!
    audio_policy_ready=0
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        kill -0 "$audio_policy_pid"
        audio_policy_ready=1
        for service in org.freedesktop.ohm org.maemo.resource.manager; do
            owner=$(dbus-send --system --print-reply --reply-timeout=1000 \
                --dest=org.freedesktop.DBus /org/freedesktop/DBus \
                org.freedesktop.DBus.GetConnectionUnixProcessID "string:$service" \
                2>/dev/null | sed -n 's/^[[:space:]]*uint32 //p')
            if [ "$owner" != "$audio_policy_pid" ]; then audio_policy_ready=0; fi
        done
        if [ "$audio_policy_ready" = 1 ]; then break; fi
        sleep 1
    done
    test "$audio_policy_ready" = 1
    printf '\nN00_AUDIO_POLICY_BEGIN\nN00_AUDIO_POLICY_PID %s\n' "$audio_policy_pid"
    sed -n '1,8p' "/proc/$audio_policy_pid/status"
    readlink "/proc/$audio_policy_pid/exe"
    md5sum /usr/sbin/ohmd "/proc/$audio_policy_pid/exe"
    for service in org.freedesktop.ohm org.maemo.resource.manager; do
        printf 'N00_AUDIO_POLICY_OWNER %s\n' "$service"
        dbus-send --system --print-reply --reply-timeout=1000 \
            --dest=org.freedesktop.DBus /org/freedesktop/DBus \
            org.freedesktop.DBus.GetConnectionUnixProcessID "string:$service"
    done
    printf 'N00_AUDIO_POLICY_END\n'
}

report_systemui() {
    ids=$(pidof sysuid) || return 1
    case "$ids" in ''|*[!0-9]*) echo 'Expected one sysuid process' >&2; return 1 ;; esac
    # Font/theme startup can temporarily sleep in disk I/O. Retry startup
    # instead of declaring that incomplete sample ready or weakening the gate.
    sed -n '1,8p' "/proc/$ids/status" > /tmp/n00-systemui-process.log || return 1
    grep -q '^State:[[:space:]]*[RS]' /tmp/n00-systemui-process.log || return 1
    printf '\nN00_SYSTEMUI_REPORT_BEGIN\nN00_SYSTEMUI_PROCESS %s\n' "$ids"
    cat /tmp/n00-systemui-process.log
    readlink "/proc/$ids/exe"
    md5sum /usr/bin/sysuid "/proc/$ids/exe"
    printf 'N00_SYSTEMUI_OWNER_BEGIN\n'
    su user -c "$user_env dbus-send --session --print-reply --reply-timeout=2000 --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID string:com.meego.core.MStatusBar" || return 1
    printf 'N00_SYSTEMUI_OWNER_END\nN00_SYSTEMUI_PIXMAP_BEGIN\n'
    su user -c "$user_env dbus-send --session --print-reply --reply-timeout=2000 --dest=com.meego.core.MStatusBar /statusbar com.meego.core.MStatusBar.sharedPixmapHandle" || return 1
    printf 'N00_SYSTEMUI_PIXMAP_END\nN00_SYSTEMUI_REPORT_END\n'
}

report_processes() {
    for name in Xorg mthemedaemon mcompositor meegotouchhome; do
        ids=$(pidof "$name" 2>/dev/null || true)
        printf 'N00_SHELL_PROCESS %s %s\n' "$name" "${ids:-absent}"
        for id in $ids; do
            sed -n '1,8p' "/proc/$id/status" 2>/dev/null || true
        done
    done
}

report_animations() {
    ids=$(pidof mcompositor) || return 1
    case "$ids" in ''|*[!0-9]*) return 1 ;; esac
    printf '\nN00_ANIMATIONS_BEGIN\nN00_ANIMATIONS_PID %s\n' "$ids"
    md5sum /usr/lib/libmcompositor.so.1.1.3 /tmp/n00-compositor-matrices.so
    tr '\000' '\n' < "/proc/$ids/environ" | grep '^LD_PRELOAD='
    grep -q '/tmp/n00-compositor-matrices.so$' "/proc/$ids/maps"
    printf 'N00_ANIMATIONS_MAPPED\n'
    grep '^N00_COMPOSITOR_' /tmp/n00-shell-compositor.log
    # The helper is not inherited by Home, System UI, or the test application.
    for id in $(pidof meegotouchhome sysuid calc 2>/dev/null || true); do
        if grep -q '/tmp/n00-compositor-matrices.so$' "/proc/$id/maps"; then return 1; fi
    done
    printf 'N00_ANIMATIONS_PROCESS_SCOPE_OK\nN00_ANIMATIONS_END\n'
}

report_home() {
    tail -200 /tmp/n00-shell-home.log
    report_processes
    pidof meegotouchhome
    if [ "${N00_UI_SYSTEMUI:-0}" = 1 ]; then report_systemui; fi
    if [ "${N00_UI_ANIMATIONS:-0}" = 1 ]; then report_animations; fi
    perl /tmp/n00-shell-x11.pl
    if [ "${N00_UI_SPLASH:-0}" = 1 ]; then report_splash; fi
    check_startup_input home
}

report_splash() {
    printf '\nN00_SPLASH_REPORT_BEGIN\n'
    md5sum /usr/bin/invoker /tmp/n00-ui-helpers/N00X11.pm /tmp/n00-ui-helpers/splash-screen-guest.pl
    printf 'N00_SPLASH_LOG_BEGIN\n'
    cat /tmp/n00-splash-screen.log
    printf 'N00_SPLASH_LOG_END\nN00_SPLASH_REPORT_END\n'
}

send_startup_input() {
    # Nonblocking open fails if the guard died, instead of hanging a FIFO writer.
    perl -MFcntl=O_WRONLY,O_NONBLOCK -e 'sysopen(my $f, $ARGV[0], O_WRONLY|O_NONBLOCK) or die "startup control: $!"; print $f "$ARGV[1]\n" or die "startup write: $!"; close $f or die "startup close: $!";' /tmp/n00-startup-input/control "$1"
}

check_startup_input() {
    test "${N00_UI_STARTUP_GUARD:-0}" = 1 || return 0
    send_startup_input "check $1"
    for attempt in 1 2 3 4 5; do
        if grep -q "^N00_STARTUP_INPUT_CHECK tag=$1 " /tmp/n00-startup-input/guard.log; then return 0; fi
        sleep 1
    done
    return 1
}

report_clock() {
    test "${N00_UI_CLOCK_SYNC:-0}" = 1 || return 0
    test -r "$N00_UI_TZFILE"
    clock_dsme_pid=$(pidof dsme 2>/dev/null || true)
    clock_server_pid=$(pidof dsme-server 2>/dev/null || true)
    case "$clock_dsme_pid,$clock_server_pid" in
        *[!0-9,]*|,*|*,)
            printf 'N00_CLOCK_HEARTBEAT_FAILURE dsme=%s server=%s socket=%s\n' \
                "${clock_dsme_pid:-absent}" "${clock_server_pid:-absent}" "$([ -S /dev/shm/iphb ] && echo ready || echo absent)"
            tail -200 /tmp/n00-shell-iphb.log 2>/dev/null || true
            return 1
            ;;
    esac
    test -S /dev/shm/iphb
    clock_zone_md5=$(md5sum "$N00_UI_TZFILE" | cut -d ' ' -f 1)
    # One date process observes one instant, even when slow TCG scheduling
    # crosses a second between fork/exec calls. Keep the strict epoch/TZ gate.
    clock_sample=$(TZ=:"$N00_UI_TZFILE" date '+utc_epoch=%s local=%Y-%m-%dT%H:%M:%S%z offset=%z')
    printf 'N00_CLOCK_REPORT phase=%s %s zone_md5=%s heartbeat=%s,%s\n' \
        "$1" "$clock_sample" "$clock_zone_md5" "$clock_dsme_pid" "$clock_server_pid"
}

start_heartbeat() {
    test "$(md5sum /sbin/dsme | cut -d ' ' -f 1)" = a00ca1ff8a6ca38f189e288b17c2c11e
    test "$(md5sum /sbin/dsme-server | cut -d ' ' -f 1)" = 87cac7bd773955d8f293894660a314ae
    test "$(md5sum /lib/dsme/heartbeat.so | cut -d ' ' -f 1)" = d08eef15c3226700a4299fdecbbd5951
    test "$(md5sum /lib/dsme/iphb.so | cut -d ' ' -f 1)" = d87a519165b291e1d379a2ec75affde9
    test "$(md5sum /usr/lib/libiphb.so.0.0.0 | cut -d ' ' -f 1)" = c4ed4fd3c3c9566fade0270a25029610
    test -z "$(pidof dsme dsme-server 2>/dev/null || true)"
    mkdir -p /dev/shm
    chmod 1777 /dev/shm
    rm -f /dev/shm/iphb /tmp/dsmesock /tmp/dsme.pid
    if [ -r /sys/class/misc/iphb/dev ] && [ ! -c /dev/iphb ]; then
        mknod /dev/iphb c "$(cut -d: -f1 /sys/class/misc/iphb/dev)" "$(cut -d: -f2 /sys/class/misc/iphb/dev)"
    fi
    test -c /dev/iphb
    chmod 0600 /dev/iphb
    DSME_RD_FLAGS='no-ext-wd,no-omap-wd' /sbin/dsme -l stderr -v 7 \
        -p /lib/dsme/heartbeat.so -p /lib/dsme/iphb.so >/tmp/n00-shell-iphb.log 2>&1 &
    for clock_attempt in 1 2 3 4 5 6 7 8 9 10; do
        if [ -S /dev/shm/iphb ] && pidof dsme >/dev/null 2>&1 && pidof dsme-server >/dev/null 2>&1; then break; fi
        sleep 1
    done
    test -S /dev/shm/iphb
    clock_dsme_pid=$(pidof dsme)
    clock_server_pid=$(pidof dsme-server)
    case "$clock_dsme_pid" in ''|*[!0-9]*) return 1 ;; esac
    case "$clock_server_pid" in ''|*[!0-9]*) return 1 ;; esac
    printf '\nN00_HEARTBEAT_REPORT_BEGIN\n'
    for clock_process in dsme dsme-server; do
        clock_pid=$(pidof "$clock_process")
        printf 'N00_HEARTBEAT_PROCESS %s %s\n' "$clock_process" "$clock_pid"
        sed -n '1,8p' "/proc/$clock_pid/status"
        readlink "/proc/$clock_pid/exe"
        md5sum "/proc/$clock_pid/exe"
    done
    md5sum /sbin/dsme /sbin/dsme-server /lib/dsme/heartbeat.so /lib/dsme/iphb.so /usr/lib/libiphb.so.0.0.0
    printf 'N00_HEARTBEAT_SOCKET_READY /dev/shm/iphb\n'
    printf 'N00_HEARTBEAT_KERNEL_DEVICE_READY /dev/iphb\n'
    printf 'N00_HEARTBEAT_REPORT_END\n'
}

case ${1:-} in
    bootstrap)
        dmesg -n 1
        if [ "${N00_UI_SPLASH:-0}" = 1 ]; then
            # Only the known direct-invoker adaptation in this fresh snapshot.
            test "$(md5sum /usr/bin/invoker | cut -d ' ' -f 1)" = ca6f09e9035fdc66a34daae5d48e9083
            cp -p /usr/bin/invoker /tmp/n00-invoker-before-splash
            cp /tmp/n00-ui-helpers/invoker-direct-qemu.sh /usr/bin/invoker
            chmod 0755 /usr/bin/invoker
            touch /tmp/n00-splash-screen.log
            chown user /tmp/n00-splash-screen.log
            chmod 0600 /tmp/n00-splash-screen.log
        fi
        if [ "${N00_UI_CLOCK_SYNC:-0}" != 1 ] && [ "$(date +%s)" -lt 1356998400 ]; then
            date "$(date -r /var/cache/fontconfig +%m%d%H%M%Y.%S)" >/dev/null 2>&1 || true
        fi
        if [ "${N00_UI_CLOCK_SYNC:-0}" = 1 ]; then start_heartbeat; fi
        mkdir -p /tmp/.X11-unix /var/log /var/lib/dbus /var/run/dbus
        chmod 1777 /tmp /var/run
        chown root:messagebus /usr/lib/dbus-1.0/dbus-daemon-launch-helper
        chmod 4750 /usr/lib/dbus-1.0/dbus-daemon-launch-helper
        modprobe kfgles2
        test -r /sys/class/misc/kfgles2/dev
        if [ ! -c /dev/kfgles2 ]; then
            mknod /dev/kfgles2 c "$(cut -d: -f1 /sys/class/misc/kfgles2/dev)" "$(cut -d: -f2 /sys/class/misc/kfgles2/dev)"
        fi
        chmod 0777 /dev/kfgles2
        if [ "${N00_SHELL_INPUT:-0}" = 1 ]; then
            touch_event=
            for event in /sys/class/input/event*; do
                if [ "$(cat "$event/device/name" 2>/dev/null || true)" = 'Atmel mXT Touchscreen' ]; then
                    touch_event="/dev/input/${event##*/}"
                    mkdir -p /dev/input
                    if [ ! -c "$touch_event" ]; then
                        mknod "$touch_event" c "$(cut -d: -f1 "$event/dev")" "$(cut -d: -f2 "$event/dev")"
                    fi
                    break
                fi
            done
            test -n "$touch_event" && test -c "$touch_event"
            ln -sfn "$touch_event" /dev/input/qemu-touchscreen
            chmod 0600 "$touch_event"
            printf 'N00_SHELL_INPUT_REAL %s\n' "$touch_event"
        else
            printf 'N00_SHELL_INPUT_NOT_IMPLEMENTED\n'
        fi
        dbus-uuidgen --ensure=/var/lib/dbus/machine-id
        # Only stale endpoints in this fresh disposable guest are removed.
        test -z "$(pidof dbus-daemon Xorg 2>/dev/null || true)"
        rm -f /var/run/dbus/pid /var/run/dbus/system_bus_socket /tmp/n00-shell-session-bus
        chown messagebus:messagebus /var/run/dbus
        dbus-daemon --system --nofork >/tmp/n00-shell-system-dbus.log 2>&1 &
        su user -c "$user_env dbus-daemon --session --nofork --address=unix:path=/tmp/n00-shell-session-bus >/tmp/n00-shell-session-dbus.log 2>&1 &"
        Xorg :9 -config /etc/X11/xorg.conf -noreset -br >/tmp/n00-shell-Xorg.log 2>&1 &
        for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
            if [ -S /var/run/dbus/system_bus_socket ] && [ -S /tmp/n00-shell-session-bus ] && [ -S /tmp/.X11-unix/X9 ]; then break; fi
            sleep 1
        done
        ls -l /var/run/dbus/system_bus_socket /tmp/n00-shell-session-bus /tmp/.X11-unix/X9
        if [ -n "${N00_UI_AUDIO_SERVER:-}" ]; then start_audio_policy; fi
        if [ "${N00_UI_STARTUP_GUARD:-0}" = 1 ]; then
            mkdir -m 0755 /tmp/n00-startup-input
            mkfifo /tmp/n00-startup-input/control
            touch /tmp/n00-startup-input/guard.log
            chown user /tmp/n00-startup-input/control /tmp/n00-startup-input/guard.log
            chmod 0600 /tmp/n00-startup-input/control /tmp/n00-startup-input/guard.log
            su user -c "$user_env perl /tmp/n00-ui-helpers/startup-input-guest.pl /tmp/n00-startup-input/control >/tmp/n00-startup-input/guard.log 2>&1 &"
            for attempt in 1 2 3 4 5; do
                if grep -q '^N00_STARTUP_INPUT_HELD pid=' /tmp/n00-startup-input/guard.log; then break; fi
                sleep 1
            done
            grep '^N00_STARTUP_INPUT_HELD pid=' /tmp/n00-startup-input/guard.log
        fi
        md5sum /usr/bin/mcompositor /usr/bin/meegotouchhome /usr/lib/libEGL.so.1 /usr/lib/libGLESv2.so.1 /usr/lib/libEGL.so /usr/lib/libGLESv2.so
        report_processes
        ;;
    theme)
        rm -f /var/run/m.mthemedaemon /tmp/m.mthemedaemon
        ln -s /var/run/m.mthemedaemon /tmp/m.mthemedaemon
        su user -c "$user_env mthemedaemon >/tmp/n00-shell-theme.log 2>&1 &"
        for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
            [ -S /var/run/m.mthemedaemon ] && break
            sleep 1
        done
        tail -80 /tmp/n00-shell-theme.log
        report_processes
        test -S /var/run/m.mthemedaemon
        ;;
    systemui)
        test "${N00_UI_SYSTEMUI:-0}" = 1
        test -z "$(pidof sysuid 2>/dev/null || true)"
        test "$(md5sum /usr/bin/sysuid | cut -d ' ' -f 1)" = 6e6ca0153aea0bf3b4556c08d68f934f
        # The real provider creates/renders its own shared pixmap. No substitute
        # texture, fabricated indicators, library patch or global DBus edit.
        su user -c "$user_env sysuid -local-theme -graphicssystem raster >/tmp/n00-shell-sysuid.log 2>&1 &"
        ready=0
        for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
            if report_systemui > /tmp/n00-systemui-ready.log 2>&1; then
                if [ "$(grep -c 'uint32 [1-9][0-9]*' /tmp/n00-systemui-ready.log)" = 2 ]; then ready=1; break; fi
            fi
            sleep 1
        done
        cat /tmp/n00-systemui-ready.log
        test "$ready" = 1
        ;;
    compositor)
        if [ "${N00_UI_ANIMATIONS:-0}" = 1 ]; then
            test "$(md5sum /usr/lib/libmcompositor.so.1.1.3 | cut -d ' ' -f 1)" = 49985bb59bf13ae22d20075feb11818a
            test -s /tmp/n00-compositor-matrices.so
            chmod 0644 /tmp/n00-compositor-matrices.so
        fi
        su user -c "$user_env $compositor_env mcompositor -nohung >/tmp/n00-shell-compositor.log 2>&1 &"
        if [ "${N00_UI_READY_WAITS:-0}" = 1 ]; then
            perl /tmp/n00-ui-helpers/wait-shell-ready-guest.pl compositor
        else
            sleep 8
        fi
        tail -160 /tmp/n00-shell-compositor.log
        report_processes
        pidof mcompositor
        if [ "${N00_UI_ANIMATIONS:-0}" = 1 ]; then report_animations; fi
        ;;
    input-method)
        test "${N00_UI_KEYBOARD:-0}" = 1
        start_input_method
        ;;
    keyboard-prepare)
        test "${N00_UI_KEYBOARD:-0}" = 1
        test "$(md5sum /usr/bin/notes | cut -d ' ' -f 1)" = 59a2e909cacfdcedf2423a85913724bd
        chmod 0755 /tmp/n00-ui-helpers/keyboard-notes-read
        test -z "$(pidof notes 2>/dev/null || true)"
        ;;
    keyboard-inspect)
        inspect_keyboard_notes
        ;;
    keyboard-cpu)
        perl -e 'for $f ("/proc/stat", "/proc/uptime", glob("/proc/[0-9]*/stat")) { if (open(my $h, "<", $f)) { print "$f ", scalar(<$h>); close $h; } }'
        ;;
    home|home-start)
        # Same no-weather/raster choices as the established hybrid UI path.
        weather=/usr/share/meegotouch/applicationextensions/events-weather.desktop
        if [ -f "$weather" ]; then mv "$weather" /tmp/n00-shell-weather.desktop; fi
        # Direct-exec/single-instance entries inherit Qt raster and the stock
        # Qt Components local theme provider (mdeclarativeimageprovider.cpp).
        # It reads the original Blanco files without remote pixmap transport.
        # Explicitly OpenGL applications still need separate GLES support.
        app_viewport_env=
        if [ -f /tmp/n00-ui-helpers/app-viewport-guest.sh ]; then
            . /tmp/n00-ui-helpers/app-viewport-guest.sh
            prepare_app_viewport
        fi
        su user -c "$user_env $app_viewport_env QT_GRAPHICSSYSTEM=raster M_FORCE_LOCAL_THEME=1 meegotouchhome -local-theme -graphicssystem raster >/tmp/n00-shell-home.log 2>&1 &"
        if [ "${N00_UI_READY_WAITS:-0}" = 1 ]; then
            perl /tmp/n00-ui-helpers/wait-shell-ready-guest.pl home
        else
            sleep 25
        fi
        if [ "$1" = home ]; then report_home; fi
        ;;
    home-report)
        # The host has observed stable real pixels before requesting this
        # checkpoint. A mapped window alone can still be loading from disk.
        test "${N00_UI_READY_WAITS:-0}" = 1
        report_home
        ;;
    settled)
        sleep 5
        report_processes
        pidof mcompositor
        pidof meegotouchhome
        if [ "${N00_UI_SYSTEMUI:-0}" = 1 ]; then report_systemui; fi
        if [ "${N00_UI_ANIMATIONS:-0}" = 1 ]; then report_animations; fi
        perl /tmp/n00-shell-x11.pl
        if [ "${N00_UI_SPLASH:-0}" = 1 ]; then report_splash; fi
        check_startup_input settled
        ;;
    final)
        printf '\nN00_GUEST_MEMORY_BEGIN\n'
        cat /proc/meminfo
        printf 'N00_GUEST_MEMORY_END\n'
        if [ "${N00_UI_SYSTEMUI:-0}" = 1 ]; then
            printf '\nN00_SHELL_LOG /tmp/n00-shell-sysuid.log\n'
            tail -160 /tmp/n00-shell-sysuid.log
        fi
        for file in /tmp/n00-shell-iphb.log /tmp/n00-shell-input-method.log /tmp/n00-shell-system-dbus.log /tmp/n00-shell-session-dbus.log /tmp/n00-shell-theme.log /tmp/n00-shell-compositor.log /tmp/n00-shell-home.log /var/log/Xorg.9.log; do
            printf '\nN00_SHELL_LOG %s\n' "$file"
            tail -200 "$file" 2>/dev/null || true
        done
        report_processes
        check_startup_input final
        ;;
    startup-inspect)
        test "${N00_UI_STARTUP_GUARD:-0}" = 1
        cat /tmp/n00-startup-input/guard.log
        ;;
    startup-release)
        test "${N00_UI_STARTUP_GUARD:-0}" = 1
        send_startup_input release
        for attempt in 1 2 3 4 5 6 7 8 9 10; do
            if grep -q '^N00_STARTUP_INPUT_RELEASED ' /tmp/n00-startup-input/guard.log; then break; fi
            sleep 1
        done
        grep -q '^N00_STARTUP_INPUT_RELEASED ' /tmp/n00-startup-input/guard.log
        cat /tmp/n00-startup-input/guard.log
        ;;
    orientation-inspect)
        if [ "${N00_UI_SYSTEMUI:-0}" = 1 ]; then report_systemui; fi
        md5sum /usr/bin/organiser
        ids=$(pidof organiser 2>/dev/null || true)
        printf 'N00_CALENDAR_PROCESS %s\n' "${ids:-absent}"
        for id in $ids; do
            sed -n '1,8p' "/proc/$id/status"
            readlink "/proc/$id/exe"
            md5sum "/proc/$id/exe"
            tr '\000' '\n' < "/proc/$id/environ" | grep '^CONTEXT_PROVIDERS='
        done
        perl /tmp/n00-shell-x11.pl
        ;;
    calculator-inspect)
        case ${2:-} in before|opened|sum|returned|reopened|final) ;; *) exit 2 ;; esac
        if [ "${N00_UI_SYSTEMUI:-0}" = 1 ]; then report_systemui; fi
        if [ "${N00_UI_ANIMATIONS:-0}" = 1 ]; then report_animations; fi
        if [ "${N00_UI_SPLASH:-0}" = 1 ]; then report_splash; fi
        printf '\nN00_CALCULATOR_INSPECT\n'
        for file in /usr/share/applications/*calc*.desktop /usr/bin/*calc*; do
            [ -f "$file" ] || continue
            ls -l "$file"
            md5sum "$file"
            case "$file" in *.desktop) cat "$file" ;; esac
        done
        head -4 /usr/bin/invoker
        ids=$(pidof calc 2>/dev/null || true)
        printf 'N00_CALCULATOR_PROCESS %s\n' "${ids:-absent}"
        for id in $ids; do
            sed -n '1,8p' "/proc/$id/status"
            readlink "/proc/$id/exe"
            md5sum "/proc/$id/exe"
        done
        ps axw
        tail -120 /tmp/n00-shell-home.log
        tail -80 /tmp/n00-shell-compositor.log
        perl /tmp/n00-shell-x11.pl
        if [ "${N00_UI_CLOCK_SYNC:-0}" = 1 ] && [ "$2" = final ]; then
            printf '\nN00_HEARTBEAT_RUNTIME_BEGIN\n'
            # Longer keyboard/animation runs exceed 200 lines. Retain the
            # original module loads as well as every subsequent wake/re-arm.
            cat /tmp/n00-shell-iphb.log
            printf 'N00_HEARTBEAT_RUNTIME_END\n'
        fi
        report_clock "calculator-$2"
        ;;
    *) echo 'Expected bootstrap, theme, compositor, home, settled or final' >&2; exit 2 ;;
esac

case ${1:-} in
    home-report) report_clock home ;;
    bootstrap|theme|compositor|home|settled|final) report_clock "$1" ;;
esac
if [ "${N00_UI_KEYBOARD:-0}" = 1 ]; then
    case ${1:-} in home|home-report|settled|final) report_input_method ;; esac
fi
