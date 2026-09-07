"""Portable C tests of the recovered Nokia SDK register contracts."""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    'sdk_power', ROOT / 'scripts/harmattan-qemu/diagnose-sdk-power.py')
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class SDKPowerEvidenceTests(unittest.TestCase):
    RECORD = b'''N00_BME_IDENTITY_OK
N00_BME_ABSENT_REJECTED
N00_BME_STATS_BEGIN
++ BME stat
   battery max. level:    8
   battery cur. level:    6
   battery pct. level:    75
N00_BME_STATS_END
N00_BME_ALIVE
N00_BME_STOPPED
N00_BME_EXIT_0
'''

    def test_original_statistics_do_not_require_a_full_battery(self):
        values = PROBE.validate_serial(self.RECORD.replace(b'\n', b'\r\n'))
        self.assertEqual(values['cur. level'], 6)

    def test_kernel_faults_and_slub_repairs_never_pass(self):
        for error in (b'BUG kmalloc-128: Poison overwritten',
                      b'BUG: bad page state', b'Internal error: Oops',
                      b'Unable to handle kernel NULL pointer dereference',
                      b'Kernel panic - not syncing'):
            with self.subTest(error=error), self.assertRaises(ValueError):
                PROBE.validate_kernel_log(b'boot\r\n<3>[    0.174] ' + error + b'\r\n' + self.RECORD)

    def test_missing_security_backend_is_a_readiness_fact_not_a_kernel_crash(self):
        PROBE.validate_kernel_log(b'[ 0.2] sec_init: kci parameter is not set\n'
                                  b'BB5 open failed -1\n' + self.RECORD)

    def test_missing_identity_exit_or_liveness_is_not_a_pass(self):
        for marker in (b'N00_BME_IDENTITY_OK', b'N00_BME_ABSENT_REJECTED',
                       b'N00_BME_ALIVE', b'N00_BME_STOPPED', b'N00_BME_EXIT_0'):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                PROBE.validate_serial(self.RECORD.replace(marker, b'FAILED'))

    def test_duplicate_records_are_not_a_pass(self):
        for data in (self.RECORD * 2, self.RECORD.replace(
                b'N00_BME_STATS_BEGIN', b'N00_BME_STATS_BEGIN\nN00_BME_STATS_BEGIN')):
            with self.assertRaises(ValueError):
                PROBE.validate_serial(data)

    def test_unknown_or_invalid_capacity_is_not_a_pass(self):
        for before, after in ((b'level:    8', b'level:    0'),
                              (b'level:    6', b'level:    9'),
                              (b'level:    75', b'level:    101'),
                              (b'level:    6', b'level:    unknown')):
            with self.subTest(after=after), self.assertRaises(ValueError):
                PROBE.validate_serial(self.RECORD.replace(before, after))


class SDKPowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('cc')
        if not compiler:
            raise RuntimeError('SDK power register tests require a C compiler')
        cls.work = tempfile.TemporaryDirectory(prefix='n00-sdk-power-')
        cls.addClassCleanup(cls.work.cleanup)
        cls.program = str(Path(cls.work.name) / 'register-test')
        subprocess.run([compiler, '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'ports/qemu-n00'),
                        str(Path(__file__).with_name('sdk-power-registers-host.c')),
                        '-o', cls.program], check=True, capture_output=True)

    def check_case(self, case):
        result = subprocess.run([self.program, str(case)], check=True,
                                capture_output=True, text=True)
        self.assertEqual(result.stdout, 'PASS\n')

    def test_chip_identity_is_read_only_and_survives_reset(self):
        self.check_case(1)

    def test_status_and_control_masks(self):
        self.check_case(2)

    def test_repeated_start_and_little_endian_transfers(self):
        self.check_case(3)

    def test_status_clear_and_software_reset(self):
        self.check_case(4)

    def test_unsupported_gauge_registers_fail(self):
        self.check_case(5)

    def test_original_adc_bit_layout(self):
        self.check_case(6)
