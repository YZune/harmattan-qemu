# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends Control
## Local-only view of real QMP pixels. The controller owns the guest and session.

const RAW_SIZE := Vector2i(480, 864)
const POLL_SECONDS := 1.0 / 30.0
const MOVE_INTERVAL_USEC := 33333
const FRONTEND_MAX_FPS := 30
const STALE_MS := 5000
const TOP := 54.0
const BOTTOM := 78.0
const MARGIN := 18.0

var session_dir := ""
var configuration_error := ""
var metrics_enabled := false
var exit_with_controller := false

var client_id := "%d-%d-%08x" % [int(Time.get_unix_time_from_system() * 1000.0), OS.get_process_id(), randi()]
var controller_id := ""
var sequence := 0
var acknowledged := 0
var quit_sequence := 0
var frame_counter := -1
var frame_texture: ImageTexture
var status: Dictionary = {}
var status_seen := false
var connected := false
var live := false
var poll_elapsed := 0.0
var heartbeat_elapsed := 0.0
var dragging := false
var last_point := Vector2i.ZERO
var pending_move: Dictionary = {}
var pending_move_input_usec := 0
var last_move_published_usec := 0
var frame_rect := Rect2()
var content_rect := Rect2()
var transport_error := ""
var frame_error := ""
var status_label: Label
var details_label: Label
var title_label: Label
var back_button: Button
var quit_button: Button
# Measurement only: a post-draw observation is not physical display/scanout timing.
var telemetry_file: FileAccess
var telemetry_elapsed := 0.0
var pending_frame_observation: Dictionary = {}
var drawn_frame_counter := -1
var observed_frame_counter := -1
var loaded_frame_count := 0
var observed_frame_count := 0
var skipped_before_load_total := 0
var superseded_before_draw_total := 0
var event_enqueue_times: Dictionary = {}
var raw_mouse_moves := 0
var published_mouse_moves := 0
var coalesced_mouse_moves := 0
var cpu_clock_ticks := 0
var resource_previous_ticks := -1
var resource_previous_usec := 0


func _ready() -> void:
	# Bound the native software renderer independently of guest capture cadence.
	Engine.max_fps = FRONTEND_MAX_FPS
	get_tree().auto_accept_quit = false
	get_window().min_size = Vector2i(320, 560)
	get_window().close_requested.connect(_request_quit)
	get_window().focus_exited.connect(_cancel_input)
	get_window().mouse_exited.connect(_cancel_input)
	get_window().go_back_requested.connect(_go_back)
	texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_build_chrome()
	resized.connect(_layout)
	_layout()
	if not _configure(OS.get_cmdline_user_args()):
		_show_configuration_error()
		return
	if metrics_enabled:
		RenderingServer.frame_post_draw.connect(_on_frame_post_draw)
		cpu_clock_ticks = _read_cpu_clock_ticks()
	_poll()


func _configure(arguments: PackedStringArray) -> bool:
	session_dir = ""
	metrics_enabled = false
	exit_with_controller = false
	configuration_error = ""
	var selected_session := ""
	var session_seen := false
	var index := 0
	while index < arguments.size():
		match arguments[index]:
			"--session":
				if session_seen or index + 1 >= arguments.size():
					configuration_error = "Pass --session once with an existing absolute session path."
					return false
				index += 1
				session_seen = true
				selected_session = arguments[index]
			"--exit-with-controller":
				if exit_with_controller:
					configuration_error = "Pass --exit-with-controller at most once."
					return false
				exit_with_controller = true
			"--metrics":
				if metrics_enabled:
					configuration_error = "Pass --metrics at most once."
					return false
				metrics_enabled = true
			_:
				configuration_error = "Unknown frontend argument: " + arguments[index]
				return false
		index += 1
	if not selected_session.begins_with("/") or selected_session.contains("://"):
		configuration_error = "Required: --session ABSOLUTE_PATH after Godot's -- separator."
		return false
	selected_session = selected_session.trim_suffix("/")
	if selected_session.is_empty() or selected_session != selected_session.simplify_path():
		configuration_error = "Use a normalized absolute session path without '.' or '..'."
		return false
	for path in [selected_session, selected_session.path_join("events")]:
		var parent := DirAccess.open(path.get_base_dir())
		if parent == null or parent.is_link(path.get_file()) or not DirAccess.dir_exists_absolute(path):
			configuration_error = "Session and events must already be real directories created by the controller."
			return false
		# Godot exposes Unix modes, but no owner UID API. The controller also
		# verifies ownership; opening mode-0700 directories checks accessibility.
		var private_mode := FileAccess.UNIX_READ_OWNER | FileAccess.UNIX_WRITE_OWNER | FileAccess.UNIX_EXECUTE_OWNER
		if FileAccess.get_unix_permissions(path) != private_mode or DirAccess.open(path) == null:
			configuration_error = "Session and events must be accessible, owned mode-0700 directories; restart the controller."
			return false
	session_dir = selected_session
	return true


func _show_configuration_error() -> void:
	set_process(false)
	set_process_input(false)
	back_button.disabled = true
	status_label.text = "Configuration error"
	status_label.add_theme_color_override("font_color", Color(1.0, 0.55, 0.45))
	details_label.text = configuration_error
	details_label.tooltip_text = configuration_error
	get_window().title = "Harmattan · Configuration error"
	push_error(configuration_error)
	queue_redraw()
	if DisplayServer.get_name() == "headless":
		_close_window(2)


func _build_chrome() -> void:
	back_button = Button.new()
	back_button.text = "Back"
	back_button.tooltip_text = "Right-edge return gesture (Escape)"
	back_button.focus_mode = Control.FOCUS_NONE
	back_button.pressed.connect(_go_back)
	add_child(back_button)
	quit_button = Button.new()
	quit_button.text = "Quit"
	quit_button.tooltip_text = "Request guest/controller cleanup and wait for completion"
	quit_button.focus_mode = Control.FOCUS_NONE
	quit_button.pressed.connect(_request_quit)
	add_child(quit_button)
	title_label = _make_label(15)
	title_label.text = "Harmattan · QMP display"
	title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	status_label = _make_label(14)
	details_label = _make_label(12)
	details_label.add_theme_color_override("font_color", Color(0.65, 0.71, 0.78))
	details_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART


func _make_label(font_size: int) -> Label:
	var label := Label.new()
	label.mouse_filter = Control.MOUSE_FILTER_IGNORE
	label.add_theme_font_size_override("font_size", font_size)
	add_child(label)
	return label


func _layout() -> void:
	if back_button == null:
		return
	back_button.position = Vector2(12, 10)
	back_button.size = Vector2(64, 32)
	quit_button.position = Vector2(size.x - 76, 10)
	quit_button.size = Vector2(64, 32)
	title_label.position = Vector2(82, 11)
	title_label.size = Vector2(maxf(0.0, size.x - 164.0), 30)
	content_rect = Rect2(Vector2(0, TOP), Vector2(size.x, maxf(1.0, size.y - TOP - BOTTOM)))
	var available := Vector2(maxf(1.0, size.x - MARGIN * 2), maxf(1.0, content_rect.size.y - 12))
	var scale_factor := minf(available.x / RAW_SIZE.x, available.y / RAW_SIZE.y)
	var display_size := Vector2(RAW_SIZE) * scale_factor
	frame_rect = Rect2(content_rect.position + (content_rect.size - display_size) / 2, display_size)
	status_label.position = Vector2(12, size.y - BOTTOM + 6)
	status_label.size = Vector2(size.x - 24, 22)
	details_label.position = Vector2(12, size.y - BOTTOM + 31)
	details_label.size = Vector2(size.x - 24, 43)
	queue_redraw()


func _process(delta: float) -> void:
	poll_elapsed += delta
	heartbeat_elapsed += delta
	telemetry_elapsed += delta
	if poll_elapsed >= POLL_SECONDS:
		# Preserve fractional time without replaying obsolete polls after a stall.
		poll_elapsed = fmod(poll_elapsed, POLL_SECONDS)
		_poll()
	if heartbeat_elapsed >= 0.5:
		heartbeat_elapsed = 0.0
		_write_heartbeat()
	# A release outside the native window must not leave a held guest touch.
	if dragging and not Input.is_mouse_button_pressed(MOUSE_BUTTON_LEFT):
		_cancel_input()
	if transport_error.is_empty() and not pending_move.is_empty() and Time.get_ticks_usec() - last_move_published_usec >= MOVE_INTERVAL_USEC:
		_flush_pending_move()
	if metrics_enabled and telemetry_elapsed >= 1.0:
		telemetry_elapsed = 0.0
		_sample_process_resources()
		if telemetry_file != null:
			telemetry_file.flush()


func _poll() -> void:
	if session_dir.is_empty() or not configuration_error.is_empty():
		return
	var path := session_dir.path_join("status.json")
	if FileAccess.file_exists(path):
		var file := FileAccess.open(path, FileAccess.READ)
		if file != null and file.get_length() <= 65536:
			var parsed: Variant = JSON.parse_string(file.get_as_text())
			file.close()
			if parsed is Dictionary and parsed.get("controller_id", "") is String:
				_accept_status(parsed)
	_refresh_state()


func _accept_status(incoming: Dictionary) -> void:
	var new_controller := str(incoming.get("controller_id", ""))
	if new_controller.is_empty():
		return
	var controller_changed := new_controller != controller_id
	if controller_changed:
		# Events already queued belong to the old controller; never replay them.
		if not controller_id.is_empty():
			client_id = "%d-%d-%08x" % [int(Time.get_unix_time_from_system() * 1000.0), OS.get_process_id(), randi()]
			sequence = 0
			quit_sequence = 0
		dragging = false
		# An unpublished move is owned by the old controller, just like its queue.
		pending_move = {}
		pending_move_input_usec = 0
		last_move_published_usec = 0
		controller_id = new_controller
		acknowledged = 0
		frame_counter = -1
		frame_texture = null
		frame_error = ""
		_begin_telemetry()
	status = incoming
	status_seen = true
	if str(status.get("event_client_id", "")) == client_id:
		var previous_ack := acknowledged
		acknowledged = maxi(acknowledged, int(status.get("event_ack", 0)))
		if acknowledged > previous_ack:
			_observe_event_ack(previous_ack)
	var candidate := int(status.get("frame_counter", -1))
	if candidate >= 0 and candidate != frame_counter:
		_load_frame(candidate)
	if controller_changed:
		# Publish the lease before this controller can become live for input.
		_write_heartbeat()


func _load_frame(candidate: int) -> void:
	var load_start_usec := Time.get_ticks_usec()
	var load_start_unix_ms := int(Time.get_unix_time_from_system() * 1000.0)
	var filename := str(status.get("frame_file", "frame.png"))
	# Frame paths are controller-owned basenames in this one session, never URLs.
	if filename.get_file() != filename or not filename.begins_with("frame") or not filename.ends_with(".png"):
		frame_error = "Invalid controller frame filename"
		return
	var path := session_dir.path_join(filename)
	if not FileAccess.file_exists(path):
		return
	var image := Image.new()
	var result := image.load(path)
	if result != OK:
		frame_error = "Cannot decode controller frame (%d)" % result
		return
	if image.get_size() != RAW_SIZE:
		frame_error = "Unexpected frame size: %d×%d" % [image.get_width(), image.get_height()]
		return
	var decode_end_usec := Time.get_ticks_usec()
	image.convert(Image.FORMAT_RGB8)
	var convert_end_usec := Time.get_ticks_usec()
	if frame_texture == null:
		frame_texture = ImageTexture.create_from_image(image)
	else:
		frame_texture.update(image)
	var load_end_usec := Time.get_ticks_usec()
	if metrics_enabled:
		_record_frame_load(candidate, load_start_usec, load_start_unix_ms, decode_end_usec, convert_end_usec, load_end_usec)
	frame_counter = candidate
	frame_error = ""
	queue_redraw()


func _record_frame_load(candidate: int, load_start_usec: int, load_start_unix_ms: int, decode_end_usec: int, convert_end_usec: int, load_end_usec: int) -> void:
	var skipped := maxi(0, candidate - frame_counter - 1) if frame_counter >= 0 else 0
	skipped_before_load_total += skipped
	if not pending_frame_observation.is_empty():
		superseded_before_draw_total += 1
	loaded_frame_count += 1
	pending_frame_observation = {
		"frame_counter": candidate,
		"previous_loaded_frame_counter": frame_counter,
		"loaded_frame_count": loaded_frame_count,
		"skipped_before_load": skipped,
		"skipped_before_load_total": skipped_before_load_total,
		"superseded_before_draw_total": superseded_before_draw_total,
		"frame_updated_ms": int(status.get("frame_updated_ms", 0)),
		"load_start_usec": load_start_usec,
		"load_end_usec": load_end_usec,
		"load_start_unix_ms": load_start_unix_ms,
		"load_end_unix_ms": int(Time.get_unix_time_from_system() * 1000.0),
		"load_duration_usec": load_end_usec - load_start_usec,
		"decode_usec": decode_end_usec - load_start_usec,
		"convert_usec": convert_end_usec - decode_end_usec,
		"texture_update_usec": load_end_usec - convert_end_usec,
		"event_ack_at_load": acknowledged,
	}


func _fresh(timestamp: Variant, now_ms: int) -> bool:
	if not (timestamp is int or timestamp is float):
		return false
	var age := now_ms - int(timestamp)
	return age >= -2000 and age <= STALE_MS


func _refresh_state() -> void:
	var now_ms := int(Time.get_unix_time_from_system() * 1000.0)
	var was_live := live
	connected = status_seen and _fresh(status.get("updated_ms", 0), now_ms)
	var frame_fresh := _fresh(status.get("frame_updated_ms", 0), now_ms)
	var controller_ready: bool = status.get("ready") is bool and status.get("ready")
	live = connected and controller_ready and frame_fresh and frame_texture != null and frame_error.is_empty() and transport_error.is_empty() and quit_sequence == 0
	if was_live and not live:
		_cancel_input()
	var state := str(status.get("state", "waiting"))
	var state_error := str(status.get("error", ""))
	var close_locally := _can_close_locally()
	var line := "Waiting for controller"
	var color := Color(0.96, 0.77, 0.40)
	if close_locally and not controller_id.is_empty():
		line = "Controller unavailable · cleanup not confirmed"
	elif quit_sequence > 0:
		line = "Quit requested · waiting for clean shutdown"
	elif not status_seen:
		line = "Disconnected · waiting for controller"
	elif not connected:
		line = "Disconnected · controller heartbeat is stale"
	elif not frame_error.is_empty():
		line = "Frame error · " + frame_error
	elif not state_error.is_empty():
		line = "Controller · " + state_error
	elif live:
		line = "Live · frame %d · input ack %d/%d" % [frame_counter, acknowledged, sequence]
		color = Color(0.50, 0.88, 0.68)
	elif controller_ready and not frame_fresh:
		line = "Disconnected · framebuffer is stale"
	else:
		line = "Controller · " + state
	if not transport_error.is_empty():
		line = "Input error · " + transport_error
	if status_label.text != line:
		status_label.text = line
		status_label.tooltip_text = line
	if status_label.get_theme_color("font_color") != color:
		status_label.add_theme_color_override("font_color", color)
	var details := "Letters, Space, Enter and Backspace use the guest keyboard; use on-screen symbols."
	var details_tooltip := ""
	var key_error := str(status.get("key_error", ""))
	if not key_error.is_empty():
		details = "Keyboard: " + key_error
		details_tooltip = key_error
	elif live:
		details = "Guest keyboard: %s · Drag from the side margin for edge gestures. Escape returns Home." % str(status.get("keyboard_layout", "unknown"))
		details_tooltip = "Letters, Space, Enter and Backspace use the guest keyboard; use on-screen symbols. The controller must recognize the real keyboard. Unsupported keys are rejected visibly."
	if close_locally and not controller_id.is_empty():
		details = "Close window to exit this frontend. Guest/controller cleanup is not confirmed; check the launcher. " + str(status.get("error", ""))
		details_tooltip = details
	elif quit_sequence > 0:
		details = "Input ack %d/%d · %s. This window closes after the controller confirms cleanup." % [acknowledged, sequence, state]
	if details_label.text != details:
		details_label.text = details
	if details_label.tooltip_text != details_tooltip:
		details_label.tooltip_text = details_tooltip
	if back_button.disabled == live:
		back_button.disabled = not live
	var quit_text := "Close" if close_locally else "Quit"
	var quit_tooltip := "Close only this window; guest cleanup is not confirmed" if close_locally else "Request guest/controller cleanup and wait for completion"
	if quit_button.text != quit_text:
		quit_button.text = quit_text
	if quit_button.tooltip_text != quit_tooltip:
		quit_button.tooltip_text = quit_tooltip
	var quit_disabled := quit_sequence > 0 and not close_locally
	if quit_button.disabled != quit_disabled:
		quit_button.disabled = quit_disabled
	var window_title := "Harmattan · " + ("Live framebuffer" if live else line)
	if get_window().title != window_title:
		get_window().title = window_title
	if was_live != live:
		queue_redraw()
	if exit_with_controller and _controller_finished_cleanly():
		# A bounded session may finish without a window-originated Quit event.
		# The supervisor separately requires the controller's clean result/exit.
		_close_window(0)
	elif quit_sequence > 0 and acknowledged >= quit_sequence and state in ["stopped", "closed", "exited", "complete"]:
		_close_window(0)


func _controller_finished_cleanly() -> bool:
	var ready: Variant = status.get("ready")
	var passed: Variant = status.get("passed")
	var qemu_exit: Variant = status.get("qemu_exit")
	return connected and not controller_id.is_empty() and status.get("controller_id") == controller_id \
		and status.get("state") == "exited" and ready is bool and not ready and passed is bool and passed \
		and (qemu_exit is int or qemu_exit is float) and qemu_exit == 0 \
		and configuration_error.is_empty() and transport_error.is_empty() and frame_error.is_empty()



func _draw() -> void:
	draw_rect(Rect2(Vector2.ZERO, size), Color(0.043, 0.055, 0.075))
	draw_rect(frame_rect.grow(2), Color(0.24, 0.28, 0.34), false, 1.0)
	draw_rect(frame_rect, Color.BLACK)
	if frame_texture != null:
		draw_texture_rect(frame_texture, frame_rect, false, Color.WHITE if live else Color(0.55, 0.55, 0.55))
		drawn_frame_counter = frame_counter
	if not live:
		var text := "Waiting for real framebuffer" if frame_texture == null else "Display paused · last captured frame"
		if not configuration_error.is_empty():
			text = "Start through the Linux native launcher"
		var font := ThemeDB.fallback_font
		var measured := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14)
		var pos := frame_rect.position + Vector2((frame_rect.size.x - measured.x) / 2, 30)
		draw_rect(Rect2(frame_rect.position, Vector2(frame_rect.size.x, 44)), Color(0, 0, 0, 0.8))
		draw_string(font, pos, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 14, Color(0.85, 0.88, 0.92))


func _raw_point(point: Vector2) -> Vector2i:
	var fraction := (point - frame_rect.position) / frame_rect.size
	return Vector2i(clampi(int(floor(fraction.x * RAW_SIZE.x)), 0, RAW_SIZE.x - 1), clampi(int(floor(fraction.y * RAW_SIZE.y)), 0, RAW_SIZE.y - 1))


func _input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT:
		if event.pressed and live and content_rect.has_point(event.position) and frame_rect.grow(MARGIN).has_point(event.position):
			last_point = _raw_point(event.position)
			dragging = _pointer("down", last_point)
			get_viewport().set_input_as_handled()
		elif not event.pressed and dragging:
			last_point = _raw_point(event.position)
			_pointer("up", last_point)
			dragging = false
			get_viewport().set_input_as_handled()
	elif event is InputEventMouseMotion and dragging:
		raw_mouse_moves += 1
		var point := _raw_point(event.position)
		if point != last_point:
			last_point = point
			_pointer("move", point)
		get_viewport().set_input_as_handled()
	elif event is InputEventKey and event.pressed and not event.echo and live:
		var input_usec := Time.get_ticks_usec()
		if event.ctrl_pressed or event.alt_pressed or event.meta_pressed:
			return
		var key := ""
		match event.keycode:
			KEY_ESCAPE:
				_go_back(input_usec)
				get_viewport().set_input_as_handled()
				return
			KEY_ENTER, KEY_KP_ENTER:
				key = "Enter"
			KEY_BACKSPACE:
				key = "Backspace"
		if key.is_empty() and event.unicode >= 32 and event.unicode <= 126:
			key = String.chr(event.unicode)
		if not key.is_empty():
			_release_all()
			_send_event({"type": "key", "key": key}, input_usec)
			get_viewport().set_input_as_handled()


func _pointer(action: String, point: Vector2i) -> bool:
	var input_usec := Time.get_ticks_usec()
	var payload := {"type": "pointer", "action": action, "x": point.x, "y": point.y, "created_ms": int(Time.get_unix_time_from_system() * 1000.0)}
	if action == "move":
		if controller_id.is_empty() or quit_sequence > 0 or not transport_error.is_empty():
			return false
		# Only the unpublished slot can be replaced. Published sequence files stay intact.
		if not pending_move.is_empty():
			coalesced_mouse_moves += 1
		pending_move = payload
		pending_move_input_usec = input_usec
		if input_usec - last_move_published_usec >= MOVE_INTERVAL_USEC:
			return _flush_pending_move()
		return true
	var published := _send_event(payload, input_usec)
	if published and action == "down":
		last_move_published_usec = 0
	return published


func _flush_pending_move() -> bool:
	if pending_move.is_empty():
		return true
	# Retain the slot on failure and keep later input behind it in sequence order.
	if not _send_event(pending_move, pending_move_input_usec):
		return false
	pending_move = {}
	pending_move_input_usec = 0
	last_move_published_usec = Time.get_ticks_usec()
	return true


func _release_all(control_kind: String = "release") -> void:
	if dragging:
		_pointer("up", last_point)
		dragging = false
	if not controller_id.is_empty() and quit_sequence == 0:
		_send_event({"type": control_kind})


func _cancel_input() -> void:
	# Focus loss and stale/error transitions discard queued work. Before-key
	# releases remain ordered barriers so rapid typing never cancels earlier keys.
	_release_all("cancel")


func _go_back(input_seen_usec: int = 0) -> void:
	if live:
		_release_all()
		_send_event({"type": "key", "key": "Escape"}, input_seen_usec)


func _can_close_locally() -> bool:
	return not configuration_error.is_empty() or not transport_error.is_empty() or (status_seen and (not connected or str(status.get("state", "")) in ["error", "failed", "cancelled"]))


func _close_window(exit_code: int) -> void:
	get_tree().quit(exit_code)


func _request_quit() -> void:
	if _can_close_locally():
		# A local window close must never be reported as controller cleanup.
		_close_window(2)
		return
	if quit_sequence > 0:
		return
	if controller_id.is_empty() or str(status.get("state", "")) in ["stopped", "closed", "exited", "complete"]:
		_close_window(0)
		return
	_release_all()
	if _send_event({"type": "quit"}):
		quit_sequence = sequence
		_refresh_state()


func _send_event(payload: Dictionary, input_seen_usec: int = 0) -> bool:
	if controller_id.is_empty() or session_dir.is_empty() or not configuration_error.is_empty() or not transport_error.is_empty():
		return false
	# Up, release/cancel, key, back, quit and a new down follow the last motion.
	if not (payload.get("type", "") == "pointer" and payload.get("action", "") == "move"):
		if not _flush_pending_move():
			return false
	var enqueue_start_usec := Time.get_ticks_usec()
	var next_sequence := sequence + 1
	payload["v"] = 1
	payload["controller_id"] = controller_id
	payload["client_id"] = client_id
	payload["seq"] = next_sequence
	if not payload.has("created_ms"):
		payload["created_ms"] = int(Time.get_unix_time_from_system() * 1000.0)
	var filename := "%s.%020d.json" % [client_id, next_sequence]
	var path := session_dir.path_join("events").path_join(filename)
	var temporary := path + ".tmp"
	if FileAccess.file_exists(path) or FileAccess.file_exists(temporary):
		_stop_input("Event filename collision; input stopped")
		return false
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		_stop_input("Cannot write event queue (%d)" % FileAccess.get_open_error())
		return false
	file.store_string(JSON.stringify(payload))
	file.flush()
	var write_error := file.get_error()
	file.close()
	if write_error != OK:
		_stop_input("Cannot flush input event (%d)" % write_error)
		return false
	var result := DirAccess.rename_absolute(temporary, path)
	if result != OK:
		_stop_input("Cannot publish input event (%d)" % result)
		return false
	sequence = next_sequence
	var enqueue_end_usec := Time.get_ticks_usec()
	if payload.get("type", "") == "pointer" and payload.get("action", "") == "move":
		published_mouse_moves += 1
	if not metrics_enabled:
		return true
	# Bound diagnostic bookkeeping even if the controller stops acknowledging.
	if event_enqueue_times.size() >= 2048:
		event_enqueue_times.erase(event_enqueue_times.keys()[0])
	event_enqueue_times[sequence] = enqueue_end_usec
	_telemetry("event_enqueued", {
		"event_sequence": sequence,
		"event_type": str(payload.get("type", "")),
		"input_kind": ("escape_gesture" if payload.get("key", "") == "Escape" else "keyboard") if payload.get("type", "") == "key" else "",
		"pointer_action": str(payload.get("action", "")),
		"enqueue_start_usec": enqueue_start_usec,
		"enqueue_end_usec": enqueue_end_usec,
		"enqueue_duration_usec": enqueue_end_usec - enqueue_start_usec,
		"input_seen_usec": input_seen_usec,
		"input_pending_usec": enqueue_start_usec - input_seen_usec if input_seen_usec > 0 else 0,
		"input_to_enqueue_usec": enqueue_end_usec - input_seen_usec if input_seen_usec > 0 else 0,
		"created_ms": payload["created_ms"],
	})
	return true


func _stop_input(reason: String) -> void:
	transport_error = reason
	live = false
	dragging = false
	# Stop heartbeats immediately so the controller's lease releases held touch.
	# Keep the unpublished move for diagnostics; no later event may overtake it.
	_refresh_state()
	queue_redraw()


func _begin_telemetry() -> void:
	if telemetry_file != null:
		telemetry_file.close()
		telemetry_file = null
	if not metrics_enabled or session_dir.is_empty() or not configuration_error.is_empty():
		return
	var path := session_dir.path_join("telemetry.%s.jsonl" % client_id)
	telemetry_file = FileAccess.open(path, FileAccess.READ_WRITE if FileAccess.file_exists(path) else FileAccess.WRITE_READ)
	if telemetry_file != null:
		telemetry_file.seek_end()
	else:
		push_warning("Cannot open frontend telemetry (%d)" % FileAccess.get_open_error())
	pending_frame_observation = {}
	drawn_frame_counter = -1
	observed_frame_counter = -1
	loaded_frame_count = 0
	observed_frame_count = 0
	skipped_before_load_total = 0
	superseded_before_draw_total = 0
	event_enqueue_times.clear()
	raw_mouse_moves = 0
	published_mouse_moves = 0
	coalesced_mouse_moves = 0
	resource_previous_ticks = -1
	resource_previous_usec = 0
	_telemetry("session_start", {
		"render_observation_boundary": "RenderingServer.frame_post_draw after this Control._draw",
		"physical_scanout_measured": false,
		"display_server": DisplayServer.get_name(),
		"poll_seconds": POLL_SECONDS,
		"move_interval_usec": MOVE_INTERVAL_USEC,
		"engine_max_fps": Engine.max_fps,
		"cpu_clock_ticks_per_second": cpu_clock_ticks,
	})
	_sample_process_resources()


func _telemetry(kind: String, fields: Dictionary) -> void:
	if telemetry_file == null:
		return
	fields["v"] = 1
	fields["kind"] = kind
	fields["controller_id"] = controller_id
	fields["client_id"] = client_id
	fields["pid"] = OS.get_process_id()
	fields["raw_mouse_moves"] = raw_mouse_moves
	fields["published_mouse_moves"] = published_mouse_moves
	fields["coalesced_mouse_moves"] = coalesced_mouse_moves
	fields["pending_mouse_move"] = not pending_move.is_empty()
	fields["logged_usec"] = Time.get_ticks_usec()
	fields["logged_unix_ms"] = int(Time.get_unix_time_from_system() * 1000.0)
	telemetry_file.store_line(JSON.stringify(fields))


func _on_frame_post_draw() -> void:
	if pending_frame_observation.is_empty() or drawn_frame_counter != frame_counter:
		return
	# The headless renderer is a dummy and cannot establish a presentation sample.
	if DisplayServer.get_name() == "headless":
		return
	var now_usec := Time.get_ticks_usec()
	var now_unix_ms := int(Time.get_unix_time_from_system() * 1000.0)
	var record := pending_frame_observation
	pending_frame_observation = {}
	observed_frame_count += 1
	record["post_draw_usec"] = now_usec
	record["post_draw_unix_ms"] = now_unix_ms
	record["load_to_post_draw_usec"] = now_usec - int(record["load_end_usec"])
	record["publish_to_post_draw_ms"] = now_unix_ms - int(record["frame_updated_ms"])
	record["previous_observed_frame_counter"] = observed_frame_counter
	record["skipped_since_previous_post_draw"] = maxi(0, frame_counter - observed_frame_counter - 1) if observed_frame_counter >= 0 else 0
	record["observed_frame_count"] = observed_frame_count
	record["event_ack_seen"] = acknowledged
	record["event_sequence"] = sequence
	record["status_event_client_id"] = str(status.get("event_client_id", ""))
	record["status_event_ack"] = int(status.get("event_ack", 0))
	record["window_width"] = get_window().size.x
	record["window_height"] = get_window().size.y
	record["window_visible"] = get_window().visible
	record["window_mode"] = get_window().mode
	record["live"] = live
	observed_frame_counter = frame_counter
	_telemetry("frame_post_draw", record)


func _observe_event_ack(previous_ack: int) -> void:
	if not metrics_enabled:
		return
	var now_usec := Time.get_ticks_usec()
	var queue_to_ack: Array = []
	for event_sequence: int in event_enqueue_times.keys():
		if event_sequence <= acknowledged:
			queue_to_ack.append({"event_sequence": event_sequence, "enqueue_to_ack_seen_usec": now_usec - int(event_enqueue_times[event_sequence])})
			event_enqueue_times.erase(event_sequence)
	_telemetry("event_ack_seen", {
		"previous_ack": previous_ack,
		"event_ack_seen": acknowledged,
		"ack_seen_usec": now_usec,
		"enqueue_to_ack_samples": queue_to_ack,
	})


func _read_cpu_clock_ticks() -> int:
	# Linux auxv supplies AT_CLKTCK without spawning a command or assuming HZ.
	if not OS.has_feature("linux") or not (OS.has_feature("x86") or OS.has_feature("arm")):
		return 0
	var file := FileAccess.open("/proc/self/auxv", FileAccess.READ)
	if file == null:
		return 0
	for index in range(128):
		var tag := file.get_64() if OS.has_feature("64") else file.get_32()
		var value := file.get_64() if OS.has_feature("64") else file.get_32()
		if file.get_error() != OK or tag == 0:
			break
		if tag == 17:
			file.close()
			return value
	file.close()
	return 0


func _sample_process_resources() -> void:
	if controller_id.is_empty() or telemetry_file == null or not OS.has_feature("linux"):
		return
	var sample_start_usec := Time.get_ticks_usec()
	var record: Dictionary = {
		"sample_usec": sample_start_usec,
		"engine_max_fps": Engine.max_fps,
		"engine_process_frames": Engine.get_process_frames(),
		"engine_drawn_frames": Engine.get_frames_drawn(),
		"engine_fps": Engine.get_frames_per_second(),
	}
	# procfs reports a zero file length: read lines instead of get_as_text().
	var stat_file := FileAccess.open("/proc/self/stat", FileAccess.READ)
	if stat_file != null:
		var stat_line := stat_file.get_line()
		stat_file.close()
		var comm_end := stat_line.rfind(")")
		if comm_end >= 0:
			var fields := stat_line.substr(comm_end + 2).split(" ", false)
			if fields.size() >= 13:
				var user_ticks := int(fields[11])
				var system_ticks := int(fields[12])
				var cpu_ticks := user_ticks + system_ticks
				record["cpu_user_ticks"] = user_ticks
				record["cpu_system_ticks"] = system_ticks
				record["cpu_clock_ticks_per_second"] = cpu_clock_ticks
				if resource_previous_ticks >= 0 and sample_start_usec > resource_previous_usec:
					var elapsed_usec := sample_start_usec - resource_previous_usec
					record["cpu_sample_elapsed_usec"] = elapsed_usec
					record["cpu_delta_ticks"] = cpu_ticks - resource_previous_ticks
					if cpu_clock_ticks > 0:
						# 100% means one logical core; multithreaded usage can exceed it.
						record["cpu_percent_one_core"] = float(cpu_ticks - resource_previous_ticks) * 100000000.0 / (float(cpu_clock_ticks) * elapsed_usec)
				resource_previous_ticks = cpu_ticks
				resource_previous_usec = sample_start_usec
	var status_file := FileAccess.open("/proc/self/status", FileAccess.READ)
	if status_file != null:
		for index in range(128):
			if status_file.eof_reached():
				break
			var line := status_file.get_line()
			if line.begins_with("VmRSS:"):
				record["rss_kib"] = line.trim_prefix("VmRSS:").strip_edges().split(" ", false)[0].to_int()
				break
		status_file.close()
	record["sample_duration_usec"] = Time.get_ticks_usec() - sample_start_usec
	_telemetry("process_resources", record)


func _exit_tree() -> void:
	if telemetry_file != null:
		_telemetry("session_end", {"last_frame_counter": frame_counter, "observed_frame_count": observed_frame_count})
		telemetry_file.close()


func _write_heartbeat() -> void:
	if controller_id.is_empty() or session_dir.is_empty() or not configuration_error.is_empty() or not transport_error.is_empty():
		return
	var path := session_dir.path_join("heartbeat.%s.json" % client_id)
	var temporary := path + ".tmp"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		_stop_input("Cannot write frontend heartbeat (%d)" % FileAccess.get_open_error())
		return
	file.store_string(JSON.stringify({"controller_id": controller_id, "client_id": client_id, "updated_ms": int(Time.get_unix_time_from_system() * 1000.0)}))
	file.flush()
	var result := file.get_error()
	file.close()
	if result != OK:
		_stop_input("Cannot flush frontend heartbeat (%d)" % result)
		return
	result = DirAccess.rename_absolute(temporary, path)
	if result != OK:
		_stop_input("Cannot publish frontend heartbeat (%d)" % result)
