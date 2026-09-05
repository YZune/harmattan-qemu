#!/bin/sh
# Run inside a derived QEMU guest; never on the host or a phone.
set -eu
test -r /sys/class/net/eth0/address
test "$(cat /sys/class/net/eth0/address)" = 52:54:00:12:34:56
test -x /sbin/udhcpc
chmod 0700 /tmp/n00-network-lease.sh
ifconfig lo 127.0.0.1 up
/sbin/udhcpc -n -q -i eth0 -s /tmp/n00-network-lease.sh
ifconfig eth0
route -n
cat /etc/resolv.conf
printf 'N00_NETWORK_READY\n'
