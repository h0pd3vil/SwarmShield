extends RefCounted
class_name PythonBridge

const PROTOCOL_VERSION := 1
const RESPONSE_TIMEOUT_MS := 3000
const COMPARISON_TIMEOUT_MS := 15000

var stdio: FileAccess
var stderr_pipe: FileAccess
var process_id := -1
var next_request_id := 1
var receive_buffer := ""


func start() -> bool:
	if is_alive():
		return true
	var python_path := OS.get_environment("SWARMSHIELD_PYTHON")
	if python_path.is_empty():
		python_path = "python" if OS.get_name() == "Windows" else "python3"
	var script_path := ProjectSettings.globalize_path("res://python_bridge.py")
	var process := OS.execute_with_pipe(python_path, PackedStringArray(["-u", script_path]), false)
	if process.is_empty():
		return false
	stdio = process.get("stdio") as FileAccess
	stderr_pipe = process.get("stderr") as FileAccess
	process_id = int(process.get("pid", -1))
	if stdio == null or process_id <= 0:
		_terminate_process()
		return false
	return true


func is_alive() -> bool:
	return stdio != null and process_id > 0


func request(command: String, payload: Dictionary = {}, timeout_ms: int = RESPONSE_TIMEOUT_MS) -> Dictionary:
	if not is_alive() and not start():
		return {"ok": false, "error": {"code": "startup_failed", "message": "Could not launch the Python backend. Set SWARMSHIELD_PYTHON if needed."}}
	var request_id := next_request_id
	next_request_id += 1
	var request_data := {
		"version": PROTOCOL_VERSION,
		"request_id": request_id,
		"command": command,
		"payload": payload,
	}
	stdio.store_string(JSON.stringify(request_data) + "\n")
	stdio.flush()
	if stdio.get_error() != OK:
		return _process_error("Could not write to the Python backend.")
	var started_at := Time.get_ticks_msec()
	while Time.get_ticks_msec() - started_at < timeout_ms:
		var newline_index := receive_buffer.find("\n")
		if newline_index >= 0:
			var line := receive_buffer.substr(0, newline_index)
			receive_buffer = receive_buffer.substr(newline_index + 1)
			var parsed: Variant = JSON.parse_string(line)
			if not parsed is Dictionary:
				_terminate_process()
				return {"ok": false, "error": {"code": "malformed_response", "message": "Python returned malformed JSON."}}
			if parsed.get("request_id") != request_id:
				_terminate_process()
				return {"ok": false, "error": {"code": "request_mismatch", "message": "Python response did not match the request."}}
			return parsed
		var available := stdio.get_length()
		if available > 0:
			receive_buffer += stdio.get_buffer(available).get_string_from_utf8()
		elif stdio.get_error() not in [OK, ERR_FILE_EOF]:
			return _process_error("The Python process closed its output pipe.")
		_read_diagnostics()
		OS.delay_msec(2)
	_terminate_process()
	return {"ok": false, "error": {"code": "response_timeout", "message": "The Python backend did not answer within %d milliseconds." % timeout_ms}}


func close() -> void:
	if not is_alive():
		return
	request("shutdown")
	_terminate_process()


func _terminate_process() -> void:
	var old_process_id := process_id
	if stdio != null:
		stdio.close()
	if stderr_pipe != null:
		stderr_pipe.close()
	stdio = null
	stderr_pipe = null
	process_id = -1
	var exit_deadline := Time.get_ticks_msec() + 250
	while old_process_id > 0 and OS.is_process_running(old_process_id) and Time.get_ticks_msec() < exit_deadline:
		OS.delay_msec(5)
	if old_process_id > 0 and OS.is_process_running(old_process_id):
		OS.kill(old_process_id)


func _read_diagnostics() -> void:
	if stderr_pipe == null:
		return
	var available := stderr_pipe.get_length()
	if available > 0:
		var diagnostics := stderr_pipe.get_buffer(available).get_string_from_utf8()
		if not diagnostics.is_empty():
			push_warning("Python backend: " + diagnostics.strip_edges())


func _process_error(message: String) -> Dictionary:
	_terminate_process()
	return {"ok": false, "error": {"code": "process_error", "message": message}}
