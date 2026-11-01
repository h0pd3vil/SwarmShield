extends PanelContainer
class_name MissionPanel

signal reassignment_requested(task_id: String, agent_id: String)
signal protection_requested(entity_id: String, radius: float, zone_type: String)
signal protection_remove_requested(entity_id: String)

const TEXT := Color("#e3edf8")
const MUTED := Color("#91a5bb")
const CYAN := Color("#55c2ff")
const GREEN := Color("#8fe388")
const AMBER := Color("#ffd166")

var mission_title: Label
var status_badge: Label
var description: Label
var objectives: VBoxContainer
var task_rows: VBoxContainer
var task_picker: OptionButton
var agent_picker: OptionButton
var reassign_button: Button
var footnote: Label
var context_label: Label
var protection_selection_label: Label
var protection_status_label: Label
var protection_radius: SpinBox
var protection_type_picker: OptionButton
var protection_button: Button
var protection_remove_button: Button
var selected_entity_id := ""
var selected_entity_owner := ""
var active_protection_zones: Array = []
var latest_snapshot: Dictionary = {}
var run_active := false


func _ready() -> void:
	_build()


func _build() -> void:
	_apply_panel_style()
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 8)
	add_child(content)
	var header := HBoxContainer.new()
	content.add_child(header)
	mission_title = Label.new()
	mission_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mission_title.add_theme_font_size_override("font_size", 18)
	mission_title.add_theme_color_override("font_color", TEXT)
	header.add_child(mission_title)
	status_badge = Label.new()
	status_badge.add_theme_font_size_override("font_size", 10)
	header.add_child(status_badge)
	description = Label.new()
	description.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	description.add_theme_font_size_override("font_size", 12)
	description.add_theme_color_override("font_color", MUTED)
	content.add_child(description)
	var separator := HSeparator.new()
	content.add_child(separator)
	var section := Label.new()
	section.text = "MISSION OBJECTIVES"
	section.add_theme_font_size_override("font_size", 10)
	section.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(section)
	objectives = VBoxContainer.new()
	objectives.add_theme_constant_override("separation", 7)
	content.add_child(objectives)
	var task_heading := Label.new()
	task_heading.text = "MISSION TASKS / UAV ASSIGNMENTS"
	task_heading.add_theme_font_size_override("font_size", 10)
	task_heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(task_heading)
	task_rows = VBoxContainer.new()
	task_rows.add_theme_constant_override("separation", 5)
	content.add_child(task_rows)
	var protection_heading := Label.new()
	protection_heading.text = "ENTITY PROTECTION / MONITORING"
	protection_heading.add_theme_font_size_override("font_size", 10)
	protection_heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(protection_heading)
	protection_selection_label = Label.new()
	protection_selection_label.text = "Select a known entity track on the map to inspect or designate it."
	protection_selection_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	protection_selection_label.add_theme_font_size_override("font_size", 10)
	protection_selection_label.add_theme_color_override("font_color", MUTED)
	content.add_child(protection_selection_label)
	protection_status_label = Label.new()
	protection_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	protection_status_label.add_theme_font_size_override("font_size", 10)
	protection_status_label.add_theme_color_override("font_color", TEXT)
	content.add_child(protection_status_label)
	var protection_command_row := HBoxContainer.new()
	protection_command_row.add_theme_constant_override("separation", 5)
	content.add_child(protection_command_row)
	protection_type_picker = OptionButton.new()
	protection_type_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	protection_type_picker.add_item("Monitoring", 0)
	protection_type_picker.add_item("Protection", 1)
	protection_type_picker.tooltip_text = "Both designations require actual local observations inside the configured perimeter."
	protection_command_row.add_child(protection_type_picker)
	protection_radius = SpinBox.new()
	protection_radius.min_value = 2.0
	protection_radius.max_value = 30.0
	protection_radius.step = 1.0
	protection_radius.value = 10.0
	protection_radius.suffix = " u"
	protection_radius.custom_minimum_size.x = 72
	protection_radius.tooltip_text = "The assigned UAV must collect two local observations from within this distance of the known entity track."
	protection_command_row.add_child(protection_radius)
	protection_button = Button.new()
	protection_button.text = "Designate"
	protection_button.pressed.connect(_on_protection_pressed)
	protection_command_row.add_child(protection_button)
	protection_remove_button = Button.new()
	protection_remove_button.text = "Remove"
	protection_remove_button.pressed.connect(_on_protection_remove_pressed)
	protection_command_row.add_child(protection_remove_button)
	var command_heading := Label.new()
	command_heading.text = "COMMANDER ACTION"
	command_heading.add_theme_font_size_override("font_size", 10)
	command_heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(command_heading)
	var command_row := HBoxContainer.new()
	command_row.add_theme_constant_override("separation", 5)
	content.add_child(command_row)
	task_picker = OptionButton.new()
	task_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	task_picker.tooltip_text = "Choose an active mission task to request reassignment. Python checks availability, route, energy, capabilities and deadline."
	task_picker.item_selected.connect(func(_index: int) -> void: _update_reassign_button())
	command_row.add_child(task_picker)
	agent_picker = OptionButton.new()
	agent_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	agent_picker.tooltip_text = "Choose an available UAV. Python validates that it can safely accept the task."
	agent_picker.item_selected.connect(func(_index: int) -> void: _update_reassign_button())
	command_row.add_child(agent_picker)
	reassign_button = Button.new()
	reassign_button.text = "Reassign"
	reassign_button.tooltip_text = "Submit a validated task reassignment request to the Python engine."
	reassign_button.pressed.connect(_on_reassign_pressed)
	command_row.add_child(reassign_button)
	var context_heading := Label.new()
	context_heading.text = "LIVE RUN CONTEXT"
	context_heading.add_theme_font_size_override("font_size", 10)
	context_heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(context_heading)
	context_label = Label.new()
	context_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	context_label.add_theme_font_size_override("font_size", 11)
	context_label.add_theme_color_override("font_color", TEXT)
	content.add_child(context_label)
	footnote = Label.new()
	footnote.text = "At the horizon, every objective must pass; unavailable measurements do not pass. Thresholds are provisional gameplay choices."
	footnote.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	footnote.add_theme_font_size_override("font_size", 10)
	footnote.add_theme_color_override("font_color", MUTED)
	content.add_child(footnote)
	_set_empty()


func set_mission(mission: Dictionary) -> void:
	if mission.is_empty():
		_set_empty()
		return
	mission_title.text = str(mission.get("name", "Mission"))
	description.text = str(mission.get("description", ""))
	var mission_status := str(mission.get("status", "running"))
	var status_color := GREEN if mission_status == "success" else (Color("#ff7d6e") if mission_status == "failure" else AMBER if mission_status in ["incomplete", "paused"] else CYAN)
	status_badge.text = "◆  " + mission_status.replace("_", " ").to_upper()
	status_badge.add_theme_color_override("font_color", status_color)
	footnote.text = "PROTOTYPE · at the horizon, every available objective must pass; objective thresholds are provisional." if bool(mission.get("prototype", false)) else "At the horizon, every objective must pass; unavailable measurements do not pass. Thresholds are provisional gameplay choices."
	_clear_objectives()
	var rows: Array = mission.get("objectives", [])
	if rows.is_empty():
		var empty := Label.new()
		empty.text = "Objective definitions are unavailable from the backend."
		empty.add_theme_color_override("font_color", MUTED)
		objectives.add_child(empty)
	else:
		for objective_value in rows:
			if not objective_value is Dictionary:
				continue
			var objective: Dictionary = objective_value
			objectives.add_child(_objective_row(objective))
	_render_task_rows(mission.get("tasks", []))


func set_snapshot(snapshot: Dictionary) -> void:
	latest_snapshot = snapshot
	var mission: Dictionary = snapshot.get("mission", {})
	set_mission(mission)
	active_protection_zones = snapshot.get("world", {}).get("protection_zones", [])
	_update_protection_inspector()
	if mission.is_empty():
		context_label.text = "Scenario, team policy, and current simulated network status appear here after a run starts."
		return
	var scenario: Dictionary = snapshot.get("scenario", {})
	var metrics: Dictionary = snapshot.get("metrics", {})
	var tasks: Array = mission.get("tasks", snapshot.get("mission_tasks", []))
	_set_reassignment_choices(tasks, snapshot.get("world", {}).get("agents", []))
	var tick := int(snapshot.get("tick", 0))
	var horizon := int(scenario.get("steps", 0))
	var mode := "Cooperative sharing" if str(mission.get("team_mode", "cooperative")) == "cooperative" else "Independent views"
	var policy := str(mission.get("scheduler_policy", scenario.get("scheduler_policy", "unavailable"))).replace("-", " ").capitalize()
	var network := str(metrics.get("communication_status", "unavailable")).replace("_", " ").capitalize()
	var stale := 0
	for track in snapshot.get("world", {}).get("tracks", []):
		if tick - int(track.get("observed_at", 0)) > int(scenario.get("max_track_age_steps", 10)):
			stale += 1
	var completed_tasks := int(metrics.get("mission_tasks_completed", 0))
	var task_count := int(metrics.get("mission_task_count", tasks.size()))
	var area_coverage: Variant = metrics.get("mission_area_coverage_fraction")
	var distance := float(metrics.get("total_uav_distance_travelled", 0.0))
	var energy := float(metrics.get("uav_energy_consumed", 0.0))
	context_label.text = "Logical run  T%03d / %03d · %d ticks remaining\nTeam policy  %s · scheduler %s\nMission work  %d / %d tasks · area coverage %s\nUAV resources  %.1f distance units · %.1f energy units\nNetwork  %s · %d stale local tracks" % [
		tick, horizon, maxi(0, horizon - tick), mode, policy,
		completed_tasks, task_count, "n/a" if area_coverage == null else "%.1f%%" % (float(area_coverage) * 100.0),
		distance, energy, network, stale,
	]
	_update_protection_buttons()


func set_protection_selection(entity_id: String, owner_agent_id: String) -> void:
	selected_entity_id = entity_id
	selected_entity_owner = owner_agent_id
	_update_protection_inspector()
	_update_protection_buttons()


func set_run_active(active: bool) -> void:
	run_active = active
	_update_protection_buttons()


func _update_protection_inspector() -> void:
	if protection_selection_label == null:
		return
	if selected_entity_id.is_empty():
		protection_selection_label.text = "Select a known entity track on the map to inspect or designate it."
		protection_status_label.text = "%d active protection perimeter(s)" % active_protection_zones.size()
		return
	var track_details := "Track details are unavailable."
	var world: Dictionary = latest_snapshot.get("world", {})
	var tick := int(latest_snapshot.get("tick", 0))
	var scenario: Dictionary = latest_snapshot.get("scenario", {})
	var max_age := int(scenario.get("max_track_age_steps", 10))
	for track_value in world.get("tracks", []):
		if not track_value is Dictionary:
			continue
		var track: Dictionary = track_value
		if str(track.get("entity_id", "")) != selected_entity_id or str(track.get("agent_id", "")) != selected_entity_owner:
			continue
		var observed_at := int(track.get("observed_at", 0))
		var age := tick - observed_at
		track_details = "known at (%.1f, %.1f) · T%d · %d ticks old · %s" % [
			float(track.get("x", 0.0)), float(track.get("y", 0.0)), observed_at, age,
			"fresh" if age <= max_age else "stale",
		]
		break
	protection_selection_label.text = "Selected %s · %s · via %s" % [selected_entity_id, track_details, selected_entity_owner]
	var zone: Dictionary = {}
	for value in active_protection_zones:
		if value is Dictionary and str(value.get("entity_id", "")) == selected_entity_id:
			zone = value
			break
	if zone.is_empty():
		protection_status_label.text = "No active perimeter. Designation creates an engine-owned monitoring task."
	else:
		protection_status_label.text = "%s · %s zone · radius %.1f · task %s" % [
			str(zone.get("status", "caution")).capitalize(),
			str(zone.get("zone_type", "monitoring")),
			float(zone.get("radius", 0.0)),
			str(zone.get("task_id", "n/a")),
		]


func _update_protection_buttons() -> void:
	if protection_button == null:
		return
	var has_selection := not selected_entity_id.is_empty()
	protection_button.disabled = not run_active or not has_selection
	protection_remove_button.disabled = not run_active or not _selected_entity_is_protected()
	protection_button.text = "Update" if _selected_entity_is_protected() else "Designate"


func _selected_entity_is_protected() -> bool:
	for value in active_protection_zones:
		if value is Dictionary and str(value.get("entity_id", "")) == selected_entity_id:
			return true
	return false


func _on_protection_pressed() -> void:
	if selected_entity_id.is_empty():
		return
	var zone_type := "monitoring" if protection_type_picker.get_selected_id() == 0 else "protection"
	protection_requested.emit(selected_entity_id, protection_radius.value, zone_type)


func _on_protection_remove_pressed() -> void:
	if selected_entity_id.is_empty() or not _selected_entity_is_protected():
		return
	protection_remove_requested.emit(selected_entity_id)


func _objective_row(objective: Dictionary) -> Control:
	var row := VBoxContainer.new()
	row.add_theme_constant_override("separation", 2)
	var title_row := HBoxContainer.new()
	row.add_child(title_row)
	var title := Label.new()
	title.text = str(objective.get("label", objective.get("id", "Objective")))
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	title.add_theme_font_size_override("font_size", 11)
	title.add_theme_color_override("font_color", TEXT)
	title_row.add_child(title)
	var actual: Variant = objective.get("actual")
	var passed := bool(objective.get("passed", false))
	var badge := Label.new()
	badge.text = "✓ MET" if passed else ("— NO DATA" if actual == null else "○ TRACKING")
	badge.add_theme_font_size_override("font_size", 9)
	badge.add_theme_color_override("font_color", GREEN if passed else (MUTED if actual == null else AMBER))
	title_row.add_child(badge)
	var target: Variant = objective.get("target")
	var operator := str(objective.get("operator", ">="))
	var metric := str(objective.get("metric", ""))
	var detail := Label.new()
	detail.text = "Actual %s  %s  target %s" % [_format_metric(actual, metric), operator, _format_metric(target, metric)]
	detail.add_theme_font_size_override("font_size", 10)
	detail.add_theme_color_override("font_color", MUTED)
	row.add_child(detail)
	var progress := ProgressBar.new()
	progress.max_value = 1.0
	progress.show_percentage = false
	progress.custom_minimum_size.y = 5
	var background := StyleBoxFlat.new()
	background.bg_color = Color("#202c3b")
	background.set_corner_radius_all(3)
	progress.add_theme_stylebox_override("background", background)
	var fill := StyleBoxFlat.new()
	fill.bg_color = GREEN if passed else CYAN
	fill.set_corner_radius_all(3)
	progress.add_theme_stylebox_override("fill", fill)
	progress.value = _objective_progress(actual, target, operator)
	progress.visible = actual != null and target != null
	row.add_child(progress)
	var guidance := Label.new()
	guidance.text = str(objective.get("guidance", ""))
	guidance.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	guidance.add_theme_font_size_override("font_size", 9)
	guidance.add_theme_color_override("font_color", GREEN if passed else AMBER)
	guidance.visible = not passed and not guidance.text.is_empty()
	row.add_child(guidance)
	return row


func _render_task_rows(tasks: Array) -> void:
	_clear_task_rows()
	if tasks.is_empty():
		var empty := Label.new()
		empty.text = "No spatial tasks are defined for this mission."
		empty.add_theme_font_size_override("font_size", 10)
		empty.add_theme_color_override("font_color", MUTED)
		task_rows.add_child(empty)
		return
	for task_value in tasks:
		if task_value is Dictionary:
			task_rows.add_child(_mission_task_row(task_value))


func _mission_task_row(task: Dictionary) -> Control:
	var row := VBoxContainer.new()
	row.add_theme_constant_override("separation", 1)
	var task_id := str(task.get("task_id", "task"))
	var status := str(task.get("status", "unassigned")).replace("_", " ")
	var owner := str(task.get("assigned_agent_id", "unassigned"))
	var title := Label.new()
	title.text = "%s  ·  %s  ·  %s" % [task_id, owner, status]
	title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	title.add_theme_font_size_override("font_size", 10)
	var status_color := GREEN if status == "completed" else (Color("#ff7d6e") if status in ["failed", "expired"] else AMBER if owner == "unassigned" else TEXT)
	title.add_theme_color_override("font_color", status_color)
	row.add_child(title)
	var detail := Label.new()
	detail.text = "%s · due T%s" % [str(task.get("task_type", "task")).replace("_", " "), str(task.get("deadline_step", "n/a"))]
	detail.add_theme_font_size_override("font_size", 9)
	detail.add_theme_color_override("font_color", MUTED)
	row.add_child(detail)
	var reason := str(task.get("failure_reason", ""))
	if reason.is_empty() and owner == "unassigned":
		reason = str(task.get("assignment_reason", ""))
	if not reason.is_empty():
		var explanation := Label.new()
		explanation.text = reason.replace("_", " ")
		explanation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		explanation.add_theme_font_size_override("font_size", 9)
		explanation.add_theme_color_override("font_color", AMBER if owner == "unassigned" else MUTED)
		row.add_child(explanation)
	return row


func _set_reassignment_choices(tasks: Array, agents: Array) -> void:
	task_picker.clear()
	task_picker.add_item("Choose task", 0)
	for task in tasks:
		if not task is Dictionary or str(task.get("status", "")) not in ["assigned", "navigating", "executing"]:
			continue
		var index := task_picker.item_count
		task_picker.add_item(str(task.get("task_id", "task")), index)
		task_picker.set_item_metadata(index, str(task.get("task_id", "")))
	agent_picker.clear()
	agent_picker.add_item("Choose free UAV", 0)
	for agent in agents:
		if not agent is Dictionary:
			continue
		var task_id: Variant = agent.get("current_task_id")
		var recovery_target: Variant = agent.get("recovery_target")
		var status := str(agent.get("uav_status", "available"))
		if task_id != null or recovery_target != null or status not in ["available", "arrived"]:
			continue
		var index := agent_picker.item_count
		agent_picker.add_item(str(agent.get("id", "UAV")), index)
		agent_picker.set_item_metadata(index, str(agent.get("id", "")))
	_update_reassign_button()


func _update_reassign_button() -> void:
	if reassign_button == null:
		return
	reassign_button.disabled = task_picker.selected <= 0 or agent_picker.selected <= 0


func _on_reassign_pressed() -> void:
	if task_picker.selected <= 0 or agent_picker.selected <= 0:
		return
	reassignment_requested.emit(
		str(task_picker.get_item_metadata(task_picker.selected)),
		str(agent_picker.get_item_metadata(agent_picker.selected)),
	)


func _objective_progress(actual: Variant, target: Variant, operator: String) -> float:
	if actual == null or target == null:
		return 0.0
	var actual_value := float(actual)
	var target_value := float(target)
	if operator == "<=":
		if actual_value <= target_value:
			return 1.0
		return clampf(target_value / actual_value, 0.0, 1.0) if actual_value > 0.0 else 0.0
	if target_value <= 0.0:
		return 1.0 if actual_value >= target_value else 0.0
	return clampf(actual_value / target_value, 0.0, 1.0)


func _format_metric(value: Variant, metric: String) -> String:
	if value == null:
		return "n/a"
	if metric.ends_with("coverage") or metric.ends_with("rate"):
		return "%.0f%%" % (float(value) * 100.0)
	if metric == "recovery_time_steps":
		return "%d ticks" % int(value)
	return str(value)


func _clear_objectives() -> void:
	for child in objectives.get_children():
		objectives.remove_child(child)
		child.queue_free()


func _clear_task_rows() -> void:
	for child in task_rows.get_children():
		task_rows.remove_child(child)
		child.queue_free()


func _set_empty() -> void:
	mission_title.text = "Mission briefing"
	description.text = "Choose a scenario and start a run. Objectives and progress come directly from the Python simulation."
	status_badge.text = "○  READY"
	status_badge.add_theme_color_override("font_color", MUTED)
	footnote.text = "At the horizon, every objective must pass. The bundled thresholds are provisional gameplay choices."
	context_label.text = "Scenario, team policy, and current simulated network status appear here after a run starts."
	_clear_objectives()
	_clear_task_rows()
	if task_picker != null:
		task_picker.clear()
		task_picker.add_item("Choose task", 0)
		agent_picker.clear()
		agent_picker.add_item("Choose free UAV", 0)
		_update_reassign_button()
	var hint := Label.new()
	hint.text = "Select Shared Awareness, Deadline Pressure, or Network Recovery to review its objective criteria."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_font_size_override("font_size", 11)
	hint.add_theme_color_override("font_color", MUTED)
	objectives.add_child(hint)
	var task_hint := Label.new()
	task_hint.text = "Assigned mission tasks will appear when a run starts."
	task_hint.add_theme_font_size_override("font_size", 10)
	task_hint.add_theme_color_override("font_color", MUTED)
	task_rows.add_child(task_hint)


func _apply_panel_style() -> void:
	var style := StyleBoxFlat.new()
	style.bg_color = Color("#0d1622")
	style.border_color = Color("#26374b")
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	style.content_margin_left = 13
	style.content_margin_right = 13
	style.content_margin_top = 12
	style.content_margin_bottom = 12
	add_theme_stylebox_override("panel", style)
