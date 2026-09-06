# SPDX-License-Identifier: GPL-2.0-or-later
# Sourced only in the QEMU guest's Home startup. Unknown apps remain unchanged.
prepare_app_viewport() {
    app_viewport_env=
    app=/opt/fbreader/bin/FBReader
    if [ ! -f "$app" ]; then return 0; fi
    if [ "$(md5sum "$app" | cut -d ' ' -f 1)" != a4f60e9b2da8416348101b04140950c0 ]; then
        echo 'N00_APP_VIEWPORT_SKIPPED unknown FBReader version'
        return 0
    fi
    # Verify the actual loader links, not just similarly named files.
    for record in \
        libQtCore.so.4:c2cf68548da8f885ce2aa91ee0e6e212 \
        libQtGui.so.4:24510eddaa9ea5eda5fc4ab1150d02e9 \
        libQtOpenGL.so.4:33332829d385e91cdcbd286c68662f92; do
        library=${record%:*}; expected=${record#*:}
        if [ "$(md5sum "/usr/lib/$library" | cut -d ' ' -f 1)" != "$expected" ]; then
            echo "N00_APP_VIEWPORT_ERROR library $library" >&2
            return 1
        fi
    done
    helper=/tmp/n00-ui-helpers/n00-app-viewport.so
    if [ "$(md5sum "$helper" | cut -d ' ' -f 1)" != '@HELPER_MD5@' ]; then
        echo 'N00_APP_VIEWPORT_ERROR helper identity' >&2
        return 1
    fi
    app_viewport_env="LD_PRELOAD=$helper N00_FB_READER_RASTER=a4f60e9b2da8416348101b04140950c0"
    echo 'N00_APP_VIEWPORT_READY FBReader=0.99.5 Qt=4.7.4'
}
