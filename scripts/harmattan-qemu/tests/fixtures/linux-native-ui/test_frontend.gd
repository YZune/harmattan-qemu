# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
extends "res://main.gd"

# Observe the production close decision without terminating the test harness.
var closed_with := -1

func _close_window(exit_code: int) -> void:
	closed_with = exit_code
