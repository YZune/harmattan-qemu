# SPDX-License-Identifier: GPL-2.0-or-later
# Sourced in the QEMU guest before starting the original session bus/Home.
prepare_browser() {
    test ! -L /tmp/n00-browser-runtime
    mkdir -p /tmp/n00-browser-runtime
    mount -t tmpfs -o size=512k,mode=0755 tmpfs /tmp/n00-browser-runtime
    for record in \
        /usr/share/applications/browser.desktop:browser.desktop:4efc2178f074de927851cd26f30dd94f:@DESKTOP_MD5@ \
        /usr/share/dbus-1/services/com.nokia.browser.service:com.nokia.browser.service:5d51786364f868cc99ae9250d3d37f45:@SERVICE_MD5@; do
        target=${record%%:*}; rest=${record#*:}
        name=${rest%%:*}; rest=${rest#*:}
        original=${rest%:*}; adapted=${rest#*:}
        test -f "$target"
        test ! -L "$target"
        if grep -Fq " $target " /proc/mounts; then
            echo "N00_BROWSER_ERROR entry already mounted: $target" >&2
            return 1
        fi
        test "$(md5sum "$target" | cut -d ' ' -f 1)" = "$original"
        test "$(md5sum "/tmp/n00-ui-helpers/$name" | cut -d ' ' -f 1)" = "$adapted"
        cp "/tmp/n00-ui-helpers/$name" "/tmp/n00-browser-runtime/$name"
        chmod 0644 "/tmp/n00-browser-runtime/$name"
        mount --bind "/tmp/n00-browser-runtime/$name" "$target"
    done
    chmod 0755 /tmp/n00-ui-helpers/browser-launch-guest.sh
    printf '\nN00_BROWSER_SETUP_BEGIN\n'
    md5sum /usr/bin/grob /usr/bin/QtWebProcess /usr/lib/libQtWebKit2experimental.so.4 \
        /tmp/n00-ui-helpers/n00-browser.so /usr/share/applications/browser.desktop \
        /usr/share/dbus-1/services/com.nokia.browser.service
    grep -E ' /usr/share/(applications/browser.desktop|dbus-1/services/com.nokia.browser.service) tmpfs ' /proc/mounts
    printf 'N00_BROWSER_SETUP_END\n'
}
