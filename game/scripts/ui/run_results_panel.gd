extends PanelContainer
class_name RunResultsPanel

signal matched_comparison_requested(dimension: String, seed_count: int)
signal saved_comparison_selected(comparison_id: String)

const TEXT := Color("#e3edf8")
const MUTED := Color("#91a5bb")
const GREEN := Color("#8fe388")
const RED := Color("#ff9c83")
const AMBER := Color("#ffd166")

var result_picker: OptionButton
var view_picker: OptionButton
var comparison_picker: OptionButton
var comparison_dimension_picker: OptionButton
var seed_count_picker: SpinBox
var comparison_button: Button
var comparison_controls: HFlowContainer
var comparison_hint: Label
var content: VBoxContainer
var history: Array[Dictionary] = []
var saved_comparisons: Array[Dictionary] = []
var loaded_comparisons: Dictionary = {}
var showing_comparison := false


func _ready() -> void:
	_build()
	_render_empty()


func add_result(summary: Dictionary, final_snapshot: Dictionary, artifact_path: String, scenario_name: String, seed: int, event_highlights: PackedStringArray) -> void:
	history.append({
		"summary": summary.duplicate(true),
		"snapshot": final_snapshot.duplicate(true),
		"artifact_path": artifact_path,
		"scenario_name": scenario_name,
		"seed": seed,
		"event_highlights": event_highlights.duplicate(),
	})
	result_picker.add_item("%02d · %s · seed %d" % [history.size(), scenario_name, seed], history.size() - 1)
	result_picker.select(history.size() - 1)
	if not showing_comparison:
		_render(history.size() - 1)
	_update_view_controls()


func set_saved_comparisons(comparisons: Array) -> void:
	saved_comparisons.clear()
	loaded_comparisons.clear()
	comparison_picker.clear()
	for value in comparisons:
		if not value is Dictionary:
			continue
		var record: Dictionary = value
		saved_comparisons.append(record.duplicate(true))
		var item_index := comparison_picker.item_count
		comparison_picker.add_item(_comparison_title(record))
		comparison_picker.set_item_metadata(item_index, str(record.get("comparison_id", "")))
	if not saved_comparisons.is_empty():
		comparison_picker.select(0)
		_on_comparison_selected(0)
	else:
		_render_comparison_empty()
	_update_view_controls()


func add_comparison(comparison: Dictionary) -> void:
	var comparison_id := str(comparison.get("comparison_id", ""))
	if comparison_id.is_empty():
		return
	loaded_comparisons[comparison_id] = comparison.duplicate(true)
	var found := false
	for existing in saved_comparisons:
		if str(existing.get("comparison_id", "")) == comparison_id:
			found = true
			break
	if not found:
		saved_comparisons.push_front({
			"comparison_id": comparison_id,
			"scenario_name": comparison.get("scenario_name", "Mission"),
			"dimension": comparison.get("dimension", "scheduler"),
			"seed_count": comparison.get("seed_count", 0),
			"start_seed": comparison.get("start_seed", 0),
			"created_at_utc": comparison.get("created_at_utc", ""),
		})
	_rebuild_comparison_picker(comparison_id)
	showing_comparison = true
	view_picker.select(1)
	_update_view_controls()
	_render_comparison(comparison)


func set_comparison(comparison: Dictionary) -> void:
	var comparison_id := str(comparison.get("comparison_id", ""))
	if comparison_id.is_empty():
		return
	loaded_comparisons[comparison_id] = comparison.duplicate(true)
	if showing_comparison and comparison_picker.get_item_count() > 0:
		_render_comparison(comparison)


func set_comparison_running(running: bool) -> void:
	comparison_button.disabled = running
	comparison_button.text = "Running matched runs…" if running else "Run matched comparison"


func set_comparison_basis(scenario_name: String, mode: String, policy: String, start_seed: int, dimension: String) -> void:
	if dimension == "scheduler":
		comparison_hint.text = "Uses %s · holds %s mode constant · first seed %d. Both schedulers receive every same seed." % [scenario_name, "cooperative" if mode == "cooperative" else "independent", start_seed]
	else:
		comparison_hint.text = "Uses %s · holds %s scheduler constant · first seed %d. Both sharing modes receive every same seed." % [scenario_name, "fixed priority" if policy == "fixed-priority" else "EDF", start_seed]


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
	var outer := VBoxContainer.new()
	outer.add_theme_constant_override("separation", 8)
	add_child(outer)
	var header := HBoxContainer.new()
	outer.add_child(header)
	var title := Label.new()
	title.text = "RESULTS"
	title.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	title.add_theme_font_size_override("font_size", 12)
	title.add_theme_color_override("font_color", Color("#8fb2d8"))
	header.add_child(title)
	view_picker = OptionButton.new()
	view_picker.add_item("Runs", 0)
	view_picker.add_item("Comparisons", 1)
	view_picker.select(0)
	view_picker.fit_to_longest_item = false
	view_picker.custom_minimum_size.x = 105
	view_picker.item_selected.connect(_on_view_selected)
	view_picker.tooltip_text = "Switch between individual mission results and saved matched-seed experiments."
	header.add_child(view_picker)
	result_picker = OptionButton.new()
	result_picker.custom_minimum_size.x = 175
	result_picker.item_selected.connect(_on_result_selected)
	header.add_child(result_picker)
	comparison_picker = OptionButton.new()
	comparison_picker.fit_to_longest_item = false
	comparison_picker.custom_minimum_size.x = 155
	comparison_picker.item_selected.connect(_on_comparison_selected)
	header.add_child(comparison_picker)
	comparison_controls = HFlowContainer.new()
	comparison_controls.add_theme_constant_override("h_separation", 6)
	comparison_controls.add_theme_constant_override("v_separation", 4)
	outer.add_child(comparison_controls)
	comparison_dimension_picker = OptionButton.new()
	comparison_dimension_picker.add_item("Scheduler · FP / EDF", 0)
	comparison_dimension_picker.set_item_metadata(0, "scheduler")
	comparison_dimension_picker.add_item("Sharing · solo / shared", 1)
	comparison_dimension_picker.set_item_metadata(1, "sharing")
	comparison_dimension_picker.select(0)
	comparison_dimension_picker.custom_minimum_size.x = 205
	comparison_dimension_picker.tooltip_text = "Compare schedulers while holding team mode constant, or compare sharing while holding the scheduler constant."
	comparison_controls.add_child(comparison_dimension_picker)
	seed_count_picker = SpinBox.new()
	seed_count_picker.min_value = 2
	seed_count_picker.max_value = 30
	seed_count_picker.step = 1
	seed_count_picker.value = 5
	seed_count_picker.suffix = " seeds"
	seed_count_picker.custom_minimum_size.x = 95
	comparison_controls.add_child(seed_count_picker)
	comparison_button = Button.new()
	comparison_button.text = "Run matched comparison"
	comparison_button.custom_minimum_size.y = 30
	comparison_button.pressed.connect(_on_comparison_requested)
	comparison_button.tooltip_text = "Runs both treatments at every seed and saves each treatment as a normal run artifact."
	comparison_controls.add_child(comparison_button)
	comparison_hint = Label.new()
	comparison_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	comparison_hint.add_theme_font_size_override("font_size", 9)
	comparison_hint.add_theme_color_override("font_color", MUTED)
	outer.add_child(comparison_hint)
	content = VBoxContainer.new()
	content.add_theme_constant_override("separation", 7)
	outer.add_child(content)
	_update_view_controls()


func _render_empty() -> void:
	_clear_content()
	var hint := Label.new()
	hint.text = "Complete a mission to review its objectives, score, raw engine metrics, event highlights, and saved artifacts. New runs will not erase saved results."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_font_size_override("font_size", 11)
	hint.add_theme_color_override("font_color", MUTED)
	content.add_child(hint)
	if not showing_comparison:
		result_picker.visible = false


func _render(index: int) -> void:
	_clear_content()
	if history.is_empty() or index < 0 or index >= history.size():
		_render_empty()
		return
	result_picker.visible = history.size() > 1
	var record: Dictionary = history[index]
	var summary: Dictionary = record.get("summary", {})
	var metrics: Dictionary = summary.get("metrics", {})
	var game_result: Dictionary = summary.get("game_result", {})
	var mission: Dictionary = game_result.get("mission", {})
	var score: Dictionary = game_result.get("score", {})
	var status := str(mission.get("status", "incomplete"))
	var outcome := Label.new()
	var outcome_icon := "✓" if status == "success" else ("!" if status == "failure" else "○")
	outcome.text = "%s  %s" % [outcome_icon, status.replace("_", " ").to_upper()]
	outcome.add_theme_font_size_override("font_size", 18)
	outcome.add_theme_color_override("font_color", GREEN if status == "success" else (RED if status == "failure" else Color("#ffd166")))
	content.add_child(outcome)
	var run_info := Label.new()
	run_info.text = "%s · seed %s · %d logical ticks" % [str(record.get("scenario_name", "Mission")), str(record.get("seed", "n/a")), int(summary.get("steps", 0))]
	run_info.add_theme_font_size_override("font_size", 10)
	run_info.add_theme_color_override("font_color", MUTED)
	content.add_child(run_info)

	_add_section_heading("PROVISIONAL GAME SCORE")
	var total_score: Variant = score.get("total_score")
	_add_value("Total score", "n/a" if total_score == null else "%.2f / 100" % float(total_score), GREEN)
	var components: Dictionary = score.get("components", {})
	for dimension in ["awareness", "timeliness", "reliability", "efficiency"]:
		var component: Dictionary = components.get(dimension, {})
		var value: Variant = component.get("normalized_value")
		var effective_weight: Variant = component.get("effective_weight")
		var value_text := "n/a" if value == null else "%.0f%%" % (float(value) * 100.0)
		var weight_text := "configured %d%%" % int(round(float(component.get("configured_weight", 0.0)) * 100.0)) if effective_weight == null else "weight %d%%" % int(round(float(effective_weight) * 100.0))
		_add_value(dimension.capitalize(), "%s · %s" % [value_text, weight_text])
	var scoring_note := Label.new()
	scoring_note.text = "Game score is separate from the raw metrics below. Score weights and mission thresholds are provisional."
	scoring_note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	scoring_note.add_theme_font_size_override("font_size", 9)
	scoring_note.add_theme_color_override("font_color", MUTED)
	content.add_child(scoring_note)

	_add_section_heading("OBJECTIVES")
	var objectives: Array = mission.get("objectives", [])
	if objectives.is_empty():
		_add_value("Mission objectives", "Unavailable")
	for objective in objectives:
		_add_value(
			("✓ " if bool(objective.get("passed", false)) else "× ") + str(objective.get("label", objective.get("id", "Objective"))),
			"%s %s target %s" % [
				_format_metric(objective.get("actual"), str(objective.get("metric", ""))),
				str(objective.get("operator", ">=")),
				_format_metric(objective.get("target"), str(objective.get("metric", ""))),
			],
			GREEN if bool(objective.get("passed", false)) else RED,
		)
		if not bool(objective.get("passed", false)) and not str(objective.get("guidance", "")).is_empty():
			_add_value("Next", str(objective.get("guidance", "")), MUTED)

	_add_section_heading("RAW ENGINE RESULTS")
	_add_value("Fresh team coverage", _percent(metrics.get("any_agent_awareness_coverage")))
	_add_value("Mean local coverage", _percent(metrics.get("mean_agent_track_coverage")))
	var per_agent: Dictionary = record.get("snapshot", {}).get("metrics", {}).get("agent_track_coverage", {})
	if per_agent.is_empty():
		_add_value("Per-agent coverage", "Unavailable")
	else:
		var agent_values := PackedStringArray()
		var agent_ids: Array = per_agent.keys()
		agent_ids.sort()
		for agent_id in agent_ids:
			agent_values.append("%s %s" % [str(agent_id), _percent(per_agent[agent_id])])
		_add_value("Per-agent coverage", " · ".join(agent_values))
	_add_value("Decision tasks", "%d / %d complete · %d expired · %d dropped" % [int(metrics.get("decision_tasks_completed", 0)), int(metrics.get("decision_tasks_created", 0)), int(metrics.get("decision_tasks_expired", 0)), int(metrics.get("decision_tasks_dropped_overload", 0))])
	_add_value("Deadline misses", "%d · rate %s" % [int(metrics.get("deadline_misses", 0)), _percent(metrics.get("deadline_miss_rate"))])
	_add_value("Messages", "%d delivered / %d sent · %d lost · %d pending" % [int(metrics.get("messages_delivered", 0)), int(metrics.get("messages_sent", 0)), int(metrics.get("messages_dropped", 0)), int(metrics.get("pending_messages", 0))])
	_add_value("Mean track age", _ticks(metrics.get("mean_track_age_steps")))
	_add_value("Queue workload", "mean %.1f · max %d · %d pending" % [float(metrics.get("mean_queue_backlog_tasks", 0.0)), int(metrics.get("max_queue_backlog_tasks", 0)), int(metrics.get("decision_tasks_pending", 0))])
	_add_value("Review tasks", "%d / %d complete · %d pending" % [int(metrics.get("coordination_tasks_completed", 0)), int(metrics.get("coordination_tasks_created", 0)), int(metrics.get("coordination_tasks_pending", 0))])
	if metrics.get("recovery_time_steps") != null:
		_add_value("Network recovery", "%d ticks after restoration" % int(metrics.get("recovery_time_steps")))

	_add_section_heading("EVENT HIGHLIGHTS")
	var highlights: PackedStringArray = record.get("event_highlights", PackedStringArray())
	if highlights.is_empty():
		_add_value("Timeline", "No important events recorded")
	else:
		for highlight in highlights:
			_add_value("", str(highlight))
	_add_section_heading("SAVED RESEARCH ARTIFACTS")
	var artifact := Label.new()
	artifact.text = str(record.get("artifact_path", "Unavailable"))
	artifact.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	artifact.add_theme_font_size_override("font_size", 10)
	artifact.add_theme_color_override("font_color", Color("#55c2ff"))
	content.add_child(artifact)


func _on_result_selected(index: int) -> void:
	_render(index)


func _on_view_selected(index: int) -> void:
	showing_comparison = index == 1
	_update_view_controls()
	if showing_comparison:
		if comparison_picker.item_count > 0:
			_on_comparison_selected(comparison_picker.get_selected())
		else:
			_render_comparison_empty()
	elif history.is_empty():
		_render_empty()
	else:
		_render(result_picker.get_selected())


func _update_view_controls() -> void:
	if view_picker == null:
		return
	result_picker.visible = not showing_comparison and history.size() > 1
	comparison_picker.visible = showing_comparison and comparison_picker.item_count > 0
	comparison_controls.visible = showing_comparison
	comparison_hint.visible = showing_comparison


func _on_comparison_selected(index: int) -> void:
	if not showing_comparison or index < 0 or index >= comparison_picker.item_count:
		return
	var comparison_id := str(comparison_picker.get_item_metadata(index))
	if loaded_comparisons.has(comparison_id):
		_render_comparison(loaded_comparisons[comparison_id])
	else:
		saved_comparison_selected.emit(comparison_id)


func _on_comparison_requested() -> void:
	var dimension := str(comparison_dimension_picker.get_item_metadata(comparison_dimension_picker.get_selected()))
	matched_comparison_requested.emit(dimension, int(seed_count_picker.value))


func _rebuild_comparison_picker(selected_id: String) -> void:
	comparison_picker.clear()
	for record in saved_comparisons:
		var index := comparison_picker.item_count
		comparison_picker.add_item(_comparison_title(record))
		comparison_picker.set_item_metadata(index, str(record.get("comparison_id", "")))
		if str(record.get("comparison_id", "")) == selected_id:
			comparison_picker.select(index)


func _comparison_title(record: Dictionary) -> String:
	var kind := "scheduler" if str(record.get("dimension", "scheduler")) == "scheduler" else "sharing"
	return "%s · %d seeds" % [str(record.get("scenario_name", "Mission")), int(record.get("seed_count", 0))]


func _render_comparison_empty() -> void:
	_clear_content()
	var hint := Label.new()
	hint.text = "No saved comparisons yet. Choose Scheduler or Sharing, then run both treatments over the same seed set. Each treatment is saved as a normal run artifact and the paired differences are saved under runs/comparisons/."
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	hint.add_theme_font_size_override("font_size", 11)
	hint.add_theme_color_override("font_color", MUTED)
	content.add_child(hint)
	var note := Label.new()
	note.text = "The comparison uses the mission, seed start, and held-constant selector shown above. Matched results are descriptive and do not claim statistical significance."
	note.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	note.add_theme_font_size_override("font_size", 10)
	note.add_theme_color_override("font_color", AMBER)
	content.add_child(note)


func _render_comparison(comparison: Dictionary) -> void:
	_clear_content()
	if comparison.is_empty():
		_render_comparison_empty()
		return
	var left: Dictionary = comparison.get("left_treatment", {})
	var right: Dictionary = comparison.get("right_treatment", {})
	_add_section_heading("MATCHED-SEED POLICY COMPARISON")
	_add_value("Mission", "%s · %d logical ticks" % [str(comparison.get("scenario_name", "Mission")), int(comparison.get("configured_steps", 0))])
	_add_value("Seed set", "%d seeds from %d · %d treatment runs" % [int(comparison.get("seed_count", 0)), int(comparison.get("start_seed", 0)), (comparison.get("runs", []) as Array).size()])
	_add_value("Treatments", "%s vs %s" % [str(left.get("label", "Left")), str(right.get("label", "Right"))])
	_add_value("Held constant", _held_constant_text(comparison.get("held_constant", {})))
	_add_value("Difference", str(comparison.get("difference_label", "Right minus left")) + " · paired by seed")
	var interpretation := Label.new()
	interpretation.text = str(comparison.get("interpretation_note", "Paired descriptive results; no statistical significance is implied."))
	interpretation.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	interpretation.add_theme_font_size_override("font_size", 9)
	interpretation.add_theme_color_override("font_color", MUTED)
	content.add_child(interpretation)

	_add_section_heading("PAIRED ENGINE METRICS")
	var aggregates: Dictionary = comparison.get("aggregates", {})
	var definitions: Dictionary = comparison.get("metric_definitions", {})
	var metric_order := [
		"game_score", "mission_task_completion_rate", "mission_task_deadline_miss_rate",
		"mission_area_coverage_fraction", "mission_completion_time_steps",
		"any_agent_awareness_coverage", "mean_agent_track_coverage", "deadline_miss_rate",
		"decision_latency_p95_steps", "mean_queue_backlog_tasks", "message_delivery_ratio",
		"task_completion_rate", "mean_observation_to_shared_application_delay_steps",
		"total_uav_distance_travelled", "uav_energy_consumed", "recovery_time_steps",
	]
	for metric_value in metric_order:
		var metric := str(metric_value)
		var aggregate: Dictionary = aggregates.get(metric, {})
		if int(aggregate.get("n", 0)) == 0:
			continue
		var definition: Dictionary = definitions.get(metric, {})
		var delta: Variant = aggregate.get("mean_difference")
		var ci_low: Variant = aggregate.get("ci95_low")
		var ci_high: Variant = aggregate.get("ci95_high")
		var direction := str(definition.get("direction", "higher"))
		var interpretation_text := "higher values are better" if direction == "higher" else "lower values are better"
		var tint := GREEN
		if delta != null:
			var right_better := float(delta) > 0.0 if direction == "higher" else float(delta) < 0.0
			if is_zero_approx(float(delta)):
				tint = MUTED
			else:
				tint = GREEN if right_better else AMBER
		var interval_text := "95%% CI %s to %s" % [
			_format_comparison_value(metric, ci_low), _format_comparison_value(metric, ci_high),
		] if ci_low != null and ci_high != null else "95% CI unavailable (need at least two paired seeds)"
		_add_value(str(definition.get("label", metric)), "%s %s · Δ %s · %s · %s" % [
			_format_comparison_value(metric, aggregate.get("left_mean")),
			_format_comparison_value(metric, aggregate.get("right_mean")),
			_format_comparison_value(metric, delta),
			interpretation_text,
			interval_text,
		], tint)

	_add_section_heading("PER-SEED PAIRS")
	for pair_value in comparison.get("paired_results", []):
		if not pair_value is Dictionary:
			continue
		var pair: Dictionary = pair_value
		var values: Dictionary = pair.get("values", {})
		var score_pair: Dictionary = values.get("game_score", {})
		var deadline_pair: Dictionary = values.get("deadline_miss_rate", {})
		_add_value("Seed %d" % int(pair.get("seed", 0)), "score %s → %s · deadline miss %s → %s" % [
			_format_comparison_value("game_score", score_pair.get("left")),
			_format_comparison_value("game_score", score_pair.get("right")),
			_format_comparison_value("deadline_miss_rate", deadline_pair.get("left")),
			_format_comparison_value("deadline_miss_rate", deadline_pair.get("right")),
		])

	_add_section_heading("SAVED RUN ARTIFACTS")
	for run_value in comparison.get("runs", []):
		if not run_value is Dictionary:
			continue
		var run: Dictionary = run_value
		_add_value("Seed %d · %s · %s" % [int(run.get("seed", 0)), str(run.get("treatment_label", "Treatment")), str(run.get("mission_status", "unknown"))], str(run.get("artifact_path", "Unavailable")), MUTED)
	_add_value("Comparison file", str(comparison.get("artifact_path", "Unavailable")), Color("#55c2ff"))


func _held_constant_text(value: Variant) -> String:
	if not value is Dictionary or value.is_empty():
		return "No common factors reported"
	var parts := PackedStringArray()
	var fields: Dictionary = value
	for key in fields.keys():
		parts.append("%s: %s" % [str(key).replace("_", " "), str(fields[key]).replace("-", " ")])
	return " · ".join(parts)


func _format_comparison_value(metric: String, value: Variant) -> String:
	if value == null:
		return "n/a"
	var numeric := float(value)
	if metric in ["any_agent_awareness_coverage", "mean_agent_track_coverage", "deadline_miss_rate", "message_delivery_ratio", "task_completion_rate", "mission_task_completion_rate", "mission_task_deadline_miss_rate", "mission_area_coverage_fraction"]:
		return "%.1f%%" % (numeric * 100.0)
	if metric == "game_score":
		return "%.2f" % numeric
	if metric.ends_with("_steps"):
		return "%.2f ticks" % numeric
	return "%.2f" % numeric


func _add_section_heading(text: String) -> void:
	var separator := HSeparator.new()
	content.add_child(separator)
	var heading := Label.new()
	heading.text = text
	heading.add_theme_font_size_override("font_size", 10)
	heading.add_theme_color_override("font_color", Color("#8fb2d8"))
	content.add_child(heading)


func _add_value(key: String, value: String, tint: Color = TEXT) -> void:
	var label := Label.new()
	label.text = (key + "  ·  " if not key.is_empty() else "") + value
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", 10)
	label.add_theme_color_override("font_color", tint)
	content.add_child(label)


func _clear_content() -> void:
	for child in content.get_children():
		content.remove_child(child)
		child.queue_free()


func _format_metric(value: Variant, metric: String) -> String:
	if value == null:
		return "n/a"
	if metric.ends_with("coverage") or metric.ends_with("rate"):
		return _percent(value)
	if metric == "recovery_time_steps":
		return "%d ticks" % int(value)
	return str(value)


func _percent(value: Variant) -> String:
	return "n/a" if value == null else "%.1f%%" % (float(value) * 100.0)


func _ticks(value: Variant) -> String:
	return "n/a" if value == null else "%.1f ticks" % float(value)
