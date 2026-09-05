#!/bin/sh

# Start the minimum PR1.3 UI stack from the hybrid rescue shell.

set -eu

export PATH=/sbin:/bin:/usr/sbin:/usr/bin

user_env='HOME=/home/user USER=user LOGNAME=user DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/session_bus_socket'

ulimit -l unlimited

# Nokia's old QEMU sends the guest console through an emulated UART.  PR1.3
# Aegis reports one missing reference hash for nearly every mapped binary and
# shared library; printing those messages is disproportionately expensive under
# TCG/Rosetta.  Keep Aegis itself enabled, but only send emergency kernel
# messages to the interactive serial console after the rescue shell is ready.
dmesg -n 1 || true

# The n00 rescue path has no RTC, so every boot starts in 1970.  Besides making
# application dates nonsensical, this makes Fontconfig reject the PR1.3 cache
# as newer than the system clock.  Advance to the newest stable timestamp that
# is already part of the derived image; never move an established guest clock
# backwards.
current_epoch=$(date +%s)
if [ "$current_epoch" -lt 1356998400 ]; then
    clock_epoch=1356998400
    clock_value=010100002013.00
    for clock_source in "$0" /var/cache/fontconfig; do
        [ -e "$clock_source" ] || continue
        candidate_epoch=$(date -r "$clock_source" +%s 2>/dev/null || true)
        case "$candidate_epoch" in
            ''|*[!0-9]*) continue ;;
        esac
        if [ "$candidate_epoch" -gt "$clock_epoch" ]; then
            clock_epoch=$candidate_epoch
            clock_value=$(date -r "$clock_source" +%m%d%H%M%Y.%S)
        fi
    done
    date "$clock_value" >/dev/null 2>&1 || true
fi

# The n00 model exposes a single emulated CPU.  Avoid ondemand transitions and
# keep the UI work ahead of optional services activated by D-Bus.
governor=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
if [ -w "$governor" ] && grep -qw performance /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors; then
    echo performance >"$governor"
fi

mkdir -p /tmp/.X11-unix /var/log /var/lib/dbus /var/run/dbus
chmod 1777 /tmp /var/run

# Harmattan normally grants this helper through Aegis credentials.  The
# PR1.0 QEMU kernel cannot supply the PR1.3 credential set, so this derived
# image uses the conventional, messagebus-restricted setuid mode instead.
chown root:messagebus /usr/lib/dbus-1.0/dbus-daemon-launch-helper
chmod 4750 /usr/lib/dbus-1.0/dbus-daemon-launch-helper

if ! lsmod | grep -q '^kfgles2 '; then
    modprobe kfgles2
fi

if [ ! -r /sys/class/misc/kfgles2/dev ]; then
    echo "kfgles2 misc device was not registered" >&2
    exit 1
fi

touch_event=
for input_event in /sys/class/input/event*; do
    if [ "$(cat "$input_event/device/name" 2>/dev/null || true)" = "Atmel mXT Touchscreen" ]; then
        touch_event="/dev/input/${input_event##*/}"
        break
    fi
done

if [ -z "$touch_event" ] || [ ! -c "$touch_event" ]; then
    echo "QEMU touchscreen input device was not found" >&2
    exit 1
fi

ln -sfn "$touch_event" /dev/input/qemu-touchscreen
chmod 0600 "$touch_event"

device_major=$(cut -d: -f1 /sys/class/misc/kfgles2/dev)
device_minor=$(cut -d: -f2 /sys/class/misc/kfgles2/dev)
if [ ! -c /dev/kfgles2 ]; then
    mknod /dev/kfgles2 c "$device_major" "$device_minor"
fi
chmod 0777 /dev/kfgles2

dbus-uuidgen --ensure=/var/lib/dbus/machine-id

bus_restarted=0

if ! ps | grep -q '[d]bus-daemon --system'; then
    rm -f /var/run/dbus/pid /var/run/dbus/system_bus_socket
    chown messagebus:messagebus /var/run/dbus
    dbus-daemon --system --nofork >/tmp/system-dbus-pr13.log 2>&1 &
    bus_restarted=1
fi

if ! ps | grep -q '[d]bus-daemon --session.*session_bus_socket'; then
    rm -f /tmp/session_bus_socket
    su user -c "$user_env dbus-daemon --session --nofork --address=unix:path=/tmp/session_bus_socket >/tmp/session-dbus-pr13.log 2>&1 &"
    bus_restarted=1
fi

dbus_wait=0
while { [ ! -S /var/run/dbus/system_bus_socket ] || [ ! -S /tmp/session_bus_socket ]; } && [ "$dbus_wait" -lt 20 ]; do
    sleep 1
    dbus_wait=$((dbus_wait + 1))
done

if [ ! -S /var/run/dbus/system_bus_socket ] || [ ! -S /tmp/session_bus_socket ]; then
    echo "D-Bus did not create both bus sockets" >&2
    tail -80 /tmp/system-dbus-pr13.log >&2 || true
    tail -80 /tmp/session-dbus-pr13.log >&2 || true
    exit 1
fi

if [ "$bus_restarted" -eq 1 ]; then
    killall meegotouchhome mcompositor mthemedaemon 2>/dev/null || true
    rm -f /var/run/m.mthemedaemon /tmp/m.mthemedaemon
fi

if ! pidof Xorg >/dev/null 2>&1; then
    # Every UI process owns resources tied to this X server and kfgles2
    # instance.  A process can remain stopped/alive after Xorg disappears,
    # so pidof alone is not a health check.
    killall meegotouchhome mcompositor mthemedaemon 2>/dev/null || true
    sleep 1
    killall -9 meegotouchhome mcompositor mthemedaemon 2>/dev/null || true
    rm -f /var/run/m.mthemedaemon /tmp/m.mthemedaemon

    # /tmp lives on the persistent rootfs in this rescue environment.  A
    # previous unclean shutdown can therefore leave display :0 locked even
    # though no X server is running.
    rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
    Xorg :0 -config /etc/X11/xorg.conf -noreset >/tmp/Xorg-pr13.log 2>&1 &
fi

xorg_wait=0
while { ! pidof Xorg >/dev/null 2>&1 || [ ! -S /tmp/.X11-unix/X0 ]; } && [ "$xorg_wait" -lt 15 ]; do
    sleep 1
    xorg_wait=$((xorg_wait + 1))
done

if ! pidof Xorg >/dev/null 2>&1 || [ ! -S /tmp/.X11-unix/X0 ]; then
    echo "Xorg did not create display :0" >&2
    tail -80 /tmp/Xorg-pr13.log >&2 || true
    exit 1
fi

renice -10 -p "$(pidof Xorg | cut -d' ' -f1)" >/dev/null 2>&1 || true

if ! pidof mthemedaemon >/dev/null 2>&1; then
    rm -f /var/run/m.mthemedaemon /tmp/m.mthemedaemon
    ln -s /var/run/m.mthemedaemon /tmp/m.mthemedaemon
    su user -c "$user_env mthemedaemon >/tmp/mthemedaemon-pr13.log 2>&1 &"
else
    ln -sfn /var/run/m.mthemedaemon /tmp/m.mthemedaemon
fi

theme_wait=0
while [ ! -S /var/run/m.mthemedaemon ] && [ "$theme_wait" -lt 60 ]; do
    sleep 1
    theme_wait=$((theme_wait + 1))
done

if [ ! -S /var/run/m.mthemedaemon ]; then
    echo "mthemedaemon did not create its socket" >&2
    tail -80 /tmp/mthemedaemon-pr13.log >&2 || true
    exit 1
fi

if ! pidof mcompositor >/dev/null 2>&1; then
    su user -c "$user_env mcompositor -nohung >/tmp/mcompositor-pr13.log 2>&1 &"
    sleep 4
fi

renice -10 -p "$(pidof mcompositor | cut -d' ' -f1)" >/dev/null 2>&1 || true

if ! pidof mcompositor >/dev/null 2>&1; then
    echo "mcompositor exited" >&2
    tail -120 /tmp/mcompositor-pr13.log >&2 || true
    exit 1
fi

# The weather background depends on services that are absent from this rescue
# runtime and adds a second full MeeGo Touch process to the one-vCPU cold path.
# Disable only its discovery entry by default and keep the packaged file for a
# fidelity run with HARMATTAN_QEMU_ENABLE_WEATHER=1.
weather_extension=/usr/share/meegotouch/applicationextensions/events-weather.desktop
weather_backup=/usr/local/libexec/harmattan-qemu/disabled-extensions/events-weather.desktop
if [ "${HARMATTAN_QEMU_ENABLE_WEATHER:-0}" = 1 ]; then
    if [ ! -f "$weather_extension" ] && [ -f "$weather_backup" ]; then
        mv "$weather_backup" "$weather_extension"
    fi
else
    mkdir -p "${weather_backup%/*}"
    if [ -f "$weather_extension" ]; then
        mv "$weather_extension" "$weather_backup"
    fi
fi

home_pid=$(pidof meegotouchhome 2>/dev/null | cut -d' ' -f1 || true)
if [ -n "$home_pid" ] && grep -q '^State:.*T' "/proc/$home_pid/status"; then
    kill -9 "$home_pid"
    home_pid=
fi

if [ -z "$home_pid" ]; then
    # --upstart deliberately SIGSTOPs meegotouchhome after initialisation.
    # The rescue environment has no Upstart job to send the matching
    # SIGCONT, so launch it in its documented non-Upstart mode.
    # The PR1.0 QEMU GLES stack does not expose EGL_KHR_image.  Even with
    # -local-theme, the MeeGo graphics system therefore produces invalid EGL
    # pixmap handles; MTheme renders those as solid red diagnostic squares.
    # Raster keeps local theme images on the X11 pixmap path and preserves the
    # real Blanco launcher icons under this hybrid runtime.
    su user -c "$user_env meegotouchhome -local-theme -graphicssystem raster >/tmp/meegotouchhome-pr13.log 2>&1 &"
    sleep 8
fi

if ! pidof meegotouchhome >/dev/null 2>&1; then
    echo "meegotouchhome exited" >&2
    tail -160 /tmp/meegotouchhome-pr13.log >&2 || true
    exit 1
fi

home_pid=$(pidof meegotouchhome | cut -d' ' -f1)
if grep -q '^State:.*T' "/proc/$home_pid/status"; then
    echo "meegotouchhome is stopped instead of running" >&2
    tail -160 /tmp/meegotouchhome-pr13.log >&2 || true
    exit 1
fi

renice -10 -p "$home_pid" >/dev/null 2>&1 || true

# A weather-enabled fidelity run still keeps the extension behind interactive
# shell work on the one-vCPU emulator.
extension_pid=$(pidof mapplicationextensionrunner 2>/dev/null | cut -d' ' -f1 || true)
if [ -n "$extension_pid" ]; then
    renice 10 -p "$extension_pid" >/dev/null 2>&1 || true
fi

echo "PR1.3 UI stack is running"
ps | grep -E '[X]org|[m]themedaemon|[m]compositor|[m]eegotouchhome'
