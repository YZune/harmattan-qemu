"""Fail closed when the execution diagnostic sees incomplete or wrong CPU state."""
import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "gp_monitor", Path(__file__).resolve().parents[1] / "diagnose-gp-cache-monitor.py")
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class MonitorValidationTests(unittest.TestCase):
    def snapshot(self, registers, psr):
        return " ".join(f"R{i:02d}={registers.get(i, 0):08x}" for i in range(16)) + f" PSR={psr:08x}"

    def test_incomplete_snapshot_rejected(self):
        with self.assertRaises(ValueError):
            monitor.parse_registers("R15=40200200 PSR=600001d3")

    def test_all_registers_and_flags_must_survive(self):
        name = "cache-invalidate"
        _, expected = monitor.fixture(name)
        registers = expected | {15: monitor.BASE + 0x200}
        monitor.validate(name, self.snapshot(registers, 0x600001d3), expected)
        for index in range(16):
            with self.subTest(register=index), self.assertRaises(ValueError):
                monitor.validate(name, self.snapshot(registers | {index: 0}, 0x600001d3), expected)
        with self.assertRaises(ValueError):
            monitor.validate(name, self.snapshot(registers, 0x200001d3), expected)

    def test_unsupported_call_requires_monitor_rejection(self):
        name = "hs-smc"
        monitor.validate(name, self.snapshot({15: 0x80}, 0x600001d6), {})
        for pc, psr in ((monitor.BASE + 0x200, 0x600001d3), (0x80, 0x600001d3),
                        (0x8, 0x600001d6)):
            with self.subTest(pc=pc, psr=psr), self.assertRaises(ValueError):
                monitor.validate(name, self.snapshot({15: pc}, psr), {})
