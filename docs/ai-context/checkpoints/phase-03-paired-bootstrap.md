# Phase 03 Paired Bootstrap and Holm Inference

- status: `COMPLETE / VERIFIED / TWO FORMAL COMPARISONS`
- implementation_commit: `db6efe20a6317edac47343d1c713e9f4ec51263b`
- date: 2026-07-23 CST

## Frozen contract

`src/kairos/statistical_artifacts.py` publishes prediction- and
metrics-bound comparisons at
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/<comparison-id>`.
Each immutable 0700 directory contains one canonical 0600
`statistics.json` and a manifest-last 0600 `manifest.json`; files require
`nlink=1` and existing targets are never replaced.

All contrasts are `candidate - reference`. The fixed bootstrap uses 10,000
resamples, seed 20260723 and an explicitly implemented SplitMix64 index
generator. TORQUE resamples all 571 `(passage_id, cluster_id)` groups and
preserves the variable question count within a sampled group; TimeQA resamples
989 records. Intervals are linear-interpolated percentile 95% intervals.
Two-sided bootstrap sign p-values use add-one correction, and Holm correction
is applied across all reported metrics within each dataset comparison.

Publication verifies both prediction and metrics artifacts, replays fixed
source scoring, checks clean exact Git before target creation and before
manifest, then repeats the complete computation. Offline verification ignores
stored result authority and independently recomputes the comparison.

## Development verification

- focused suite: 6/6 passed in 1.045 seconds;
- full repository suite: 471/471 passed in 14.807 seconds;
- GPU hidden; CPU threads fixed to two;
- tests cover both bootstrap units, deterministic replay, no-replace,
  input change between gates, rehashed result tampering, manifest binding,
  exact file set and file modes.

## TORQUE CoT minus Direct

Comparison ID:
`paired-torque-dev-cot-vs-direct-43410b587f33`

| Metric (%) | Direct | CoT | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Question set EM | 15.643965 | 12.609575 | -3.034390 | [-4.410821, -1.708817] | 0.000200 | 0.000800 |
| Question set F1 | 16.069850 | 12.777831 | -3.292019 | [-4.673535, -1.953807] | 0.000200 | 0.000800 |
| Cluster exact | 1.576182 | 1.225919 | -0.350263 | [-1.225919, 0.525394] | 0.562944 | 1.000000 |
| Cluster F1>=0.8 | 1.576182 | 1.225919 | -0.350263 | [-1.225919, 0.525394] | 0.562944 | 1.000000 |

Artifact path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-cot-vs-direct-43410b587f33`

- aggregation commit/time: `db6efe20a6317edac47343d1c713e9f4ec51263b`,
  `2026-07-23T14:04:00Z`
- statistics: 3,757 bytes, SHA256
  `38646b8241d4c7a9985ca24a616261e393a301d42ff67dfeb7037f7d29b9044c`
- manifest: 764 bytes, SHA256
  `d1b08455308b8b3bb721aadde1abfafe626d3ebf93bb1fbc77cb68f5d0efeb7a`

The question-level negative difference is statistically supported under the
frozen group bootstrap. The cluster metrics are not distinguishable. This is
a negative prompt-baseline result, not evidence about Kairos because no
trained Kairos or matched-supervision run is in the contrast.

## TimeQA-Hard CoT minus Direct strict primary

Comparison ID:
`paired-timeqa-hard-cot-vs-direct-a03673eba45e`

| Metric (%) | Direct | CoT | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Normalized EM | 0.000000 | 0.505561 | +0.505561 | [0.101112, 1.011122] | 0.015198 | 0.030397 |
| Token F1 | 0.000000 | 0.505561 | +0.505561 | [0.101112, 1.011122] | 0.015198 | 0.030397 |

Artifact path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-timeqa-hard-cot-vs-direct-a03673eba45e`

- aggregation commit/time: `db6efe20a6317edac47343d1c713e9f4ec51263b`,
  `2026-07-23T14:05:00Z`
- statistics: 3,122 bytes, SHA256
  `d1b5c7a908008fedbc0631965583d5d00861952b49347d19114ceceb555dab93`
- manifest: 765 bytes, SHA256
  `a44331e9ffa3c0a40e8d7e1e480e89af046a88107a3857f86853f2f98a4e823e`

The strict metric difference is statistically nonzero under the frozen record
bootstrap, but it reflects approximately five CoT exact answers against zero
Direct exact answers while 969/989 and 986/989 outputs respectively fail the
strict parser. It is evidence about the frozen prompt/parser interaction, not
evidence that CoT improves temporal reasoning. D-019 remains unchanged; no
post-hoc output recovery was used.

Both comparison directories passed a separate fresh-process offline replay
after publication. No raw response or sample content was printed or committed.
