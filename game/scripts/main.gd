extends Control

const SCENARIOS := ["shared_awareness", "deadline_pressure", "network_recovery"]
const SCENARIO_NAMES := ["Shared Awareness", "Deadline Pressure", "Network Recovery"]
const SPEEDS := [0.25, 0.5, 1.0, 2.0, 4.0]
const BACKGROUND := Color("#080e16")
const TEXT := Color("#e3edf8")
const MUTED := Color("#91a5bb")
const CYAN := Color("#55c2ff")
const GREEN := Color("#8fe388")
const AMBER := Color("#ffd166")
const RED := Color("#ff9c83")

var bridge := PythonBridge.new()
var tick_timer: Timer
var mission_picker: OptionButton
var mode_picker: OptionButton
var policy_picker: OptionButton
var seed_picker: SpinBox
var speed_picker: OptionButton
var start_button: Button
var pause_button: Button
var resume_button: Button
var reset_button: Button
var apply_policy_button: Button
var manual_destination_toggle: CheckBox
var status_label: Label
var status_card: PanelContainer
var mission_name_label: Label
var tick_label: Label
var network_badge: Label
var freshness_badge: Label
var sidebar_tabs: TabContainer
var world_view: WorldView
var mission_panel: MissionPanel
var metrics_panel: TeamMetricsPanel
var inspector_panel: AgentInspector
var timeline_panel: EventTimeline
var results_panel: RunResultsPanel

var selected_agent := ""
var selected_entity_id := ""
var current_snapshot: Dictionary = {}
var current_scenario_id := ""
var current_scenario_name := ""
var current_seed := 42
var initial_policy := "fixed-priority"
var has_session := false
var run_active := false
var run_paused := false
var has_completed_results := false


func _ready() -> void:
	_build_ui()
	_set_controls()
	if not bridge.start():
		_set_status("BACKEND ERROR", RED, "Could not start the Python simulation process.")
		return
	var scenarios := bridge.request("list_scenarios")
	if not _accept(scenarios):
		return
	var available: Array = scenarios.get("result", {}).get("scenarios", [])
	if available.size() != SCENARIOS.size():
		_set_status("CONFIGURATION WARNING", AMBER, "The backend mission list differs from the expected bundled scenarios.")
	var saved_comparisons := bridge.request("list_saved_comparisons")
	if _accept(saved_comparisons):
		results_panel.set_saved_comparisons(saved_comparisons.get("result", {}).get("comparisons", []))


func _exit_tree() -> void:
	bridge.close()


func _build_ui() -> void:
	var backdrop := ColorRect.new()
	backdrop.color = BACKGROUND
	backdrop.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	backdrop.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(backdrop)

	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	margin.add_theme_constant_override("margin_left", 20)
	margin.add_theme_constant_override("margin_right", 20)
	margin.add_theme_constant_override("margin_top", 14)
	margin.add_theme_constant_override("margin_bottom", 12)
	add_child(margin)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 9)
	margin.add_child(root)

	_build_header(root)
	_build_setup_bar(root)
	_build_play_area(root)
	var footer := Label.new()
	footer.text = "ENGINE TIME IS FIXED-TICK  ·  All agents, entities, tasks, and communication failures are synthetic. Rendering does not advance simulation time."
	footer.add_theme_font_size_override("font_size", 9)
	footer.add_theme_color_override("font_color", Color("#70839a"))
	root.add_child(footer)

	tick_timer = Timer.new()
	tick_timer.one_shot = false
	tick_timer.wait_time = 0.5
	tick_timer.timeout.connect(_on_tick)
	add_child(tick_timer)


func _build_header(root: VBoxContainer) -> void:
	var header := HBoxContainer.new()
	header.add_theme_constant_override("separation", 10)
	root.add_child(header)
	var title := Label.new()
	title.text = "SWARMSHIELD"
	title.add_theme_font_size_override("font_size", 23)
	title.add_theme_color_override("font_color", TEXT)
	header.add_child(title)
	var divider := VSeparator.new()
	header.add_child(divider)
	mission_name_label = Label.new()
	mission_name_label.text = "COORDINATION SIMULATOR  /  SYNTHETIC WORLD"
	mission_name_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mission_name_label.add_theme_font_size_override("font_size", 11)
	mission_name_label.add_theme_color_override("font_color", MUTED)
	header.add_child(mission_name_label)
	tick_label = Label.new()
	tick_label.text = "T000 / 000  ·  0 elapsed ticks"
	tick_label.add_theme_font_size_override("font_size", 11)
	tick_label.add_theme_color_override("font_color", Color("#c6d5e5"))
	header.add_child(tick_label)
	status_card = PanelContainer.new()
	_apply_status_style(status_card, Color("#193044"))
	status_label = Label.new()
	status_label.text = "●  READY"
	status_label.add_theme_font_size_override("font_size", 10)
	status_label.add_theme_color_override("font_color", CYAN)
	status_card.add_child(status_label)
	header.add_child(status_card)
	pause_button = _make_button("Pause", false)
	pause_button.pressed.connect(_on_pause)
	header.add_child(pause_button)
	resume_button = _make_button("Resume", false)
	resume_button.pressed.connect(_on_resume)
	header.add_child(resume_button)
	reset_button = _make_button("Reset", false)
	reset_button.pressed.connect(_on_reset)
	header.add_child(reset_button)


func _build_setup_bar(root: VBoxContainer) -> void:
	var bar := HFlowContainer.new()
	bar.add_theme_constant_override("h_separation", 9)
	bar.add_theme_constant_override("v_separation", 5)
	root.add_child(bar)

	mission_picker = OptionButton.new()
	for index in range(SCENARIOS.size()):
		mission_picker.add_item(SCENARIO_NAMES[index], index)
	mission_picker.select(0)
	mission_picker.tooltip_text = "Choose an engine-backed mission. Thresholds are provisional gameplay choices."
	_add_field(bar, "MISSION", mission_picker, 184)

	mode_picker = OptionButton.new()
	mode_picker.add_item("Cooperative sharing", 0)
	mode_picker.add_item("Independent views", 1)
	mode_picker.select(0)
	mode_picker.tooltip_text = "Cooperative reports share observations through the simulated network; independent mode disables peer sharing."
	_add_field(bar, "TEAM POLICY", mode_picker, 158)

	policy_picker = OptionButton.new()
	policy_picker.add_item("Fixed priority", 0)
	policy_picker.add_item("Earliest deadline first", 1)
	policy_picker.select(0)
	policy_picker.tooltip_text = "Select the decision scheduler for a new mission or submit it as a live policy intervention."
	_add_field(bar, "SCHEDULER", policy_picker, 164)

	seed_picker = SpinBox.new()
	seed_picker.min_value = 0
	seed_picker.max_value = 2147483647
	seed_picker.step = 1
	seed_picker.value = 42
	seed_picker.prefix = "Seed "
	seed_picker.custom_minimum_size.x = 108
	_add_field(bar, "REPRODUCIBLE RUN", seed_picker, 108)

	speed_picker = OptionButton.new()
	for index in range(SPEEDS.size()):
		speed_picker.add_item("×%s" % str(SPEEDS[index]), index)
	speed_picker.select(2)
	speed_picker.item_selected.connect(func(_index: int) -> void: _update_speed())
	speed_picker.tooltip_text = "Changes the wall-clock interval between fixed engine tick requests. It does not change simulation rules."
	_add_field(bar, "TICK RATE", speed_picker, 78)

	start_button = _make_button("Start mission", true)
	start_button.pressed.connect(_on_start)
	bar.add_child(start_button)
	apply_policy_button = _make_button("Apply scheduler", false)
	apply_policy_button.tooltip_text = "Submit the selected supported scheduler-policy intervention to Python."
	apply_policy_button.pressed.connect(_on_apply_policy)
	bar.add_child(apply_policy_button)


func _build_play_area(root: VBoxContainer) -> void:
	var split := HSplitContainer.new()
	split.size_flags_vertical = Control.SIZE_EXPAND_FILL
	split.split_offset = -420
	split.dragger_visibility = SplitContainer.DRAGGER_VISIBLE
	root.add_child(split)

	var map_column := VBoxContainer.new()
	map_column.custom_minimum_size.x = 520
	map_column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map_column.size_flags_vertical = Control.SIZE_EXPAND_FILL
	map_column.add_theme_constant_override("separation", 8)
	split.add_child(map_column)
	_build_map_card(map_column)
	metrics_panel = TeamMetricsPanel.new()
	metrics_panel.custom_minimum_size.y = 185
	map_column.add_child(metrics_panel)

	sidebar_tabs = TabContainer.new()
	sidebar_tabs.custom_minimum_size.x = 330
	sidebar_tabs.size_flags_horizontal = Control.SIZE_FILL
	sidebar_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	sidebar_tabs.add_theme_constant_override("side_margin", 5)
	split.add_child(sidebar_tabs)
	mission_panel = MissionPanel.new()
	mission_panel.reassignment_requested.connect(_on_task_reassignment_requested)
	mission_panel.protection_requested.connect(_on_protection_requested)
	mission_panel.protection_remove_requested.connect(_on_protection_remove_requested)
	inspector_panel = AgentInspector.new()
	inspector_panel.agent_selected.connect(_on_agent_selected)
	timeline_panel = EventTimeline.new()
	results_panel = RunResultsPanel.new()
	results_panel.matched_comparison_requested.connect(_on_matched_comparison_requested)
	results_panel.saved_comparison_selected.connect(_on_saved_comparison_selected)
	_add_tab("MISSION", mission_panel)
	_add_tab("AGENT", inspector_panel)
	_add_tab("EVENTS", timeline_panel)
	_add_tab("RESULTS", results_panel)
	sidebar_tabs.set_tab_title(0, "MISSION")
	sidebar_tabs.set_tab_title(1, "AGENT")
	sidebar_tabs.set_tab_title(2, "EVENTS")
	sidebar_tabs.set_tab_title(3, "RESULTS")


func _build_map_card(parent: VBoxContainer) -> void:
	var card := PanelContainer.new()
	card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	card.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var style := StyleBoxFlat.new()
	style.bg_color = Color("#0b1320")
	style.border_color = Color("#26384d")
	style.set_border_width_all(1)
	style.set_corner_radius_all(8)
	style.content_margin_left = 10
	style.content_margin_right = 10
	style.content_margin_top = 9
	style.content_margin_bottom = 8
	card.add_theme_stylebox_override("panel", style)
	parent.add_child(card)
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 6)
	card.add_child(content)
	var map_header := HBoxContainer.new()
	content.add_child(map_header)
	var map_title := Label.new()
	map_title.text = "LIVE TACTICAL MAP"
	map_title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	map_title.add_theme_font_size_override("font_size", 11)
	map_title.add_theme_color_override("font_color", Color("#8fb2d8"))
	map_header.add_child(map_title)
	network_badge = Label.new()
	network_badge.text = "○  WAITING FOR RUN"
	network_badge.add_theme_font_size_override("font_size", 9)
	network_badge.add_theme_color_override("font_color", MUTED)
	map_header.add_child(network_badge)
	freshness_badge = Label.new()
	freshness_badge.text = "0 STALE TRACKS"
	freshness_badge.add_theme_font_size_override("font_size", 9)
	freshness_badge.add_theme_color_override("font_color", GREEN)
	map_header.add_child(freshness_badge)
	var map_controls := HFlowContainer.new()
	map_controls.add_theme_constant_override("h_separation", 7)
	map_controls.add_theme_constant_override("v_separation", 0)
	content.add_child(map_controls)
	world_view = WorldView.new()
	world_view.custom_minimum_size = Vector2(480, 280)
	world_view.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	world_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	world_view.agent_selected.connect(_on_agent_selected)
	world_view.entity_selected.connect(_on_entity_selected)
	world_view.destination_requested.connect(_on_destination_requested)
	_add_map_toggle(map_controls, "UAVs", "uavs", true, "Show or hide UAV artwork. Simulation state and selection data are unchanged.")
	_add_map_toggle(map_controls, "Tasks", "task_assignments", true, "Show or hide task regions and route overlays. Assignments and metrics are unchanged.")
	_add_map_toggle(map_controls, "Terrain", "terrain", true, "Show or hide terrain, roads, vegetation, obstacles and points of interest. World geometry is unchanged.")
	_add_map_toggle(map_controls, "Mission areas", "mission_areas", false, "Show configured mission-area geometry. Task state and progress are unchanged.")
	_add_map_toggle(map_controls, "Obstacle edges", "obstacle_boundaries", true, "Show or hide backend solid obstacles and building footprints. Collision and sensing behavior are unchanged.")
	_add_map_toggle(map_controls, "Safe areas", "safe_areas", false, "Show configured launch and recovery areas. UAV behavior is unchanged.")
	_add_map_toggle(map_controls, "Restricted zones", "restricted_zones", true, "Show configured zones and their backend policy: deny entry, monitor, warn, or inactive.")
	_add_map_toggle(map_controls, "Caution zones", "caution_zones", false, "Show configured caution zones. This only changes map rendering.")
	_add_map_toggle(map_controls, "Protection zones", "protection_zones", true, "Show active perimeters centered on each entity's last known agent track; status comes from monitoring-task evidence.")
	_add_map_toggle(map_controls, "Links", "communication_links", false, "Show up to four recent backend-confirmed or currently pending agent-to-agent routes. This only changes map rendering.")
	_add_map_toggle(map_controls, "Local observations", "local_observations", true, "Show local observation markers. Metrics and agent knowledge remain unchanged.")
	_add_map_toggle(map_controls, "Shared reports", "shared_reports", false, "Show reports received from another agent. Metrics and agent knowledge remain unchanged.")
	_add_map_toggle(map_controls, "Fog", "fog_of_war", false, "Shade unexplored cells; explored cells come from actual sensor coverage and applied peer reports.")
	_add_map_toggle(map_controls, "Stale tracks", "stale_tracks", false, "Show stale track markers. Track freshness metrics remain unchanged.")
	_add_map_toggle(map_controls, "Sensor range", "sensor_visibility", false, "Show the selected UAV's backend-configured sensing radius. This does not alter sensing.")
	_add_map_toggle(map_controls, "Entity labels", "entity_labels", true, "Show entity labels only while the entity is hovered or selected.")
	_add_map_toggle(map_controls, "Grid", "coordinate_grid", false, "Show a subtle coordinate grid for analysis. This only changes rendering.")
	_add_map_camera_button(map_controls, "−", "Zoom out one step around the map center.", func() -> void: world_view.zoom_at(1.0 / 1.2, world_view.size * 0.5))
	_add_map_camera_button(map_controls, "+", "Zoom in one step around the map center.", func() -> void: world_view.zoom_at(1.2, world_view.size * 0.5))
	_add_map_camera_button(map_controls, "Center", "Zoom to the selected UAV or known entity.", func() -> void: world_view.zoom_to_selection())
	_add_map_camera_button(map_controls, "Fit", "Reset map zoom and pan.", func() -> void: world_view.reset_camera())
	manual_destination_toggle = CheckBox.new()
	manual_destination_toggle.text = "Set destination"
	manual_destination_toggle.button_pressed = false
	manual_destination_toggle.disabled = true
	manual_destination_toggle.tooltip_text = "Select an idle UAV, enable this, then click an empty map point. Python validates and plans the route."
	manual_destination_toggle.add_theme_font_size_override("font_size", 9)
	manual_destination_toggle.toggled.connect(func(enabled: bool) -> void: world_view.set_manual_destination_enabled(enabled))
	map_controls.add_child(manual_destination_toggle)
	content.add_child(world_view)
	var legend := HFlowContainer.new()
	legend.add_theme_constant_override("h_separation", 10)
	legend.add_theme_constant_override("v_separation", 2)
	content.add_child(legend)
	_add_legend(legend, "Quadcopter · observer", Color("#55c2ff"))
	_add_legend(legend, "Observed contact track · local/shared", Color("#f4c95d"))
	_add_legend(legend, "○ local  ·  ◇ shared", Color("#c39bff"))
	_add_legend(legend, "Solid fresh  ·  broken stale", Color("#c7d8e8"))
	_add_legend(legend, "Green delivered  ·  amber pending  ·  red lost", Color("#8fe388"))
	_add_legend(legend, "Protection: blue monitored  ·  amber caution  ·  red alert  ·  optional cyan sensor range", Color("#91acb9"))
	_add_legend(legend, "Fog: dark unknown  ·  teal current  ·  blue shared  ·  tan prior sweep", Color("#72c8b1"))
	_add_legend(legend, "Roads, mission areas and obstacles follow backend geometry", Color("#7d9288"))


func _add_tab(title: String, panel: Control) -> void:
	var scroll := ScrollContainer.new()
	scroll.name = title.replace(" ", "")
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var stack := VBoxContainer.new()
	stack.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	stack.add_theme_constant_override("separation", 0)
	stack.add_child(panel)
	scroll.add_child(stack)
	sidebar_tabs.add_child(scroll)


func _add_field(parent: HFlowContainer, caption: String, control: Control, width: float) -> void:
	var field := VBoxContainer.new()
	field.add_theme_constant_override("separation", 2)
	field.custom_minimum_size.x = width
	var label := Label.new()
	label.text = caption
	label.add_theme_font_size_override("font_size", 8)
	label.add_theme_color_override("font_color", MUTED)
	field.add_child(label)
	control.custom_minimum_size.x = width
	field.add_child(control)
	parent.add_child(field)


func _add_legend(parent: HFlowContainer, text: String, tint: Color) -> void:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", 9)
	label.add_theme_color_override("font_color", tint)
	parent.add_child(label)


func _add_map_toggle(parent: HFlowContainer, label: String, layer: String, initially_enabled: bool, help: String) -> void:
	var toggle := CheckBox.new()
	toggle.text = label
	toggle.button_pressed = initially_enabled
	toggle.tooltip_text = help
	toggle.add_theme_font_size_override("font_size", 9)
	toggle.add_theme_color_override("font_color", Color("#c7d8e8"))
	toggle.add_theme_color_override("font_hover_color", TEXT)
	toggle.toggled.connect(func(enabled: bool) -> void:
		world_view.set_display_layer(layer, enabled)
	)
	parent.add_child(toggle)


func _add_map_camera_button(parent: HFlowContainer, title: String, help: String, action: Callable) -> void:
	var button := _make_button(title, false)
	button.custom_minimum_size = Vector2(42, 24)
	button.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	button.tooltip_text = help
	button.add_theme_font_size_override("font_size", 9)
	button.pressed.connect(action)
	parent.add_child(button)


func _make_button(text: String, primary: bool) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size.y = 32
	button.add_theme_font_size_override("font_size", 10)
	var base := Color("#17364a") if primary else Color("#152131")
	var border := Color("#3e86ae") if primary else Color("#30445b")
	for state in ["normal", "hover", "pressed", "disabled", "focus"]:
		var style := StyleBoxFlat.new()
		style.bg_color = base
		style.border_color = border
		style.set_border_width_all(1)
		style.set_corner_radius_all(5)
		style.content_margin_left = 10
		style.content_margin_right = 10
		style.content_margin_top = 5
		style.content_margin_bottom = 5
		if state == "hover":
			style.bg_color = base.lightened(0.12)
		if state == "pressed":
			style.bg_color = base.darkened(0.12)
		if state == "disabled":
			style.bg_color = Color("#111923")
			style.border_color = Color("#26313d")
		button.add_theme_stylebox_override(state, style)
	button.add_theme_color_override("font_color", TEXT)
	button.add_theme_color_override("font_disabled_color", MUTED)
	return button


func _on_start() -> void:
	if run_active:
		return
	var scenario_index := clampi(mission_picker.get_selected_id(), 0, SCENARIOS.size() - 1)
	current_scenario_id = SCENARIOS[scenario_index]
	current_scenario_name = SCENARIO_NAMES[scenario_index]
	current_seed = int(seed_picker.value)
	var selected_policy := "fixed-priority" if policy_picker.get_selected_id() == 0 else "edf"
	initial_policy = selected_policy
	var selected_mode := "cooperative" if mode_picker.get_selected_id() == 0 else "independent"
	var response := bridge.request("start_run", {
		"scenario": current_scenario_id,
		"seed": current_seed,
		"mode": selected_mode,
		"policy": selected_policy,
	})
	if not _accept(response):
		return
	has_session = true
	run_active = true
	run_paused = false
	selected_agent = ""
	selected_entity_id = ""
	world_view.select_agent("")
	mission_panel.set_protection_selection("", "")
	current_snapshot.clear()
	timeline_panel.clear_run()
	sidebar_tabs.current_tab = 0
	mission_name_label.text = current_scenario_name.to_upper()
	_set_status("RUNNING", GREEN, "Python owns all simulation ticks and state transitions.")
	_set_controls()
	_update_speed()
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)
	_on_tick()
	tick_timer.start()


func _on_pause() -> void:
	if not run_active:
		return
	var response := bridge.request("pause_run")
	if _accept(response):
		run_paused = true
		tick_timer.stop()
		_set_status("PAUSED", AMBER, "Virtual time is stopped until the run resumes.")
		_set_controls()
		var snapshot_response := bridge.request("get_snapshot")
		if _accept(snapshot_response):
			_update_snapshot(snapshot_response.result)


func _on_resume() -> void:
	if not run_active:
		return
	var response := bridge.request("resume_run")
	if _accept(response):
		run_paused = false
		tick_timer.start()
		_set_status("RUNNING", GREEN, "Python owns all simulation ticks and state transitions.")
		_set_controls()


func _on_reset() -> void:
	if not has_session:
		return
	tick_timer.stop()
	var response := bridge.request("reset_run")
	if not _accept(response):
		return
	run_active = true
	run_paused = false
	policy_picker.select(0 if initial_policy == "fixed-priority" else 1)
	selected_agent = ""
	selected_entity_id = ""
	world_view.select_agent("")
	mission_panel.set_protection_selection("", "")
	current_scenario_id = str(response.result.get("scenario", current_scenario_id))
	mission_name_label.text = current_scenario_name.to_upper() + " · RESET"
	timeline_panel.clear_run()
	inspector_panel.set_agent({})
	_set_status("RESET · TICK 0", CYAN, "The same scenario and seed are ready to replay.")
	_set_controls()
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)
	tick_timer.start()


func _on_apply_policy() -> void:
	if not run_active:
		return
	var policy := "fixed-priority" if policy_picker.get_selected_id() == 0 else "edf"
	var response := bridge.request("apply_intervention", {
		"action": "set_scheduler_policy",
		"parameters": {"policy": policy},
	})
	if not _accept(response):
		return
	var outcome: Dictionary = response.result
	if bool(outcome.get("accepted", false)):
		_set_status("POLICY UPDATED", GREEN, "Scheduler now uses %s at logical tick %d." % [policy, int(outcome.get("step", 0))])
	else:
		_set_status("POLICY REJECTED", AMBER, str(outcome.get("outcome", "The engine rejected the intervention.")))
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)


func _on_destination_requested(agent_id: String, destination: Vector2) -> void:
	if not run_active or agent_id != selected_agent:
		return
	var response := bridge.request("apply_intervention", {
		"action": "set_uav_destination",
		"parameters": {"agent_id": agent_id, "destination": [destination.x, destination.y]},
	})
	if not _accept(response):
		return
	var outcome: Dictionary = response.result
	if bool(outcome.get("accepted", false)):
		_set_status("DESTINATION ACCEPTED", GREEN, "Python validated the world position and planned route for %s." % agent_id)
	else:
		_set_status("DESTINATION REJECTED", AMBER, str(outcome.get("outcome", "Python rejected the route request.")))
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)


func _on_task_reassignment_requested(task_id: String, agent_id: String) -> void:
	if not run_active:
		return
	var response := bridge.request("apply_intervention", {
		"action": "reassign_mission_task",
		"parameters": {"task_id": task_id, "agent_id": agent_id},
	})
	if not _accept(response):
		return
	var outcome: Dictionary = response.result
	if bool(outcome.get("accepted", false)):
		_set_status("TASK REASSIGNED", GREEN, "Python reassigned %s to %s and dispatched its engine route." % [task_id, agent_id])
	else:
		_set_status("REASSIGNMENT REJECTED", AMBER, str(outcome.get("outcome", "Python rejected the reassignment request.")))
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)


func _on_tick() -> void:
	if not run_active or run_paused:
		return
	var response := bridge.request("advance_ticks", {"count": 1})
	if not _accept(response):
		tick_timer.stop()
		run_active = false
		_set_controls()
		return
	var result: Dictionary = response.result
	current_snapshot = result.get("snapshot", {})
	_update_snapshot(current_snapshot)
	if result.get("status") == "completed":
		tick_timer.stop()
		run_active = false
		run_paused = false
		has_completed_results = true
		var summary: Dictionary = result.get("summary", {})
		var mission_result: Dictionary = summary.get("game_result", {}).get("mission", {})
		var outcome := str(mission_result.get("status", "incomplete"))
		var tone := GREEN if outcome == "success" else (RED if outcome == "failure" else AMBER)
		_set_status("MISSION " + outcome.to_upper(), tone, "Run artifacts saved by the Python engine.")
		results_panel.add_result(summary, current_snapshot, str(result.get("artifact_path", "")), current_scenario_name, current_seed, timeline_panel.highlights())
		sidebar_tabs.current_tab = 3
		_set_controls()


func _update_speed() -> void:
	if tick_timer == null:
		return
	var speed: float = float(SPEEDS[clampi(speed_picker.get_selected_id(), 0, SPEEDS.size() - 1)])
	var response := bridge.request("set_simulation_speed", {"speed": speed})
	if not _accept(response):
		return
	tick_timer.wait_time = 0.5 / speed
	if tick_timer.time_left > tick_timer.wait_time and tick_timer.is_stopped() == false:
		tick_timer.start()


func _update_snapshot(snapshot: Dictionary) -> void:
	if snapshot.is_empty():
		return
	current_snapshot = snapshot
	world_view.set_snapshot(snapshot)
	metrics_panel.set_snapshot(snapshot)
	mission_panel.set_snapshot(snapshot)
	inspector_panel.set_available_agents(snapshot.get("world", {}).get("agents", []))
	timeline_panel.add_events(snapshot.get("recent_events", []))
	timeline_panel.add_events(snapshot.get("presentation_events", []))
	var tick := int(snapshot.get("tick", 0))
	var scenario: Dictionary = snapshot.get("scenario", {})
	var horizon := int(scenario.get("steps", 0))
	tick_label.text = "T%03d / %03d  ·  %d elapsed ticks" % [tick, horizon, tick]
	var mission: Dictionary = snapshot.get("mission", {})
	if not mission.is_empty():
		current_scenario_name = str(mission.get("name", current_scenario_name))
		mission_name_label.text = current_scenario_name.to_upper()
	var network_status := str(snapshot.get("metrics", {}).get("communication_status", "unavailable"))
	match network_status:
		"partitioned":
			network_badge.text = "▲  SIMULATED PARTITION"
			network_badge.add_theme_color_override("font_color", AMBER)
		"peer_sharing_disabled":
			network_badge.text = "○  PEER SHARING OFF"
			network_badge.add_theme_color_override("font_color", MUTED)
		"available":
			network_badge.text = "●  PEER NETWORK AVAILABLE"
			network_badge.add_theme_color_override("font_color", GREEN)
		_:
			network_badge.text = "○  NETWORK STATUS N/A"
			network_badge.add_theme_color_override("font_color", MUTED)
	var stale_count := world_view.stale_track_count
	freshness_badge.text = ("!  %d STALE TRACKS" % stale_count) if stale_count > 0 else "✓  TRACKS FRESH"
	freshness_badge.add_theme_color_override("font_color", AMBER if stale_count > 0 else GREEN)
	if not selected_agent.is_empty():
		var inspected := bridge.request("inspect_agent", {"agent_id": selected_agent})
		if inspected.get("ok", false):
			inspector_panel.set_agent(inspected.result)
	if snapshot.get("status") == "paused":
		_set_status("PAUSED", AMBER, "Virtual time is stopped until the run resumes.")
	_set_controls()


func _on_agent_selected(agent_id: String) -> void:
	selected_agent = agent_id
	selected_entity_id = ""
	world_view.select_agent(agent_id)
	mission_panel.set_protection_selection("", "")
	if agent_id.is_empty():
		inspector_panel.set_agent({})
		_set_controls()
		return
	sidebar_tabs.current_tab = 1
	var response := bridge.request("inspect_agent", {"agent_id": agent_id})
	if _accept(response):
		inspector_panel.set_agent(response.result)
	_set_controls()


func _on_entity_selected(entity_id: String, owner_agent_id: String) -> void:
	if entity_id.is_empty():
		selected_entity_id = ""
		mission_panel.set_protection_selection("", "")
		_set_controls()
		return
	selected_entity_id = entity_id
	mission_panel.set_protection_selection(entity_id, owner_agent_id)
	sidebar_tabs.current_tab = 0
	_set_status("ENTITY TRACK SELECTED", CYAN, "%s is known through %s. Protection commands use only Python-validated entity IDs and current agent tracks." % [entity_id, owner_agent_id])
	_set_controls()


func _on_protection_requested(entity_id: String, radius: float, zone_type: String) -> void:
	if not run_active:
		return
	var response := bridge.request("apply_intervention", {
		"action": "designate_entity_protection",
		"parameters": {"entity_id": entity_id, "radius": radius, "zone_type": zone_type},
	})
	if not _accept(response):
		return
	var outcome: Dictionary = response.result
	if bool(outcome.get("accepted", false)):
		_set_status("MONITORING TASK CREATED", GREEN, "Python created or updated the perimeter and evidence-based mission task.")
	else:
		_set_status("PROTECTION COMMAND REJECTED", AMBER, str(outcome.get("outcome", "Python rejected the designation.")))
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)


func _on_protection_remove_requested(entity_id: String) -> void:
	if not run_active:
		return
	var response := bridge.request("apply_intervention", {
		"action": "remove_entity_protection",
		"parameters": {"entity_id": entity_id},
	})
	if not _accept(response):
		return
	var outcome: Dictionary = response.result
	if bool(outcome.get("accepted", false)):
		_set_status("PROTECTION REMOVED", AMBER, "Python cancelled any active monitoring task and recorded the intervention.")
	else:
		_set_status("REMOVE REJECTED", AMBER, str(outcome.get("outcome", "Python rejected the request.")))
	var snapshot_response := bridge.request("get_snapshot")
	if _accept(snapshot_response):
		_update_snapshot(snapshot_response.result)


func _on_matched_comparison_requested(dimension: String, seed_count: int) -> void:
	if run_active:
		_set_status("FINISH LIVE RUN FIRST", AMBER, "Matched comparisons run complete fixed-tick treatments without interrupting an active mission.")
		return
	var scenario_index := clampi(mission_picker.get_selected_id(), 0, SCENARIOS.size() - 1)
	var scenario_id: String = SCENARIOS[scenario_index]
	var scenario_name: String = SCENARIO_NAMES[scenario_index]
	var mode := "cooperative" if mode_picker.get_selected_id() == 0 else "independent"
	var policy := "fixed-priority" if policy_picker.get_selected_id() == 0 else "edf"
	var start_seed := int(seed_picker.value)
	results_panel.set_comparison_basis(scenario_name, mode, policy, start_seed, dimension)
	results_panel.set_comparison_running(true)
	_set_status("RUNNING MATCHED COMPARISON", CYAN, "Python is running both engine treatments at each of the same seeds.")
	var response := bridge.request("run_matched_comparison", {
		"scenario": scenario_id,
		"start_seed": start_seed,
		"seed_count": seed_count,
		"dimension": dimension,
		"mode": mode,
		"policy": policy,
	}, PythonBridge.COMPARISON_TIMEOUT_MS)
	results_panel.set_comparison_running(false)
	if not _accept(response):
		return
	var comparison: Dictionary = response.get("result", {})
	results_panel.add_comparison(comparison)
	sidebar_tabs.current_tab = 3
	_set_status("MATCHED COMPARISON SAVED", GREEN, "Each treatment run and the paired comparison were saved beneath runs/.")


func _on_saved_comparison_selected(comparison_id: String) -> void:
	var response := bridge.request("load_saved_comparison", {"comparison_id": comparison_id})
	if not _accept(response):
		return
	results_panel.set_comparison(response.get("result", {}).get("comparison", {}))


func _set_controls() -> void:
	if start_button == null:
		return
	start_button.disabled = run_active
	start_button.text = "Start another mission" if has_completed_results and not run_active else "Start mission"
	mission_picker.disabled = run_active
	mode_picker.disabled = run_active
	seed_picker.editable = not run_active
	policy_picker.disabled = false
	apply_policy_button.disabled = not run_active
	pause_button.disabled = not run_active or run_paused
	resume_button.disabled = not run_active or not run_paused
	reset_button.disabled = not has_session
	if manual_destination_toggle != null:
		var allowed := run_active and _selected_agent_can_receive_manual_destination()
		manual_destination_toggle.disabled = not allowed
		if not allowed and manual_destination_toggle.button_pressed:
			manual_destination_toggle.button_pressed = false
			world_view.set_manual_destination_enabled(false)
	if results_panel != null:
		results_panel.set_comparison_running(run_active)
	if mission_panel != null:
		mission_panel.set_run_active(run_active)


func _selected_agent_can_receive_manual_destination() -> bool:
	if selected_agent.is_empty():
		return false
	for agent_value in current_snapshot.get("world", {}).get("agents", []):
		if not agent_value is Dictionary or str(agent_value.get("id", "")) != selected_agent:
			continue
		var status := str(agent_value.get("uav_status", "available"))
		return agent_value.get("current_task_id") == null and agent_value.get("recovery_target") == null and status in ["available", "arrived"]
	return false


func _set_status(message: String, tint: Color, hint: String = "") -> void:
	if status_label == null:
		return
	status_label.text = "●  " + message
	status_label.tooltip_text = hint
	status_label.add_theme_color_override("font_color", tint)
	_apply_status_style(status_card, tint.darkened(0.72))


func _apply_status_style(panel: PanelContainer, color: Color) -> void:
	var style := StyleBoxFlat.new()
	style.bg_color = color
	style.border_color = color.lightened(0.25)
	style.set_border_width_all(1)
	style.set_corner_radius_all(5)
	style.content_margin_left = 8
	style.content_margin_right = 8
	style.content_margin_top = 5
	style.content_margin_bottom = 5
	panel.add_theme_stylebox_override("panel", style)


func _accept(response: Dictionary) -> bool:
	if bool(response.get("ok", false)):
		return true
	var error: Dictionary = response.get("error", {})
	var message := str(error.get("message", "Unknown backend error"))
	_set_status("BACKEND ERROR", RED, message)
	return false
