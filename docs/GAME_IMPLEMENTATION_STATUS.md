# Game Implementation Status

This page summarizes the current repository, not the initial baseline. The module-by-module history and exact test record are in [Implementation Progress](IMPLEMENTATION_PROGRESS.md).

## Current implementation

- Python owns a deterministic fixed-tick 2D simulation, seeded independent random streams, typed map geometry, synthetic moving entities, UAV motion/battery, deterministic A* route planning, heading/FOV/range/LOS sensing, local agent tracks, and delayed/lossy/duplicating peer messages.
- Spatial mission tasks have centralized feasibility-based assignment, autonomous routing, guarded evidence-based lifecycle states, inclusive deadlines, automatic unavailable-owner reassignment, and low-battery return behavior. Decision-queue work, abstract review tasks, and spatial mission tasks remain separate models.
- Godot 4 is a presentation and input layer. Its map uses original UAV/contact artwork, a synthetic satellite-inspired ground texture, and roads/buildings/vegetation/overlays placed from backend geometry. It displays one freshest marker per known entity; selecting an agent filters markers to that UAV's own local/shared view. It never renders raw evaluator truth as known contact data.
- Map controls change rendering only. Communication links default off and draw only recent actual backend events or current pending messages. UAVs, tasks/routes, terrain, mission areas, caution/restricted/protection zones, local/shared/stale tracks, fog, sensor range, labels, and grid can be controlled independently. Unselected task regions are visually subdued. Zoom, drag pan, fit/reset, and zoom-to-selection preserve world-coordinate input mapping.
- Restricted-zone policy is enforced by Python movement and navigation checks, with actual entry, exit, warning, and denied-entry events. Entity protection starts only from a fresh known track and creates a backend task whose completion requires repeated local observation evidence within the configured perimeter.
- Supported in-run player interventions are scheduler policy change, a validated destination for an eligible free UAV, and mission-task reassignment. Python accepts or rejects and records each command in the event stream and `interventions.json`.
- Matched scheduler and sharing comparisons run actual mission tasks on the same selected seed set, save every treatment through the normal artifact writer, and include per-seed differences plus descriptive 95% paired Student-t intervals.
- The original Python CLI, task-free batch runner, configuration-based communication/workload sweeps, and optional Streamlit dashboard continue to work without Godot.

## Launch

From the repository root:

```bash
godot --path game
```

Headless Python run:

```bash
python3 -m swarmshield.runner --config configs/baseline.json --mode cooperative --policy edf
```

See [README](../README.md) for installation requirements, controls, artifact locations, and batch commands.

## Verification

The latest full regression gate passed:

- `python3 -m unittest discover -s tests -v` — **144 tests passed**.
- `python3 -m compileall -q swarmshield app.py experiments tests game/python_bridge.py` — passed.
- Godot 4.7.2 editor import, headless `test_world_view.gd`, `test_mission_view.gd`, `test_results_view.gd`, `test_game_flow.gd`, and `godot --headless --path ./game --quit-after 5` — passed.
- The end-to-end Godot scene started the Python bridge, ran the selected seed-42 mission to tick 100, opened an agent inspector, and displayed a successful engine result. The four distinct UAV deployments completed the configured spatial tasks.
- The Python suite includes the archived task-free baseline summary/event equality check and batch CSV tests.
- A separate seed-42 100-tick Python demo accepted protection designation from a fresh agent track, completed its evidence task, moved all four UAVs and synthetic entities, and recorded actual delivered/dropped peer messages. Exact commands and limits are in [Terrain Map Upgrade](TERRAIN_MAP_UPGRADE.md).

Each bundled mission now assigns four spatial survey sectors to four distinct UAVs, with routes that carry them beyond their initial sensing range. See the [Module 28 deployment report](../experiments/results/module28-deployment-validation.md) for matched outcome checks after this change. The earlier [Module 26 sharing report](../experiments/results/module26-sharing-validation.md) records the former three-sector layout and is not a result for the current mission layout.

Exact module results and the next research experiment are tracked in [Implementation Progress](IMPLEMENTATION_PROGRESS.md).

## Limits

- UAV assignment and behavior are centralized, not distributed. The network partition is global; communication has no physical transport, bandwidth, hop routing, or obstacle-based radio occlusion.
- Sensor-footprint area coverage is a deterministic geometric 2-world-unit sample and does not model probabilistic detection.
- The ground artwork is synthetic rather than georeferenced imagery. Optional fog uses a coarse sensor footprint grid and report-applied sharing; peer footprints travel with real entity-observation reports, not standalone empty-area coverage messages. It shows sensing footprint, not guaranteed entity detection.
- Composite game-score weights are provisional. Mission success is determined by each mission's configured engine objectives; spatial task state affects results only when a configured objective explicitly references its metric.
- Matched t intervals are descriptive, rely on seed-level paired differences, and do not constitute a significance test or multiple-comparison correction.
- Godot tests validate map/panel state and bridge flow headlessly; they do not perform GPU screenshot comparisons across window sizes. Dashboard browser interaction was not re-run in this module sequence.
- This workspace has no Git metadata, so manifests cannot store a source commit and `git status` cannot be reported.
