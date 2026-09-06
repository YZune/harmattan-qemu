#!/usr/bin/env python3
"""Bounded guest PCM and WAV/GStreamer playback through real CoreAudio."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audio = sibling('arm64-audio')
maintenance = sibling('arm64-maintenance')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or '-snapshot' not in command:
        parser.error('requires an independent snapshot command')
    args.output.mkdir(parents=True, exist_ok=False)
    subprocess.run(['sh', str(Path(__file__).with_name('build-audio-guest.sh'))], check=True)
    workspace = Path(os.environ.get('HARMATTAN_PORT_WORKSPACE', Path(__file__).resolve().parents[2] / 'extracted/qemu-arm64-port'))
    binary = (workspace / 'audio-guest/n00-audio-probe').read_bytes()
    result = {'passed': False, 'qemu_sha256': hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
              'probe_sha256': hashlib.sha256(binary).hexdigest(), 'playback': {},
              'scope': 'original guest libpulse and GStreamer WAV pipeline, private CoreAudio output monitor; not Nokia Music UI or acoustic acceptance'}
    output = None
    try:
        output = audio.Output(args.output / 'host')
        with maintenance.Session(command, args.output / 'guest', networking=True) as session:
            script = 'set -eu\n'
            for name, payload in (('probe', binary), ('cookie', output.cookie)):
                script += f"perl -e 'print pack(\"H*\",\"{payload.hex()}\")' > /tmp/n00-audio.{name}\n"
            script += 'chmod 755 /tmp/n00-audio.probe\nchmod 600 /tmp/n00-audio.cookie\nchown user /tmp/n00-audio.cookie\n'
            session.run(script, 'N00_AUDIO_SETUP')
            for mode, marker in (('pulse', b'N00_AUDIO_PULSE_DRAINED frames=132300'),
                                 ('gstreamer', b'N00_AUDIO_GSTREAMER_EOS'),
                                 ('muted', b'N00_AUDIO_PULSE_DRAINED frames=132300')):
                if mode == 'muted':
                    output.control('set-sink-mute', output.sink, '1')
                raw_path = args.output / (mode + '.raw')
                with raw_path.open('xb') as raw, (args.output / (mode + '-monitor.log')).open('xb') as errors:
                    recorder = subprocess.Popen([str(output.parec), '--server=' + output.server,
                        '--device=' + output.monitor, '--raw', '--format=s16le', '--rate=44100',
                        '--channels=2', '--latency-msec=50'], env=output.env, stdout=raw, stderr=errors)
                    try:
                        playback = 'pulse' if mode == 'muted' else mode
                        data = session.run(f"printf '\\n'\nsu user -c 'HOME=/home/user {output.guest_environment()} /tmp/n00-audio.probe {playback}'\n",
                                           'N00_AUDIO_' + mode.upper(), timeout=45)
                        if data.splitlines().count(marker) != 1:
                            raise ValueError('missing completed guest playback')
                    finally:
                        recorder.terminate()
                        recorder.wait(timeout=10)
                result['playback'][mode] = (audio.validate_muted if mode == 'muted' else audio.validate_pcm)(raw_path.read_bytes())
                print(f'PASS: guest {mode} playback reached the CoreAudio output stream.', flush=True)
            output.control('set-sink-mute', output.sink, '0')
            output.check()
        result.update(passed=True, audio=output.info)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        if output:
            output.close()
        (args.output / 'audio-result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
