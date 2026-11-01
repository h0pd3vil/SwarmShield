extends PanelContainer
class_name EventTimeline

const TEXT := Color("#e3edf8")
const MUTED := Color("#91a5bb")
const IMPORTANT_TYPES := [
	"observation_created", "track_updated", "message_sent", "message_delivered", "message_dropped", "message_expired", "duplicate_delivered",
	"communication_partition_started", "communication_restored", "mission_task_assigned", "mission_task_navigating",
	"mission_task_started", "mission_task_completed", "mission_task_failed", "mission_task_expired",
	"mission_task_cancelled", "mission_task_reassigned", "task_created", "task_dropped",
	"task_started", "task_completed", "task_expired", "task_pending", "coordination_task_created",
	"coordination_task_dropped", "coordination_task_assigned", "coordination_task_started",
	"coordination_task_completed", "coordination_task_expired", "assignment_conflict",
	"uav_recovery_started", "uav_recovered", "player_intervention_accepted", "player_intervention_rejected",
	"restricted_zone_entered", "restricted_zone_exited", "restricted_zone_violation", "restricted_zone_entry_denied",
	"entity_protection_zone_created", "entity_protection_zone_updated", "entity_protection_zone_removed",
	"entity_protection_monitoring_missed",
]

var events_box: VBoxContainer
var empty_label: Label
var groups: Array[Dictionary] = []
var seen: Dictionary = {}
var group_lookup: Dictionary = {}


func _ready() -> void:
	_build()


func clear_run() -> void:
	groups.clear()
	seen.clear()
	group_lookup.clear()
	_render()


func add_events(incoming: Array) -> void:
	for value in incoming:
		if not value is Dictionary:
			continue
		var event: Dictionary = value
		var kind := str(event.get("event_type", ""))
		if kind not in IMPORTANT_TYPES:
			continue
		var event_key := _event_key(event)
		if seen.has(event_key):
			continue
		seen[event_key] = true
		var step := int(event.get("step", 0))
		var subtype := str(event.get("details", "")) if kind == "message_dropped" else ""
		var task_subject := str(event.get("task_id", "")) if kind.begins_with("mission_task_") else ""
		var key := "%d|%s|%s|%s" % [step, kind, task_subject, subtype]
		if group_lookup.has(key):
			var group: Dictionary = groups[int(group_lookup[key])]
			group["count"] = int(group.get("count", 1)) + 1
			if str(group.get("entity_id", "")).is_empty():
				group["entity_id"] = str(event.get("entity_id", ""))
		else:
			group_lookup[key] = groups.size()
			groups.append({"key": key, "step": step, "kind": kind, "count": 1, "event": event.duplicate(true), "entity_id": str(event.get("entity_id", ""))})
	while groups.size() > 240:
		groups.pop_front()
		_reindex_groups()
	_render()


func highlights(limit: int = 8) -> PackedStringArray:
	var output := PackedStringArray()
	var start := maxi(0, groups.size() - limit)
	for index in range(start, groups.size()):
		var group: Dictionary = groups[index]
		output.append("T%03d · %s · %s" % [int(group.get("step", 0)), _category(str(group.get("kind", ""))), _description(group)])
	return output


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
	content.add_theme_constant_override("separation", 8)
	add_child(content)
	var heading := Label.new()
	heading.text = "RECENT COORDINATION EVENTS"
	heading.add_theme_font_size_override("font_size", 12)
	heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(heading)
	var hint := Label.new()
	hint.text = "Engine events · grouped by logical tick · most recent first"
	hint.add_theme_font_size_override("font_size", 10)
	hint.add_theme_color_override("font_color", MUTED)
	content.add_child(hint)
	empty_label = Label.new()
	empty_label.text = "No events yet. Observations, message delivery, task changes, and interventions will appear here during the mission."
	empty_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	empty_label.add_theme_font_size_override("font_size", 11)
	empty_label.add_theme_color_override("font_color", MUTED)
	content.add_child(empty_label)
	events_box = VBoxContainer.new()
	events_box.add_theme_constant_override("separation", 5)
	content.add_child(events_box)


func _render() -> void:
	if events_box == null:
		return
	for child in events_box.get_children():
		events_box.remove_child(child)
		child.queue_free()
	empty_label.visible = groups.is_empty()
	var start := maxi(0, groups.size() - 12)
	for index in range(groups.size() - 1, start - 1, -1):
		events_box.add_child(_make_event_row(groups[index]))


func _make_event_row(group: Dictionary) -> Control:
	var event: Dictionary = group.get("event", {})
	var kind := str(group.get("kind", ""))
	var tint := _severity_color(kind)
	var row := PanelContainer.new()
	var row_style := StyleBoxFlat.new()
	row_style.bg_color = Color("#111b29")
	row_style.border_color = Color("#202f42")
	row_style.set_border_width_all(1)
	row_style.border_width_left = 3
	row_style.border_color = tint
	row_style.set_corner_radius_all(5)
	row_style.content_margin_left = 8
	row_style.content_margin_right = 8
	row_style.content_margin_top = 6
	row_style.content_margin_bottom = 6
	row.add_theme_stylebox_override("panel", row_style)
	var stack := VBoxContainer.new()
	stack.add_theme_constant_override("separation", 2)
	row.add_child(stack)
	var header := HBoxContainer.new()
	stack.add_child(header)
	var severity := Label.new()
	severity.text = _severity_icon(kind)
	severity.add_theme_color_override("font_color", tint)
	header.add_child(severity)
	var category := Label.new()
	category.text = _category(kind)
	category.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	category.add_theme_font_size_override("font_size", 9)
	category.add_theme_color_override("font_color", MUTED)
	header.add_child(category)
	var tick := Label.new()
	tick.text = "T%03d" % int(group.get("step", 0))
	tick.add_theme_font_size_override("font_size", 9)
	tick.add_theme_color_override("font_color", Color("#9db5ce"))
	header.add_child(tick)
	var message := Label.new()
	message.text = _description(group)
	message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	message.add_theme_font_size_override("font_size", 11)
	message.add_theme_color_override("font_color", TEXT)
	stack.add_child(message)
	var detail := _detail(event, group)
	if not detail.is_empty():
		var detail_label := Label.new()
		detail_label.text = detail
		detail_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		detail_label.add_theme_font_size_override("font_size", 9)
		detail_label.add_theme_color_override("font_color", MUTED)
		stack.add_child(detail_label)
	return row


func _description(group: Dictionary) -> String:
	var count := int(group.get("count", 1))
	var kind := str(group.get("kind", ""))
	var singular := ""
	match kind:
		"observation_created": singular = "local observation recorded"
		"track_updated": singular = "track applied to agent knowledge"
		"message_sent": singular = "report queued for peer sharing"
		"message_delivered": singular = "shared report delivered"
		"message_dropped": singular = "message lost · " + str(group.get("key", "")).get_slice("|", 2)
		"message_expired": singular = "message expired before application"
		"duplicate_delivered": singular = "duplicate report received"
		"communication_partition_started": singular = "simulated network partition began"
		"communication_restored": singular = "communication restored"
		"mission_task_assigned": singular = "mission task assigned to a UAV"
		"mission_task_navigating": singular = "UAV navigating to mission task"
		"mission_task_started": singular = "UAV started mission task work"
		"mission_task_completed": singular = "mission task completed from engine evidence"
		"mission_task_failed": singular = "mission task failed"
		"mission_task_expired": singular = "mission task missed its deadline"
		"mission_task_cancelled": singular = "mission task cancelled"
		"mission_task_reassigned": singular = "mission task reassignment began"
		"uav_recovery_started": singular = "UAV returning to a recovery area"
		"uav_recovered": singular = "UAV reached a recovery area"
		"task_created": singular = "decision task queued"
		"task_dropped": singular = "decision task dropped · queue full"
		"task_started": singular = "decision task started"
		"task_completed": singular = "decision task completed"
		"task_expired": singular = "decision task missed its deadline"
		"task_pending": singular = "decision task remains pending at horizon"
		"coordination_task_created": singular = "abstract review task created"
		"coordination_task_dropped": singular = "abstract review task dropped · queue full"
		"coordination_task_assigned": singular = "review task assigned"
		"coordination_task_started": singular = "review work started"
		"coordination_task_completed": singular = "review task completed"
		"coordination_task_expired": singular = "review task missed its deadline"
		"assignment_conflict": singular = "conflicting proposals reconciled"
		"player_intervention_accepted": singular = "scheduler policy intervention accepted"
		"player_intervention_rejected": singular = "scheduler policy intervention rejected"
		"restricted_zone_entered": singular = "UAV entered a configured restricted zone"
		"restricted_zone_exited": singular = "UAV exited a configured restricted zone"
		"restricted_zone_violation": singular = "unauthorized restricted-zone entry warned"
		"restricted_zone_entry_denied": singular = "restricted-zone entry blocked by navigation policy"
		"entity_protection_zone_created": singular = "entity protection perimeter created"
		"entity_protection_zone_updated": singular = "entity protection perimeter updated"
		"entity_protection_zone_removed": singular = "entity protection perimeter removed"
		"entity_protection_monitoring_missed": singular = "entity monitoring task missed"
	if count > 1:
		return "%d × %s" % [count, singular]
	return singular


func _detail(event: Dictionary, group: Dictionary) -> String:
	var count := int(group.get("count", 1))
	if count > 1:
		return "Grouped backend events from the same logical tick."
	var parts := PackedStringArray()
	var sender := str(event.get("sender_id", ""))
	var recipient := str(event.get("recipient_id", ""))
	var entity := str(event.get("entity_id", ""))
	var resource := str(event.get("resource_id", ""))
	if not sender.is_empty() and not recipient.is_empty():
		parts.append(sender + " → " + recipient)
	if str(event.get("event_type", "")) == "mission_task_assigned" and not resource.is_empty():
		parts.append("assigned to " + resource)
	elif str(event.get("event_type", "")) in ["mission_task_navigating", "mission_task_started", "mission_task_completed", "mission_task_failed", "mission_task_expired", "mission_task_cancelled"] and not resource.is_empty():
		parts.append(resource)
	if not entity.is_empty():
		parts.append(entity)
	if str(event.get("deadline", "")).is_valid_int():
		parts.append("deadline T" + str(event.get("deadline", "")))
	var details := str(event.get("details", ""))
	if str(event.get("event_type", "")).begins_with("player_intervention_"):
		var parsed: Variant = JSON.parse_string(details)
		if parsed is Dictionary:
			parts.append(str(parsed.get("outcome", "" )).replace("_", " "))
	elif str(event.get("event_type", "")) == "track_updated":
		var parsed_track: Variant = JSON.parse_string(details)
		if parsed_track is Dictionary:
			parts.append(str(parsed_track.get("provenance", "unknown")) + " report · age " + str(parsed_track.get("age_steps", "?")) + " ticks")
	elif str(event.get("event_type", "")) == "mission_task_assigned":
		var parsed_assignment: Variant = JSON.parse_string(details)
		if parsed_assignment is Dictionary:
			parts.append("ETA T" + str(parsed_assignment.get("estimated_completion_step", "?")))
	elif str(event.get("event_type", "")).begins_with("mission_task_"):
		var parsed_task: Variant = JSON.parse_string(details)
		if parsed_task is Dictionary:
			var reason := str(parsed_task.get("reason", ""))
			if not reason.is_empty():
				parts.append(reason.replace("_", " "))
			var evidence: Variant = parsed_task.get("evidence", {})
			if evidence is Dictionary and evidence.has("coverage_fraction"):
				parts.append("coverage %.0f%%" % (float(evidence["coverage_fraction"]) * 100.0))
	elif str(event.get("event_type", "")) in ["uav_recovery_started", "uav_recovered"]:
		var parsed_recovery: Variant = JSON.parse_string(details)
		if parsed_recovery is Dictionary and parsed_recovery.has("destination"):
			var point: Variant = parsed_recovery["destination"]
			if point is Array and point.size() == 2:
				parts.append("recovery zone %.1f, %.1f" % [float(point[0]), float(point[1])])
	elif str(event.get("event_type", "")).begins_with("restricted_zone_") or str(event.get("event_type", "")).begins_with("entity_protection_zone_") or str(event.get("event_type", "")) == "entity_protection_monitoring_missed":
		var parsed_zone: Variant = JSON.parse_string(details)
		if parsed_zone is Dictionary:
			var zone_id := str(parsed_zone.get("zone_id", parsed_zone.get("entity_id", entity)))
			if not zone_id.is_empty():
				parts.append(zone_id)
			var policy := str(parsed_zone.get("policy", ""))
			if not policy.is_empty():
				parts.append(policy.replace("_", " "))
			if parsed_zone.has("authorized"):
				parts.append("authorized" if bool(parsed_zone["authorized"]) else "unauthorized")
			if parsed_zone.has("radius"):
				parts.append("radius %.1f" % float(parsed_zone["radius"]))
			if parsed_zone.has("task_id"):
				parts.append("task " + str(parsed_zone["task_id"]))
	elif not details.is_empty() and details not in ["on_time", "abstract_outcome", "abstract_review", "queued_for_reconciliation"]:
		parts.append(details.replace("_", " "))
	return " · ".join(parts)


func _category(kind: String) -> String:
	if kind.begins_with("communication_") or kind.begins_with("message_") or kind == "duplicate_delivered":
		return "NETWORK"
	if kind.begins_with("player_intervention_"):
		return "PLAYER CONTROL"
	if kind.begins_with("restricted_zone_"):
		return "AIRSPACE"
	if kind.begins_with("entity_protection_"):
		return "PROTECTION"
	if kind.begins_with("mission_task_"):
		return "MISSION TASK"
	if kind.begins_with("uav_recover"):
		return "RECOVERY"
	if kind.begins_with("coordination_") or kind in ["assignment_conflict"]:
		return "TEAM TASKING"
	if kind.begins_with("task_"):
		return "PROCESSING"
	return "OBSERVATION"


func _severity_color(kind: String) -> Color:
	if kind in ["message_dropped", "message_expired", "task_dropped", "task_expired", "coordination_task_dropped", "coordination_task_expired", "mission_task_failed", "mission_task_expired", "assignment_conflict", "player_intervention_rejected", "restricted_zone_violation", "restricted_zone_entry_denied", "entity_protection_monitoring_missed"]:
		return Color("#ff9c83")
	if kind in ["communication_partition_started", "task_pending", "mission_task_navigating", "mission_task_started", "mission_task_reassigned", "mission_task_cancelled", "uav_recovery_started", "restricted_zone_entered", "restricted_zone_exited"]:
		return Color("#ffd166")
	if kind in ["track_updated", "communication_restored", "mission_task_assigned", "mission_task_completed", "uav_recovered", "task_completed", "coordination_task_completed", "player_intervention_accepted", "entity_protection_zone_created", "entity_protection_zone_updated", "entity_protection_zone_removed"]:
		return Color("#8fe388")
	return Color("#55c2ff")


func _severity_icon(kind: String) -> String:
	if _severity_color(kind) == Color("#ff9c83"):
		return "!"
	if _severity_color(kind) == Color("#8fe388"):
		return "✓"
	if _severity_color(kind) == Color("#ffd166"):
		return "▲"
	return "◆"


func _event_key(event: Dictionary) -> String:
	var fields := ["step", "event_type", "message_id", "task_id", "entity_id", "sender_id", "recipient_id", "resource_id", "details", "copy_index"]
	var values := PackedStringArray()
	for field in fields:
		values.append(str(event.get(field, "")))
	return "|".join(values)


func _reindex_groups() -> void:
	group_lookup.clear()
	for index in range(groups.size()):
		group_lookup[str(groups[index].get("key", ""))] = index
