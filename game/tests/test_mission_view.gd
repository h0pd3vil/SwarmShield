extends SceneTree

const MissionPanelScript = preload("res://scripts/ui/mission_panel.gd")
const AgentInspectorScript = preload("res://scripts/ui/agent_inspector.gd")

var failures := 0


func _init() -> void:
	call_deferred("_run_tests")


func _run_tests() -> void:
	await process_frame
	_test_mission_task_rows_show_backend_state()
	_test_entity_protection_controls_send_selected_ids_and_perimeter()
	_test_agent_inspector_shows_engine_motion_and_mission_tasks()
	if failures == 0:
		print("Mission view tests passed")
	quit(1 if failures > 0 else 0)


func _expect(condition: bool, message: String) -> void:
	if condition:
		return
	failures += 1
	push_error(message)


func _test_mission_task_rows_show_backend_state() -> void:
	var panel = MissionPanelScript.new()
	root.add_child(panel)
	panel.set_snapshot({
		"tick": 4,
		"scenario": {"steps": 100},
		"mission": {
			"name": "Test mission",
			"status": "running",
			"objectives": [{"id": "coverage", "label": "Coverage", "actual": 0.4, "target": 0.8, "metric": "coverage", "operator": ">=", "passed": false}],
			"tasks": [{"task_id": "survey-west", "task_type": "coverage", "status": "navigating", "assigned_agent_id": "agent-01", "deadline_step": 70}],
		},
		"world": {"agents": [
			{"id": "agent-01", "uav_status": "navigating", "current_task_id": "survey-west"},
			{"id": "agent-02", "uav_status": "available", "current_task_id": null},
		]},
	})
	_expect(panel.status_badge.text.contains("RUNNING"), "Mission status should remain visible beside task progress")
	_expect(panel.task_rows.get_child_count() == 1, "Mission panel should create one row per backend task")
	var title: Label = panel.task_rows.get_child(0).get_child(0)
	_expect(title.text.contains("survey-west") and title.text.contains("agent-01") and title.text.contains("navigating"), "Task row should show its actual owner and state")
	var requested := {"task_id": "", "agent_id": ""}
	panel.reassignment_requested.connect(func(task_id: String, agent_id: String) -> void:
		requested.task_id = task_id
		requested.agent_id = agent_id
	)
	panel.task_picker.select(1)
	panel.agent_picker.select(1)
	panel._on_reassign_pressed()
	_expect(requested.task_id == "survey-west" and requested.agent_id == "agent-02", "Commander reassignment control should submit selected task and free UAV IDs")
	panel.free()


func _test_agent_inspector_shows_engine_motion_and_mission_tasks() -> void:
	var inspector = AgentInspectorScript.new()
	root.add_child(inspector)
	inspector.set_available_agents([{"id": "agent-01"}])
	inspector.set_agent({
		"agent_id": "agent-01",
		"state": "navigating",
		"position": {"x": 12.0, "y": 18.0},
		"motion": {"speed": 1.4, "distance_travelled": 5.0, "battery_remaining": 60.0, "battery_capacity": 100.0, "current_task_id": "survey-west"},
		"locally_known_tracks": [],
		"mission_tasks": [{"task_id": "survey-west", "task_type": "coverage", "status": "navigating", "assigned_agent_id": "agent-01", "deadline_step": 70, "deadline_slack_steps": 30}],
		"pending_work": [],
		"communication": {"status": "available", "pending_inbound_messages": 0, "pending_messages": []},
	})
	_expect(inspector.state_label.text == "NAVIGATING", "Inspector should show the backend UAV navigation state")
	_expect(inspector.summary_label.text.contains("travelled 5.0 units") and inspector.summary_label.text.contains("60%"), "Inspector should show actual traveled distance and battery")
	_expect(inspector.work_label.text.contains("survey-west") and inspector.work_label.text.contains("navigating"), "Inspector should show the assigned operational mission task")
	inspector.free()


func _test_entity_protection_controls_send_selected_ids_and_perimeter() -> void:
	var panel = MissionPanelScript.new()
	root.add_child(panel)
	panel.set_run_active(true)
	panel.set_snapshot({
		"tick": 12,
		"scenario": {"steps": 100, "max_track_age_steps": 5},
		"mission": {"name": "Protection test", "status": "running", "objectives": [], "tasks": []},
		"world": {
			"agents": [],
			"tracks": [{"agent_id": "agent-02", "source_agent_id": "agent-01", "entity_id": "entity-04", "x": 31.0, "y": 42.0, "observed_at": 10}],
			"protection_zones": [],
		},
	})
	panel.set_protection_selection("entity-04", "agent-02")
	var submitted := {"entity_id": "", "radius": 0.0, "zone_type": ""}
	panel.protection_requested.connect(func(entity_id: String, radius: float, zone_type: String) -> void:
		submitted.entity_id = entity_id
		submitted.radius = radius
		submitted.zone_type = zone_type
	)
	panel.protection_radius.value = 9.0
	panel.protection_type_picker.select(1)
	panel._on_protection_pressed()
	_expect(not panel.protection_button.disabled, "A live run and a selected known contact should enable designation")
	_expect(submitted.entity_id == "entity-04" and is_equal_approx(submitted.radius, 9.0) and submitted.zone_type == "protection", "Protection control should submit the selected backend entity and configured perimeter")
	panel.set_snapshot({
		"tick": 13,
		"scenario": {"steps": 100, "max_track_age_steps": 5},
		"mission": {"name": "Protection test", "status": "running", "objectives": [], "tasks": []},
		"world": {
			"agents": [],
			"tracks": [{"agent_id": "agent-02", "source_agent_id": "agent-01", "entity_id": "entity-04", "x": 32.0, "y": 43.0, "observed_at": 12}],
			"protection_zones": [{"entity_id": "entity-04", "x": 32.0, "y": 43.0, "radius": 9.0, "status": "monitored", "zone_type": "protection", "task_id": "protection-entity-04"}],
		},
	})
	_expect(panel.protection_status_label.text.contains("Monitored") and panel.protection_status_label.text.contains("radius 9.0"), "Inspector should report backend protection status and radius")
	_expect(not panel.protection_remove_button.disabled, "An active backend designation should expose its remove action")
	panel.free()
