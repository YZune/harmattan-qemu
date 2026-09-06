#!/usr/bin/env python3
"""Install explicitly supplied ARMEL packages inside a closed private profile."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import secrets
import shlex
import threading

import importlib.util


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


packages = sibling('armel-packages')
maintenance = sibling('arm64-maintenance')


def prepare(paths):
    if not 1 <= len(paths) <= 24:
        raise ValueError('supply 1 to 24 reviewed packages in dependency order')
    records, payloads, names, total = [], [], set(), 0
    for path in paths:
        path = Path(path)
        if not path.is_file() or not 0 < path.stat().st_size <= packages.MAX_PACKAGE:
            raise ValueError('invalid or oversized package input')
        payload = path.read_bytes()
        record = packages.inspect_bytes(payload)
        total += len(payload)
        if record['package'] in names or total > 96 * 1024 ** 2:
            raise ValueError('duplicate package or batch exceeds 96 MiB')
        names.add(record['package'])
        records.append(dict(filename=path.name, **record))
        payloads.append(payload)
    return records, payloads


def install_script(records, token, port):
    # URLs are private random names; the host never exposes a directory server.
    lines = ['set -eu', 'test -x /usr/bin/dpkg.real', 'command -v sha1sum',
             'mkdir -m 700 /tmp/n00-packages', "cat > /tmp/n00-fetch.pl <<'N00_FETCH'",
             '''use IO::Socket::INET;
$SIG{ALRM}=sub { die "package download timeout" }; alarm 90;
my ($port,$path,$target,$length)=@ARGV;
my $s=IO::Socket::INET->new(PeerAddr=>"10.0.2.2",PeerPort=>$port,Proto=>"tcp",Timeout=>10) or die $!;
print $s "GET $path HTTP/1.0\\r\\nHost: host\\r\\n\\r\\n";
my $status=<$s>; die "HTTP status" unless $status =~ m{^HTTP/1\\.[01] 200 };
my $header=""; while (my $line=<$s>) { last if $line eq "\\r\\n"; $header.=$line; die "headers too large" if length($header)>8192; }
die "HTTP length" unless $header =~ /^Content-Length: (\\d+)\\r$/mi && $1==$length;
open my $f,">",$target or die $!; binmode $f;
my $received=0; while (1) { my $n=read($s,my $chunk,65536); die $! unless defined $n; last unless $n; $received+=$n; die "oversized body" if $received>$length; print $f $chunk or die $!; }
close $f or die $!; close $s; die "short body" unless $received==$length; alarm 0;
''', 'N00_FETCH']
    targets = []
    for i, record in enumerate(records):
        target = f'/tmp/n00-packages/{i}.deb'
        targets.append(target)
        lines += [f'perl /tmp/n00-fetch.pl {port} /{token}/{i} {target} {record["bytes"]}',
                  f"printf '%s\\n' '{record['sha1']}  {target}' | sha1sum -c -"]
    lines += ['DEBIAN_FRONTEND=noninteractive /usr/bin/dpkg.real --install ' + ' '.join(targets)]
    for record in records:
        lines.append("dpkg-query -W -f='N00_PACKAGE ${Package} ${Version} ${Status}\\n' " + shlex.quote(record['package']))
    # Remove only this session's downloaded copies after successful configure.
    lines += ['rm ' + ' '.join(targets), 'rmdir /tmp/n00-packages']
    return '\n'.join(lines) + '\n'


def validate_install(data, records):
    actual = [line for line in data.splitlines() if line.startswith(b'N00_PACKAGE ')]
    expected = [f'N00_PACKAGE {r["package"]} {r["version"]} install ok installed'.encode() for r in records]
    if actual != expected:
        raise ValueError('dpkg did not configure every requested package at the inspected version')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--image-tool', type=Path, required=True)
    parser.add_argument('--package-list', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    paths = json.loads(args.package_list.read_text())
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        parser.error('package list must be a JSON array of filenames')
    records, payloads = prepare(paths)
    args.output.mkdir(parents=True, exist_ok=False)
    token = secrets.token_hex(24)
    routes = {f'/{token}/{i}': payload for i, payload in enumerate(payloads)}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            payload = routes.get(self.path)
            if payload is None:
                self.send_error(404)
                return
            self.connection.settimeout(30)
            self.send_response(200)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *unused):
            pass

    result = {'passed': False, 'packages': records,
              'qemu_sha256': hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
              'scope': 'guest dpkg configuration only; application launch and functions require separate validation'}
    profile = server = thread = None
    try:
        profile = maintenance.storage.Profile(args.profile, args.base, args.image_tool)
        command = maintenance.storage.persistent_command(command, profile.disk)
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with maintenance.Session(command, args.output / 'guest', profile, networking=True) as session:
            graphics = Path(__file__).with_name('restore-sdk-graphics-guest.sh').read_text()
            session.run(graphics, 'N00_GRAPHICS_BEFORE')
            print('Guest network ready; transferring and configuring reviewed packages.', flush=True)
            try:
                data = session.run(install_script(records, token, server.server_port), 'N00_INSTALL', timeout=600)
                validate_install(data, records)
            finally:
                # Standard package triggers can restore retail SGX SONAME
                # symlinks. Keep the prepared SDK adaptation usable, also
                # when dpkg reports an ordinary package/configuration failure.
                session.run(graphics, 'N00_GRAPHICS_AFTER')
        result.update(passed=True, profile_state=profile.state['state'])
        print('PASS: every requested package configured; private profile flushed and closed.', flush=True)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if profile:
            result['profile_state'] = profile.state['state']
            profile.close()
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join(timeout=2)
        (args.output / 'install-result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
