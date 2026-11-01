extends SceneTree

const ResultsPanelScript = preload("res://scripts/ui/run_results_panel.gd")

var failures := 0


func _init() -> void:
	call_deferred("_run_tests")


func _run_tests() -> void:
	await process_frame
	var panel = ResultsPanelScript.new()
	root.add_child(panel)
	await process_frame
	panel._render_comparison({
		"scenario_name": "Shared Awareness",
		"configured_steps": 100,
		"seed_count": 2,
		"start_seed": 42,
		"left_treatment": {"label": "Independent"},
		"right_treatment": {"label": "Cooperative"},
		"held_constant": {"scheduler_policy": "edf"},
		"aggregates": {
			"mission_task_completion_rate": {"n": 2, "left_mean": 0.5, "right_mean": 1.0, "mean_difference": 0.5, "ci95_low": 0.1, "ci95_high": 0.9},
			"mission_area_coverage_fraction": {"n": 2, "left_mean": 0.4, "right_mean": 0.7, "mean_difference": 0.3},
		},
		"metric_definitions": {
			"mission_task_completion_rate": {"label": "Mission task completion", "direction": "higher"},
			"mission_area_coverage_fraction": {"label": "Mission area sensor coverage", "direction": "higher"},
		},
		"runs": [],
		"paired_results": [],
	})
	var visible_text: Array[String] = []
	_collect_text(panel.content, visible_text)
	var text := " ".join(visible_text)
	_expect(text.contains("Mission task completion"), "Results comparisons should display mission task completion")
	_expect(text.contains("Mission area sensor coverage"), "Results comparisons should display mapped area coverage")
	_expect(text.contains("50.0%") and text.contains("100.0%"), "Results comparisons should format operational rates as percentages")
	_expect(text.contains("95% CI 10.0% to 90.0%"), "Results comparisons should show paired-seed uncertainty intervals")
	if failures == 0:
		print("Results view tests passed")
	panel.free()
	quit(1 if failures > 0 else 0)


func _collect_text(node: Node, result: Array[String]) -> void:
	if node is Label:
		result.append((node as Label).text)
	for child in node.get_children():
		_collect_text(child, result)


func _expect(condition: bool, message: String) -> void:
	if condition:
		return
	failures += 1
	push_error(message)
