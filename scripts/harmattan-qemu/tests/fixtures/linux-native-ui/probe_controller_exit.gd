# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends SceneTree
const Frontend = preload("res://test_frontend.gd")
var checks := 0

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		push_error("FAILED: " + label)
		quit(1)
		assert(condition, label)

func _run() -> void:
	var cases = [{}, {"ready": true}, {"ready": null}, {"ready": 0}, {"state": "error"}, {"state": "cancelled"}, {"state": "stopping"},
		{"passed": false}, {"passed": "true"}, {"passed": 1}, {"passed": null},
		{"qemu_exit": 1}, {"qemu_exit": false}, {"qemu_exit": "0"}, {"qemu_exit": null},
		{"updated_ms": 1}, {"controller_id": "different-controller"}]
	for index in range(cases.size()):
		var ui = Frontend.new()
		root.add_child(ui)
		ui.set_process(false)
		ui.set_process_input(false)
		check(ui.exit_with_controller, "supervised option parsed")
		ui.controller_id = "controller-exit-fixture"
		ui.status_seen = true
		ui.status = {"controller_id": ui.controller_id, "state": "exited", "ready": false,
			"passed": true, "qemu_exit": 0, "updated_ms": int(Time.get_unix_time_from_system() * 1000.0)}
		ui.status.merge(cases[index], true)
		ui._refresh_state()
		check(ui.closed_with == (0 if index == 0 else -1), "terminal identity/freshness/exit case " + str(index))
		ui.free()
	for condition in ["manual", "transport", "frame", "configuration"]:
		var ui = Frontend.new()
		root.add_child(ui)
		ui.set_process(false)
		ui.set_process_input(false)
		ui.controller_id = "controller-exit-fixture"
		ui.status_seen = true
		ui.status = {"controller_id": ui.controller_id, "state": "exited", "ready": false,
			"passed": true, "qemu_exit": 0, "updated_ms": int(Time.get_unix_time_from_system() * 1000.0)}
		match condition:
			"manual": ui.exit_with_controller = false
			"transport": ui.transport_error = "failed publication"
			"frame": ui.frame_error = "invalid frame"
			"configuration": ui.configuration_error = "invalid configuration"
		ui._refresh_state()
		check(ui.closed_with == -1, condition + " must not close as a supervised success")
		ui.free()
	print(JSON.stringify({"result": "passed", "checks": checks}))
	quit(0)
