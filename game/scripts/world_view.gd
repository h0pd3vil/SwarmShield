extends Control
class_name WorldView

signal agent_selected(agent_id: String)
signal entity_selected(entity_id: String, owner_agent_id: String)
signal destination_requested(agent_id: String, destination: Vector2)

const PALETTE := [Color("#55c2ff"), Color("#ff7d6e"), Color("#8fe388"), Color("#c39bff"), Color("#ffd166"), Color("#6fe0cf")]
const MAX_VISIBLE_LINKS := 4
const DELIVERED_LINK_LIFETIME := 2
const LOST_LINK_LIFETIME := 3
const TERRAIN_TEXTURE: Texture2D = preload("res://assets/terrain/terrain_map.svg")
const QUADCOPTER_TEXTURE: Texture2D = preload("res://assets/uav/quadcopter.svg")
const CONTACT_TEXTURE: Texture2D = preload("res://assets/entities/unclassified_contact.svg")
const TREE_TEXTURE: Texture2D = preload("res://assets/terrain/tree_canopy.svg")
const HANGAR_TEXTURE: Texture2D = preload("res://assets/obstacles/hangar.svg")
const WATER_TOWER_TEXTURE: Texture2D = preload("res://assets/obstacles/water_tower.svg")
const WALL_TEXTURE: Texture2D = preload("res://assets/obstacles/wall_segment.svg")
const ROCK_TEXTURE: Texture2D = preload("res://assets/obstacles/rock_outcrop.svg")

var world: Dictionary = {}
var mission_tasks: Array = []
var selected_agent := ""
var selected_entity_id := ""
var selected_track_agent_id := ""
var world_width := 100.0
var world_height := 100.0
var detection_range := 0.0
var current_tick := 0
var max_track_age_steps := 10
var hovered_agent := ""
var hovered_entity_id := ""
var hovered_track_agent_id := ""
var hovered_poi_id := ""
var stale_track_count := 0
var recent_events: Array = []
var pending_message_links: Array = []
var camera_zoom := 1.0
var camera_pan := Vector2.ZERO
var pointer_down := false
var pointer_panning := false
var pointer_start := Vector2.ZERO
var pointer_pan_start := Vector2.ZERO

# These flags only control drawing. They never change or filter the snapshot.
var show_communication_links := false
var show_local_observations := true
var show_shared_reports := false
var show_stale_tracks := false
var show_entity_labels := true
var show_fog_of_war := false
var show_coordinate_grid := false
var show_uavs := true
var show_task_assignments := true
var show_terrain := true
var show_mission_areas := false
var show_obstacle_boundaries := true
var show_safe_areas := false
var show_restricted_zones := true
var show_caution_zones := false
var show_protection_zones := true
var show_sensor_visibility := false
var allow_manual_destination := false


func _ready() -> void:
	clip_contents = true
	mouse_filter = Control.MOUSE_FILTER_STOP


func set_snapshot(snapshot: Dictionary) -> void:
	world = snapshot.get("world", {})
	var mission: Dictionary = snapshot.get("mission", {})
	mission_tasks = snapshot.get("mission_tasks", mission.get("tasks", []))
	var config: Dictionary = snapshot.get("scenario", {})
	current_tick = int(snapshot.get("tick", 0))
	recent_events = snapshot.get("recent_events", [])
	pending_message_links = snapshot.get("pending_message_links", [])
	world_width = float(config.get("world_width", 100.0))
	world_height = float(config.get("world_height", 100.0))
	detection_range = float(config.get("detection_range", 0.0))
	max_track_age_steps = int(config.get("max_track_age_steps", 10))
	stale_track_count = 0
	for track in world.get("tracks", []):
		if current_tick - int(track.get("observed_at", 0)) > max_track_age_steps:
			stale_track_count += 1
	if not selected_entity_id.is_empty() and _known_track_by_id(selected_entity_id, selected_track_agent_id).is_empty():
		selected_entity_id = ""
		selected_track_agent_id = ""
		entity_selected.emit("", "")
	queue_redraw()
	if is_inside_tree():
		_update_hover(get_local_mouse_position())


func set_display_layer(layer: String, enabled: bool) -> void:
	match layer:
		"communication_links": show_communication_links = enabled
		"local_observations": show_local_observations = enabled
		"shared_reports": show_shared_reports = enabled
		"stale_tracks": show_stale_tracks = enabled
		"entity_labels": show_entity_labels = enabled
		"fog_of_war": show_fog_of_war = enabled
		"coordinate_grid": show_coordinate_grid = enabled
		"uavs": show_uavs = enabled
		"task_assignments": show_task_assignments = enabled
		"terrain": show_terrain = enabled
		"mission_areas": show_mission_areas = enabled
		"obstacle_boundaries": show_obstacle_boundaries = enabled
		"safe_areas": show_safe_areas = enabled
		"restricted_zones": show_restricted_zones = enabled
		"caution_zones": show_caution_zones = enabled
		"protection_zones": show_protection_zones = enabled
		"sensor_visibility": show_sensor_visibility = enabled
		_:
			return
	queue_redraw()


func select_agent(agent_id: String) -> void:
	selected_agent = agent_id
	selected_entity_id = ""
	selected_track_agent_id = ""
	queue_redraw()


func reset_camera() -> void:
	camera_zoom = 1.0
	camera_pan = Vector2.ZERO
	queue_redraw()
	if is_inside_tree():
		_update_hover(get_local_mouse_position())


func zoom_at(factor: float, focal_point: Vector2) -> void:
	if factor <= 0.0 or not is_finite(factor):
		return
	var world_anchor := _to_world(focal_point)
	camera_zoom = clampf(camera_zoom * factor, 0.5, 6.0)
	var map_scale := _map_scale()
	var map_origin := (size - Vector2(world_width, world_height) * map_scale) * 0.5
	camera_pan = focal_point - map_origin - Vector2(world_anchor.x * map_scale.x, world_anchor.y * map_scale.y)
	queue_redraw()
	if is_inside_tree():
		_update_hover(get_local_mouse_position())


func zoom_to_selection() -> void:
	var world_point := Vector2(-1.0, -1.0)
	if not selected_agent.is_empty():
		for agent in world.get("agents", []):
			if str(agent.get("id", "")) == selected_agent:
				world_point = Vector2(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
				break
	elif not selected_entity_id.is_empty():
		var track := _known_track_by_id(selected_entity_id, selected_track_agent_id)
		if not track.is_empty():
			world_point = Vector2(float(track.get("x", 0.0)), float(track.get("y", 0.0)))
	if world_point.x < 0.0:
		return
	camera_zoom = 3.0
	var map_scale := _map_scale()
	var map_origin := (size - Vector2(world_width, world_height) * map_scale) * 0.5
	camera_pan = size * 0.5 - map_origin - Vector2(world_point.x * map_scale.x, world_point.y * map_scale.y)
	queue_redraw()
	if is_inside_tree():
		_update_hover(get_local_mouse_position())


func set_manual_destination_enabled(enabled: bool) -> void:
	allow_manual_destination = enabled
	if is_inside_tree():
		tooltip_text = "Click an empty map position to request a Python-planned route for %s." % selected_agent if enabled and not selected_agent.is_empty() else ""


func visible_tracks(agents: Array) -> Array:
	var by_entity: Dictionary = {}
	for track_value in world.get("tracks", []):
		if not track_value is Dictionary:
			continue
		var track: Dictionary = track_value
		var agent_id := str(track.get("agent_id", ""))
		if _agent_index(agents, agent_id) < 0:
			continue
		if not selected_agent.is_empty() and agent_id != selected_agent:
			continue
		var source_agent_id := str(track.get("source_agent_id", agent_id))
		var shared := source_agent_id != agent_id
		if shared and not show_shared_reports:
			continue
		if not shared and not show_local_observations:
			continue
		var fresh := current_tick - int(track.get("observed_at", 0)) <= max_track_age_steps
		if not fresh and not show_stale_tracks:
			continue
		var entity_id := str(track.get("entity_id", ""))
		if entity_id.is_empty():
			continue
		if not by_entity.has(entity_id) or _track_is_more_relevant(track, by_entity[entity_id]):
			by_entity[entity_id] = track
	var visible: Array = by_entity.values()
	visible.sort_custom(func(left: Dictionary, right: Dictionary) -> bool:
		return str(left.get("entity_id", "")) < str(right.get("entity_id", ""))
	)
	return visible


func _track_is_more_relevant(candidate: Dictionary, current: Dictionary) -> bool:
	var candidate_tick := int(candidate.get("observed_at", -1))
	var current_tick_value := int(current.get("observed_at", -1))
	if candidate_tick != current_tick_value:
		return candidate_tick > current_tick_value
	var candidate_local := str(candidate.get("source_agent_id", candidate.get("agent_id", ""))) == str(candidate.get("agent_id", ""))
	var current_local := str(current.get("source_agent_id", current.get("agent_id", ""))) == str(current.get("agent_id", ""))
	if candidate_local != current_local:
		return candidate_local
	return str(candidate.get("agent_id", "")) < str(current.get("agent_id", ""))


func visible_agents() -> Array:
	return world.get("agents", []) if show_uavs else []


func visible_agent_routes(agents: Array) -> Array:
	if not show_task_assignments:
		return []
	var routes: Array = []
	for agent in agents:
		if not agent is Dictionary:
			continue
		var agent_id := str(agent.get("id", ""))
		if not selected_agent.is_empty() and agent_id != selected_agent:
			continue
		var destination: Variant = agent.get("destination")
		var waypoints: Array = agent.get("route_waypoints", [])
		if destination == null and waypoints.is_empty():
			continue
		routes.append({
			"agent_id": agent_id,
			"position": [float(agent.get("x", 0.0)), float(agent.get("y", 0.0))],
			"destination": destination,
			"route_waypoints": waypoints,
			"final_destination": agent.get("final_destination"),
			"task_id": str(agent.get("current_task_id", "")),
			"uav_status": str(agent.get("uav_status", "available")),
		})
	return routes


func visible_mission_tasks() -> Array:
	if not show_task_assignments:
		return []
	return mission_tasks.filter(func(value: Variant) -> bool: return value is Dictionary)


func visible_protection_zones() -> Array:
	if not show_protection_zones:
		return []
	var zones: Array = []
	for value in world.get("protection_zones", []):
		if value is Dictionary:
			zones.append(value)
	return zones


func visible_sensor_coverage_cells() -> Array:
	if not show_fog_of_war:
		return []
	var visible: Array = []
	for value in world.get("sensor_coverage_cells", []):
		if not value is Dictionary:
			continue
		if not selected_agent.is_empty() and str(value.get("agent_id", "")) != selected_agent:
			continue
		visible.append(value)
	return visible


func visible_point_features() -> Array:
	var geometry: Dictionary = world.get("geometry", {})
	var points: Array = []
	for value in geometry.get("points_of_interest", []):
		if value is Dictionary:
			points.append(value)
	return points


func obstacle_asset_kind(kind: String) -> String:
	match kind.to_lower():
		"building", "hangar": return "hangar"
		"tower", "water_tower": return "water_tower"
		"wall": return "wall"
		"rock", "boulder", "rock_outcrop": return "rock"
		_: return "polygon"


func visible_obstacle_assets() -> Array:
	var result: Array = []
	var geometry: Dictionary = world.get("geometry", {})
	for value in geometry.get("obstacles", []) + geometry.get("buildings", []):
		if not value is Dictionary:
			continue
		var feature: Dictionary = value
		result.append({
			"id": str(feature.get("id", "")),
			"kind": str(feature.get("kind", "")),
			"asset": obstacle_asset_kind(str(feature.get("kind", ""))),
			"vertices": feature.get("vertices", []),
		})
	return result


func visible_communication_routes(agents: Array) -> Array:
	if not show_communication_links:
		return []
	var route_groups: Dictionary = {}
	for event_value in recent_events:
		if not event_value is Dictionary:
			continue
		var event: Dictionary = event_value
		var kind := str(event.get("event_type", ""))
		if kind not in ["message_delivered", "message_dropped", "message_expired"]:
			continue
		var event_step := int(event.get("step", current_tick))
		var state := "delivered" if kind == "message_delivered" else "lost"
		var lifetime := DELIVERED_LINK_LIFETIME if state == "delivered" else LOST_LINK_LIFETIME
		var age := current_tick - event_step
		if age < 0 or age > lifetime:
			continue
		_add_route(route_groups, event, state, event_step)
	for pending_value in pending_message_links:
		if pending_value is Dictionary:
			_add_pending_route(route_groups, pending_value)
	var routes: Array = []
	for route_value in route_groups.values():
		var route: Dictionary = route_value
		if _agent_index(agents, str(route.get("sender_id", ""))) < 0:
			continue
		if _agent_index(agents, str(route.get("recipient_id", ""))) < 0:
			continue
		if not selected_agent.is_empty() and selected_agent not in [str(route.sender_id), str(route.recipient_id)]:
			continue
		routes.append(route)
	routes.sort_custom(func(left: Dictionary, right: Dictionary) -> bool:
		if bool(left.get("pending", false)) != bool(right.get("pending", false)):
			return bool(left.get("pending", false))
		if int(left.get("sort_step", 0)) != int(right.get("sort_step", 0)):
			return int(left.get("sort_step", 0)) > int(right.get("sort_step", 0))
		return str(left.get("key", "")) < str(right.get("key", ""))
	)
	if routes.size() > MAX_VISIBLE_LINKS:
		routes.resize(MAX_VISIBLE_LINKS)
	return routes


func _draw() -> void:
	var rect := Rect2(Vector2.ZERO, size)
	var map_rect := _map_screen_rect()
	draw_rect(rect, Color("#18221c"), true)
	if show_terrain and TERRAIN_TEXTURE != null:
		draw_texture_rect(TERRAIN_TEXTURE, map_rect, false)
	else:
		draw_rect(map_rect, Color("#15221f"), true)
	if show_fog_of_war:
		_draw_fog_of_war()
	if show_coordinate_grid:
		_draw_coordinate_grid()
	draw_rect(rect, Color("#34445b"), false, 2.0)
	draw_rect(map_rect, Color("#b8b99a", 0.26), false, 1.0)
	_draw_terrain_landmarks()
	if world.is_empty():
		draw_string(ThemeDB.fallback_font, Vector2(24, 38), "Start a mission to connect to the Python simulation.", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color("#b5c5d8"))
		return
	var simulation_agents: Array = world.get("agents", [])
	var agents := visible_agents()
	if show_sensor_visibility:
		_draw_selected_sensing_range(simulation_agents)
	_draw_mission_tasks()
	_draw_agent_routes(agents)
	for index in range(agents.size()):
		var agent: Dictionary = agents[index]
		var agent_id := str(agent.get("id", ""))
		var point := _to_canvas(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
		var color: Color = PALETTE[index % PALETTE.size()]
		if not selected_agent.is_empty() and agent_id != selected_agent:
			color.a = 0.78
		_draw_sprite(QUADCOPTER_TEXTURE, point, Vector2(34, 34), _agent_canvas_rotation(agent), Color(1, 1, 1, color.a))
		if agent_id == selected_agent:
			draw_arc(point, 22.0, 0.0, TAU, 48, Color.WHITE, 2.4)
		elif agent_id == hovered_agent:
			draw_arc(point, 21.0, 0.0, TAU, 40, Color(0.85, 0.93, 1.0, 0.86), 1.8)
		var agent_status := str(agent.get("uav_status", "available"))
		if agent_status in ["unavailable", "unreachable", "blocked"]:
			draw_arc(point, 25.0, 0.0, TAU, 40, Color("#ff7d6e", 0.92), 2.2)
			draw_line(point + Vector2(11, -13), point + Vector2(17, -7), Color("#ff9c83"), 2.0)
			draw_line(point + Vector2(17, -13), point + Vector2(11, -7), Color("#ff9c83"), 2.0)
		if agent_id in [selected_agent, hovered_agent]:
			_draw_label(_label_position(point, agent_id), agent_id, Color.WHITE)
	# Evaluator truth positions are deliberately not rendered. Contact sprites come
	# only from actual agent-owned local/shared tracks in the protocol snapshot.
	for track in visible_tracks(simulation_agents):
		var agent_index := _agent_index(simulation_agents, str(track.get("agent_id", "")))
		var color: Color = PALETTE[agent_index % PALETTE.size()]
		var owner_id := str(track.get("agent_id", ""))
		if not selected_agent.is_empty() and owner_id != selected_agent:
			color.a = 0.24
		var point := _to_canvas(float(track.get("x", 0.0)), float(track.get("y", 0.0)))
		var fresh := current_tick - int(track.get("observed_at", 0)) <= max_track_age_steps
		var shared := str(track.get("source_agent_id", owner_id)) != owner_id
		_draw_track_marker(point, track, color, fresh, shared)
		var entity_id := str(track.get("entity_id", ""))
		if show_entity_labels and ((entity_id == hovered_entity_id and owner_id == hovered_track_agent_id) or (entity_id == selected_entity_id and owner_id == selected_track_agent_id)):
			_draw_label(_label_position(point, entity_id), entity_id, Color("#f2dfaa"))
	# Communication is a transient, capped overlay and never appears in the default view.
	_draw_communication_routes(agents)


func _draw_fog_of_war() -> void:
	var cell_size := float(world.get("sensor_coverage_cell_size", 2.5))
	if cell_size <= 0.0:
		return
	var known: Dictionary = {}
	for value in visible_sensor_coverage_cells():
		var cell: Array = value.get("cell", [])
		if cell.size() < 2:
			continue
		var key := Vector2i(int(cell[0]), int(cell[1]))
		var local_tick := int(value.get("local_observed_at", -1)) if value.get("local_observed_at") != null else -1
		var shared_tick := int(value.get("shared_observed_at", -1)) if value.get("shared_observed_at") != null else -1
		if not known.has(key):
			known[key] = {"local": local_tick, "shared": shared_tick}
		else:
			var record: Dictionary = known[key]
			record["local"] = maxi(int(record.local), local_tick)
			record["shared"] = maxi(int(record.shared), shared_tick)
	var columns := ceili(world_width / cell_size)
	var rows := ceili(world_height / cell_size)
	for column in range(columns):
		var left := float(column) * cell_size
		var right := minf(left + cell_size, world_width)
		for row in range(rows):
			var top := float(row) * cell_size
			var bottom := minf(top + cell_size, world_height)
			var rect := Rect2(_to_canvas(left, top), _world_size_to_canvas(Vector2(right - left, bottom - top)) + Vector2(0.5, 0.5))
			var key := Vector2i(column, row)
			if not known.has(key):
				draw_rect(rect, Color("#111916", 0.58), true)
				continue
			var record: Dictionary = known[key]
			var local_tick := int(record.local)
			var shared_tick := int(record.shared)
			var is_shared := shared_tick > local_tick
			var observed_at := shared_tick if is_shared else local_tick
			var age := current_tick - observed_at
			var tint := Color("#5795c0", 0.15) if is_shared else (Color("#72c8b1", 0.18) if age <= 0 else Color("#c0af76", 0.11))
			if age > max_track_age_steps:
				tint = Color("#a0a39a", 0.12)
			draw_rect(rect, tint, true)


func _draw_coordinate_grid() -> void:
	for index in range(1, 10):
		var x := world_width * index / 10.0
		var y := world_height * index / 10.0
		draw_line(_to_canvas(x, 0.0), _to_canvas(x, world_height), Color(0.76, 0.83, 0.75, 0.15), 1.0)
		draw_line(_to_canvas(0.0, y), _to_canvas(world_width, y), Color(0.76, 0.83, 0.75, 0.15), 1.0)


func _draw_terrain_landmarks() -> void:
	var geometry: Dictionary = world.get("geometry", {})
	if show_terrain:
		_draw_vegetation_features(geometry.get("vegetation", []))
		_draw_water_features(geometry.get("water_bodies", []))
		_draw_road_features(geometry.get("roads", []))
		_draw_path_features(geometry.get("paths", []))
		_draw_parking_features(geometry.get("parking_areas", []))
		_draw_point_features()
	if show_safe_areas:
		_draw_context_polygons(geometry.get("safe_areas", []), Color("#68b882", 0.075), Color("#77bd8b", 0.50))
	if show_restricted_zones:
		_draw_restricted_zones(geometry.get("restricted_regions", []))
	if show_caution_zones:
		_draw_context_polygons(geometry.get("caution_zones", []), Color("#e3b750", 0.10), Color("#e9c776", 0.68))
	if show_mission_areas:
		_draw_context_polygons(geometry.get("mission_areas", []), Color("#57a6ca", 0.035), Color("#8ab9d3", 0.32))
	if show_protection_zones:
		_draw_dynamic_protection_zones(visible_protection_zones())
	if show_obstacle_boundaries:
		for feature in visible_obstacle_assets():
			_draw_obstacle_feature(feature)


func _draw_restricted_zones(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		var behavior := str(value.get("behavior", "deny_entry"))
		var outline := Color("#8c9492", 0.58) if behavior == "inactive" else (Color("#e9bd59", 0.78) if behavior in ["monitor", "warn"] else Color("#eb6c61", 0.76))
		var fill := outline
		fill.a = 0.10
		draw_colored_polygon(points, fill)
		_draw_polygon_outline(points, outline, 1.8)


func _draw_dynamic_protection_zones(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var center := _to_canvas(float(value.get("x", 0.0)), float(value.get("y", 0.0)))
		var radius := _world_size_to_canvas(Vector2.ONE * float(value.get("radius", 0.0)))
		var status := str(value.get("status", "inactive"))
		var zone_color := Color("#65bf83")
		match status:
			"monitored": zone_color = Color("#67b9e8")
			"caution": zone_color = Color("#e9bd59")
			"unsafe", "violation": zone_color = Color("#eb6c61")
			"inactive": zone_color = Color("#969da1")
		var perimeter := _ellipse_points(center, radius, 64)
		var closed := perimeter.duplicate()
		closed.append(perimeter[0])
		var fill := zone_color
		fill.a = 0.12
		draw_colored_polygon(perimeter, fill)
		draw_polyline(closed, Color(zone_color, 0.82), 1.8, true)


func _draw_context_polygons(features: Array, fill: Color, outline: Color) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		draw_colored_polygon(points, fill)
		_draw_polygon_outline(points, outline, 1.1)


func _draw_point_features() -> void:
	for feature in visible_point_features():
		var feature_id := str(feature.get("id", ""))
		var point := _to_canvas(float(feature.get("x", 0.0)), float(feature.get("y", 0.0)))
		var is_reference := str(feature.get("kind", "")) == "reference"
		var tint := Color("#aeb8bd", 0.48) if is_reference else Color("#e9c776", 0.84)
		var diamond := PackedVector2Array([point + Vector2(0, -5), point + Vector2(5, 0), point + Vector2(0, 5), point + Vector2(-5, 0), point + Vector2(0, -5)])
		draw_polyline(diamond, tint, 1.4, true)
		if feature_id == hovered_poi_id:
			_draw_label(_label_position(point, feature_id), feature_id, tint)


func _draw_mission_tasks() -> void:
	var agents: Array = world.get("agents", [])
	for task_value in visible_mission_tasks():
		var task: Dictionary = task_value
		var task_id := str(task.get("task_id", "task"))
		var owner := str(task.get("assigned_agent_id", ""))
		var owner_index := _agent_index(agents, owner)
		var tint: Color = PALETTE[owner_index % PALETTE.size()] if owner_index >= 0 else Color("#d2b373")
		var status := str(task.get("status", "unassigned"))
		if status == "completed":
			tint = Color("#8fa49b")
		elif status in ["failed", "expired"]:
			tint = Color("#ef8177")
		elif status == "cancelled":
			tint = Color("#81909c")
		var visual_style := mission_task_visual_style(owner)
		var alpha := float(visual_style.fill_alpha)
		var region: Array = task.get("region", [])
		if region.size() >= 3:
			var points := _canvas_polygon(region)
			var shaded := tint
			shaded.a = alpha
			draw_colored_polygon(points, shaded)
			var outline := tint
			outline.a = float(visual_style.outline_alpha)
			_draw_polygon_outline(points, outline, float(visual_style.outline_width))
			if not selected_agent.is_empty() and owner == selected_agent:
				var center := _polygon_bounds(points).get_center()
				var label_owner := owner if not owner.is_empty() else "unassigned"
				var task_label := "%s · %s" % [task_id, label_owner]
				_draw_label(_label_position(center, task_label), task_label, tint)
		var location: Variant = task.get("location")
		if location != null:
			var location_point := _to_canvas(float(location[0]), float(location[1]))
			var marker := PackedVector2Array([location_point + Vector2(0, -7), location_point + Vector2(7, 0), location_point + Vector2(0, 7), location_point + Vector2(-7, 0), location_point + Vector2(0, -7)])
			draw_polyline(marker, tint, 1.8, true)


func mission_task_visual_style(owner_id: String) -> Dictionary:
	var focused := not selected_agent.is_empty() and owner_id == selected_agent
	var unrelated := not selected_agent.is_empty() and not focused
	return {
		"fill_alpha": 0.10 if focused else (0.018 if unrelated else 0.04),
		"outline_alpha": 0.78 if focused else (0.08 if unrelated else 0.22),
		"outline_width": 1.6 if focused else 0.8,
	}


func _draw_agent_routes(agents: Array) -> void:
	for route_value in visible_agent_routes(agents):
		var route: Dictionary = route_value
		var points := PackedVector2Array()
		var position_value: Array = route.get("position", [])
		if position_value.size() >= 2:
			points.append(_to_canvas(float(position_value[0]), float(position_value[1])))
		var destination: Variant = route.get("destination")
		if destination != null:
			var point := _to_canvas(float(destination[0]), float(destination[1]))
			if points.is_empty() or not points[points.size() - 1].is_equal_approx(point):
				points.append(point)
		for waypoint in route.get("route_waypoints", []):
			var point := _to_canvas(float(waypoint[0]), float(waypoint[1]))
			if points.is_empty() or not points[points.size() - 1].is_equal_approx(point):
				points.append(point)
		var final_destination: Variant = route.get("final_destination")
		if final_destination != null:
			var point := _to_canvas(float(final_destination[0]), float(final_destination[1]))
			if points.is_empty() or not points[points.size() - 1].is_equal_approx(point):
				points.append(point)
		if points.size() < 2:
			continue
		var agent_index := _agent_index(agents, str(route.get("agent_id", "")))
		if agent_index < 0:
			continue
		var tint: Color = PALETTE[agent_index % PALETTE.size()]
		tint.a = 0.76 if selected_agent.is_empty() else 0.92
		draw_polyline(points, tint, 1.7, true)
		var endpoint := points[points.size() - 1]
		draw_arc(endpoint, 5.0, 0.0, TAU, 20, tint, 1.4)


func _draw_road_features(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		var kind := str(value.get("kind", "arterial"))
		var arterial := kind == "arterial" or kind == "road"
		var closed := points.duplicate()
		closed.append(points[0])
		draw_colored_polygon(points, Color("#4d514b") if arterial else Color("#626255"))
		draw_polyline(closed, Color("#2e332f", 0.9), 3.2, true)
		_draw_polygon_outline(points, Color("#8e927e", 0.62), 1.0)
		var bounds := _polygon_bounds(points)
		var from := Vector2(bounds.get_center().x, bounds.position.y + 3.0)
		var to := Vector2(bounds.get_center().x, bounds.end.y - 3.0)
		if bounds.size.x > bounds.size.y:
			from = Vector2(bounds.position.x + 3.0, bounds.get_center().y)
			to = Vector2(bounds.end.x - 3.0, bounds.get_center().y)
		if bounds.size.length() > 48.0:
			draw_dashed_line(from, to, Color("#c2b47b", 0.52 if arterial else 0.26), 1.1, 9.0, true)


func _draw_path_features(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		draw_colored_polygon(points, Color("#a69a76", 0.84))
		_draw_polygon_outline(points, Color("#d1c39b", 0.38), 1.0)


func _draw_parking_features(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		draw_colored_polygon(points, Color("#555a53", 0.94))
		_draw_polygon_outline(points, Color("#b4b6a3", 0.58), 1.0)
		var bounds := _polygon_bounds(points)
		var wide := bounds.size.x >= bounds.size.y
		var count := maxi(2, int((bounds.size.x if wide else bounds.size.y) / 9.0))
		for index in range(1, count):
			var fraction := float(index) / count
			var start := Vector2(lerpf(bounds.position.x, bounds.end.x, fraction), bounds.position.y + 2.0)
			var end := Vector2(start.x, bounds.end.y - 2.0)
			if not wide:
				start = Vector2(bounds.position.x + 2.0, lerpf(bounds.position.y, bounds.end.y, fraction))
				end = Vector2(bounds.end.x - 2.0, start.y)
			draw_line(start, end, Color("#d4d1bd", 0.42), 0.8, true)


func _draw_water_features(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var points := _canvas_polygon(value.get("vertices", []))
		if points.size() < 3:
			continue
		draw_colored_polygon(points, Color("#526d70", 0.94))
		_draw_polygon_outline(points, Color("#a8b1a0", 0.72), 1.6)
		var bounds := _polygon_bounds(points).grow(-4.0)
		for index in range(3):
			var y := lerpf(bounds.position.y, bounds.end.y, float(index + 1) / 4.0)
			draw_dashed_line(Vector2(bounds.position.x + 3.0, y), Vector2(bounds.end.x - 3.0, y + 2.0), Color("#a5b9ad", 0.20), 0.8, 13.0, true)


func _draw_vegetation_features(features: Array) -> void:
	for value in features:
		if not value is Dictionary:
			continue
		var vertices: Array = value.get("vertices", [])
		var points := _canvas_polygon(vertices)
		if points.size() < 3:
			continue
		var world_points := _world_polygon(vertices)
		draw_colored_polygon(points, Color("#2d4934", 0.55))
		var min_x := float("inf")
		var max_x := -INF
		var min_y := float("inf")
		var max_y := -INF
		for vertex in vertices:
			min_x = minf(min_x, float(vertex[0]))
			max_x = maxf(max_x, float(vertex[0]))
			min_y = minf(min_y, float(vertex[1]))
			max_y = maxf(max_y, float(vertex[1]))
		var x := min_x + 1.4
		while x < max_x:
			var row := int(floor((x - min_x) / 3.0))
			var y := min_y + 1.4 + (1.0 if row % 2 == 1 else 0.0)
			while y < max_y:
				if Geometry2D.is_point_in_polygon(Vector2(x, y), world_points):
					var point := _to_canvas(x, y)
					var jitter := absf(sin(x * 12.9898 + y * 78.233) * 43758.5453)
					var size_world := 1.9 + fposmod(jitter, 0.5)
					var sprite_size := _world_size_to_canvas(Vector2.ONE * size_world)
					var rotation := fposmod(jitter * 10.0, TAU)
					var shade := 0.78 + fposmod(jitter * 0.2, 0.2)
					_draw_sprite(TREE_TEXTURE, point, sprite_size, rotation, Color(shade, shade, shade, 0.92))
				y += 3.0
			x += 3.0
		_draw_polygon_outline(points, Color("#78906d", 0.46), 1.2)


func _draw_obstacle_feature(feature: Dictionary) -> void:
	var points := _canvas_polygon(feature.get("vertices", []))
	if points.size() < 3:
		return
	var kind := str(feature.get("kind", ""))
	var asset := obstacle_asset_kind(kind)
	var bounds := _polygon_bounds(points)
	if asset == "rock":
		draw_colored_polygon(points, Color("#39423b", 0.88))
		_draw_sprite(ROCK_TEXTURE, bounds.get_center(), bounds.size * 0.88, 0.0, Color.WHITE)
		return
	if asset == "wall":
		draw_colored_polygon(points, Color("#3a403b", 0.94))
		_draw_polygon_outline(points, Color("#b3ae93", 0.74), 1.2)
		return
	if asset == "water_tower":
		var center := bounds.get_center()
		draw_circle(center + Vector2(2.5, 3.0), minf(bounds.size.x, bounds.size.y) * 0.48, Color("#252b26", 0.48))
		draw_circle(center, minf(bounds.size.x, bounds.size.y) * 0.44, Color("#858776"))
		draw_arc(center, minf(bounds.size.x, bounds.size.y) * 0.44, 0.0, TAU, 36, Color("#d4d2bd", 0.72), 1.4)
		draw_arc(center, minf(bounds.size.x, bounds.size.y) * 0.22, 0.0, TAU, 32, Color("#4b584d", 0.76), 1.0)
		return
	var center := bounds.get_center()
	var shadow := PackedVector2Array()
	for point in points:
		shadow.append(point + Vector2(3.0, 4.0))
	draw_colored_polygon(shadow, Color("#171c18", 0.54))
	var roof_color := Color("#8b6b56") if kind == "residential_building" else Color("#777b72")
	if kind == "commercial_building":
		roof_color = Color("#89887b")
	draw_colored_polygon(points, Color("#4a5049"))
	var roof := PackedVector2Array()
	for point in points:
		roof.append(center + (point - center) * 0.82)
	draw_colored_polygon(roof, roof_color)
	_draw_polygon_outline(roof, Color("#c3b49a", 0.78), 1.0)
	var roof_bounds := _polygon_bounds(roof).grow(-3.5)
	if roof_bounds.size.x > 9.0 and roof_bounds.size.y > 7.0:
		var vent := Rect2(roof_bounds.get_center() - Vector2(roof_bounds.size.x * 0.12, 2.0), Vector2(roof_bounds.size.x * 0.24, 4.0))
		draw_rect(vent, Color("#d1c7a9", 0.86), true)
		draw_rect(vent, Color("#424843", 0.8), false, 0.8)
		var skylight := Rect2(roof_bounds.position + Vector2(2.5, 2.5), Vector2(maxf(3.0, roof_bounds.size.x * 0.12), maxf(2.2, roof_bounds.size.y * 0.16)))
		draw_rect(skylight, Color("#c4c1aa", 0.72), true)
		if kind in ["building", "hangar"]:
			var rib_count := maxi(2, int(roof_bounds.size.x / 7.0))
			for index in range(1, rib_count):
				var x := lerpf(roof_bounds.position.x, roof_bounds.end.x, float(index) / rib_count)
				draw_line(Vector2(x, roof_bounds.position.y), Vector2(x, roof_bounds.end.y), Color("#d9d5c4", 0.28), 0.7, true)


func _canvas_polygon(vertices: Array) -> PackedVector2Array:
	var points := PackedVector2Array()
	for vertex in vertices:
		if vertex is Array and vertex.size() >= 2:
			points.append(_to_canvas(float(vertex[0]), float(vertex[1])))
	return points


func _world_polygon(vertices: Array) -> PackedVector2Array:
	var points := PackedVector2Array()
	for vertex in vertices:
		if vertex is Array and vertex.size() >= 2:
			points.append(Vector2(float(vertex[0]), float(vertex[1])))
	return points


func _polygon_bounds(points: PackedVector2Array) -> Rect2:
	if points.is_empty():
		return Rect2()
	var bounds := Rect2(points[0], Vector2.ZERO)
	for point in points:
		bounds = bounds.expand(point)
	return bounds


func _draw_polygon_outline(points: PackedVector2Array, color: Color, width: float) -> void:
	if points.size() < 2:
		return
	var closed := points.duplicate()
	closed.append(points[0])
	draw_polyline(closed, color, width, true)


func _draw_selected_sensing_range(agents: Array) -> void:
	if not show_sensor_visibility or selected_agent.is_empty():
		return
	if detection_range <= 0.0:
		return
	for agent in agents:
		if str(agent.get("id", "")) != selected_agent:
			continue
		var center := _to_canvas(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
		var radius := _world_size_to_canvas(Vector2.ONE * detection_range)
		var fill_points := _ellipse_points(center, radius, 64)
		var fill_color := Color("#55c2ff", 0.055)
		draw_colored_polygon(fill_points, fill_color)
		fill_points.append(fill_points[0])
		draw_polyline(fill_points, Color("#8bd8ff", 0.48), 1.2, true)
		return


func _ellipse_points(center: Vector2, radius: Vector2, segments: int) -> PackedVector2Array:
	var points := PackedVector2Array()
	for index in range(segments):
		var angle := TAU * float(index) / float(segments)
		points.append(center + Vector2(cos(angle) * radius.x, sin(angle) * radius.y))
	return points


func _draw_communication_routes(agents: Array) -> void:
	for route_value in visible_communication_routes(agents):
		var route: Dictionary = route_value
		var from := _agent_position(agents, str(route.get("sender_id", "")))
		var to := _agent_position(agents, str(route.get("recipient_id", "")))
		var direction := to - from
		var length := direction.length()
		if length <= 30.0:
			continue
		direction /= length
		var perpendicular := Vector2(-direction.y, direction.x)
		var curve_amount := (float(posmod(str(route.get("key", "")).hash(), 5)) - 2.0) * 10.0
		if absf(curve_amount) < 4.0:
			curve_amount = 7.0 if str(route.sender_id) < str(route.recipient_id) else -7.0
		var control := (from + to) * 0.5 + perpendicular * curve_amount
		var start := from + direction * 13.0
		var finish := to - direction * 15.0
		var color := _route_color(str(route.get("state", "delivered")))
		if bool(route.get("pending", false)):
			color.a = 0.70 if selected_agent.is_empty() else 0.94
		else:
			var lifetime := DELIVERED_LINK_LIFETIME if str(route.state) == "delivered" else LOST_LINK_LIFETIME
			var age := maxi(0, current_tick - int(route.get("step", current_tick)))
			color.a = (0.66 if selected_agent.is_empty() else 0.90) * (1.0 - float(age) / float(lifetime + 1))
		var points := _quadratic_path(start, control, finish, 14)
		draw_polyline(points, color, 1.35, true)
		var end_direction := (finish - control).normalized()
		var end_normal := Vector2(-end_direction.y, end_direction.x)
		draw_line(finish, finish - end_direction * 5.0 + end_normal * 2.7, color, 1.25, true)
		draw_line(finish, finish - end_direction * 5.0 - end_normal * 2.7, color, 1.25, true)
		if bool(route.get("pending", false)):
			var sent_step := int(route.get("pending_sent_step", current_tick))
			var due_step := int(route.get("pending_due_step", current_tick + 1))
			var duration := maxi(1, due_step - sent_step)
			var progress := clampf(float(current_tick - sent_step) / float(duration), 0.0, 0.92)
			var pulse_position := _quadratic_point(start, control, finish, 0.08 + progress * 0.78)
			draw_circle(pulse_position, 3.0, Color("#ffd166"))


func _add_route(groups: Dictionary, event: Dictionary, state: String, event_step: int) -> void:
	var sender := str(event.get("sender_id", ""))
	var recipient := str(event.get("recipient_id", ""))
	if sender.is_empty() or recipient.is_empty() or sender == recipient:
		return
	var route_key := sender + "|" + recipient
	var message_id := str(event.get("message_id", ""))
	if not groups.has(route_key):
		groups[route_key] = {
			"key": route_key,
			"sender_id": sender,
			"recipient_id": recipient,
			"state": state,
			"step": event_step,
			"sort_step": event_step,
			"message_id": message_id,
			"pending": false,
		}
		return
	var route: Dictionary = groups[route_key]
	if event_step > int(route.get("step", -1)) or (event_step == int(route.get("step", -1)) and message_id > str(route.get("message_id", ""))):
		route["state"] = state
		route["step"] = event_step
		route["sort_step"] = event_step
		route["message_id"] = message_id


func _add_pending_route(groups: Dictionary, pending: Dictionary) -> void:
	var sender := str(pending.get("sender_id", ""))
	var recipient := str(pending.get("recipient_id", ""))
	if sender.is_empty() or recipient.is_empty() or sender == recipient:
		return
	var route_key := sender + "|" + recipient
	if not groups.has(route_key):
		groups[route_key] = {
			"key": route_key,
			"sender_id": sender,
			"recipient_id": recipient,
			"state": "delayed",
			"step": int(pending.get("sent_step", current_tick)),
			"sort_step": current_tick,
			"pending": true,
		}
	var route: Dictionary = groups[route_key]
	var sent_step := int(pending.get("sent_step", current_tick))
	if not bool(route.get("pending", false)) or sent_step >= int(route.get("pending_sent_step", -1)):
		route["pending_sent_step"] = sent_step
		route["pending_due_step"] = int(pending.get("delivery_step", sent_step + 1))
		route["pending_message_id"] = str(pending.get("message_id", ""))
	route["pending"] = true
	route["state"] = "delayed"
	route["sort_step"] = int(route.get("pending_sent_step", sent_step))


func _route_color(state: String) -> Color:
	match state:
		"delayed": return Color("#ffd166")
		"lost": return Color("#ff7d6e")
		_: return Color("#8fe388")


func _quadratic_path(start: Vector2, control: Vector2, finish: Vector2, segments: int) -> PackedVector2Array:
	var points := PackedVector2Array()
	for index in range(segments + 1):
		points.append(_quadratic_point(start, control, finish, float(index) / float(segments)))
	return points


func _quadratic_point(start: Vector2, control: Vector2, finish: Vector2, t: float) -> Vector2:
	var inverse := 1.0 - t
	return inverse * inverse * start + 2.0 * inverse * t * control + t * t * finish


func _draw_label(position: Vector2, text: String, color: Color) -> void:
	var font := ThemeDB.fallback_font
	var label_size := font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 11)
	var box := Rect2(position - Vector2(3, 12), label_size + Vector2(7, 5))
	draw_rect(box, Color(0.025, 0.055, 0.09, 0.9), true)
	draw_string(font, position, text, HORIZONTAL_ALIGNMENT_LEFT, -1, 11, color)


func _label_position(point: Vector2, text: String) -> Vector2:
	var text_width := ThemeDB.fallback_font.get_string_size(text, HORIZONTAL_ALIGNMENT_LEFT, -1, 11).x + 8.0
	var x := point.x + 16.0
	if x + text_width > size.x - 4.0:
		x = point.x - text_width - 8.0
	var y := point.y - 7.0
	if y < 16.0:
		y = point.y + 24.0
	return Vector2(clampf(x, 4.0, maxf(4.0, size.x - text_width - 4.0)), clampf(y, 14.0, maxf(14.0, size.y - 4.0)))


func _draw_sprite(texture: Texture2D, point: Vector2, target_size: Vector2, rotation: float, modulate: Color) -> void:
	if texture == null:
		return
	var texture_size := Vector2(texture.get_width(), texture.get_height())
	var sprite_scale := Vector2(target_size.x / texture_size.x, target_size.y / texture_size.y)
	draw_set_transform(point, rotation, sprite_scale)
	draw_texture(texture, -texture_size * 0.5, modulate)
	draw_set_transform(Vector2.ZERO, 0.0, Vector2.ONE)


func _agent_canvas_rotation(agent: Dictionary) -> float:
	var heading := float(agent.get("heading_rad", -PI * 0.5))
	var scale := _map_scale()
	var canvas_direction := Vector2(
		cos(heading) * scale.x,
		sin(heading) * scale.y
	)
	# The sprite's nose points upward; convert backend +X-based heading to it.
	return canvas_direction.angle() + PI * 0.5


func _agent_position(agents: Array, agent_id: String) -> Vector2:
	for agent in agents:
		if str(agent.get("id", "")) == agent_id:
			return _to_canvas(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
	return Vector2(-1.0, -1.0)


func _to_canvas(x: float, y: float) -> Vector2:
	if world_width <= 0.0 or world_height <= 0.0:
		return Vector2.ZERO
	var scale := _map_scale()
	return _map_screen_rect().position + Vector2(x * scale.x, y * scale.y)


func _to_world(point: Vector2) -> Vector2:
	var scale := _map_scale()
	if is_zero_approx(scale.x) or is_zero_approx(scale.y):
		return Vector2.ZERO
	var relative := point - _map_screen_rect().position
	return Vector2(relative.x / scale.x, relative.y / scale.y)


func _map_scale() -> Vector2:
	if world_width <= 0.0 or world_height <= 0.0:
		return Vector2.ZERO
	return Vector2(size.x / world_width, size.y / world_height) * camera_zoom


func _world_size_to_canvas(world_size: Vector2) -> Vector2:
	var scale := _map_scale()
	return Vector2(world_size.x * scale.x, world_size.y * scale.y)


func _map_screen_rect() -> Rect2:
	var extent := _world_size_to_canvas(Vector2(world_width, world_height))
	return Rect2((size - extent) * 0.5 + camera_pan, extent)


func _agent_index(agents: Array, agent_id: String) -> int:
	for index in range(agents.size()):
		if str(agents[index].get("id", "")) == agent_id:
			return index
	return -1


func _known_track_by_id(entity_id: String, owner_id: String = "") -> Dictionary:
	for track_value in world.get("tracks", []):
		if track_value is Dictionary and str(track_value.get("entity_id", "")) == entity_id and (owner_id.is_empty() or str(track_value.get("agent_id", "")) == owner_id):
			return track_value
	return {}


func _draw_track_marker(point: Vector2, track: Dictionary, color: Color, fresh: bool, shared: bool) -> void:
	var marker_color := color if fresh else color.darkened(0.38)
	_draw_sprite(CONTACT_TEXTURE, point, Vector2(23, 23), 0.0, Color(1.0, 1.0, 1.0, color.a))
	if shared:
		var diamond := PackedVector2Array([point + Vector2(0, -13), point + Vector2(13, 0), point + Vector2(0, 13), point + Vector2(-13, 0), point + Vector2(0, -13)])
		draw_polyline(diamond, Color("#f5f8fc", marker_color.a), 1.4, true)
	elif fresh:
		draw_arc(point, 13.0, 0.0, TAU, 28, marker_color, 1.4)
	else:
		for segment in range(8):
			var start := TAU * segment / 8.0
			draw_arc(point, 13.0, start, start + TAU / 16.0, 5, marker_color, 1.4)
	var entity_id := str(track.get("entity_id", ""))
	var owner_id := str(track.get("agent_id", ""))
	if (entity_id == hovered_entity_id and owner_id == hovered_track_agent_id) or (entity_id == selected_entity_id and owner_id == selected_track_agent_id):
		draw_arc(point, 16.0, 0.0, TAU, 32, Color("#ffe6a0", marker_color.a), 1.7)


func _gui_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion:
		var motion := event as InputEventMouseMotion
		if pointer_down and (int(motion.button_mask) & MOUSE_BUTTON_MASK_LEFT) != 0:
			if not pointer_panning and motion.position.distance_to(pointer_start) >= 4.0:
				pointer_panning = true
			if pointer_panning:
				camera_pan = pointer_pan_start + motion.position - pointer_start
				queue_redraw()
		_update_hover(motion.position)
		return
	if not event is InputEventMouseButton:
		return
	var mouse_event := event as InputEventMouseButton
	if mouse_event.button_index == MOUSE_BUTTON_WHEEL_UP and mouse_event.pressed:
		zoom_at(1.2, mouse_event.position)
		return
	if mouse_event.button_index == MOUSE_BUTTON_WHEEL_DOWN and mouse_event.pressed:
		zoom_at(1.0 / 1.2, mouse_event.position)
		return
	if mouse_event.button_index != MOUSE_BUTTON_LEFT:
		return
	if mouse_event.pressed:
		pointer_down = true
		pointer_panning = false
		pointer_start = mouse_event.position
		pointer_pan_start = camera_pan
		return
	if not pointer_down:
		return
	pointer_down = false
	if pointer_panning:
		pointer_panning = false
		return
	_handle_map_click(mouse_event.position)


func _handle_map_click(screen_position: Vector2) -> void:
	if not _map_screen_rect().has_point(screen_position):
		return
	var world_position := _to_world(screen_position)
	if world_position.x < 0.0 or world_position.x > world_width or world_position.y < 0.0 or world_position.y > world_height:
		return
	var agents: Array = world.get("agents", [])
	var nearest_agent := ""
	var nearest_agent_distance := 25.0
	for agent in agents:
		var point := _to_canvas(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
		var distance := point.distance_to(screen_position)
		if distance < nearest_agent_distance:
			nearest_agent_distance = distance
			nearest_agent = str(agent.get("id", ""))
	if not nearest_agent.is_empty():
		agent_selected.emit(nearest_agent)
		return
	var nearest_track := _nearest_known_track(screen_position, 15.0)
	if not nearest_track.is_empty():
		if not selected_agent.is_empty():
			agent_selected.emit("")
		selected_entity_id = str(nearest_track.get("entity_id", ""))
		selected_track_agent_id = str(nearest_track.get("agent_id", ""))
		entity_selected.emit(selected_entity_id, selected_track_agent_id)
		queue_redraw()
		return
	var cleared_entity_selection := not selected_entity_id.is_empty()
	selected_entity_id = ""
	selected_track_agent_id = ""
	if cleared_entity_selection:
		entity_selected.emit("", "")
	if allow_manual_destination and not selected_agent.is_empty():
		destination_requested.emit(selected_agent, world_position)
		return
	if not selected_agent.is_empty():
		agent_selected.emit("")
	else:
		queue_redraw()


func _update_hover(position: Vector2) -> void:
	if size.x <= 0.0 or size.y <= 0.0:
		return
	var old_agent := hovered_agent
	var old_entity := hovered_entity_id
	var old_track_agent := hovered_track_agent_id
	var old_poi := hovered_poi_id
	hovered_agent = ""
	hovered_entity_id = ""
	hovered_track_agent_id = ""
	hovered_poi_id = ""
	var agents: Array = world.get("agents", [])
	var best_agent := ""
	var best_distance := 24.0
	for agent in agents:
		var point := _to_canvas(float(agent.get("x", 0.0)), float(agent.get("y", 0.0)))
		var distance := point.distance_to(position)
		if distance < best_distance:
			best_distance = distance
			best_agent = str(agent.get("id", ""))
	if not best_agent.is_empty():
		var track_count := 0
		for track in world.get("tracks", []):
			if str(track.get("agent_id", "")) == best_agent:
				track_count += 1
		tooltip_text = "%s · virtual UAV · %d local/shared tracks · click to inspect" % [best_agent, track_count]
		hovered_agent = best_agent
		mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
		if old_agent != hovered_agent or old_entity != hovered_entity_id or old_track_agent != hovered_track_agent_id or old_poi != hovered_poi_id:
			queue_redraw()
		return
	var best_track := _nearest_known_track(position, 15.0)
	if not best_track.is_empty():
		hovered_entity_id = str(best_track.get("entity_id", ""))
		hovered_track_agent_id = str(best_track.get("agent_id", ""))
		var owner := str(best_track.get("agent_id", "agent"))
		var source := str(best_track.get("source_agent_id", owner))
		var age := current_tick - int(best_track.get("observed_at", 0))
		var freshness := "fresh" if age <= max_track_age_steps else "stale"
		var provenance := "local observation" if owner == source else "shared from " + source
		tooltip_text = "%s · %s knows %s · %s · age %d ticks" % [str(best_track.get("entity_id", "track")), owner, provenance, freshness, age]
		mouse_default_cursor_shape = Control.CURSOR_POINTING_HAND
	else:
		var point_feature := _nearest_point_feature(position, 10.0)
		if not point_feature.is_empty():
			hovered_poi_id = str(point_feature.get("id", ""))
			tooltip_text = "%s · map point of interest (%s)" % [hovered_poi_id, str(point_feature.get("kind", "feature"))]
			mouse_default_cursor_shape = Control.CURSOR_ARROW
		else:
			tooltip_text = ""
			mouse_default_cursor_shape = Control.CURSOR_ARROW
	if old_agent != hovered_agent or old_entity != hovered_entity_id or old_track_agent != hovered_track_agent_id or old_poi != hovered_poi_id:
		queue_redraw()


func _nearest_known_track(position: Vector2, max_distance: float) -> Dictionary:
	var best_track: Dictionary = {}
	var best_distance := max_distance
	for track in visible_tracks(world.get("agents", [])):
		if not track is Dictionary:
			continue
		if not selected_agent.is_empty() and str(track.get("agent_id", "")) != selected_agent:
			continue
		var point := _to_canvas(float(track.get("x", 0.0)), float(track.get("y", 0.0)))
		var distance := point.distance_to(position)
		if distance < best_distance:
			best_distance = distance
			best_track = track
	return best_track


func _nearest_point_feature(position: Vector2, max_distance: float) -> Dictionary:
	var best_feature: Dictionary = {}
	var best_distance := max_distance
	for feature in visible_point_features():
		var point := _to_canvas(float(feature.get("x", 0.0)), float(feature.get("y", 0.0)))
		var distance := point.distance_to(position)
		if distance < best_distance:
			best_distance = distance
			best_feature = feature
	return best_feature
