"""Explicit SDK BME integration; retain the original IPC, provider and UI."""
import importlib.util
import json
from pathlib import Path
import re

SPEC = importlib.util.spec_from_file_location(
    "sdk_power", Path(__file__).with_name("diagnose-sdk-power.py"))
sdk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sdk)
BME_MD5 = "3656cad5df189b759639aa21bb5e00ea"
COMMAND = b"/usr/sbin/bme_RX-71 -n -l stderr -v 5 -c /usr/lib/hwi/hw/rx71.so "


def prepare_command(command, mode):
    command = list(command)
    if mode == "off":
        return command
    if mode != "sdk-bme" or command.count("-append") != 1:
        raise ValueError("SDK BME requires one kernel command line")
    index = command.index("-append") + 1
    if index >= len(command):
        raise ValueError("Missing kernel command line")
    if any(value.startswith(("mtdparts=", "n00.ui_sdk_power=")) for value in command[index].split()):
        raise ValueError("SDK BME cannot override an existing power flag or flash partition layout")
    command[index] += " n00.ui_sdk_power=1 " + sdk.PARTITIONS
    return command


def validate_configuration(mode, *, system_ui, profile, environment, command):
    if mode not in ("off", "sdk-bme"):
        raise ValueError("UI power mode must be off or sdk-bme")
    if mode == "off":
        return
    if not system_ui or profile:
        raise ValueError("SDK BME mode requires original System UI and a disposable disk")
    if environment.get("HARMATTAN_N00_SDK_POWER") != "on":
        raise ValueError("SDK BME mode requires SDK power hardware")
    if command.count("-append") != 1 or command.index("-append") + 1 >= len(command):
        raise ValueError("SDK BME mode requires one explicit kernel command line")
    append = command[command.index("-append") + 1].split()
    if append.count("n00.ui_sdk_power=1") != 1 or append.count(sdk.PARTITIONS) != 1:
        raise ValueError("SDK BME mode requires its explicit boot flag and SDK partition layout")


def validate_reports(data, required, expected_pid=None):
    data = data.replace(b"\r", b"")
    sdk.validate_kernel_log(data)
    blocks = re.findall(rb"^N00_UI_POWER_REPORT_BEGIN (\w+)\n(.*?)"
                        rb"^N00_UI_POWER_REPORT_END \1$", data, re.M | re.S)
    if any(len(blocks) != len(re.findall(rb"^N00_UI_POWER_REPORT_" + marker + rb" ", data, re.M))
           for marker in (b"BEGIN", b"END")):
        raise ValueError("Incomplete BME report")
    phases = [phase.decode() for phase, _ in blocks]
    if (len(phases) != len(set(phases)) or not set(required) <= set(phases)
            or not set(phases) <= {"startup", "settled", "final", "shutdown"}):
        raise ValueError("Missing or duplicate BME phase")
    result = {}
    for phase, block in blocks:
        pid = re.findall(rb"^N00_UI_POWER_PROCESS ([1-9][0-9]+)$", block, re.M)
        if len(pid) != 1:
            raise ValueError("Missing or ambiguous BME process")
        pid = int(pid[0])
        if expected_pid is not None and pid != expected_pid:
            raise ValueError("BME was restarted or replaced")
        expected_pid = pid
        digests = re.findall(rb"^([0-9a-f]{32})  /proc/" + str(pid).encode() + rb"/exe$", block, re.M)
        if digests != [BME_MD5.encode()]:
            raise ValueError("Original BME executable identity mismatch")
        if re.findall(rb"^N00_UI_POWER_ARGS (.*)$", block, re.M) != [COMMAND]:
            raise ValueError("BME hardware-only isolation argument missing or changed")
        stats = re.findall(rb"^N00_UI_POWER_STATS_BEGIN\n(.*?)^N00_UI_POWER_STATS_END$", block, re.M | re.S)
        if len(stats) != 1:
            raise ValueError("Missing or ambiguous BME statistics")
        values = sdk.parse_stats(stats[0])
        if phase != b"startup":
            owner = re.findall(rb"^N00_UI_CELLULAR_OWNER_BEGIN\n(.*?)^N00_UI_CELLULAR_OWNER_END$", block, re.M | re.S)
            found = re.findall(rb"^\s+boolean (true|false)$", owner[0], re.M) if len(owner) == 1 else []
            if len(found) != 1:
                raise ValueError("Missing cellular provider ownership observation")
            values["cellular_provider_owned"] = found == [b"true"]
        result[phase.decode()] = values
    return {"enabled": True, "mode": "sdk-bme", "pid": expected_pid,
            "runtime_md5": BME_MD5, "reports": result, "full_services": False,
            "scope": "original BME -n on SDK virtual power hardware; no host battery or cellular telemetry"}


def run_phase(serial, wait_line, output, action, info):
    if action not in ("start", "settled", "final", "stop"):
        raise ValueError("Unsupported BME phase")
    argument = action if action in ("start", "stop") else "report " + action
    tag = "N00_UI_POWER_" + action.upper()
    serial.sendall((f"printf '\\n'; sh /tmp/n00-ui-helpers/ui-sdk-power-guest.sh {argument}; "
                    f"printf '\\n{tag}_EXIT_%s\\n{tag}_DONE\\n' $?\n").encode())
    wait_line((tag + "_DONE").encode())
    data = (output / "serial.log").read_bytes().replace(b"\r", b"")
    if re.findall(rb"^" + tag.encode() + rb"_EXIT_(\d+)$", data, re.M) != [b"0"]:
        raise ValueError(f"Original BME {action} failed; inspect guest serial log")
    phase = {"start": "startup", "stop": "shutdown"}.get(action, action)
    info.update(validate_reports(data, [phase], info.get("pid")))
    if action == "stop":
        if data.splitlines().count(b"N00_UI_POWER_STOPPED") != 1:
            raise ValueError("BME shutdown did not complete")
        info["stopped"] = True
    (output / "power-result.json").write_text(json.dumps(info, indent=2) + "\n")
