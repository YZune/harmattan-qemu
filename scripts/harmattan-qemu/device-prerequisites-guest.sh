#!/bin/sh
# Run only through the disposable diagnostic. Never initialize/relax Aegis here.
set -eu
test "$(uname -m)" = armv7l
grep -q 'n00.device_prerequisites=1' /proc/cmdline
for service in dsme mce csd bme_RX-71; do
    test -z "$(pidof "$service" 2>/dev/null || true)"
done

printf '\nN00_PREREQ_BEGIN\n'
printf 'N00_PREREQ kernel %s\n' "$(uname -r)"
soc=$(sed -n 's/^SoC Info[[:space:]]*:[[:space:]]*//p' /proc/cpuinfo)
printf 'N00_PREREQ soc %s\n' "${soc:-unknown}"
kci=unknown
if test -r /sys/module/omap_sec/parameters/kci; then
    kci=$(cat /sys/module/omap_sec/parameters/kci)
fi
printf 'N00_PREREQ kci %s\n' "$kci"
firmware=missing
if test "$kci" != unknown && test "$kci" != 0 &&
   test -s "/lib/firmware/omap3_pa_${kci}.bin" &&
   test -s "/lib/firmware/omap3_pafmt_${kci}.bin"; then
    firmware=present
fi
printf 'N00_PREREQ kci_firmware %s\n' "$firmware"

# A device node alone is insufficient; sec_open also requires a backend.
# Do not manufacture a node, certificates, a KCI, or secure-call responses.
perl -e 'use Fcntl qw(O_RDWR); if (sysopen(my $f, "/dev/omap_sec", O_RDWR)) {
    print "N00_PREREQ omap_sec open\n"; close $f;
} else { print "N00_PREREQ omap_sec errno_", 0+$!, "\n"; }'

# Exact Linux sockaddr_nl ABI and DSME validatorlistener protocol/group.
# Opening the socket alone misses the observed bind failure.
perl -e 'my $s; if (!socket($s, 16, 3, 25)) {
    print "N00_PREREQ validator_netlink socket_errno_", 0+$!, "\n";
} elsif (!bind($s, pack("SSII", 16, 0, $$, 1))) {
    print "N00_PREREQ validator_netlink bind_errno_", 0+$!, "\n";
} else { print "N00_PREREQ validator_netlink bound\n"; close $s; }'

ssi_exit=0
modprobe omap_ssi >/tmp/n00-prerequisites-ssi.log 2>&1 || ssi_exit=$?
cat /tmp/n00-prerequisites-ssi.log
printf 'N00_PREREQ ssi_modprobe %s\n' "$ssi_exit"
ssi_bound=no
if test -L /sys/bus/platform/drivers/omap_ssi/omap_ssi.0; then
    ssi_bound=yes
fi
printf 'N00_PREREQ ssi_bound %s\n' "$ssi_bound"
printf 'N00_PREREQ_END\n'
# Keep the underlying driver errors in local evidence, outside parsed facts.
dmesg | grep -E 'omap_sec|omap_hs|HS/EMU|SSI|ssi|validator' || true
