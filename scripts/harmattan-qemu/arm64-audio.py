"""Private PulseAudio output through the Mac's current CoreAudio device."""
import array
import ctypes
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time


def default_output():
    if platform.system() != 'Darwin':
        raise ValueError('CoreAudio output requires macOS')

    class Address(ctypes.Structure):
        _fields_ = [('selector', ctypes.c_uint32), ('scope', ctypes.c_uint32), ('element', ctypes.c_uint32)]

    api = ctypes.CDLL('/System/Library/Frameworks/CoreAudio.framework/CoreAudio')
    address = Address(int.from_bytes(b'dOut', 'big'), int.from_bytes(b'glob', 'big'), 0)
    value, size = ctypes.c_uint32(), ctypes.c_uint32(4)
    status = api.AudioObjectGetPropertyData(1, ctypes.byref(address), 0, None, ctypes.byref(size), ctypes.byref(value))
    if status or not value.value or size.value != 4:
        raise ValueError('Mac has no readable default audio output')
    return value.value


def validate_pcm(data, seconds=3):
    if not data or len(data) % 4 or len(data) > 44100 * 4 * 30:
        raise ValueError('invalid stereo PCM capture size')
    samples = array.array('h', data)
    if __import__('sys').byteorder != 'little':
        samples.byteswap()
    left, right = samples[::2], samples[1::2]
    active = [i for i, sample in enumerate(left) if abs(sample) > 100]
    if not active:
        raise ValueError('silent output')
    first, last = active[0], active[-1]
    duration = (last - first + 1) / 44100
    signal = left[first:last + 1]
    rms = math.sqrt(sum(x * x for x in signal) / len(signal))
    crossings = sum(a <= 0 < b for a, b in zip(signal, signal[1:]))
    frequency = crossings / duration
    # PulseAudio's 50% software volume is cubic: 0.5**3 amplitude.
    # The 4000-peak triangle therefore has about 289 RMS at this sink.
    expected_rms = 4000 / math.sqrt(3) * .5 ** 3
    if (not seconds - .15 <= duration <= seconds + .25 or not .85 * expected_rms < rms < 1.15 * expected_rms or
            not 425 < frequency < 455 or max(map(abs, samples)) >= 32760 or left != right):
        raise ValueError('output duration, level, frequency or stereo content mismatch')
    return {'format': 's16le', 'rate': 44100, 'channels': 2,
            'active_seconds': round(duration, 4), 'rms': round(rms, 2),
            'frequency_hz': round(frequency, 2), 'peak': max(map(abs, samples)),
            'scope': 'monitor of this private CoreAudio output stream; not a microphone or acoustic measurement'}


def validate_muted(data):
    if len(data) % 4 or not 2.8 <= len(data) / (44100 * 4) <= 3.3 or any(data):
        raise ValueError('muted playback did not produce a complete silent output stream')
    return {'silent': True, 'seconds': round(len(data) / (44100 * 4), 4)}


class Output:
    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.process = self.log = self.temporary = None
        binary = shutil.which(os.environ.get('HARMATTAN_PULSEAUDIO', 'pulseaudio'))
        if not binary:
            raise ValueError('Install PulseAudio for source audio output, or select HARMATTAN_UI_AUDIO=off')
        self.binary = Path(binary).resolve()
        self.pactl, self.parec = (self.binary.with_name(name) for name in ('pactl', 'parec'))
        if not self.pactl.is_file() or not self.parec.is_file():
            raise ValueError('PulseAudio requires its matching pactl and parec tools')
        try:
            device = default_output()
            self.temporary = tempfile.TemporaryDirectory(prefix='n00-audio-', dir='/private/tmp')
            private = Path(self.temporary.name)
            for name in ('runtime', 'state'):
                (private / name).mkdir(mode=0o700)
            self.cookie = os.urandom(256)
            cookie = private / 'cookie'
            cookie.write_bytes(self.cookie)
            cookie.chmod(0o600)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                self.port = probe.getsockname()[1]
            self.server = 'unix:' + str(private / 'runtime/native')
            self.guest_server = f'tcp:10.0.2.2:{self.port}'
            configuration = private / 'output.pa'
            configuration.write_text(
                f'load-module module-coreaudio-device object_id={device} record=no playback=yes\n'
                f'load-module module-native-protocol-unix socket={private}/runtime/native auth-cookie={cookie}\n'
                f'load-module module-native-protocol-tcp listen=127.0.0.1 port={self.port} auth-cookie={cookie}\n')
            self.env = os.environ.copy() | {'PULSE_RUNTIME_PATH': str(private / 'runtime'),
                'PULSE_STATE_PATH': str(private / 'state'), 'PULSE_COOKIE': str(cookie),
                'PULSE_SERVER': self.server, 'LC_ALL': 'en_US.UTF-8'}
            self.log = (self.output / 'pulseaudio.log').open('xb')
            self.process = subprocess.Popen([str(self.binary), '-n', '--daemonize=no', '--use-pid-file=no',
                '--exit-idle-time=-1', '--disable-shm=yes', '--disallow-module-loading=yes',
                '--log-level=debug', '--log-target=stderr', '-F', str(configuration)],
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log, env=self.env)
            deadline = time.monotonic() + 20
            while not (private / 'runtime/native').exists():
                self.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('CoreAudio server startup timed out')
                time.sleep(.05)
            sinks = json.loads(self.control('--format=json', 'list', 'sinks'))
            if len(sinks) != 1 or sinks[0].get('driver') != 'module-coreaudio-device.c':
                raise ValueError('expected one real CoreAudio output sink')
            self.sink = sinks[0]['name']
            self.monitor = sinks[0]['monitor_source']
            # This is the private server's software volume; Mac volume remains
            # under the user's normal controls. No recording device is loaded.
            self.control('set-sink-volume', self.sink, '50%')
            self.info = {'enabled': True, 'backend': 'PulseAudio/CoreAudio', 'host_version':
                subprocess.check_output([str(self.binary), '--version'], env=self.env,
                    stderr=self.log, text=True, timeout=10).strip(),
                'guest_server': self.guest_server, 'recording': False,
                'scope': 'PulseAudio clients through SDK Ethernet; no DAC33/McBSP emulation or Nokia audio policy'}
            (self.output / 'audio.json').write_text(json.dumps(self.info, indent=2) + '\n')
        except BaseException:
            self.close()
            raise

    def control(self, *arguments):
        self.check()
        return subprocess.check_output([str(self.pactl), '--server=' + self.server, *arguments],
                                       env=self.env, stderr=self.log, text=True, timeout=10)

    def check(self):
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError('private PulseAudio server exited; inspect its log')

    def guest_environment(self):
        return f'PULSE_SERVER={self.guest_server} PULSE_COOKIE=/tmp/n00-audio.cookie'

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log:
            self.log.close()
        if self.temporary:
            self.temporary.cleanup()
