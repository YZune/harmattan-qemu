#!/bin/sh
# Only inside the prepared PR1.3-on-SDK QEMU guest, never a host or phone.
# Retail libraries stay present; restore the overlay's known symlink contract.
set -eu
grep -q '^# HARMATTAN_QEMU_DIRECT_INVOKER$' /usr/bin/invoker
test "$(md5sum /usr/lib/libEGL.so.1.3.0 | cut -d ' ' -f1)" = 2d33b733564f1adf8d2978f6e74efde2
test "$(md5sum /usr/lib/libGLES_CM.so.1.4.5 | cut -d ' ' -f1)" = fa48bf460368d69fb9e692f6b51a3704
test "$(md5sum /usr/lib/libGLESv2.so.1.4.9 | cut -d ' ' -f1)" = 061a075a2191fd79abd43640851c60b2
for library in EGL GLES_CM GLESv2; do
    case "$library" in EGL) version=1.3.0 ;; GLES_CM) version=1.4.5 ;; GLESv2) version=1.4.9 ;; esac
    for suffix in so so.1; do
        path="/usr/lib/lib$library.$suffix"
        test -L "$path"
        target=$(readlink "$path")
        case "$target" in "lib$library.so.$version"|"lib${library}_r125.so") ;; *) echo "Unknown graphics link: $path -> $target" >&2; exit 1 ;; esac
    done
done
for pair in EGL:1.3.0 GLES_CM:1.4.5 GLESv2:1.4.9; do
    library=${pair%:*}; version=${pair#*:}
    ln -sfn "lib$library.so.$version" "/usr/lib/lib$library.so"
    ln -sfn "lib$library.so.$version" "/usr/lib/lib$library.so.1"
done
# Rebuild the cache without having ldconfig select retail SONAME links again.
ldconfig -X
printf '\nN00_SDK_GRAPHICS_RESTORED\n'
