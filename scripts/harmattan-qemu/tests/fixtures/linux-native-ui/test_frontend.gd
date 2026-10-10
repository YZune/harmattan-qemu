# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends "res://main.gd"

# Observe the production close decision without terminating the test harness.
var closed_with := -1
var release_delay_msec := 0

func _release_all(control_kind: String = "release") -> void:
	# Make time spent before event publication observable in the keyboard probe.
	if release_delay_msec > 0:
		OS.delay_msec(release_delay_msec)
	super._release_all(control_kind)

func _close_window(exit_code: int) -> void:
	closed_with = exit_code
