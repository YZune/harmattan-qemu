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
