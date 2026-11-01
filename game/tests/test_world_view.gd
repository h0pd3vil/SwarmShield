extends SceneTree

const WorldViewScript = preload("res://scripts/world_view.gd")

var failures := 0


func _init() -> void:
	call_deferred("_run_tests")


func _run_tests() -> void:
	await process_frame
	_test_default_layers_and_track_filters()
	_test_fog_only_uses_snapshot_coverage_and_selected_agent()
	_test_task_regions_only_emphasize_selected_agent()
	_test_selected_agent_shows_its_own_deduplicated_tracks()
	_test_entity_selection_and_clear_signals()
	_test_protection_zone_overlay_uses_authoritative_last_known_data()
	_test_backend_geometry_selects_matching_obstacle_assets()
	_test_main_view_uses_real_routes_tasks_and_known_contacts()
	_test_manual_destination_converts_map_click_to_world_coordinates()
	_test_zoom_pan_preserve_world_coordinate_mapping()
	_test_routes_use_only_recent_real_events_and_pending_messages()
	_test_selected_agent_filters_routes_and_route_cap()
	_test_agent_heading_follows_backend_orientation_in_canvas()
	await _test_fog_layer_draws_backend_coverage()
	if failures == 0:
		print("WorldView tests passed")
	quit(1 if failures > 0 else 0)


func _expect(condition: bool, message: String) -> void:
	if condition:
		return
	failures += 1
	push_error(message)


func _test_default_layers_and_track_filters() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := _snapshot()
	view.set_snapshot(snapshot)
	var agents: Array = snapshot.world.agents
	_expect(not view.show_communication_links, "Communication links should be hidden by default")
	_expect(view.visible_communication_routes(agents).is_empty(), "Hidden links should produce no map routes")
	_expect(view.show_local_observations and not view.show_shared_reports and not view.show_stale_tracks, "The clean default should keep only fresh local observations visible")
	_expect(not view.show_coordinate_grid, "The coordinate grid should remain optional and hidden by default")
	_expect(not view.show_fog_of_war, "The fog overlay should remain optional until enabled")
	_expect(not view.show_mission_areas and not view.show_caution_zones, "Optional mission and caution geometry should start hidden to keep the map clear")
	_expect(view.show_entity_labels, "Entity labels should use hover/selection visibility by default")
	_expect(view.show_uavs and view.show_task_assignments and view.show_terrain, "Essential UAV, task, and terrain layers should be visible by default")
	_expect(not view.show_sensor_visibility, "Sensor visibility should be an optional overlay hidden by default")
	_expect(view.detection_range == 25.0, "The selected-agent sensing overlay should use the backend mission range")
	_expect(view.TERRAIN_TEXTURE != null and view.QUADCOPTER_TEXTURE != null and view.CONTACT_TEXTURE != null, "Recognizable map sprites should load from the local asset library")
	_expect(view.WALL_TEXTURE != null and view.ROCK_TEXTURE != null, "Wall and rock obstacle sprites should load from the local asset library")
	_expect(view.visible_tracks(agents).size() == 1, "Fresh local observation markers should remain visible by default")
	view.set_display_layer("coordinate_grid", true)
	_expect(view.show_coordinate_grid, "The optional grid toggle should affect only map render state")
	view.set_display_layer("coordinate_grid", false)
	view.set_display_layer("entity_labels", false)
	_expect(not view.show_entity_labels, "Entity label toggle should update render state")
	view.set_display_layer("entity_labels", true)
	view.set_display_layer("shared_reports", true)
	_expect(view.visible_tracks(agents).size() == 1, "Shared copies of one entity should collapse to one map marker")
	view.set_display_layer("stale_tracks", true)
	_expect(view.visible_tracks(agents).size() == 2, "Enabling stale tracks should add the stale entity without duplicating fresh shared copies")
	view.set_display_layer("local_observations", false)
	_expect(view.visible_tracks(agents).size() == 1, "Hiding local observations should also hide stale local tracks")
	view.set_display_layer("stale_tracks", false)
	_expect(view.visible_tracks(agents).size() == 1, "Hiding stale tracks should preserve the fresh shared report")
	view.set_display_layer("sensor_visibility", true)
	_expect(view.show_sensor_visibility, "Sensor range should have an independent rendering-only toggle")
	view.set_display_layer("uavs", false)
	_expect(view.visible_agents().is_empty(), "The UAV toggle should hide markers from the rendered agent layer")
	view.set_display_layer("task_assignments", false)
	_expect(view.visible_mission_tasks().is_empty() and view.visible_agent_routes(agents).is_empty(), "The task toggle should hide task and route overlays")
	view.set_display_layer("terrain", false)
	_expect(not view.show_terrain, "Terrain geometry should have an independent rendering-only toggle")
	_expect(snapshot.world.agents.size() == 3 and snapshot.world.tracks.size() == 3, "Hiding visual layers must preserve simulation agents and knowledge")
	_expect(snapshot.world.tracks.size() == 3, "Render filters must not mutate snapshot tracks")
	view.free()


func _test_fog_only_uses_snapshot_coverage_and_selected_agent() -> void:
	var view = WorldViewScript.new()
	var snapshot := {
		"scenario": {"world_width": 20.0, "world_height": 20.0},
		"world": {"sensor_coverage_cell_size": 2.5, "sensor_coverage_cells": [
			{"agent_id": "agent-01", "cell": [2, 3], "local_observed_at": 4, "shared_observed_at": null},
			{"agent_id": "agent-02", "cell": [6, 3], "local_observed_at": null, "shared_observed_at": 3},
		]},
	}
	view.set_snapshot(snapshot)
	_expect(view.visible_sensor_coverage_cells().is_empty(), "Fog coverage should be hidden by default")
	view.set_display_layer("fog_of_war", true)
	_expect(view.visible_sensor_coverage_cells().size() == 2, "Fog should draw only cells supplied by backend sensor state")
	view.select_agent("agent-02")
	var selected_cells: Array = view.visible_sensor_coverage_cells()
	_expect(selected_cells.size() == 1 and selected_cells[0].agent_id == "agent-02", "Selected-agent focus should filter fog to that UAV's local/shared coverage")
	_expect(snapshot.world.sensor_coverage_cells.size() == 2, "Fog toggles and agent focus must not mutate backend coverage")
	view.free()


func _test_fog_layer_draws_backend_coverage() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	view.set_snapshot({
		"tick": 4,
		"scenario": {"world_width": 20.0, "world_height": 20.0},
		"world": {"sensor_coverage_cell_size": 2.5, "sensor_coverage_cells": [
			{"agent_id": "agent-01", "cell": [2, 3], "local_observed_at": 4, "shared_observed_at": null},
		]},
	})
	view.set_display_layer("fog_of_war", true)
	root.add_child(view)
	await process_frame
	view.queue_redraw()
	await process_frame
	view.free()
	await process_frame


func _test_task_regions_only_emphasize_selected_agent() -> void:
	var view = WorldViewScript.new()
	var ambient: Dictionary = view.mission_task_visual_style("agent-01")
	_expect(float(ambient.outline_alpha) < 0.3 and float(ambient.fill_alpha) < 0.05, "Unselected task regions should remain subtle in the default map")
	view.select_agent("agent-01")
	var focused: Dictionary = view.mission_task_visual_style("agent-01")
	var unrelated: Dictionary = view.mission_task_visual_style("agent-02")
	_expect(float(focused.outline_alpha) > float(ambient.outline_alpha), "Selecting an assigned UAV should emphasize its task region")
	_expect(float(unrelated.outline_alpha) < float(ambient.outline_alpha), "Selecting a UAV should dim unrelated task regions")
	view.free()


func _test_selected_agent_shows_its_own_deduplicated_tracks() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := _snapshot()
	view.set_snapshot(snapshot)
	view.set_display_layer("shared_reports", true)
	view.select_agent("agent-02")
	var tracks: Array = view.visible_tracks(snapshot.world.agents)
	_expect(tracks.size() == 1 and tracks[0].agent_id == "agent-02", "Selecting a UAV should show its own freshest view, once per entity")
	view.select_agent("")
	tracks = view.visible_tracks(snapshot.world.agents)
	_expect(tracks.size() == 1 and tracks[0].agent_id == "agent-01", "Unfocused map should prefer the newest source track for an entity")
	view.free()


func _test_entity_selection_and_clear_signals() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := _snapshot()
	view.set_snapshot(snapshot)
	var signals := []
	view.entity_selected.connect(func(entity_id: String, owner_agent_id: String) -> void:
		signals.append([entity_id, owner_agent_id])
	)
	view._handle_map_click(view._to_canvas(70.0, 45.0))
	_expect(view.selected_entity_id == "entity-01" and signals.size() == 1, "Clicking a known contact should select and inspect its actual track")
	view._handle_map_click(Vector2(400, 250))
	_expect(view.selected_entity_id.is_empty() and signals.size() == 2 and signals[1] == ["", ""], "Clicking empty map space should clear entity selection")
	view.free()


func _test_protection_zone_overlay_uses_authoritative_last_known_data() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := {
		"scenario": {"world_width": 100.0, "world_height": 100.0},
		"world": {
			"entities": [{"id": "truth-only", "x": 90.0, "y": 90.0}],
			"protection_zones": [{"entity_id": "entity-01", "x": 31.0, "y": 42.0, "radius": 8.0, "status": "caution"}],
		},
	}
	view.set_snapshot(snapshot)
	var visible := view.visible_protection_zones()
	_expect(visible.size() == 1 and visible[0].x == 31.0 and visible[0].y == 42.0, "Protection overlay should use backend-provided last-known coordinates")
	view.set_display_layer("protection_zones", false)
	_expect(view.visible_protection_zones().is_empty(), "Protection visibility toggle should only change rendered layers")
	_expect(snapshot.world.protection_zones.size() == 1, "Hiding protection graphics must preserve backend state")
	view.free()


func _test_backend_geometry_selects_matching_obstacle_assets() -> void:
	var view = WorldViewScript.new()
	view.set_snapshot({
		"scenario": {"world_width": 100.0, "world_height": 100.0},
		"world": {"geometry": {"obstacles": [
			{"id": "building-01", "kind": "building", "vertices": [[10, 10], [20, 10], [20, 20], [10, 20]]},
			{"id": "tower-01", "kind": "tower", "vertices": [[30, 10], [35, 10], [35, 18], [30, 18]]},
			{"id": "wall-01", "kind": "wall", "vertices": [[40, 10], [43, 10], [43, 30], [40, 30]]},
			{"id": "rock-01", "kind": "rock", "vertices": [[50, 10], [60, 10], [60, 20], [50, 20]]},
		]}},
	})
	var features: Array = view.visible_obstacle_assets()
	_expect(features.size() == 4, "The map should render obstacle features from the backend geometry snapshot")
	var by_id := {}
	for feature in features:
		by_id[str(feature.id)] = feature
	_expect(by_id["building-01"].asset == "hangar", "Backend building geometry should use the hangar artwork")
	_expect(by_id["tower-01"].asset == "water_tower", "Backend tower geometry should use water tower artwork")
	_expect(by_id["wall-01"].asset == "wall", "Backend wall geometry should use wall artwork")
	_expect(by_id["rock-01"].asset == "rock", "Backend rock geometry should use outcrop artwork")
	_expect(by_id["wall-01"].vertices[0] == [40, 10], "Artwork placement must retain the authoritative collision polygon coordinates")
	view.free()


func _test_main_view_uses_real_routes_tasks_and_known_contacts() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var truth_only := {
		"scenario": {"world_width": 100.0, "world_height": 100.0},
		"world": {
			"agents": [{"id": "agent-01", "x": 10.0, "y": 10.0}],
			"entities": [{"id": "hidden-truth", "x": 80.0, "y": 80.0}],
			"tracks": [],
		},
	}
	view.set_snapshot(truth_only)
	_expect(view.visible_tracks(truth_only.world.agents).is_empty(), "Raw evaluator entities must not be exposed as map contact markers without an agent track")

	var snapshot := {
		"scenario": {"world_width": 100.0, "world_height": 100.0},
		"world": {
			"agents": [
				{"id": "agent-01", "x": 10.0, "y": 10.0, "destination": [20.0, 20.0], "route_waypoints": [[15.0, 20.0]], "final_destination": [20.0, 20.0], "current_task_id": "survey-west"},
				{"id": "agent-02", "x": 90.0, "y": 90.0, "destination": null, "route_waypoints": []},
			],
			"entities": [{"id": "hidden-truth", "x": 80.0, "y": 80.0}],
			"tracks": [{"agent_id": "agent-01", "source_agent_id": "agent-01", "entity_id": "known-track", "x": 30.0, "y": 30.0, "observed_at": 1}],
			"geometry": {"points_of_interest": [{"id": "poi-west", "kind": "search", "x": 12.0, "y": 32.0}]},
		},
		"mission_tasks": [{"task_id": "survey-west", "task_type": "coverage", "region": [[12, 12], [24, 12], [24, 24], [12, 24]], "location": null, "assigned_agent_id": "agent-01", "status": "navigating", "deadline_step": 70}],
	}
	view.set_snapshot(snapshot)
	var routes: Array = view.visible_agent_routes(snapshot.world.agents)
	_expect(routes.size() == 1, "Only an agent with an actual backend destination should have a route overlay")
	_expect(routes[0].agent_id == "agent-01" and routes[0].route_waypoints.size() == 1, "Route overlays should preserve backend waypoint order and owner")
	_expect(view.visible_mission_tasks().size() == 1 and view.visible_mission_tasks()[0].assigned_agent_id == "agent-01", "Task areas should retain actual mission assignment/status")
	_expect(view.visible_point_features().size() == 1, "Configured points of interest should be available to the map layer")
	_expect(view.visible_tracks(snapshot.world.agents).size() == 1 and view.visible_tracks(snapshot.world.agents)[0].entity_id == "known-track", "Contact markers should use the agent knowledge track, not the evaluator truth list")
	view.select_agent("agent-02")
	_expect(view.visible_agent_routes(snapshot.world.agents).is_empty(), "Selected-agent focus must not retain an unrelated UAV route")
	view.free()


func _test_manual_destination_converts_map_click_to_world_coordinates() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	view.set_snapshot({
		"scenario": {"world_width": 100.0, "world_height": 100.0},
		"world": {"agents": [{"id": "agent-01", "x": 10.0, "y": 10.0}], "tracks": []},
	})
	view.select_agent("agent-01")
	var received := {"agent_id": "", "destination": Vector2.ZERO}
	view.destination_requested.connect(func(agent_id: String, destination: Vector2) -> void:
		received.agent_id = agent_id
		received.destination = destination
	)
	view.set_manual_destination_enabled(true)
	var click := InputEventMouseButton.new()
	click.button_index = MOUSE_BUTTON_LEFT
	click.pressed = true
	click.position = Vector2(400, 250)
	view._gui_input(click)
	click.pressed = false
	view._gui_input(click)
	_expect(received.agent_id == "agent-01", "Map destination commands should target the currently selected UAV")
	_expect(received.destination.is_equal_approx(Vector2(50, 50)), "Map pixels should convert to the backend's world coordinate space")
	view.free()


func _test_zoom_pan_preserve_world_coordinate_mapping() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	view.world_width = 100.0
	view.world_height = 100.0
	var cursor := Vector2(310, 190)
	var anchor_world: Vector2 = view._to_world(cursor)
	view.zoom_at(2.0, cursor)
	_expect(view._to_canvas(anchor_world.x, anchor_world.y).is_equal_approx(cursor), "Zooming should keep the world point under the mouse fixed")
	view.camera_pan += Vector2(87, -43)
	var known_world := Vector2(23.5, 79.25)
	var screen := view._to_canvas(known_world.x, known_world.y)
	_expect(view._to_world(screen).is_equal_approx(known_world), "Pan and zoom transforms must round-trip map coordinates")
	view.reset_camera()
	_expect(is_equal_approx(view.camera_zoom, 1.0) and view.camera_pan == Vector2.ZERO, "Fit/reset should return the map camera to its reproducible default")
	view.free()


func _test_agent_heading_follows_backend_orientation_in_canvas() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	view.world_width = 100.0
	view.world_height = 100.0
	var heading := 0.73
	var rotation := view._agent_canvas_rotation({"heading_rad": heading})
	var expected_direction := Vector2(cos(heading) * 800.0, sin(heading) * 500.0).normalized()
	_expect(Vector2.UP.rotated(rotation).is_equal_approx(expected_direction), "The drone's nose should follow the engine heading after map aspect scaling")
	view.free()


func _test_routes_use_only_recent_real_events_and_pending_messages() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := _snapshot()
	view.set_snapshot(snapshot)
	view.set_display_layer("communication_links", true)
	var routes: Array = view.visible_communication_routes(snapshot.world.agents)
	_expect(routes.size() == 3, "Repeated messages should collapse by agent pair while recent expired routes remain briefly visible")
	var by_pair := _routes_by_pair(routes)
	_expect(by_pair.has("agent-01|agent-02"), "A current pending message should have a route")
	_expect(by_pair["agent-01|agent-02"].state == "delayed", "Pending messages must remain amber and never appear delivered")
	_expect(by_pair.has("agent-02|agent-03") and by_pair["agent-02|agent-03"].state == "delivered", "Recent delivered event should use its backend-confirmed status")
	_expect(by_pair.has("agent-03|agent-02") and by_pair["agent-03|agent-02"].state == "lost", "Recent expired messages should appear as lost, not delivered")
	_expect(not by_pair.has("agent-03|agent-01"), "Old message events should not remain on the map")
	_expect(not by_pair.has("agent-04|agent-01"), "Events with unknown endpoints should not create map links")
	view.free()


func _test_selected_agent_filters_routes_and_route_cap() -> void:
	var view = WorldViewScript.new()
	view.size = Vector2(800, 500)
	var snapshot := _snapshot()
	for index in range(4, 10):
		snapshot.world.agents.append({"id": "agent-%02d" % index, "x": 10.0 + index * 8.0, "y": 50.0})
	for index in range(1, 9):
		snapshot.recent_events.append({
			"step": 10,
			"event_type": "message_delivered",
			"message_id": "bulk-%02d" % index,
			"sender_id": "agent-%02d" % index,
			"recipient_id": "agent-%02d" % (index + 1),
		})
	snapshot.pending_message_links.append({"message_id": "newest-pending", "sender_id": "agent-03", "recipient_id": "agent-04", "sent_step": 10, "delivery_step": 13})
	view.set_snapshot(snapshot)
	view.set_display_layer("communication_links", true)
	var routes: Array = view.visible_communication_routes(snapshot.world.agents)
	_expect(routes.size() == 4, "Communication rendering should cap simultaneous links")
	_expect(bool(routes[0].pending) and str(routes[0].sender_id) == "agent-03", "Newest active pending route should receive priority")
	view.select_agent("agent-03")
	routes = view.visible_communication_routes(snapshot.world.agents)
	_expect(not routes.is_empty(), "Selected agent should retain its related recent links")
	for route in routes:
		_expect("agent-03" in [str(route.sender_id), str(route.recipient_id)], "Selected-agent focus should omit unrelated links")
	view.free()


func _routes_by_pair(routes: Array) -> Dictionary:
	var pairs := {}
	for route in routes:
		pairs["%s|%s" % [route.sender_id, route.recipient_id]] = route
	return pairs


func _snapshot() -> Dictionary:
	return {
		"tick": 10,
		"scenario": {"world_width": 100.0, "world_height": 100.0, "detection_range": 25.0, "max_track_age_steps": 2},
		"world": {
			"agents": [
				{"id": "agent-01", "x": 10.0, "y": 50.0},
				{"id": "agent-02", "x": 35.0, "y": 50.0},
				{"id": "agent-03", "x": 60.0, "y": 50.0},
			],
			"entities": [{"id": "entity-01", "x": 72.0, "y": 48.0}],
			"tracks": [
				{"agent_id": "agent-01", "source_agent_id": "agent-01", "entity_id": "entity-01", "x": 70.0, "y": 45.0, "observed_at": 10},
				{"agent_id": "agent-02", "source_agent_id": "agent-01", "entity_id": "entity-01", "x": 71.0, "y": 46.0, "observed_at": 9},
				{"agent_id": "agent-02", "source_agent_id": "agent-02", "entity_id": "entity-02", "x": 74.0, "y": 48.0, "observed_at": 4},
			],
		},
		"recent_events": [
			{"step": 10, "event_type": "message_delivered", "message_id": "msg-01", "sender_id": "agent-01", "recipient_id": "agent-02"},
			{"step": 10, "event_type": "message_dropped", "message_id": "msg-02", "sender_id": "agent-01", "recipient_id": "agent-02"},
			{"step": 9, "event_type": "message_delivered", "message_id": "msg-03", "sender_id": "agent-02", "recipient_id": "agent-03"},
			{"step": 1, "event_type": "message_delivered", "message_id": "old", "sender_id": "agent-03", "recipient_id": "agent-01"},
			{"step": 10, "event_type": "message_dropped", "message_id": "unknown", "sender_id": "agent-04", "recipient_id": "agent-01"},
			{"step": 10, "event_type": "message_expired", "message_id": "expired-01", "sender_id": "agent-03", "recipient_id": "agent-02"},
			{"step": 10, "event_type": "task_completed", "message_id": "not-a-message", "sender_id": "agent-02", "recipient_id": "agent-03"},
		],
		"pending_message_links": [
			{"message_id": "pending-1", "sender_id": "agent-01", "recipient_id": "agent-02", "sent_step": 9, "delivery_step": 12},
		],
	}
