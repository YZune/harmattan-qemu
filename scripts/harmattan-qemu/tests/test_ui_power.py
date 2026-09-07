"""SDK BME opt-in and original-process evidence boundaries."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("ui_power", Path(__file__).resolve().parents[1] / "arm64-ui-power.py")
power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(power)


def report(phase="startup", pid=276):
    owner = ("N00_UI_CELLULAR_OWNER_BEGIN\nmethod return\n   boolean false\nN00_UI_CELLULAR_OWNER_END\n"
             if phase != "startup" else "")
    return (f"N00_UI_POWER_REPORT_BEGIN {phase}\nN00_UI_POWER_PROCESS {pid}\n"
            f"{power.BME_MD5}  /proc/{pid}/exe\nN00_UI_POWER_ARGS " + power.COMMAND.decode() +
            "\nN00_UI_POWER_STATS_BEGIN\nbattery max. level: 8\nbattery cur. level: 6\n"
            f"battery pct. level: 75\nN00_UI_POWER_STATS_END\n{owner}N00_UI_POWER_REPORT_END {phase}\n").encode()


class UIPowerTests(unittest.TestCase):
    def test_disabled_command_is_unchanged(self):
        command = ["qemu", "-append", "console=ttyS0", "-snapshot"]
        self.assertEqual(power.prepare_command(command, "off"), command)
        configured = power.prepare_command(command, "sdk-bme")
        self.assertNotEqual(configured, command)
        self.assertEqual(command[2], "console=ttyS0")
        power.validate_configuration("sdk-bme", system_ui=True, profile=None,
            environment={"HARMATTAN_N00_SDK_POWER": "on"}, command=configured)

    def test_partition_override_and_missing_command_line_rejected(self):
        for command in (["qemu"], ["qemu", "-append"],
                        ["qemu", "-append", "mtdparts=unknown"],
                        ["qemu", "-append", "n00.ui_sdk_power=0"],
                        ["qemu", "-append", "a", "-append", "b"]):
            with self.subTest(command=command), self.assertRaises(ValueError):
                power.prepare_command(command, "sdk-bme")

    def test_missing_hardware_systemui_or_disposable_disk_rejected(self):
        command = power.prepare_command(["qemu", "-append", "console=ttyS0"], "sdk-bme")
        for ui, profile, env in ((False, None, {"HARMATTAN_N00_SDK_POWER": "on"}),
                                  (True, Path("profile"), {"HARMATTAN_N00_SDK_POWER": "on"}),
                                  (True, None, {})):
            with self.subTest(ui=ui, profile=profile, env=env), self.assertRaises(ValueError):
                power.validate_configuration("sdk-bme", system_ui=ui, profile=profile,
                                             environment=env, command=command)

    def test_valid_original_non_full_battery_and_same_process(self):
        result = power.validate_reports(report() + report("settled"), ["startup", "settled"])
        self.assertEqual(result["pid"], 276)
        self.assertEqual(result["reports"]["startup"]["pct. level"], 75)
        self.assertFalse(result["full_services"])

    def test_malformed_identity_isolation_and_stats_fail(self):
        for old, new in ((power.BME_MD5.encode(), b"0" * 32), (b" -n ", b" "),
                         (b"pct. level: 75", b"pct. level: 101"),
                         (b"cur. level: 6", b"cur. level: 9"),
                         (b"max. level: 8", b"max. level: 0"),
                         (b"REPORT_END startup", b"REPORT_END final")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                power.validate_reports(report().replace(old, new), ["startup"])

    def test_restarted_missing_duplicate_and_partial_reports_fail(self):
        for data in (b"", report() * 2, report() + report("settled", 277),
                     report() + b"N00_UI_POWER_REPORT_BEGIN final\n",
                     report() + b"N00_UI_POWER_REPORT_END startup\n"):
            with self.subTest(data=data[-50:]), self.assertRaises(ValueError):
                power.validate_reports(data, ["startup"])
        with self.assertRaises(ValueError):
            power.validate_reports(report(), ["settled"])
        with self.assertRaises(ValueError):
            power.validate_reports(report(), ["startup"], expected_pid=277)

    def test_cellular_observation_is_required_and_not_fabricated(self):
        with self.assertRaises(ValueError):
            power.validate_reports(report('settled').replace(b'boolean false', b'unknown'), ['settled'])
        for state in ('true', 'false'):
            result = power.validate_reports(report('settled').replace(b'boolean false', ('boolean '+state).encode()), ['settled'])
            self.assertEqual(result['reports']['settled']['cellular_provider_owned'], state == 'true')

    def test_shell_mode_errors_precede_runtime_or_disk_access(self):
        baseline = {k: v for k, v in os.environ.items() if not k.startswith("HARMATTAN_")}
        for overrides, args, message in (
            ({"HARMATTAN_UI_POWER": "fake"}, [], "must be off or sdk-bme"),
            ({"HARMATTAN_UI_POWER": "sdk-bme", "HARMATTAN_UI_STARTUP_WAITS": "fixed"}, [], "requires ready"),
            ({"HARMATTAN_UI_POWER": "sdk-bme", "HARMATTAN_USER_PROFILE": "absent"}, [], "disposable"),
            ({"HARMATTAN_UI_POWER": "sdk-bme", "HARMATTAN_N00_SDK_POWER": "off"}, [], "conflicts"),
            ({"HARMATTAN_UI_POWER": "sdk-bme"}, ["--network-diagnostic"], "supports interactive")):
            result = subprocess.run(["sh", str(ROOT / "scripts/harmattan-qemu/run-arm64-ui.sh"), *args],
                                    env=baseline | overrides, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(message, result.stderr)
