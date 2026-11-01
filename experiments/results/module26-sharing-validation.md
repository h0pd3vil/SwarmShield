# Module 26: matched sharing validation

> Historical result for the former three-sector mission configuration. The currently bundled missions use four dispersed sectors; see the [Module 28 deployment validation](module28-deployment-validation.md) for results from the current configuration.

## Question and design

For the bundled **Shared Awareness** mission, how does cooperative peer sharing compare with independent local sensing when the scheduler and task behavior are held constant? The comparison ran the actual mission-backed engine for 100 logical ticks with fixed-priority scheduling and matched seeds **42–46**. The treatment contrast is cooperative minus independent. Each seed produced a normal run artifact; the comparison manifest and raw paired values are in [`matched-sharing-20261031T061213Z-b7330ecb.json`](../../runs/comparisons/matched-sharing-20261031T061213Z-b7330ecb.json).

## Results

| Metric | Independent mean | Cooperative mean | Paired difference (95% descriptive Student-t interval) |
|---|---:|---:|---:|
| Mean per-agent track coverage | 12.08% | 46.67% | **+34.58 pp** [+26.49, +42.68] |
| Any-agent awareness coverage | 48.33% | 48.33% | 0.00 pp [0.00, 0.00] |
| Spatial mission task completion | 100% | 100% | 0.00 pp [0.00, 0.00] |
| Spatial mission area coverage | 100% | 100% | 0.00 pp [0.00, 0.00] |
| Game score | 79.334 | 81.694 | +2.36 [+1.33, +3.39] |

The configured mission objectives passed in **0/5 independent runs** and **3/5 cooperative runs**. Cooperative runs met both coverage thresholds for seeds 42, 45, and 46; neither treatment met the team-coverage threshold for seeds 43 and 44. Every run completed the configured spatial tasks and reached full sampled mission-area coverage, so task execution and overall objective success are distinct outcomes in this mission. Per-seed objective values and all ten run IDs are recorded in the comparison artifact.

| Seed | Mean local coverage: independent | Mean local coverage: cooperative | Mission result: independent / cooperative |
|---:|---:|---:|---|
| 42 | 14.58% | 56.25% | Failure / Success |
| 43 | 10.42% | 41.67% | Failure / Failure |
| 44 | 10.42% | 35.42% | Failure / Failure |
| 45 | 12.50% | 50.00% | Failure / Success |
| 46 | 12.50% | 50.00% | Failure / Success |

## Interpretation and limits

Under these settings, sharing increased average local track coverage on all five paired seeds while the union of team awareness, spatial task completion, and sampled mission-area coverage stayed the same. This is consistent with sharing redistributing already available knowledge across agents and helping more runs meet the configured per-agent awareness objective. The result applies only to this scenario, policy, engine version, and five seeds.

Intervals are descriptive paired Student-t intervals with `n=5`; they are not significance tests. Seeds do not guarantee identical later random draws between treatments. The composite game score uses provisional weights and is not a research endpoint. The comparison does not establish general superiority or real-world performance.
