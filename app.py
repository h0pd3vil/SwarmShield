"""Optional Streamlit dashboard for real SwarmShield engine output."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import replace
import io
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import plotly.graph_objects as go
    import streamlit as st
except ImportError as error:  # pragma: no cover - exercised only without optional UI dependencies
    raise SystemExit(
        "Dashboard dependencies are optional. Install them with: "
        "python3 -m pip install streamlit plotly"
    ) from error

from swarmshield.config import load_config
from swarmshield.runner import EVENT_FIELDS, run_simulation


def _format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _format_steps(value: int | None) -> str:
    return "n/a" if value is None else f"{value} steps"


def _events_csv(events: list[dict[str, object]]) -> str:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=EVENT_FIELDS)
    writer.writeheader()
    writer.writerows(events)
    return stream.getvalue()


st.set_page_config(page_title="SwarmShield", layout="wide")
st.title("SwarmShield")
st.caption("Synthetic multi-agent awareness and deadline-scheduling simulation")
st.info(
    "Simulation only: entities, observations, messages, and abstract review tasks are synthetic. "
    "Displayed values come from the simulation engine and evaluator."
)

config_path = PROJECT_ROOT / "configs" / "baseline.json"
base_config = load_config(config_path)

with st.sidebar:
    st.header("Scenario")
    mode = st.selectbox("Information sharing", ("independent", "cooperative"))
    policy = st.selectbox("Decision scheduler", ("fixed-priority", "edf"))
    coordination_mode = st.selectbox("Task coordination", ("centralized", "decentralized"))
    seed = st.number_input("Random seed", min_value=0, value=base_config.seed, step=1)
    steps = st.number_input("Simulation steps", min_value=1, max_value=5000, value=base_config.steps, step=10)
    run_button = st.button("Run selected scenario", type="primary")
    compare_button = st.button("Compare scheduler policies")

config = replace(
    base_config,
    seed=int(seed),
    steps=int(steps),
    coordination_mode=coordination_mode,
)

if run_button:
    summary, events = run_simulation(config, mode, policy)
    st.session_state["swarmshield_run"] = {"summary": summary, "events": events}
    st.session_state.pop("swarmshield_comparison", None)

if compare_button:
    comparison = {}
    for selected_policy in ("fixed-priority", "edf"):
        summary, events = run_simulation(config, mode, selected_policy)
        comparison[selected_policy] = {"summary": summary, "events": events}
    st.session_state["swarmshield_comparison"] = comparison
    st.session_state["swarmshield_run"] = comparison[policy]

comparison = st.session_state.get("swarmshield_comparison")
if comparison:
    st.subheader("Matched policy comparison")
    comparison_rows = []
    for selected_policy, data in comparison.items():
        comparison_rows.append(
            {
                "policy": selected_policy,
                "deadline miss rate": data["summary"]["metrics"]["deadline_miss_rate"],
                "decision P95 (steps)": data["summary"]["metrics"]["decision_latency_p95_steps"],
                "mean queue backlog": data["summary"]["metrics"]["mean_queue_backlog_tasks"],
                "awareness coverage": data["summary"]["metrics"]["any_agent_awareness_coverage"],
            }
        )
    st.dataframe(comparison_rows, use_container_width=True, hide_index=True)

run_data = st.session_state.get("swarmshield_run")
if not run_data:
    st.write("Choose a scenario and run it to view engine state and measured results.")
    st.stop()

summary = run_data["summary"]
events = run_data["events"]
metrics = summary["metrics"]
st.subheader(f"Run results · {summary['mode']} · {summary['scheduler_policy']} · seed {summary['seed']}")

metric_columns = st.columns(4)
metric_columns[0].metric("Awareness coverage", f"{metrics['any_agent_awareness_coverage']:.1%}")
metric_columns[1].metric("Deadline miss rate", _format_percent(metrics["deadline_miss_rate"]))
metric_columns[2].metric("Decision P95", _format_steps(metrics["decision_latency_p95_steps"]))
metric_columns[3].metric("Message delivery", _format_percent(metrics["message_delivery_ratio"]))

coordination_columns = st.columns(4)
coordination_columns[0].metric("Review tasks completed", str(metrics["coordination_tasks_completed"]))
coordination_columns[1].metric("Assignment conflicts", str(metrics["assignment_conflicts"]))
coordination_columns[2].metric("Capacity violations", str(metrics["capacity_violations"]))
coordination_columns[3].metric("Wall runtime", f"{metrics['wall_clock_runtime_seconds']:.3f} s")

snapshots = [event for event in events if event["event_type"] == "simulation_snapshot"]
if snapshots:
    snapshot_by_step = {int(event["step"]): json.loads(str(event["details"])) for event in snapshots}
    available_steps = sorted(snapshot_by_step)
    selected_step = st.slider(
        "Simulation step",
        min_value=available_steps[0],
        max_value=available_steps[-1],
        value=available_steps[-1],
    )
    snapshot = snapshot_by_step[selected_step]
    zone = snapshot["protected_zone"]
    figure = go.Figure()
    figure.add_shape(
        type="circle",
        x0=zone["x"] - zone["radius"],
        y0=zone["y"] - zone["radius"],
        x1=zone["x"] + zone["radius"],
        y1=zone["y"] + zone["radius"],
        line={"color": "#d62728", "dash": "dash"},
        fillcolor="rgba(214,39,40,0.08)",
    )
    figure.add_trace(
        go.Scatter(
            x=[entity["x"] for entity in snapshot["entities"]],
            y=[entity["y"] for entity in snapshot["entities"]],
            mode="markers+text",
            text=[entity["id"] for entity in snapshot["entities"]],
            textposition="top center",
            name="Synthetic entities",
            marker={"size": 10, "color": "#e0a800", "symbol": "circle"},
        )
    )
    figure.add_trace(
        go.Scatter(
            x=[agent["x"] for agent in snapshot["agents"]],
            y=[agent["y"] for agent in snapshot["agents"]],
            mode="markers+text",
            text=[agent["id"] for agent in snapshot["agents"]],
            textposition="bottom center",
            name="Virtual observers",
            marker={"size": 14, "color": "#1f77b4", "symbol": "diamond"},
        )
    )
    for agent in snapshot["agents"]:
        agent_tracks = [
            track
            for track in snapshot["tracks"]
            if track["agent_id"] == agent["id"]
            and selected_step - track["observed_at"] <= config.max_track_age_steps
        ]
        figure.add_trace(
            go.Scatter(
                x=[track["x"] for track in agent_tracks],
                y=[track["y"] for track in agent_tracks],
                mode="markers",
                name=f"Tracks · {agent['id']}",
                marker={"size": 8, "symbol": "x"},
                text=[track["entity_id"] for track in agent_tracks],
                hovertemplate="%{text}<extra>%{fullData.name}</extra>",
            )
        )
    figure.update_layout(
        title=f"Engine state at step {selected_step}",
        xaxis_title="World X",
        yaxis_title="World Y",
        xaxis={"range": [0, config.world_width], "scaleanchor": "y"},
        yaxis={"range": [0, config.world_height]},
        height=650,
        legend={"orientation": "h"},
    )
    st.plotly_chart(figure, use_container_width=True)
else:
    st.warning("No simulation snapshots were returned by the engine.")

st.subheader("Message and task event timeline")
timeline_types = (
    "message_sent",
    "message_delivered",
    "message_dropped",
    "task_completed",
    "task_expired",
    "coordination_task_completed",
    "assignment_conflict",
)
timeline_counts = Counter(
    (int(event["step"]), str(event["event_type"]))
    for event in events
    if event["event_type"] in timeline_types
)
timeline = go.Figure()
for event_type in timeline_types:
    timeline.add_trace(
        go.Scatter(
            x=available_steps if snapshots else [],
            y=[timeline_counts[(step, event_type)] for step in available_steps] if snapshots else [],
            mode="lines+markers",
            name=event_type.replace("_", " "),
        )
    )
timeline.update_layout(
    xaxis_title="Simulation step",
    yaxis_title="Events per step",
    height=360,
    legend={"orientation": "h"},
)
st.plotly_chart(timeline, use_container_width=True)

with st.expander("Recent task and message events"):
    relevant_events = [
        event for event in events
        if event["event_type"] in timeline_types or event["event_type"].startswith("coordination_task_")
    ]
    st.dataframe(relevant_events[-100:], use_container_width=True, hide_index=True)

with st.expander("All measured metrics"):
    st.json(metrics)

event_csv = _events_csv(events)
summary_json = json.dumps(summary, indent=2, sort_keys=True)
download_columns = st.columns(2)
download_columns[0].download_button(
    "Download event log CSV",
    data=event_csv,
    file_name="swarmshield_events.csv",
    mime="text/csv",
)
download_columns[1].download_button(
    "Download run summary JSON",
    data=summary_json,
    file_name="swarmshield_summary.json",
    mime="application/json",
)
