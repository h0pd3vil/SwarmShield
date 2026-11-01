extends PanelContainer
class_name AgentInspector

signal agent_selected(agent_id: String)

const TEXT := Color("#e3edf8")
const MUTED := Color("#91a5bb")
const AMBER := Color("#ffd166")
const RED := Color("#ff9c83")

var agent_picker: OptionButton
var title_label: Label
var state_label: Label
var summary_label: Label
var communication_label: Label
var work_label: Label
var tracks_label: RichTextLabel
var suppress_picker_signal := false


func _ready() -> void:
	_build()


func set_agent(agent: Dictionary) -> void:
	if agent.is_empty():
		_set_empty()
		return
	var agent_id := str(agent.get("agent_id", "Unknown agent"))
	_select_agent_option(agent_id)
	title_label.text = agent_id
	var state: Variant = agent.get("state")
	state_label.text = "UNAVAILABLE" if state == null else str(state).replace("_", " ").to_upper()
	var position: Dictionary = agent.get("position", {})
	var motion: Dictionary = agent.get("motion", {})
	var tracks: Array = agent.get("locally_known_tracks", [])
	var fresh_count := 0
	var stale_count := 0
	for track in tracks:
		if bool(track.get("fresh", false)):
			fresh_count += 1
		else:
			stale_count += 1
	var battery := float(motion.get("battery_remaining", 0.0))
	var battery_capacity := float(motion.get("battery_capacity", 0.0))
	var battery_text := "n/a" if battery_capacity <= 0.0 else "%0.0f%%" % (100.0 * battery / battery_capacity)
	summary_label.text = "Position  %s\nSpeed  %0.2f · travelled %0.1f units\nBattery  %s\nLocal knowledge  %d tracks · %d fresh · %d stale" % [
		"(%0.1f, %0.1f)" % [float(position.get("x", 0.0)), float(position.get("y", 0.0))],
		float(motion.get("speed", 0.0)), float(motion.get("distance_travelled", 0.0)), battery_text,
		tracks.size(), fresh_count, stale_count,
	]

	var communication: Dictionary = agent.get("communication", {})
	var status := str(communication.get("status", "unavailable")).replace("_", " ")
	communication_label.text = "Peer network  %s\nInbound messages  %d pending\nLast send / receive  %s / %s" % [
		status.capitalize(),
		int(communication.get("pending_inbound_messages", 0)),
		_step_or_na(communication.get("last_sent_step")),
		_step_or_na(communication.get("last_received_step")),
	]
	var pending_messages: Array = communication.get("pending_messages", [])
	if not pending_messages.is_empty():
		var pending_ids: Array[String] = []
		for message in pending_messages.slice(0, 3):
			pending_ids.append("%s · due T%s" % [str(message.get("entity_id", "report")), str(message.get("delivery_step", "?"))])
		communication_label.text += "\n" + ", ".join(pending_ids)
	var work: Array = agent.get("pending_work", [])
	var mission_work: Array = agent.get("mission_tasks", [])
	if mission_work.is_empty():
		work_label.text = "Mission task  None currently assigned"
	else:
		work_label.text = "Mission task assignments"
	var urgent_work := false
	var overdue_work := false
	for task in mission_work:
		var slack := int(task.get("deadline_slack_steps", 999999))
		if slack <= 2:
			urgent_work = true
		if slack <= 0:
			overdue_work = true
		work_label.text += "\n%s  %s · %s · %s" % [
			"⚠" if slack <= 2 and str(task.get("status", "")) not in ["completed", "cancelled"] else "•",
			str(task.get("task_id", "task")), str(task.get("status", "unassigned")).replace("_", " "),
			"due T%s" % str(task.get("deadline_step", "n/a")),
		]
		var reason := str(task.get("failure_reason", ""))
		if reason.is_empty() and str(task.get("status", "")) == "unassigned":
			reason = str(task.get("assignment_reason", ""))
		if not reason.is_empty():
			work_label.text += "\n  " + reason.replace("_", " ")
	work_label.text += "\nDecision work  %d pending · global queue %d" % [
		work.size(), int(agent.get("global_decision_queue_backlog_tasks", 0)),
	]
	work_label.add_theme_color_override("font_color", RED if overdue_work else (AMBER if urgent_work else TEXT))

	var lines := PackedStringArray()
	if tracks.is_empty():
		lines.append("No local tracks observed yet.")
	else:
		for track in tracks:
			var fresh := bool(track.get("fresh", false))
			var provenance := "local" if str(track.get("source_agent_id", agent_id)) == agent_id else "shared from %s" % str(track.get("source_agent_id", "another agent"))
			lines.append("%s  %s  ·  %d ticks old  ·  %s  ·  confidence %s" % [
				"●" if fresh else "○",
				str(track.get("entity_id", "entity")),
				int(track.get("age_steps", 0)),
				provenance,
				"n/a" if track.get("confidence") == null else "%.0f%%" % (float(track.get("confidence", 0.0)) * 100.0),
			])
	tracks_label.text = "\n".join(lines)


func set_available_agents(agents: Array) -> void:
	var selected_id := ""
	if agent_picker.get_selected_id() > 0:
		selected_id = str(agent_picker.get_item_text(agent_picker.get_selected()))
	suppress_picker_signal = true
	agent_picker.clear()
	agent_picker.add_item("Choose observer", 0)
	for index in range(agents.size()):
		var agent: Dictionary = agents[index]
		agent_picker.add_item(str(agent.get("id", "Agent %d" % (index + 1))), index + 1)
	agent_picker.select(0)
	if not selected_id.is_empty():
		_select_agent_option(selected_id)
	suppress_picker_signal = false


func _select_agent_option(agent_id: String) -> void:
	if agent_picker == null:
		return
	for index in range(agent_picker.item_count):
		if index > 0 and str(agent_picker.get_item_text(index)) == agent_id:
			suppress_picker_signal = true
			agent_picker.select(index)
			suppress_picker_signal = false
			return


func _build() -> void:
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
	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 7)
	add_child(content)
	var selection_row := HBoxContainer.new()
	selection_row.add_theme_constant_override("separation", 8)
	content.add_child(selection_row)
	var choose_label := Label.new()
	choose_label.text = "INSPECT UAV"
	choose_label.add_theme_font_size_override("font_size", 9)
	choose_label.add_theme_color_override("font_color", Color("#8fb2d8"))
	selection_row.add_child(choose_label)
	agent_picker = OptionButton.new()
	agent_picker.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	agent_picker.add_item("Choose observer", 0)
	agent_picker.item_selected.connect(_on_agent_option_selected)
	agent_picker.tooltip_text = "Choose a UAV or select its quadcopter sprite on the map."
	selection_row.add_child(agent_picker)
	var header := HBoxContainer.new()
	title_label = Label.new()
	title_label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title_label.add_theme_font_size_override("font_size", 18)
	title_label.add_theme_color_override("font_color", TEXT)
	header.add_child(title_label)
	state_label = Label.new()
	state_label.add_theme_font_size_override("font_size", 9)
	state_label.add_theme_color_override("font_color", MUTED)
	header.add_child(state_label)
	content.add_child(header)
	summary_label = _add_section(content, "AGENT OVERVIEW")
	communication_label = _add_section(content, "COMMUNICATION")
	work_label = _add_section(content, "TASKING AND DEADLINES")
	var tracks_heading := Label.new()
	tracks_heading.text = "LOCAL KNOWLEDGE"
	_style_section(tracks_heading)
	content.add_child(tracks_heading)
	tracks_label = RichTextLabel.new()
	tracks_label.fit_content = true
	tracks_label.scroll_active = false
	tracks_label.bbcode_enabled = false
	tracks_label.custom_minimum_size.y = 56
	tracks_label.add_theme_font_size_override("normal_font_size", 11)
	tracks_label.add_theme_color_override("default_color", TEXT)
	content.add_child(tracks_label)
	_set_empty()


func _on_agent_option_selected(index: int) -> void:
	if suppress_picker_signal or index <= 0:
		return
	var agent_id := str(agent_picker.get_item_text(index))
	if not agent_id.is_empty():
		agent_selected.emit(agent_id)


func _add_section(parent: VBoxContainer, heading: String) -> Label:
	var title := Label.new()
	title.text = heading
	_style_section(title)
	parent.add_child(title)
	var body := Label.new()
	body.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	body.add_theme_font_size_override("font_size", 11)
	body.add_theme_color_override("font_color", TEXT)
	parent.add_child(body)
	return body


func _style_section(label: Label) -> void:
	label.add_theme_font_size_override("font_size", 10)
	label.add_theme_color_override("font_color", Color("#8fb2d8"))


func _set_empty() -> void:
	if agent_picker != null:
		suppress_picker_signal = true
		agent_picker.select(0)
		suppress_picker_signal = false
	title_label.text = "Select an agent"
	state_label.text = "CLICK A DIAMOND"
	summary_label.text = "Select a quadcopter to inspect its engine state, route, task assignment, communication, and locally known tracks."
	communication_label.text = "Communication status will appear here."
	work_label.text = "Mission task assignments and deadlines appear here after a run starts."
	tracks_label.text = "No agent selected."


func _step_or_na(value: Variant) -> String:
	return "n/a" if value == null else "T" + str(value)


func _deadline_text(task: Dictionary) -> String:
	var deadline := str(task.get("deadline", "n/a"))
	var slack: Variant = task.get("deadline_slack_steps")
	if slack == null or int(slack) > 2:
		return "due T" + deadline
	if int(slack) <= 0:
		return "due T" + deadline + " · due now"
	return "due T" + deadline + " · %d ticks left" % int(slack)
