# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends SceneTree

const Frontend = preload("res://test_frontend.gd")
var checks := 0
var failures := 0

func _initialize() -> void:
	call_deferred("_run")

func check(condition: bool, label: String) -> void:
	checks += 1
	if not condition:
		failures += 1
		push_error("FAILED: " + label)
		quit(1)
		assert(condition, label)

func frontend(name: String):
	var ui = Frontend.new()
	ui.size = Vector2(468, 840)
	root.add_child(ui)
	check(ui.configuration_error.is_empty(), "valid CLI configuration")
	check(ui.closed_with == -1, "valid configuration remains open")
	ui.set_process(false)
	ui.set_process_input(false)
	ui.controller_id = "isolated-test-controller"
	ui.client_id = name
	ui.status = {"state": "ready"}
	ui.live = true
	ui._begin_telemetry()
	return ui

func event(ui, seq: int) -> Dictionary:
	var path = ui.session_dir.path_join("events").path_join("%s.%020d.json" % [ui.client_id, seq])
	return JSON.parse_string(FileAccess.get_file_as_string(path))

func held_moves(ui) -> int:
	check(ui._pointer("down", Vector2i(0, 200)), "immediate edge down")
	ui.dragging = true
	ui.last_move_published_usec = Time.get_ticks_usec() + 1000000
	for n in range(20):
		check(ui._pointer("move", Vector2i(100 + n, 200)), "pending move accepted")
	ui.last_point = Vector2i(119, 200)
	check(ui.sequence == 1, "coalesced motions reserve no sequence")
	check(ui.coalesced_mouse_moves == 19, "overwritten unpublished count")
	check(ui.pending_move.x == 119, "latest coordinate retained")
	return int(ui.pending_move.created_ms)

func _run() -> void:
	var ui = frontend("rerun-test-up")
	check(Engine.max_fps == 30, "engine FPS capped at 30")
	var created = held_moves(ui)
	OS.delay_msec(5)
	check(ui._pointer("up", Vector2i(125, 201)), "terminal up succeeds")
	check(ui.sequence == 3 and ui.pending_move.is_empty(), "down move up sequence")
	check(event(ui, 1).x == 0 and event(ui, 1).action == "down", "edge origin preserved")
	check(event(ui, 2).action == "move" and event(ui, 2).x == 119, "final retained move before up")
	check(event(ui, 2).created_ms == created, "original input timestamp preserved")
	check(event(ui, 3).action == "up" and event(ui, 3).x == 125, "up coordinate preserved")
	if ui.metrics_enabled:
		ui.telemetry_file.flush()
		var records = FileAccess.get_file_as_string(ui.session_dir.path_join("telemetry.rerun-test-up.jsonl")).split("\n", false)
		var move_record: Dictionary = {}
		for line in records:
			var record = JSON.parse_string(line)
			if record.kind == "event_enqueued" and record.pointer_action == "move":
				move_record = record
		check(move_record.input_pending_usec >= 4000, "pending input delay measured")
		check(not move_record.has("key"), "telemetry omits typed text")
	else:
		check(ui.telemetry_file == null, "metrics off by default")
		check(ui.event_enqueue_times.is_empty(), "no event metric bookkeeping by default")
		check(ui.pending_frame_observation.is_empty(), "no frame metric bookkeeping by default")
		check(not FileAccess.file_exists(ui.session_dir.path_join("telemetry.rerun-test-up.jsonl")), "no default telemetry file")
	ui.free()

	for action in ["release", "focus", "mouse_exit", "back", "quit", "key"]:
		ui = frontend("rerun-test-" + action)
		held_moves(ui)
		match action:
			"release": ui._release_all()
			"focus": ui.get_window().focus_exited.emit()
			"mouse_exit": ui.get_window().mouse_exited.emit()
			"back": ui._go_back()
			"quit": ui._request_quit()
			"key": ui._send_event({"type": "key", "key": "x"})
		check(event(ui, 2).action == "move", "pending move before " + action)
		check(ui.pending_move.is_empty(), "pending slot cleared for " + action)
		if action == "key":
			check(event(ui, 3).type == "key", "key follows final move")
		else:
			var control_kind = "cancel" if action in ["focus", "mouse_exit"] else "release"
			check(event(ui, 3).action == "up" and event(ui, 4).type == control_kind, "touch release and control ordering for " + action)
		if action == "back":
			check(event(ui, 5).key == "Escape", "back key follows release")
		if action == "quit":
			check(event(ui, 5).type == "quit" and ui.quit_sequence == 5, "quit follows release")
		ui.free()

	ui = frontend("rerun-test-failure")
	created = held_moves(ui)
	var collision = ui.session_dir.path_join("events").path_join("%s.%020d.json.tmp" % [ui.client_id, 2])
	var collision_file = FileAccess.open(collision, FileAccess.WRITE)
	collision_file.store_string("isolated test collision")
	collision_file.close()
	check(not ui._send_event({"type": "key", "key": "x"}), "publication failure blocks later event")
	check(ui.sequence == 1 and not ui.pending_move.is_empty(), "failed move retains slot and sequence")
	check(not ui.live and not ui.dragging, "transport failure immediately disables input")
	check(ui.quit_button.text == "Close" and not ui.quit_button.disabled, "failed transport can close local window")
	ui._write_heartbeat()
	check(not FileAccess.file_exists(ui.session_dir.path_join("heartbeat.%s.json" % ui.client_id)), "failed transport stops heartbeat")
	check(not ui._pointer("down", Vector2i(3, 4)), "failed transport rejects fresh input")
	check(ui.sequence == 1, "rejected input preserves sequence")
	check(ui.pending_move.created_ms == created, "failed publication preserves input timestamp")
	DirAccess.remove_absolute(collision)
	ui.transport_error = ""
	check(ui._send_event({"type": "key", "key": "x"}), "same sequence succeeds after fixture removal")
	check(ui.sequence == 3 and event(ui, 2).action == "move" and event(ui, 3).type == "key", "retry maintains order and contiguous sequence")
	ui.free()

	ui = frontend("rerun-test-controller-change")
	held_moves(ui)
	ui._accept_status({"controller_id": "replacement-controller", "frame_counter": -1})
	check(ui.pending_move.is_empty() and not ui.dragging and ui.sequence == 0, "controller change drops unpublished old input")
	var heartbeat = JSON.parse_string(FileAccess.get_file_as_string(ui.session_dir.path_join("heartbeat.%s.json" % ui.client_id)))
	check(heartbeat.controller_id == "replacement-controller" and heartbeat.client_id == ui.client_id, "new controller lease precedes input")
	check(heartbeat.updated_ms > 0 and absf(float(heartbeat.updated_ms) - Time.get_unix_time_from_system() * 1000.0) < 1000, "new controller heartbeat is current")
	ui.free()

	ui = frontend("test-heartbeat-failure")
	var blocked_heartbeat = ui.session_dir.path_join("heartbeat.%s.json" % ui.client_id)
	check(DirAccess.make_dir_absolute(blocked_heartbeat) == OK, "heartbeat publication failure fixture created")
	ui._write_heartbeat()
	check(not ui.transport_error.is_empty() and not ui.live and not ui.dragging, "heartbeat publication failure disables input")
	check(not ui._send_event({"type": "key", "key": "x"}), "heartbeat failure blocks later input")
	DirAccess.remove_absolute(blocked_heartbeat)
	ui._write_heartbeat()
	check(not FileAccess.file_exists(blocked_heartbeat), "failed transport never resumes heartbeat implicitly")
	ui.free()

	ui = frontend("rerun-test-rate")
	check(ui._pointer("down", Vector2i(0, 200)), "rate test down")
	var start = Time.get_ticks_usec()
	for n in range(70):
		ui._pointer("move", Vector2i(n + 1, 200))
		OS.delay_msec(1)
	var elapsed = Time.get_ticks_usec() - start
	var periodic_count = ui.published_mouse_moves
	check(periodic_count <= 1 + int(elapsed / Frontend.MOVE_INTERVAL_USEC), "nonterminal publications obey 30 Hz limit")
	ui._pointer("up", Vector2i(71, 200))
	check(event(ui, ui.sequence - 1).x == 70, "rate test final pending coordinate flushed")
	var rate_metrics = {"terminal_moves_published": ui.published_mouse_moves, "coalesced_moves": ui.coalesced_mouse_moves}
	ui.free()
	test_frames_and_native_input()
	test_rapid_typing()
	test_keyboard_input_timing()
	for terminal in ["error", "failed", "cancelled", "stale"]:
		ui = frontend("test-close-" + terminal)
		ui.quit_sequence = 1
		ui.sequence = 1
		ui.status_seen = true
		ui.status = {"state": terminal, "ready": false, "updated_ms": 1 if terminal == "stale" else int(Time.get_unix_time_from_system() * 1000.0), "error": "synthetic failure"}
		ui._refresh_state()
		check(ui.closed_with == -1, "terminal failure does not automatically claim cleanup")
		check(not ui.quit_button.disabled and ui.quit_button.text == "Close", "terminal failure permits local close")
		check(ui.details_label.text.contains("cleanup is not confirmed"), "local-close warning distinguishes guest cleanup")
		ui._request_quit()
		check(ui.closed_with == 2, "local close reports failure exit")
		ui.free()
	ui = frontend("test-clean-close")
	ui.quit_sequence = 1
	ui.sequence = 1
	ui.acknowledged = 1
	ui.status_seen = true
	ui.status = {"state": "stopped", "ready": false, "updated_ms": int(Time.get_unix_time_from_system() * 1000.0)}
	ui._refresh_state()
	check(ui.closed_with == 0, "acknowledged terminal cleanup closes successfully")
	ui.free()
	print(JSON.stringify({"result": "passed" if failures == 0 else "failed", "checks": checks, "failures": failures, "rate_elapsed_usec": elapsed, "motions_seen": 70, "periodic_moves_published": periodic_count, "terminal_moves_published": rate_metrics.terminal_moves_published, "coalesced_moves": rate_metrics.coalesced_moves}))
	quit(0 if failures == 0 else 1)


func test_frames_and_native_input() -> void:
	var ui = frontend("test-frame-input")
	var frame = Image.create(480, 864, false, Image.FORMAT_RGB8)
	frame.fill(Color(0.25, 0.5, 0.75))
	check(frame.save_png(ui.session_dir.path_join("frame.synthetic.png")) == OK, "synthetic fixture frame written")
	var now_ms = int(Time.get_unix_time_from_system() * 1000.0)
	ui._accept_status({"controller_id": ui.controller_id, "frame_counter": 1, "frame_file": "frame.synthetic.png", "frame_updated_ms": now_ms, "updated_ms": now_ms, "ready": true, "state": "ready"})
	ui._refresh_state()
	check(ui.live and ui.connected and ui.frame_counter == 1 and ui.frame_texture != null, "fresh controller frame permits native input")
	if ui.metrics_enabled:
		check(ui.loaded_frame_count == 1 and not ui.pending_frame_observation.is_empty(), "opt-in frame metrics recorded")
		ui._on_frame_post_draw()
		check(ui.observed_frame_count == 0, "dummy headless renderer never claims a presentation sample")
	else:
		check(ui.loaded_frame_count == 0 and ui.pending_frame_observation.is_empty(), "default frame loads produce no performance observations")
	var down = InputEventMouseButton.new()
	down.button_index = MOUSE_BUTTON_LEFT
	down.pressed = true
	down.position = Vector2(ui.frame_rect.position.x - 5, ui.frame_rect.get_center().y)
	ui._input(down)
	check(ui.dragging and event(ui, 1).action == "down" and event(ui, 1).x == 0, "native side-margin press maps to guest edge")
	ui.last_move_published_usec = Time.get_ticks_usec() + 1000000
	var move = InputEventMouseMotion.new()
	move.position = ui.frame_rect.get_center()
	ui._input(move)
	check(ui.sequence == 1 and not ui.pending_move.is_empty(), "native motion occupies unpublished slot")
	var key = InputEventKey.new()
	key.pressed = true
	key.keycode = KEY_X
	key.unicode = 120
	key.ctrl_pressed = true
	ui._input(key)
	check(ui.sequence == 1 and ui.dragging, "host shortcut does not enter guest queue")
	key.ctrl_pressed = false
	ui._input(key)
	check(event(ui, 2).action == "move" and event(ui, 3).action == "up" and event(ui, 4).type == "release" and event(ui, 5).key == "x", "native key flushes motion and held touch before typing")
	ui.status["frame_file"] = "../frame.synthetic.png"
	ui._load_frame(2)
	ui._refresh_state()
	check(not ui.live and ui.frame_error.contains("Invalid controller frame"), "escaping frame path disables input")
	check(event(ui, ui.sequence).type == "cancel", "frame failure cancels queued work")
	ui.status["frame_file"] = "frame.synthetic.png"
	ui._load_frame(2)
	check(ui.frame_error.is_empty() and ui.frame_counter == 2, "valid next frame clears decode error")
	ui._refresh_state()
	check(ui.live, "fresh valid frame restores input")
	ui.status["frame_updated_ms"] = now_ms - 6000
	ui._refresh_state()
	check(not ui.live and ui.connected, "stale framebuffer cannot accept input despite fresh controller")
	check(event(ui, ui.sequence).type == "cancel", "stale framebuffer cancels queued work")
	check(ui._fresh(now_ms - 5000, now_ms) and not ui._fresh(now_ms - 5001, now_ms), "heartbeat age limit is bounded")
	check(ui._fresh(now_ms + 2000, now_ms) and not ui._fresh(now_ms + 2001, now_ms), "future heartbeat skew is bounded")
	check(not ui._fresh("recent", now_ms), "nonnumeric heartbeat is rejected")
	ui.free()


func test_rapid_typing() -> void:
	var ui = frontend("test-rapid-typing")
	var text = "qwerty"
	# Submit faster than the guest's asynchronous keyboard steps can acknowledge.
	for letter in text:
		var key = InputEventKey.new()
		key.pressed = true
		key.unicode = letter.unicode_at(0)
		ui._input(key)
	check(ui.sequence == text.length() * 2, "rapid typing publishes every release and key")
	check(ui.acknowledged == 0, "rapid typing test keeps all keys queued")
	var queued_text = ""
	for index in range(text.length()):
		var release = event(ui, index * 2 + 1)
		var key = event(ui, index * 2 + 2)
		check(release.type == "release", "before-key control is an ordered release, never cancel")
		check(key.type == "key" and key.seq == index * 2 + 2, "rapid key has a contiguous sequence")
		queued_text += key.key
	check(queued_text == text, "rapid typing retains all characters in original order")
	ui.get_window().focus_exited.emit()
	check(event(ui, ui.sequence).type == "cancel" and ui.sequence == text.length() * 2 + 1, "focus loss explicitly cancels the queued typing")
	for index in range(text.length()):
		check(event(ui, index * 2 + 2).key == text[index], "cancellation does not rewrite published key files")
	ui.free()


func test_keyboard_input_timing() -> void:
	var ui = frontend("test-keyboard-timing")
	ui.release_delay_msec = 5
	var started := Time.get_ticks_usec()
	for code in [KEY_X, KEY_ESCAPE]:
		var key = InputEventKey.new()
		key.pressed = true
		key.keycode = code
		key.unicode = 120 if code == KEY_X else 0
		ui._input(key)
	var finished := Time.get_ticks_usec()
	check(ui.sequence == 4 and event(ui, 2).key == "x" and event(ui, 4).key == "Escape", "keyboard timing preserves release and key ordering")
	check(not event(ui, 2).has("input_seen_usec") and not event(ui, 4).has("input_kind"), "keyboard diagnostics do not change event payloads")
	if ui.metrics_enabled:
		ui.telemetry_file.flush()
		var records = FileAccess.get_file_as_string(ui.session_dir.path_join("telemetry.test-keyboard-timing.jsonl")).split("\n", false)
		var key_records := 0
		for line in records:
			var record = JSON.parse_string(line)
			if record.kind == "event_enqueued" and record.event_type == "key":
				check(record.input_seen_usec >= started and record.input_seen_usec <= finished, "keyboard timestamp comes from the input callback")
				check(record.input_pending_usec >= 4000, "keyboard timestamp includes work before publication")
				check(record.input_to_enqueue_usec >= record.input_pending_usec, "keyboard enqueue interval contains pending time")
				check(record.input_kind == ("keyboard" if record.event_sequence == 2 else "escape_gesture"), "Escape gesture timing is classified separately")
				key_records += 1
		check(key_records == 2, "ordinary key and Escape both report input timing")
	else:
		check(ui.event_enqueue_times.is_empty(), "keyboard events add no metrics bookkeeping by default")
	ui.free()
