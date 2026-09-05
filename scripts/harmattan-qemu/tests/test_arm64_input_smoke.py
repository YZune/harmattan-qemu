import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('input_smoke', Path(__file__).resolve().parents[1] / 'smoke-arm64-input.py')
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def serial_fixture():
    # Synthetic validator fixture, never published as runtime evidence.
    lines = ['S: Sysfs=/devices/platform/i2c_omap.2/i2c-2/2-004b/input/input1',
             'N00_INPUT_DEVICE /dev/input/event1 Atmel mXT Touchscreen']
    for axis, maximum in ((48, 863), (50, 0), (53, 863), (54, 479), (57, 9)):
        lines.append(f'N00_INPUT_ABS {axis} 0,0,{maximum},0,0,0')
    lines.append('N00_INPUT_READER_READY')
    packets = []
    for index, (x, y) in enumerate(((215, 119), (0, 0), (863, 479), (646, 239))):
        packets.append(([(1, 330, 1)] if index == 0 else []) +
            [(3, 0, x), (3, 1, y), (3, 53, x), (3, 54, y), (3, 48, 1), (3, 57, 0), (0, 2, 0), (0, 0, 0)])
    packets.extend(([(3, 53, 646), (3, 54, 239), (3, 48, 1), (3, 57, 0), (0, 2, 0), (0, 0, 0)],
                    [(1, 330, 0), (0, 0, 0)]))
    for number, packet in enumerate(packets, 1):
        lines.extend(f'N00_INPUT_EVENT 4.{number} {kind} {code} {value}' for kind, code, value in packet)
        lines.append(f'N00_INPUT_PACKET_{number}')
    lines.extend(('N00_INPUT_RELEASED', 'N00_INPUT_READ_OK', 'N00_INPUT_EXIT_0',
                  '221: 6 GPIO atmel_mxt', 'N00_INPUT_IRQ_DONE'))
    return ('\n'.join(lines) + '\n').encode()


class InputGateTests(unittest.TestCase):
    def test_exact_down_move_corners_release(self):
        result = SMOKE.validate_input_serial(serial_fixture())
        self.assertEqual(result['packets'], 6)
        self.assertTrue(result['released'])

    def test_device_identity_and_axis_ranges(self):
        for old, new in ((b'Atmel mXT Touchscreen', b'Fake input'), (b'2-004b', b'2-004a'),
                         (b'53 0,0,863', b'53 0,0,853'), (b'54 0,0,479', b'54 0,0,480')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                SMOKE.validate_input_serial(serial_fixture().replace(old, new))

    def test_mirrored_or_missing_coordinate_fails(self):
        for old, new in ((b'3 53 215', b'3 53 647'), (b'3 54 119', b'3 54 120'),
                         (b'3 53 863', b'3 53 862'), (b'3 54 0', b'3 54 1')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                SMOKE.validate_input_serial(serial_fixture().replace(old, new))

    def test_contact_is_not_a_release(self):
        for data in (serial_fixture().replace(b'1 330 0', b'1 330 1'),
                     serial_fixture().replace(b'N00_INPUT_RELEASED\n', b''),
                     serial_fixture().replace(b'N00_INPUT_PACKET_6\n', b'')):
            with self.assertRaises(ValueError):
                SMOKE.validate_input_serial(data)

    def test_no_echo_duplicates_or_bad_order(self):
        for marker in (b'N00_INPUT_READER_READY', b'N00_INPUT_RELEASED', b'N00_INPUT_READ_OK',
                       b'N00_INPUT_EXIT_0', b'N00_INPUT_IRQ_DONE'):
            for data in (serial_fixture().replace(marker, b'echo ' + marker), serial_fixture() + marker + b'\n'):
                with self.assertRaises(ValueError):
                    SMOKE.validate_input_serial(data)
        with self.assertRaises(ValueError):
            SMOKE.validate_input_serial(serial_fixture().replace(b'N00_INPUT_PACKET_2', b'N00_INPUT_PACKET_3'))

    def test_timestamps_and_interrupt_activity(self):
        for old, new in ((b'4.3 ', b'4.0 '), (b'4.3 ', b'4.1000000 '),
                         (b'221: 6', b'221: 0'), (b'GPIO atmel_mxt', b'INTC serial')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                SMOKE.validate_input_serial(serial_fixture().replace(old, new))

    def test_failure_cannot_hide_behind_markers(self):
        for error in (b'N00_INPUT_MISSING\n', b'N00_INPUT_EXIT_1\n', b'input packet timeout\n'):
            with self.assertRaises(ValueError):
                SMOKE.validate_input_serial(serial_fixture() + error)

    def test_no_hidden_graphics_or_host_failure(self):
        good = b'N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n'
        SMOKE.validate_input_host(good, 0)
        for data, status in ((good, 1), (good.replace(b'calls=0', b'calls=1'), 0),
                             (good.replace(b'faults=0', b'faults=1'), 0), (good + b'error\n', 0)):
            with self.assertRaises(ValueError):
                SMOKE.validate_input_host(data, status)


if __name__ == '__main__':
    unittest.main()
