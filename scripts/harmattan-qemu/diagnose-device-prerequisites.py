#!/usr/bin/env python3
"""Probe original service prerequisites in a disposable guest; never certify full services."""
import importlib.util
import json
from pathlib import Path
import re

SPEC = importlib.util.spec_from_file_location(
    "sdk_power_probe", Path(__file__).with_name("diagnose-sdk-power.py"))
power = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(power)

FIELDS = {
    "kernel": r"[a-zA-Z0-9._+\-]+",
    "soc": r"[^\r\n]+",
    "kci": r"unknown|[0-9]+",
    "kci_firmware": r"present|missing",
    "omap_sec": r"open|errno_[1-9][0-9]*",
    "validator_netlink": r"bound|(?:socket|bind)_errno_[1-9][0-9]*",
    "ssi_modprobe": r"[0-9]+",
    "ssi_bound": r"yes|no",
}


def validate_serial(data):
    lines = data.replace(b"\r", b"").decode("utf-8", errors="strict").splitlines()
    for marker in ("N00_PREREQ_BEGIN", "N00_PREREQ_END", "N00_PREREQ_EXIT_0"):
        if lines.count(marker) != 1:
            raise ValueError("missing or ambiguous prerequisite checkpoint")
    start, end = lines.index("N00_PREREQ_BEGIN"), lines.index("N00_PREREQ_END")
    if not start < end < lines.index("N00_PREREQ_EXIT_0"):
        raise ValueError("out-of-order prerequisite checkpoints")
    facts = {}
    for index, line in enumerate(lines):
        if not line.startswith("N00_PREREQ "):
            continue
        if not start < index < end:
            raise ValueError("prerequisite fact outside record")
        parts = line.split(" ", 2)
        if len(parts) != 3:
            raise ValueError("invalid prerequisite fact")
        _, key, value = parts
        if key not in FIELDS or key in facts or not re.fullmatch(FIELDS[key], value):
            raise ValueError("unknown, duplicate or invalid prerequisite fact")
        facts[key] = value
    if facts.keys() != FIELDS.keys():
        raise ValueError("incomplete prerequisite record")
    blockers = []
    if facts["kci"] == "unknown" or int(facts["kci"]) == 0:
        blockers.append("boot handoff has no KCI for omap_sec")
    if facts["kci_firmware"] != "present":
        blockers.append("PA/PAFMT files for the selected KCI are unavailable")
    if facts["omap_sec"] != "open":
        blockers.append("omap_sec cannot be opened: " + facts["omap_sec"])
    if facts["validator_netlink"] != "bound":
        blockers.append("DSME validator notification bind failed: " + facts["validator_netlink"])
    if facts["ssi_modprobe"] != "0" or facts["ssi_bound"] != "yes":
        blockers.append("original omap_ssi driver did not probe successfully")
    return {"facts": facts, "blockers": blockers,
            "service_readiness": "BLOCKED" if blockers else "UNVERIFIED",
            "unverified": ["KCI/PA signature and secure monitor compatibility",
                           "BB5, certificates and Aegis credential initialization",
                           "SSI transfers, ISI modem resources and SIM state",
                           "original DSME/MCE/CSD and statusbar consumer state"]}


def main():
    result, out = power.run_diagnostic(
        description=__doc__, guest_script="device-prerequisites-guest.sh",
        prefix="N00_PREREQ", probe_flag="n00.device_prerequisites=1",
        validator=validate_serial, result_key="prerequisites",
        scope="service prerequisite probes only; not a full service startup")
    # PASS means the bounded diagnostic executed correctly, even when it found
    # blockers. The separate readiness field can never claim service acceptance.
    state = result["prerequisites"]["service_readiness"]
    result["service_readiness"] = state
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"{state}: full services are not accepted; diagnostic evidence: {out}")
    raise SystemExit(2 if state == "BLOCKED" else 3)


if __name__ == "__main__":
    main()
