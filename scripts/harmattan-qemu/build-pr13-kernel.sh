#!/bin/sh
# Experimental PR1.3 kernel build. Does not install into any guest or host.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
work_root=${HARMATTAN_KERNEL_WORKSPACE:-"$repo_root/extracted/pr13-kernel"}
kernel_archive=${HARMATTAN_KERNEL_SOURCE:-"$repo_root/downloads/tools/kernel_2.6.32-20121301+0m8.tar.gz"}
adaptation_archive=${HARMATTAN_KERNEL_QEMU_SOURCE:-"$repo_root/downloads/tools/kernel-qemu_2.6.32.20112701+0m6.tar.gz"}
gles_archive=${HARMATTAN_GLES_TARBALL:-"$repo_root/downloads/tools/gles-libs_1.4.2-3+0m6.tar.gz"}
cross=${HARMATTAN_KERNEL_CROSS_COMPILE:-arm-linux-gnueabi-}
jobs=${HARMATTAN_BUILD_JOBS:-6}
if [ "$#" != 0 ]; then
    echo "Usage: sh $0 (configure inputs and toolchain with HARMATTAN_* variables)" >&2
    exit 2
fi
if [ "$(uname -s)" != Linux ]; then
    echo 'This experimental kernel builder requires a Linux build host or isolated VM.' >&2
    exit 1
fi
case "$jobs" in ''|*[!0-9]*|0) echo 'Invalid build job count.' >&2; exit 1;; esac
case "$work_root" in *' '*|*','*) echo 'Kernel workspace must not contain spaces or commas.' >&2; exit 1;; esac
for tool in make patch tar sha256sum sed grep awk find sort xargs lzop depmod "${cross}gcc" "${cross}nm"; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
case "$("${cross}gcc" -dumpmachine)" in arm*-*) ;; *) echo 'An ARM32 cross compiler is required.' >&2; exit 1;; esac
case "$("${cross}gcc" -dumpversion)" in 4.*) ;; *) echo 'This legacy kernel build requires GCC 4.x; GCC 4.9.4 was tested.' >&2; exit 1;; esac
verify_archive() {
    test -f "$1" || { echo "Missing source archive: $1" >&2; exit 1; }
    actual=$(sha256sum "$1" | cut -d ' ' -f 1)
    test "$actual" = "$2" || { echo "Source archive SHA-256 mismatch: $1" >&2; exit 1; }
}
verify_archive "$kernel_archive" 2ceddaf3a460c21e8ab779393de9096058bf99623e620e42c98bcaf6a65b2cd8
verify_archive "$adaptation_archive" 1599efe16deaaee36bdcea7fa3f95dc6ca80b324c1350d1516695f4708eb7331
verify_archive "$gles_archive" 2a611910254d877b76d4da26bbf679b9341a63f9eb2453790daf10928a188711
# Refuse even an empty existing directory: a failed build is retained as evidence.
test ! -e "$work_root" && test ! -L "$work_root" || {
    echo 'Kernel workspace already exists; select a fresh directory.' >&2; exit 1;
}
mkdir -p "$(dirname -- "$work_root")"
mkdir "$work_root"
work_root=$(CDPATH= cd -- "$work_root" && pwd)
touch "$work_root/.case-probe"
test ! -e "$work_root/.CASE-PROBE" || { echo 'A case-sensitive filesystem is required for kernel sources and modules.' >&2; exit 1; }
rm "$work_root/.case-probe"
sha256sum "$kernel_archive" "$adaptation_archive" "$gles_archive" > "$work_root/input-sha256.txt"
tar -xzf "$kernel_archive" -C "$work_root"
tar -xzf "$adaptation_archive" -C "$work_root"
tar -xzf "$gles_archive" -C "$work_root" gles-libs-1.4.2/kfgles2
cd "$work_root/kernel-2.6.32"
export ARCH=arm CROSS_COMPILE="$cross" GIT_CEILING_DIRECTORIES="$work_root"
find security/aegis -type f -print0 | sort -z | xargs -0 sha256sum > "$work_root/aegis-original-sha256.txt"
# Same four patches and order as Nokia's kernel-qemu debian/rules. Its
# commented-out emmc.patch is deliberately not part of the build.
for name in board-rx71-video panel-generic smc rm581_defconfig; do
    patch --batch --fuzz=0 -p1 -i "$work_root/kernel-qemu-2.6.32.20112701+0m6/patches/$name.patch"
done
patch --batch --fuzz=0 -p1 -i "$repo_root/ports/guest-kernel/kernel-2.6.32-build-tools.patch"
# Recent ld places an orphan build-id note before .text.head. objcopy removes
# it, shifting the raw image away from its linked address and breaking MMU entry.
# GCC 4.9 otherwise emits unaligned ARMv7 loads for packed kernel structures;
# this kernel enables alignment traps and predates that compiler default.
# Its ARM memset advances r0 and relies on the header macro to return the
# original pointer. Do not let GCC replace that macro result with r0 as if
# this were a hosted C library; doing so corrupts the console font tables.
kmake() { make HOSTCFLAGS='-O2 -fcommon' KCFLAGS='-mno-unaligned-access -fno-builtin' LDFLAGS_BUILD_ID= "$@"; }
kmake rm581_defconfig
# Separate module ABI directory from both original SDK and retail kernels.
sed -i 's/CONFIG_LOCALVERSION="-dfl61"/CONFIG_LOCALVERSION="-n00-pr13"/; s/CONFIG_LOCALVERSION_AUTO=y/# CONFIG_LOCALVERSION_AUTO is not set/' .config
for option in SECURITY SECURITYFS SECURITY_AEGIS SECURITY_AEGIS_VALIDATOR SECURITY_AEGIS_RESTOK SECURITY_AEGIS_CREDS SECURITY_AEGIS_CREDP OMAP_SEC; do
    grep -qx "CONFIG_${option}=y" .config || { echo "Required original configuration missing: $option" >&2; exit 1; }
done
"${cross}gcc" --version > "$work_root/compiler.txt"
kmake -j "$jobs" zImage modules
kmake M="$work_root/gles-libs-1.4.2/kfgles2" modules
# Verify original source files, ignoring additional Kbuild outputs.
sha256sum -c "$work_root/aegis-original-sha256.txt" > "$work_root/aegis-source-check.txt"
"${cross}nm" vmlinux > "$work_root/kernel-symbols.txt"
grep -q ' validator_netlink_init$' "$work_root/kernel-symbols.txt" || { echo 'Original validator netlink initializer missing.' >&2; exit 1; }
grep -qx 'b0008000 T _stext' "$work_root/kernel-symbols.txt" || { echo 'Kernel entry moved from its required load address.' >&2; exit 1; }
release=$(kmake -s kernelrelease)
test "$release" = 2.6.32.54-n00-pr13 || { echo "Unexpected kernel release: $release" >&2; exit 1; }
output="$work_root/output"
mkdir -p "$output/lib/modules/$release"
cp arch/arm/boot/zImage "$output/zImage-$release"
cp vmlinux System.map .config "$output/"
# Match the SDK's flat module layout, without silently overwriting duplicate names.
find . -name '*.ko' -type f > "$work_root/module-paths.txt"
while IFS= read -r module; do
    dest="$output/lib/modules/$release/$(basename "$module")"
    test ! -e "$dest" || { echo "Duplicate module name: $module" >&2; exit 1; }
    cp "$module" "$dest"
done < "$work_root/module-paths.txt"
cp "$work_root/gles-libs-1.4.2/kfgles2/kfgles2.ko" "$output/lib/modules/$release/"
depmod -b "$output" "$release"
# Harmattan's old module-init-tools consumes absolute text dependency paths.
# Modern kmod's relative paths/binary indexes do not work with that loader.
module_dir="$output/lib/modules/$release"
awk -v prefix="/lib/modules/$release/" '{
    for (i = 1; i <= NF; i++) {
        if ($i !~ /^[A-Za-z0-9_+.-]+\.ko:?$/) exit 1;
        printf "%s%s%s", (i == 1 ? "" : " "), prefix, $i;
    }
    print "";
}' "$module_dir/modules.dep" > "$work_root/modules.dep.legacy"
mv "$work_root/modules.dep.legacy" "$module_dir/modules.dep"
for module_index in modules.dep.bin modules.alias.bin modules.symbols.bin modules.builtin.bin modules.builtin.alias.bin; do
    rm -f "$module_dir/$module_index"
done
(cd "$output"; find . -type f -print0 | sort -z | xargs -0 sha256sum > "$work_root/output-sha256.txt")
tar -czf "$work_root/kernel-bundle.tar.gz" -C "$work_root" output output-sha256.txt compiler.txt input-sha256.txt aegis-original-sha256.txt aegis-source-check.txt kernel-symbols.txt
echo "Built experimental kernel and matching modules: $output"
echo 'Keep kernel-bundle.tar.gz intact on case-insensitive hosts; module names differ by case.'
echo 'Build success does not establish boot, graphics, security initialization or full-service acceptance.'
