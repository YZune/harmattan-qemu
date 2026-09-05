"""Configure the real SDK Ethernet driver through QEMU's user network."""
from pathlib import Path
import re


def validate_setup(data):
    lines = data.replace(b'\r', b'').split(b'\n')
    lease = b'N00_NETWORK_LEASE ip=10.0.2.15 mask=255.255.255.0 router=10.0.2.2 dns=10.0.2.3'
    for line in (lease, b'N00_NETWORK_READY', b'N00_NETWORK_EXIT_0', b'N00_NETWORK_FINISHED'):
        if lines.count(line) != 1:
            raise ValueError('network setup did not complete with one valid DHCP lease')
    exits = [line for line in lines if re.fullmatch(rb'N00_NETWORK_EXIT_\d+', line)]
    if exits != [b'N00_NETWORK_EXIT_0']:
        raise ValueError('network command failure')
    return {'enabled': True, 'backend': 'slirp', 'interface': 'eth0',
            'address': '10.0.2.15', 'gateway': '10.0.2.2', 'dns': '10.0.2.3',
            'dhcp': True, 'scope': 'SDK Ethernet and initial DHCP lease; no Wi-Fi or connection-manager emulation'}


def configure(serial, process, log, deadline, display):
    for filename, target, tag in (
            ('network-lease-guest.sh', '/tmp/n00-network-lease.sh', 'N00_NETWORK_LEASE_SCRIPT'),
            ('network-guest.sh', '/tmp/n00-network.sh', 'N00_NETWORK_SCRIPT')):
        payload = Path(__file__).with_name(filename).read_bytes().hex()
        serial.sendall(f"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' > {target} <<'{tag}'\n".encode())
        for offset in range(0, len(payload), 76):
            serial.sendall(payload[offset:offset + 76].encode() + b'\n')
        serial.sendall(f"{tag}\nprintf '\\n{tag}_DONE\\n'\n".encode())
        display.wait_serial(serial, process, log,
                            lambda data: display.has_line(data, f'{tag}_DONE'.encode()), deadline)
    serial.sendall(b"sh /tmp/n00-network.sh; printf '\\nN00_NETWORK_EXIT_%s\\n' $?; printf 'N00_NETWORK_FINISHED\\n'\n")
    display.wait_serial(serial, process, log,
                        lambda data: display.has_line(data, b'N00_NETWORK_FINISHED'), deadline)
    log.flush()
    return validate_setup(Path(log.name).read_bytes())
