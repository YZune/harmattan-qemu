"""Optional per-session guest CA store from the selected host Python's trust store."""
import hashlib
import re
import ssl


def host_store():
    certificates = sorted(set(ssl.create_default_context().get_ca_certs(binary_form=True)))
    if not 1 <= len(certificates) <= 1024 or any(not 64 <= len(cert) <= 32768 for cert in certificates):
        raise ValueError('host Python CA store is empty or outside the supported bounds')
    payload = ''.join(ssl.DER_cert_to_PEM_cert(cert) for cert in certificates).encode('ascii')
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('host CA store exceeds 2 MiB')
    # Independently parse the exported PEM before it reaches the guest. Only
    # public trust anchors are exported; no private keys or client certificates.
    checked = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    checked.load_verify_locations(cadata=payload.decode('ascii'))
    if len(checked.get_ca_certs()) != len(certificates):
        raise ValueError('exported host CA store did not preserve its trust anchors')
    return payload, {'enabled': True, 'source': 'selected host Python default TLS CA store',
        'count': len(certificates), 'bytes': len(payload),
        'sha256': hashlib.sha256(payload).hexdigest(), 'md5': hashlib.md5(payload).hexdigest(),
        'scope': 'temporary guest CA mount; certificate, hostname and validity checks remain enabled'}


def install(serial, wait_line, upload, output, payload, info):
    serial.sendall(b"sh -eu <<'N00_CA_PREPARE'\n"
        b"test ! -L /tmp/n00-host-ca\n"
        b"test ! -L /etc/ssl/certs\n"
        b"! grep -q ' /etc/ssl/certs ' /proc/mounts\n"
        b"mkdir -p /tmp/n00-host-ca /etc/ssl/certs\n"
        b"mount -t tmpfs -o size=3m,mode=0755 tmpfs /tmp/n00-host-ca\n"
        b"mount --bind /tmp/n00-host-ca /etc/ssl/certs\n"
        b"N00_CA_PREPARE\n"
        b"printf '\\nN00_CA_PREPARE_EXIT_%s\\n' $?; printf 'N00_CA_PREPARE_DONE\\n'\n")
    wait_line(b'N00_CA_PREPARE_DONE')
    data = (output / 'serial.log').read_bytes().replace(b'\r', b'')
    if re.findall(rb'^N00_CA_PREPARE_EXIT_(\d+)$', data, re.M) != [b'0']:
        raise ValueError('temporary guest CA mount failed')
    # The serial transport must be drained between bounded chunks. A whole
    # modern CA bundle can fill both ends of the UART/socket queues.
    for index, start in enumerate(range(0, len(payload), 8192)):
        tag = f'N00_CA_CHUNK_{index}'
        upload(payload[start:start + 8192], '/tmp/n00-host-ca/chunk', tag)
        serial.sendall((f"cat /tmp/n00-host-ca/chunk >> /tmp/n00-host-ca/ca.pem; "
            f"printf '\\n{tag}_APPEND_EXIT_%s\\n' $?; printf '{tag}_APPEND_DONE\\n'\n").encode())
        wait_line((tag + '_APPEND_DONE').encode())
        data = (output / 'serial.log').read_bytes().replace(b'\r', b'')
        if re.findall(rb'^' + tag.encode() + rb'_APPEND_EXIT_(\d+)$', data, re.M) != [b'0']:
            raise ValueError('guest CA chunk append failed')
    serial.sendall(b"sh -eu <<'N00_CA_CHECK'\n"
        b"chmod 0644 /tmp/n00-host-ca/ca.pem\n"
        b"printf '\\nN00_CA_REPORT_BEGIN\\n'\n"
        b"md5sum /etc/ssl/certs/ca.pem\n"
        b"grep -c '^-----BEGIN CERTIFICATE-----$' /etc/ssl/certs/ca.pem\n"
        b"grep ' /etc/ssl/certs tmpfs ' /proc/mounts\n"
        b"printf 'N00_CA_REPORT_END\\n'\n"
        b"N00_CA_CHECK\n"
        b"printf '\\nN00_CA_CHECK_EXIT_%s\\n' $?; printf 'N00_CA_CHECK_DONE\\n'\n")
    wait_line(b'N00_CA_CHECK_DONE')
    validate_install((output / 'serial.log').read_bytes(), info)


def validate_install(data, info):
    data = data.replace(b'\r', b'')
    digest = info['md5'].encode()
    reports = re.findall(rb'^N00_CA_REPORT_BEGIN\n(.*?)^N00_CA_REPORT_END$', data, re.M | re.S)
    if (re.findall(rb'^N00_CA_CHECK_EXIT_(\d+)$', data, re.M) != [b'0'] or
            data.splitlines().count(b'N00_CA_REPORT_BEGIN') != 1 or
            data.splitlines().count(b'N00_CA_REPORT_END') != 1 or
            len(reports) != 1 or
            re.findall(rb'^([0-9a-f]{32})  /etc/ssl/certs/ca.pem\n(\d+)\n', reports[0], re.M) !=
            [(digest, str(info['count']).encode())] or
            len(re.findall(rb'^tmpfs /etc/ssl/certs tmpfs [^\n]+$', reports[0], re.M)) != 1):
        raise ValueError('guest CA bytes, count or temporary mount did not match the host export')
