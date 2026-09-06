import array
import importlib.util
import math
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('audio', ROOT / 'scripts/harmattan-qemu/arm64-audio.py')
AUDIO = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIO)


def pcm(seconds=3, frequency=440, level=400, stereo=True):
    result = array.array('h')
    for index in range(round(seconds * 44100)):
        value = round(level * math.sin(2 * math.pi * frequency * index / 44100))
        result.extend((value, value if stereo else 0))
    if sys.byteorder != 'little':
        result.byteswap()
    return result.tobytes()


class AudioTests(unittest.TestCase):
    def test_policy_requires_original_live_process_and_both_bus_owners(self):
        report = b'''N00_AUDIO_POLICY_BEGIN
N00_AUDIO_POLICY_PID 716
Name:\tohmd
State:\tS (sleeping)
Tgid:\t716
Pid:\t716
PPid:\t1
TracerPid:\t0
Uid:\t0\t0\t0\t0
Gid:\t0\t0\t0\t0
/usr/sbin/ohmd
96dc1f6be9c836dc5b2c51b54f4d74b4  /usr/sbin/ohmd
96dc1f6be9c836dc5b2c51b54f4d74b4  /proc/716/exe
N00_AUDIO_POLICY_OWNER org.freedesktop.ohm
method return sender=org.freedesktop.DBus -> dest=:1.27 reply_serial=2
   uint32 716
N00_AUDIO_POLICY_OWNER org.maemo.resource.manager
method return sender=org.freedesktop.DBus -> dest=:1.28 reply_serial=2
   uint32 716
N00_AUDIO_POLICY_END
'''
        self.assertEqual(AUDIO.validate_policy(report)['pid'], 716)
        for bad in (b'', report + report, report.replace(b'S (sleeping)', b'T (stopped)'),
                    report.replace(b'TracerPid:\t0', b'TracerPid:\t50'),
                    report.replace(b'Uid:\t0', b'Uid:\t29999'),
                    report.replace(b'uint32 716', b'uint32 717', 1),
                    report.replace(b'org.maemo.resource.manager', b'org.example.other'),
                    report.replace(b'96dc1f6be9c836dc5b2c51b54f4d74b4', b'0' * 32, 1),
                    report.replace(b'/usr/sbin/ohmd\n', b'/usr/bin/substitute\n', 1)):
            with self.subTest(report=bad), self.assertRaises(ValueError):
                AUDIO.validate_policy(bad)

    def test_real_signal_has_duration_frequency_and_equal_channels(self):
        result = AUDIO.validate_pcm(b'\0' * 4000 + pcm() + b'\0' * 4000)
        self.assertAlmostEqual(result['active_seconds'], 3, delta=.01)
        self.assertAlmostEqual(result['frequency_hz'], 440, delta=1)
        self.assertAlmostEqual(result['rms'], 283, delta=3)

    def test_silence_truncation_noise_and_wrong_signal_fail(self):
        for data in (b'', b'\0' * 1000, b'\1', pcm(seconds=.5), pcm(seconds=5),
                     pcm(frequency=880), pcm(level=10), pcm(level=32767), pcm(stereo=False)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                AUDIO.validate_pcm(data)

    def test_gap_in_playback_is_not_a_continuous_tone(self):
        data = pcm(seconds=1.5) + b'\0' * (44100 * 4) + pcm(seconds=1.5)
        with self.assertRaises(ValueError):
            AUDIO.validate_pcm(data)

    def test_muted_capture_requires_full_silence_not_missing_data(self):
        silence = b'\0' * (44100 * 4 * 3)
        self.assertTrue(AUDIO.validate_muted(silence)['silent'])
        for bad in (b'', silence[:1000], silence + b'\0', b'\1' + silence[1:], pcm()):
            with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                AUDIO.validate_muted(bad)


if __name__ == '__main__':
    unittest.main()
