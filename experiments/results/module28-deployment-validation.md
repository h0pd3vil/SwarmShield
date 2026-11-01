# Module 28: four-UAV deployment validation

## Change and engine check

The three bundled missions now contain four dispersed survey sectors, one for each of the four UAVs. All task destinations lie outside the assigned UAV's initial sensor range. The seed-42 `shared_awareness` run assigned four distinct tasks and completed all four. UAV distances were 27.4, 39.4, 24.4, and 21.3 world units for `agent-001` through `agent-004`; the other two bundled missions also assigned and completed all four tasks on seed 42.

The map now renders at most one freshest contact marker per entity. When an agent is selected, the map uses only that agent's stored local/shared tracks. This prevents repeated reports from stacking into several apparent entity icons while preserving each agent's complete track state in the inspector and backend.

## Matched sharing check

To check mission behavior after changing the sector layout, the actual `shared_awareness` mission was run for 100 ticks under independent and cooperative sharing, with fixed-priority scheduling held constant and seeds **42–46** matched. Every run completed all four spatial tasks, reached 100% sampled task-area coverage, and had zero mission-task deadline misses. The comparison artifact with all ten run IDs, raw metrics, objective values, and paired differences is [`matched-sharing-20261031T064225Z-7b0d3340.json`](../../runs/comparisons/matched-sharing-20261031T064225Z-7b0d3340.json).

| Metric | Independent mean | Cooperative mean | Cooperative minus independent (paired 95% descriptive t interval) |
|---|---:|---:|---:|
| Mean per-agent track coverage | 16.25% | 60.00% | **+43.75 pp** [+38.91, +48.59] |
| Any-agent awareness coverage | 65.00% | 65.00% | 0.00 pp [0.00, 0.00] |
| Spatial task completion | 100% | 100% | 0.00 pp [0.00, 0.00] |
| Sampled task-area coverage | 100% | 100% | 0.00 pp [0.00, 0.00] |
| Total UAV distance | 112.47 | 112.47 | 0.00 [0.00, 0.00] |

The configured mission objectives passed in **5/5 cooperative runs and 0/5 independent runs**. Team coverage exceeded its 50% target in both treatments; cooperative sharing raised per-agent coverage above its 40% target on every paired seed. The score difference was +0.50 with a descriptive interval of [-1.04, +2.03], so the provisional composite score does not show a consistent difference here.

| Seed | Independent local coverage | Cooperative local coverage | Independent / cooperative mission result |
|---:|---:|---:|---|
| 42 | 18.75% | 62.50% | Failure / Success |
| 43 | 14.58% | 58.33% | Failure / Success |
| 44 | 18.75% | 68.75% | Failure / Success |
| 45 | 14.58% | 54.17% | Failure / Success |
| 46 | 14.58% | 56.25% | Failure / Success |

## Limits

The comparison uses five seeds and descriptive paired Student-t intervals, not significance tests. These results are conditional on the bundled synthetic world and current sensing/task rules. Godot verification is headless and checks map state and rendering selection logic rather than comparing GPU screenshots.
