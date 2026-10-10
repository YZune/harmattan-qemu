# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends SceneTree

func _initialize() -> void:
	call_deferred("_run")

func _run() -> void:
	var ui = preload("res://test_frontend.gd").new()
	root.add_child(ui)
	var passed = not ui.configuration_error.is_empty() and ui.session_dir.is_empty()
	passed = passed and ui.status_label.text == "Configuration error"
	passed = passed and ui.details_label.text.contains("--session ABSOLUTE_PATH")
	passed = passed and ui.back_button.disabled and not ui.quit_button.disabled
	passed = passed and not ui.is_processing() and not ui.is_processing_input()
	passed = passed and ui.closed_with == 2
	ui.controller_id = "test-controller"
	passed = passed and not ui._send_event({"type": "key", "key": "x"})
	ui._write_heartbeat()
	ui._begin_telemetry()
	ui._poll()
	passed = passed and ui.telemetry_file == null and ui.sequence == 0
	ui._request_quit()
	passed = passed and ui.closed_with == 2
	ui.free()
	print("configuration fail-closed checks passed" if passed else "configuration checks FAILED")
	quit(0 if passed else 1)
