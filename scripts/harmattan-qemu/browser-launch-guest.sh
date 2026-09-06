#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Per-application entry; run only inside the prepared QEMU guest.
set -eu
for record in \
    /usr/bin/grob:6162b4b46f28d53e93b9fcba7f4f3f7b \
    /usr/bin/QtWebProcess:5f4bff7d2401dd97cc9f88b1e4b02127 \
    /usr/lib/libQtWebKit2experimental.so.4:d93364105cdecaf69b53571275480d04 \
    /tmp/n00-ui-helpers/n00-browser.so:@HELPER_MD5@; do
    path=${record%:*}; expected=${record#*:}
    if [ "$(md5sum "$path" | cut -d ' ' -f 1)" != "$expected" ]; then
        echo "N00_BROWSER_ERROR launch identity: $path" >&2
        exit 1
    fi
done
export N00_BROWSER_RASTER=6162b4b46f28d53e93b9fcba7f4f3f7b
export N00_BROWSER_MODE=@BROWSER_MODE@
export LD_PRELOAD="/tmp/n00-ui-helpers/n00-browser.so${LD_PRELOAD:+:$LD_PRELOAD}"
exec /usr/bin/grob "$@"
