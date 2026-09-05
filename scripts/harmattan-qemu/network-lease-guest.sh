#!/bin/sh
# Invoked only by the snapshot's udhcpc. QEMU's default user network is fixed.
set -eu
case "${1:-}" in
    deconfig) ifconfig eth0 0.0.0.0 ;;
    bound)
        test "${interface:-}" = eth0
        test "${ip:-}" = 10.0.2.15
        test "${subnet:-}" = 255.255.255.0
        test "${router:-}" = 10.0.2.2
        test "${dns:-}" = 10.0.2.3
        ifconfig eth0 "$ip" netmask "$subnet" up
        route add default gw "$router" dev eth0
        printf 'nameserver %s\n' "$dns" > /etc/resolv.conf
        printf 'N00_NETWORK_LEASE ip=%s mask=%s router=%s dns=%s\n' \
            "$ip" "$subnet" "$router" "$dns"
        ;;
    *) exit 1 ;;
esac
