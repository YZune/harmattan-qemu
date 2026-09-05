# Sourced by diagnose-shell-guest.sh inside its disposable guest only.
# Uses its UI environment and the original PR1.3 input method and keyboard.
report_input_method() {
    ime_pid=$(pidof meego-im-uiserver) || return 1
    case "$ime_pid" in ''|*[!0-9]*) return 1 ;; esac
    # Match the statusbar readiness gate: font/theme disk loading can be
    # transiently uninterruptible; do not publish that as a ready checkpoint.
    for ime_state_attempt in 1 2 3 4 5; do
        sed -n '1,8p' "/proc/$ime_pid/status" >/tmp/n00-ime-process.log || return 1
        if grep -q '^State:[[:space:]]*[RS]' /tmp/n00-ime-process.log; then break; fi
        sleep 1
    done
    grep -q '^State:[[:space:]]*[RS]' /tmp/n00-ime-process.log || return 1
    printf '\nN00_IME_BEGIN\nN00_IME_PID %s\n' "$ime_pid"
    cat /tmp/n00-ime-process.log
    readlink "/proc/$ime_pid/exe"
    md5sum /usr/bin/meego-im-uiserver "/proc/$ime_pid/exe" \
        /usr/lib/meego-im-plugins/libmeego-keyboard.so \
        /usr/lib/qt4/plugins/inputmethods/libminputcontext.so
    grep -q '/usr/lib/meego-im-plugins/libmeego-keyboard.so$' "/proc/$ime_pid/maps" || return 1
    printf 'N00_IME_KEYBOARD_MAPPED\n'
    printf 'N00_IME_ARGUMENTS '
    tr '\000' ' ' < "/proc/$ime_pid/cmdline"
    printf '\nN00_IME_OWNER_BEGIN\n'
    su user -c "$user_env dbus-send --session --print-reply --reply-timeout=2000 --dest=org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus.GetConnectionUnixProcessID string:org.maliit.server" || return 1
    printf 'N00_IME_OWNER_END\nN00_IME_ADDRESS_BEGIN\n'
    su user -c "$user_env dbus-send --session --print-reply --reply-timeout=2000 --dest=org.maliit.server /org/maliit/server/address org.freedesktop.DBus.Properties.Get string:org.maliit.Server.Address string:address" || return 1
    printf 'N00_IME_ADDRESS_END\nN00_IME_END\n'
}

start_input_method() {
    test -z "$(pidof meego-im-uiserver 2>/dev/null || true)"
    test "$(md5sum /usr/bin/meego-im-uiserver | cut -d ' ' -f 1)" = bf6a04592241f1764a669324a330b0f1
    test "$(md5sum /usr/lib/meego-im-plugins/libmeego-keyboard.so | cut -d ' ' -f 1)" = 3436d74757597eb83207ab86158788c4
    test "$(md5sum /usr/lib/qt4/plugins/inputmethods/libminputcontext.so | cut -d ' ' -f 1)" = 6877d40e5cdba786a62acaaa4ceb20c3
    # MImGraphicsView's original self-composition path repaints the real client
    # pixmap behind disappearing key bubbles. The system-compositor path leaves
    # stale pixels with this raster Xorg. Do not disable bubbles or prediction.
    # No manual-redirection: mcompositor retains ownership of XComposite.
    su user -c "$user_env meego-im-uiserver -use-self-composition -software -local-theme -graphicssystem raster >/tmp/n00-shell-input-method.log 2>&1 &"
    ime_ready=0
    for ime_attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if report_input_method >/tmp/n00-ime-ready.log 2>&1; then ime_ready=1; break; fi
        sleep 1
    done
    cat /tmp/n00-ime-ready.log
    if [ "$ime_ready" != 1 ]; then tail -80 /tmp/n00-shell-input-method.log; return 1; fi
}

inspect_keyboard_notes() {
    report_input_method || return 1
    notes_pid=$(pidof notes) || return 1
    case "$notes_pid" in ''|*[!0-9]*) return 1 ;; esac
    printf 'N00_NOTES_PID %s\n' "$notes_pid"
    sed -n '1,8p' "/proc/$notes_pid/status"
    md5sum /usr/bin/notes "/proc/$notes_pid/exe"
    tr '\000' '\n' < "/proc/$notes_pid/environ" | grep '^QT_IM_MODULE=MInputContext$' || return 1
    grep -q '/usr/lib/qt4/plugins/inputmethods/libminputcontext.so$' "/proc/$notes_pid/maps" || return 1
    printf 'N00_NOTES_INPUT_CONTEXT_MAPPED\n'
    perl /tmp/n00-shell-x11.pl
    # The inspector only opens the real Notes database with SQLITE_OPEN_READONLY.
    /tmp/n00-ui-helpers/keyboard-notes-read
}
