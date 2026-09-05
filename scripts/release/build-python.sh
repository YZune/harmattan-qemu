#!/bin/sh
# Build a private launcher interpreter; never install into the host prefix.
set -eu
test "$#" -eq 2 || { echo 'Usage: build-python.sh Python-3.12.14.tar.xz new-work-directory' >&2; exit 2; }
archive=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
test "$(shasum -a 256 "$archive" | cut -d ' ' -f 1)" = 5c8462af5790baf43a321a1559dbe0db06d1be4300fb85fb53c40060668e548a
mkdir "$2"
work=$(cd "$2" && pwd)
tar -xf "$archive" -C "$work"
cd "$work/Python-3.12.14"
# This internal interpreter has no pip or third-party site-packages. Release
# packaging selects only the standard-library extension modules it needs.
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
MACOSX_DEPLOYMENT_TARGET=14.0
export MACOSX_DEPLOYMENT_TARGET
./configure --prefix=/opt/harmattan-python --enable-shared --without-ensurepip \
    --disable-test-modules --with-pkg-config=no \
    CFLAGS="-O2 -g0 -ffile-prefix-map=$work=/usr/src/harmattan-python"
make -j "${HARMATTAN_BUILD_JOBS:-8}"
make install DESTDIR="$work/stage"
echo "Private interpreter staged at $work/stage/opt/harmattan-python"
