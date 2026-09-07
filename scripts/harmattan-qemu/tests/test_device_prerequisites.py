"""A successful probe must not be confused with successful service startup."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location("device_prerequisites",
    Path(__file__).resolve().parents[1] / "diagnose-device-prerequisites.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class PrerequisiteTests(unittest.TestCase):
    BLOCKED = b"""N00_PREREQ_BEGIN
N00_PREREQ kernel 2.6.32.26
N00_PREREQ soc OMAP3430/3530 ES1.0-test
N00_PREREQ kci 0
N00_PREREQ kci_firmware missing
N00_PREREQ omap_sec errno_2
N00_PREREQ validator_netlink bind_errno_2
N00_PREREQ ssi_modprobe 1
N00_PREREQ ssi_bound no
N00_PREREQ_END
N00_PREREQ_EXIT_0
"""

    def test_completed_probe_preserves_all_blockers(self):
        result = PROBE.validate_serial(self.BLOCKED.replace(b"\n", b"\r\n"))
        self.assertEqual(result["service_readiness"], "BLOCKED")
        self.assertEqual(len(result["blockers"]), 5)

    def test_available_prerequisites_never_certify_full_services(self):
        data = self.BLOCKED
        for before, after in ((b"kci 0", b"kci 166"),
                              (b"kci_firmware missing", b"kci_firmware present"),
                              (b"omap_sec errno_2", b"omap_sec open"),
                              (b"validator_netlink bind_errno_2", b"validator_netlink bound"),
                              (b"ssi_modprobe 1", b"ssi_modprobe 0"),
                              (b"ssi_bound no", b"ssi_bound yes")):
            data = data.replace(before, after)
        result = PROBE.validate_serial(data)
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["service_readiness"], "UNVERIFIED")
        self.assertTrue(result["unverified"])

    def test_module_load_without_driver_binding_is_blocked(self):
        result = PROBE.validate_serial(self.BLOCKED.replace(b"ssi_modprobe 1", b"ssi_modprobe 0"))
        self.assertIn("original omap_ssi driver did not probe successfully", result["blockers"])

    def test_missing_or_duplicate_facts_are_rejected(self):
        for data in (self.BLOCKED.replace(b"N00_PREREQ kci 0\n", b""),
                     self.BLOCKED.replace(b"N00_PREREQ kci 0\n", b"N00_PREREQ kci 0\n" * 2),
                     self.BLOCKED + b"N00_PREREQ kci 0\n"):
            with self.assertRaises(ValueError):
                PROBE.validate_serial(data)

    def test_failure_truncation_and_malformed_facts_are_rejected(self):
        for before, after in ((b"N00_PREREQ_EXIT_0", b"N00_PREREQ_EXIT_1"),
                              (b"N00_PREREQ_END", b""),
                              (b"kci 0", b"kci invalid"),
                              (b"errno_2", b"errno_0"),
                              (b"ssi_bound no", b"ssi_bound yes please")):
            with self.subTest(after=after), self.assertRaises(ValueError):
                PROBE.validate_serial(self.BLOCKED.replace(before, after))
