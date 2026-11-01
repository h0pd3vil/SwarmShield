extends PanelContainer
class_name TeamMetricsPanel

const CARD := Color("#111b29")
const TEXT := Color("#e3edf8")
const MUTED := Color("#8fa4bb")
const CYAN := Color("#55c2ff")
const GREEN := Color("#8fe388")
const AMBER := Color("#ffd166")
const RED := Color("#ff9c83")

var grid: GridContainer
var metric_values: Array[Label] = []
var metric_notes: Array[Label] = []
var metric_bars: Array[ProgressBar] = []


func _ready() -> void:
	_build()


func _notification(what: int) -> void:
	if what == NOTIFICATION_RESIZED and grid != null:
		grid.columns = 2 if size.x < 720.0 else 3


func _build() -> void:
	var panel_style := StyleBoxFlat.new()
	panel_style.bg_color = Color("#0d1622")
	panel_style.border_color = Color("#26374b")
	panel_style.set_border_width_all(1)
	panel_style.set_corner_radius_all(8)
	panel_style.content_margin_left = 12
	panel_style.content_margin_right = 12
	panel_style.content_margin_top = 9
	panel_style.content_margin_bottom = 10
	add_theme_stylebox_override("panel", panel_style)

	var content := VBoxContainer.new()
	content.add_theme_constant_override("separation", 8)
	add_child(content)
	var heading := Label.new()
	heading.text = "TEAM STATUS"
	heading.add_theme_font_size_override("font_size", 12)
	heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(heading)

	grid = GridContainer.new()
	grid.columns = 3
	grid.add_theme_constant_override("h_separation", 8)
	grid.add_theme_constant_override("v_separation", 8)
	content.add_child(grid)
	for _index in range(6):
		var card := PanelContainer.new()
		card.custom_minimum_size.y = 75
		card.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var card_style := StyleBoxFlat.new()
		card_style.bg_color = CARD
		card_style.border_color = Color("#1e2c3d")
		card_style.set_border_width_all(1)
		card_style.set_corner_radius_all(6)
		card_style.content_margin_left = 10
		card_style.content_margin_right = 10
		card_style.content_margin_top = 7
		card_style.content_margin_bottom = 6
		card.add_theme_stylebox_override("panel", card_style)
		var stack := VBoxContainer.new()
		stack.add_theme_constant_override("separation", 2)
		card.add_child(stack)
		var caption := Label.new()
		caption.add_theme_font_size_override("font_size", 10)
		caption.add_theme_color_override("font_color", MUTED)
		stack.add_child(caption)
		var value := Label.new()
		value.add_theme_font_size_override("font_size", 17)
		value.add_theme_color_override("font_color", TEXT)
		stack.add_child(value)
		var note := Label.new()
		note.add_theme_font_size_override("font_size", 10)
		note.add_theme_color_override("font_color", MUTED)
		note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		stack.add_child(note)
		var bar := ProgressBar.new()
		bar.custom_minimum_size.y = 4
		bar.max_value = 1.0
		bar.show_percentage = false
		bar.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		var background := StyleBoxFlat.new()
		background.bg_color = Color("#202c3b")
		background.set_corner_radius_all(2)
		bar.add_theme_stylebox_override("background", background)
		var fill := StyleBoxFlat.new()
		fill.bg_color = CYAN
		fill.set_corner_radius_all(2)
		bar.add_theme_stylebox_override("fill", fill)
		stack.add_child(bar)
		grid.add_child(card)
		metric_values.append(value)
		metric_notes.append(note)
		metric_bars.append(bar)
		caption.set_meta("metric_index", _index)
		match _index:
			0: caption.text = "FRESH TEAM AWARENESS"
			1: caption.text = "INFORMATION FRESHNESS"
			2: caption.text = "COMMUNICATION"
			3: caption.text = "PROCESSING QUEUE"
			4: caption.text = "DEADLINE PERFORMANCE"
			5: caption.text = "ABSTRACT REVIEW WORK"
	_set_empty()


func set_snapshot(snapshot: Dictionary) -> void:
	var metrics: Dictionary = snapshot.get("metrics", {})
	var scenario: Dictionary = snapshot.get("scenario", {})
	var world: Dictionary = snapshot.get("world", {})
	var coverage := _number(metrics.get("any_agent_awareness_coverage"))
	var mean_coverage := _number(metrics.get("mean_agent_track_coverage"))
	_set_metric(0, _percent_or_na(coverage), "Mean local view %s · target comes from mission" % _percent_or_na(mean_coverage), coverage)

	var fresh := 0
	var stale := 0
	for track in world.get("tracks", []):
		if int(snapshot.get("tick", 0)) - int(track.get("observed_at", 0)) <= int(scenario.get("max_track_age_steps", 10)):
			fresh += 1
		else:
			stale += 1
	var age: Variant = metrics.get("mean_fresh_track_age_steps")
	_set_metric(1, "n/a" if age == null else "%.1f ticks" % float(age), "%d fresh · %d stale agent tracks" % [fresh, stale], null)

	var sent := int(metrics.get("messages_sent", 0))
	var delivered := int(metrics.get("messages_delivered", 0))
	var dropped := int(metrics.get("messages_dropped", 0))
	var pending := int(metrics.get("pending_messages", 0))
	var delivery := float(delivered) / float(sent) if sent > 0 else -1.0
	_set_metric(2, _percent_or_na(delivery), "%d delivered · %d lost · %d pending" % [delivered, dropped, pending], delivery)

	var backlog := int(metrics.get("queue_backlog_tasks", 0))
	var capacity := maxi(1, int(metrics.get("queue_capacity", scenario.get("queue_capacity", 1))))
	var created := int(metrics.get("decision_tasks_created", 0))
	var completed := int(metrics.get("decision_tasks_completed", 0))
	var queue_ratio := float(backlog) / float(capacity)
	var queue_tint := RED if queue_ratio >= 0.85 else (AMBER if queue_ratio >= 0.5 else CYAN)
	var queue_state := "Critical queue pressure" if queue_ratio >= 0.85 else ("Queue pressure rising" if queue_ratio >= 0.5 else "Queue has capacity")
	_set_metric(3, "%d / %d" % [backlog, capacity], "%s · %d completed of %d tasks" % [queue_state, completed, created], queue_ratio, queue_tint)

	var misses: int = int(metrics.get("deadline_misses", 0))
	var miss_rate: Variant = metrics.get("deadline_miss_rate")
	var eligible: int = int(metrics.get("eligible_tasks", 0))
	var success_ratio := 1.0 - float(miss_rate) if miss_rate != null else -1.0
	var urgent := int(metrics.get("urgent_deadline_tasks", 0))
	var next_slack: Variant = metrics.get("next_deadline_slack_steps")
	var urgency_note := "%d active tasks due within 2 ticks" % urgent if urgent > 0 else "No active tasks due within 2 ticks"
	if next_slack != null:
		urgency_note += " · nearest in %d ticks" % int(next_slack)
	var deadline_tint := RED if misses > 0 else (AMBER if urgent > 0 else GREEN)
	_set_metric(4, "%d misses" % misses, "%s · %s of %d eligible tasks missed" % [urgency_note, _percent_or_na(miss_rate), eligible], success_ratio, deadline_tint)

	var coordination: Dictionary = metrics.get("coordination", {})
	var review_created: int = int(coordination.get("coordination_tasks_created", 0))
	var review_completed: int = int(coordination.get("coordination_tasks_completed", 0))
	var review_pending: int = int(coordination.get("coordination_tasks_pending", 0))
	var review_rate := float(review_completed) / float(review_created) if review_created > 0 else -1.0
	_set_metric(5, "%d / %d complete" % [review_completed, review_created], "%d pending · %d dropped · %d expired" % [review_pending, int(coordination.get("coordination_tasks_dropped", 0)), int(coordination.get("coordination_tasks_expired", 0))], review_rate)


func _set_empty() -> void:
	for index in range(6):
		metric_values[index].text = "—"
		metric_notes[index].text = "Waiting for engine snapshot"
		metric_bars[index].value = 0.0


func _set_metric(index: int, value: String, note: String, progress: Variant, tint: Color = CYAN) -> void:
	metric_values[index].text = value
	metric_notes[index].text = note
	metric_bars[index].visible = progress != null and float(progress) >= 0.0
	if metric_bars[index].visible:
		metric_bars[index].value = clampf(float(progress), 0.0, 1.0)
		var fill := StyleBoxFlat.new()
		fill.bg_color = tint
		fill.set_corner_radius_all(2)
		metric_bars[index].add_theme_stylebox_override("fill", fill)


func _number(value: Variant) -> float:
	return -1.0 if value == null else float(value)


func _percent_or_na(value: Variant) -> String:
	return "n/a" if value == null or float(value) < 0.0 else "%.0f%%" % (float(value) * 100.0)
