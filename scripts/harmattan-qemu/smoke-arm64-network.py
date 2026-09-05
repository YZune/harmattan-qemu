#!/usr/bin/env python3
"""Bounded DHCP, guest DNS and bidirectional HTTP test over the real SDK NIC."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


display = sibling('smoke-arm64-display')
network = sibling('arm64-network')


def validate_transfer(data, digest, received):
    lines = data.replace(b'\r', b'').split(b'\n')
    if lines.count(f'{digest}  /tmp/n00-network-download'.encode()) != 1:
        raise ValueError('guest download digest mismatch')
    if lines.count(b'N00_NETWORK_TRANSFER_EXIT_0') != 1:
        raise ValueError('guest network transfer failed')
    if any(line.startswith(b'N00_NETWORK_TRANSFER_EXIT_') and line != b'N00_NETWORK_TRANSFER_EXIT_0' for line in lines):
        raise ValueError('guest command failure')
    if len(received) != 1 or hashlib.md5(received[0]).hexdigest() != digest:
        raise ValueError('host did not receive the exact guest upload')
    addresses = [line.split()[-1].decode() for line in lines if line.startswith(b'N00_NETWORK_DNS ')]
    if len(addresses) != 1:
        raise ValueError('missing unique guest DNS result')
    ipaddress.IPv4Address(addresses[0])
    internet = [line.split()[-1] for line in lines if line.startswith(b'N00_NETWORK_INTERNET_HTTP_200 ')]
    if len(internet) != 1 or not internet[0].isdigit() or not 0 < int(internet[0]) <= 1048576:
        raise ValueError('external HTTP did not return a bounded, nonempty 200 response')
    return {'download_md5': digest, 'upload_md5': digest,
            'bytes_each_way': len(received[0]), 'dns_name': 'example.com', 'dns_address': addresses[0],
            'internet_url': 'http://example.com/', 'internet_status': 200, 'internet_bytes': int(internet[0])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or '-snapshot' not in command or not 0 < args.timeout <= 600:
        parser.error('requires a disposable QEMU command and timeout in (0, 600]')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    payload = os.urandom(65536)
    digest = hashlib.md5(payload).hexdigest()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if self.headers.get('Content-Length') != str(len(payload)):
                self.send_error(400)
                return
            self.connection.settimeout(10)
            received.append(self.rfile.read(len(payload)))
            self.send_response(200)
            self.send_header('Content-Length', '2')
            self.end_headers()
            self.wfile.write(b'OK')

        def log_message(self, *unused):
            pass

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + args.timeout
    serial, child = socket.socketpair()
    process = None
    result = {'passed': False, 'command': command,
              'qemu_sha256': hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
              'scope': 'SDK SMC91C111, DHCP, external DNS/HTTP and bidirectional host HTTP; no TLS or UI connection manager'}
    try:
        with (out / 'serial.log').open('xb') as log, (out / 'qemu-stderr.log').open('xb') as errors:
            process = subprocess.Popen(command + ['-qmp', 'stdio', '-chardev',
                f'socket,id=n00serial,fd={child.fileno()}', '-serial', 'chardev:n00serial', '-monitor', 'none'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                env=display.qemu_environment(), pass_fds=(child.fileno(),), bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)
            display.wait_serial(serial, process, log, lambda data: b'shell ready' in data and b'/ # ' in data, deadline)
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_NETWORK_SHELL\\n'\n")
            display.wait_serial(serial, process, log, lambda data: display.has_line(data, b'N00_NETWORK_SHELL'), deadline)
            result['setup'] = network.configure(serial, process, log, deadline, display)
            print('DHCP acquired; checking guest DNS and packet transfers.', flush=True)
            port = server.server_port
            perl = '''use IO::Socket::INET; use Socket;
$SIG{ALRM}=sub { die "network timeout" }; alarm 30;
my $ip=inet_aton("example.com") or die "DNS failed";
print "\\nN00_NETWORK_DNS ",inet_ntoa($ip),"\\n";
my $s=IO::Socket::INET->new(PeerAddr=>"10.0.2.2",PeerPort=>PORT,Proto=>"tcp",Timeout=>10) or die "connect: $!";
print $s "GET /download HTTP/1.0\\r\\nHost: host\\r\\n\\r\\n";
local $/; my $r=<$s>; close $s;
my ($h,$body)=split(/\\r\\n\\r\\n/,$r,2);
die "HTTP download" unless $h =~ m{^HTTP/1\\.[01] 200 } && length($body)==65536;
open my $f,">","/tmp/n00-network-download" or die $!; binmode $f; print $f $body; close $f or die $!;
$s=IO::Socket::INET->new(PeerAddr=>"10.0.2.2",PeerPort=>PORT,Proto=>"tcp",Timeout=>10) or die "connect: $!";
print $s "POST /upload HTTP/1.0\\r\\nHost: host\\r\\nContent-Length: 65536\\r\\n\\r\\n",$body;
$r=<$s>; close $s; die "HTTP upload" unless $r =~ m{^HTTP/1\\.[01] 200 };
$s=IO::Socket::INET->new(PeerAddr=>inet_ntoa($ip),PeerPort=>80,Proto=>"tcp",Timeout=>10) or die "internet: $!";
print $s "GET / HTTP/1.0\\r\\nHost: example.com\\r\\nConnection: close\\r\\n\\r\\n";
$r=""; while (my $n=read($s,my $chunk,4096)) { $r.=$chunk; die "response too large" if length($r)>1048576; }
close $s; ($h,$body)=split(/\\r\\n\\r\\n/,$r,2);
die "internet HTTP" unless $h =~ m{^HTTP/1\\.[01] 200 } && length($body)>0;
print "N00_NETWORK_INTERNET_HTTP_200 ",length($body),"\\n"; alarm 0;
'''.replace('PORT', str(port))
            encoded = perl.encode().hex()
            serial.sendall(f"perl -e 'print pack(\"H*\",\"{encoded}\")' > /tmp/n00-network-test.pl\n".encode())
            serial.sendall(b"perl /tmp/n00-network-test.pl && md5sum /tmp/n00-network-download; printf '\\nN00_NETWORK_TRANSFER_EXIT_%s\\n' $?; printf 'N00_NETWORK_TRANSFER_FINISHED\\n'\n")
            display.wait_serial(serial, process, log, lambda data: display.has_line(data, b'N00_NETWORK_TRANSFER_FINISHED'), deadline)
            result['transfer'] = validate_transfer((out / 'serial.log').read_bytes(), digest, received)
            serial.sendall(b"sync; printf '\\nN00_NETWORK_SYNCED\\n'\n")
            display.wait_serial(serial, process, log, lambda data: display.has_line(data, b'N00_NETWORK_SYNCED'), deadline)
            qmp.call('quit')
            code = process.wait(timeout=10)
        display.validate_display_host((out / 'qemu-stderr.log').read_bytes(), code)
        result['passed'] = True
        print('PASS: DHCP, external DNS/HTTP and 64 KiB host HTTP transfer in both directions.', flush=True)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        serial.close()
        child.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        (out / 'network-result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
