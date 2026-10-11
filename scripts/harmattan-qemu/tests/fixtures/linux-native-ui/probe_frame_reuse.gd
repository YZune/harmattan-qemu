# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends SceneTree

const Frontend = preload("res://test_frontend.gd")
var checks := 0
var storage_theme_changes := 0

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		push_error("FAILED: " + label)
		quit(1)
		assert(condition, label)

func accept(ui, counter: int, filename: String = "frame.a.png") -> void:
	var now := int(Time.get_unix_time_from_system() * 1000.0)
	ui._accept_status({"controller_id": ui.controller_id, "state": "ready", "ready": true,
		"frame_counter": counter, "frame_file": filename, "frame_updated_ms": now,
		"updated_ms": now, "storage": {"mode": "persistent", "previous_exit_unclean": false}})
	ui._refresh_state()

func _run() -> void:
	var ui = Frontend.new()
	root.add_child(ui)
	ui.set_process(false)
	ui.set_process_input(false)
	ui.controller_id = "frame-reuse-fixture"
	ui.client_id = "frame-reuse-client"
	ui._begin_telemetry()
	check(Engine.max_fps == 30 and OS.low_processor_usage_mode, "processing cap unchanged with conditional rendering")
	var a := Image.create(480, 864, false, Image.FORMAT_RGB8)
	a.fill(Color(0.1, 0.2, 0.3))
	check(a.save_png(ui.session_dir.path_join("frame.a.png")) == OK, "first image saved")
	var b := a.duplicate()
	b.set_pixel(211, 411, Color(0.4, 0.5, 0.6))
	check(b.save_png(ui.session_dir.path_join("frame.b.png")) == OK, "one-pixel change saved")
	accept(ui, 1)
	check(ui.live and ui.texture_frame_counter == 1, "initial valid pixels upload")
	var texture_id = ui.frame_texture.get_instance_id()
	var pending = ui.pending_frame_observation.duplicate(true)
	var label = ui.status_label.text
	accept(ui, 2)
	accept(ui, 3)
	check(ui.frame_counter == 3 and ui.texture_frame_counter == 1, "duplicate captures advance acceptance but retain texture identity")
	check(ui.frame_texture.get_instance_id() == texture_id and ui.frame_pixels == a.get_data(), "identical exact bytes reuse existing texture")
	check(ui.loaded_frame_count == 3 and ui.uploaded_frame_count == 1 and ui.reused_frame_count == 2, "decoded upload and reuse counts are separate")
	check(ui.pending_frame_observation == pending and ui.superseded_before_draw_total == 0, "duplicates preserve pending original upload observation")
	check(ui.status_label.text == label and not label.contains("frame"), "capture numbers do not invalidate visible live label")
	accept(ui, 4, "frame.b.png")
	check(ui.texture_frame_counter == 4 and ui.frame_pixels == b.get_data(), "one pixel change cannot be deduplicated")
	accept(ui, 5)
	check(ui.texture_frame_counter == 5 and ui.frame_pixels == a.get_data(), "return to earlier pixels uploads again")
	check(ui.uploaded_frame_count == 3 and ui.reused_frame_count == 2, "alternation is counted as uploads")
	accept(ui, 6, "../frame.a.png")
	check(not ui.live and ui.frame_error.contains("Invalid controller frame"), "invalid path still blocks input")
	accept(ui, 7)
	check(ui.live and ui.frame_error.is_empty() and ui.texture_frame_counter == 5, "identical valid recovery restores readiness without upload")
	var broken := FileAccess.open(ui.session_dir.path_join("frame.broken.png"), FileAccess.WRITE)
	broken.store_string("not a PNG")
	broken.close()
	accept(ui, 8, "frame.broken.png")
	check(not ui.live and ui.frame_error.contains("Cannot decode"), "bad PNG is checked even after identical captures")
	accept(ui, 9)
	check(ui.live and ui.frame_error.is_empty(), "valid duplicate recovers after decode rejection")
	var wrong := Image.create(4, 4, false, Image.FORMAT_RGB8)
	check(wrong.save_png(ui.session_dir.path_join("frame.wrong.png")) == OK, "wrong-size image saved")
	accept(ui, 10, "frame.wrong.png")
	check(not ui.live and ui.frame_error.contains("Unexpected frame size"), "dimension validation remains strict")
	accept(ui, 11)
	check(ui.live, "valid duplicate recovers after size rejection")
	ui.dragging = true
	ui.status["frame_updated_ms"] = 1
	ui._refresh_state()
	check(not ui.live and not ui.dragging and ui.status_label.text.contains("framebuffer is stale"), "unchanged pixels cannot hide stale frame or hold touch")
	accept(ui, 12)
	check(ui.live and ui.texture_frame_counter == 5, "fresh unchanged frame restores display state")
	ui.status["event_client_id"] = ui.client_id
	ui.status["event_ack"] = ui.sequence
	ui._accept_status(ui.status.duplicate(true))
	ui._refresh_state()
	check(ui.status_label.text.contains("%d/%d" % [ui.sequence, ui.sequence]), "acknowledgement feedback changes without changed pixels")
	ui.status["key_error"] = "synthetic unsupported key"
	ui._refresh_state()
	check(ui.details_label.text.contains("synthetic unsupported key"), "keyboard warning changes without changed pixels")
	ui.status["storage"]["previous_exit_unclean"] = true
	ui._refresh_state()
	check(ui.storage_label.text.contains("Previous exit unclean"), "storage warning changes without changed pixels")
	await process_frame
	ui.storage_label.theme_changed.connect(func(): storage_theme_changes += 1)
	for n in range(6):
		ui._refresh_state()
	await process_frame
	check(storage_theme_changes == 0, "equal notice values do not invalidate theme repeatedly")
	ui.size = Vector2(640, 720)
	ui._layout()
	check(ui.frame_rect.size.x > 0 and ui.frame_rect.end.y < ui.size.y, "resize still computes bounded guest geometry")
	ui.status["updated_ms"] = 1
	ui._refresh_state()
	check(not ui.live and ui.storage_label.text == "Storage mode unavailable", "stale status hides outdated storage claims")
	ui._accept_status({"controller_id": "replacement-paused", "frame_counter": -1})
	check(ui.frame_texture == null and ui.frame_pixels.is_empty() and ui.texture_frame_counter == -1, "paused controller replacement discards old texture and cache")
	accept(ui, 1)
	check(ui.live and ui.texture_frame_counter == 1 and ui.uploaded_frame_count == 1 and ui.reused_frame_count == 0, "new controller uploads same pixels independently")
	ui._request_quit()
	check(ui.quit_sequence > 0 and ui.status_label.text.contains("Quit requested"), "Quit remains visible without a new image")
	ui.telemetry_file.flush()
	var records := FileAccess.get_file_as_string(ui.session_dir.path_join("telemetry.frame-reuse-client.jsonl")).split("\n", false)
	var reused_records := 0
	for line in records:
		var record = JSON.parse_string(line)
		if record.kind == "frame_reused":
			reused_records += 1
			check(record.texture_update_usec == 0 and record.compare_usec >= 0, "reuse comparison is not texture upload time")
			check(not record.has("post_draw_usec"), "reuse never claims native drawing")
	check(reused_records >= 5, "duplicate captures have separate measurement records")
	ui.free()
	print(JSON.stringify({"result": "passed", "checks": checks}))
	quit(0)
