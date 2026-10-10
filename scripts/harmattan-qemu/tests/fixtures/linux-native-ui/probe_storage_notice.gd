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
	var ui = Frontend.new()
	ui.size = Vector2(468, 840)
	root.add_child(ui)
	ui.set_process(false)
	ui.set_process_input(false)
	ui.controller_id = "storage-notice-fixture"
	check(ui.storage_label.mouse_filter == Control.MOUSE_FILTER_PASS, "notice supports hover guidance without consuming input")
	check(ui.storage_label.focus_mode == Control.FOCUS_NONE, "notice cannot take keyboard focus")
	ui.status_seen = true
	var pixels = Image.create(480, 864, false, Image.FORMAT_RGB8)
	pixels.fill(Color(0.1, 0.2, 0.3))
	ui.frame_texture = ImageTexture.create_from_image(pixels)
	var now := int(Time.get_unix_time_from_system() * 1000.0)
	ui.status = {"controller_id": ui.controller_id, "state": "ready", "ready": true,
		"updated_ms": now, "frame_updated_ms": now}
	var cases := [
		{"name": "temporary", "storage": {"mode": "disposable", "previous_exit_unclean": false}, "text": "Temporary files · Discarded on exit"},
		{"name": "first persistent", "storage": {"mode": "persistent", "previous_exit_unclean": false}, "text": "Persistent files · Save in app, then Quit"},
		{"name": "clean reopen", "storage": {"mode": "persistent", "previous_exit_unclean": false}, "text": "Persistent files · Save in app, then Quit"},
		{"name": "unclean reopen", "storage": {"mode": "persistent", "previous_exit_unclean": true}, "text": "Persistent files · Previous exit unclean\nCurrent disk retained; no rollback"},
	]
	for sample in cases:
		ui.status["storage"] = sample.storage
		ui._refresh_state()
		check(ui.storage_label.text == sample.text, sample.name + " notice")
		check(ui.live and ui.status_label.text.begins_with("Live"), sample.name + " preserves readiness")
		check(ui.sequence == 0, sample.name + " notice sends no input")
		ui.size = Vector2(320, 560)
		ui._layout()
		await process_frame
		check(ui.storage_label.get_minimum_size().y <= 43, sample.name + " fits minimum window")
		check(ui.storage_label.get_rect().end.y < ui.content_rect.position.y, sample.name + " stays outside guest pixels: " + str(ui.storage_label.get_rect()) + " / " + str(ui.content_rect))
		var tooltip_font = ui.storage_label.get_theme_font("font", "TooltipLabel")
		var tooltip_size = ui.storage_label.get_theme_font_size("font_size", "TooltipLabel")
		var tooltip_fits := true
		for line in ui.storage_label.tooltip_text.split("\n"):
			tooltip_fits = tooltip_fits and tooltip_font.get_string_size(line, HORIZONTAL_ALIGNMENT_LEFT, -1, tooltip_size).x < 280
		check(tooltip_fits, sample.name + " tooltip fits minimum window width")
	check(ui.storage_label.get_theme_color("font_color") == Color(0.96, 0.77, 0.40), "unclean notice is visible in warning color")
	check(ui.storage_label.tooltip_text.contains("No checkpoint restore command"), "unclean tooltip states recovery limit")
	ui.status["storage"]["profile_path"] = "/private/host/should-not-be-shown"
	ui._refresh_state()
	check(not (ui.storage_label.text + ui.storage_label.tooltip_text).contains("/private/"), "extra private path is never rendered")
	for bad in [null, [], {}, {"mode": "unknown", "previous_exit_unclean": false},
		{"mode": null, "previous_exit_unclean": false}, {"mode": true, "previous_exit_unclean": false},
		{"mode": 7, "previous_exit_unclean": false}, {"mode": [], "previous_exit_unclean": false},
		{"mode": {}, "previous_exit_unclean": false},
		{"mode": "persistent"}, {"mode": "persistent", "previous_exit_unclean": "true"},
		{"mode": "persistent", "previous_exit_unclean": 1}, {"mode": "disposable", "previous_exit_unclean": true}]:
		ui.status["storage"] = bad
		ui._refresh_state()
		check(ui.storage_label.text == "Storage mode unavailable", "invalid metadata is not a storage claim")
		check(ui.live and ui.sequence == 0, "invalid optional metadata preserves existing input readiness")
	ui.status.erase("storage")
	ui._refresh_state()
	check(ui.storage_label.text == "Storage mode unavailable" and ui.live, "legacy controller without metadata remains usable")
	ui.status["storage"] = {"mode": "persistent", "previous_exit_unclean": true}
	ui.status["error"] = "original controller failure"
	ui._refresh_state()
	check(ui.status_label.text.contains("original controller failure"), "notice does not replace controller failure")
	ui.status["updated_ms"] = 1
	ui._refresh_state()
	check(ui.storage_label.text == "Storage mode unavailable" and not ui.live, "stale status does not claim current storage mode")
	ui.free()
	print(JSON.stringify({"result": "passed", "checks": checks}))
	quit(0)
