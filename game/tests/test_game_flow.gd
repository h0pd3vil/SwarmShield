extends SceneTree

const MainScene = preload("res://main.tscn")

var failures := 0


func _initialize() -> void:
	_run()


func _run() -> void:
	var app = MainScene.instantiate()
	root.add_child(app)
	await process_frame
	if not app.bridge.is_alive():
		_fail("Godot main scene should start the Python backend")
		quit(1)
		return
	app.mission_picker.select(0)
	app.seed_picker.value = 42
	app._on_start()
	if not app.run_active:
		_fail("Mission control should launch the selected backend run")
		app.bridge.close()
		quit(1)
		return
	var first_snapshot: Dictionary = app.current_snapshot
	var agents: Array = first_snapshot.get("world", {}).get("agents", [])
	if agents.is_empty():
		_fail("The running map should receive real agent state from Python")
	else:
		app._on_agent_selected(str(agents[0].get("id", "")))
		if app.inspector_panel.summary_label.text.contains("Select a quadcopter"):
			_fail("Selecting a UAV should populate the agent inspector")
	var ticks := 0
	while app.run_active and ticks < 110:
		app._on_tick()
		ticks += 1
	if app.run_active:
		_fail("The mission should complete within its configured fixed-tick horizon")
	if int(app.current_snapshot.get("tick", 0)) != 100:
		_fail("The completed UI run should report the backend's 100 logical ticks")
	if not app.has_completed_results or not app.status_label.text.contains("SUCCESS"):
		_fail("The result panel should receive a successful backend mission summary")
	if failures == 0:
		print("Godot end-to-end mission flow passed")
	app.bridge.close()
	app.queue_free()
	quit(1 if failures > 0 else 0)


func _fail(message: String) -> void:
	failures += 1
	push_error(message)
