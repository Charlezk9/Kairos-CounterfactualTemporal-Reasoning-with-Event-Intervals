# Phase 03 TORQUE LLM-Graph Baseline

- status: `COMPLETE / VERIFIED / SIGNIFICANT NEGATIVE RESULT`
- run_id: `20260723T165048Z-llm-graph-torque-dev-s13-d52c57809644`
- execution_commit: `99209b4445df3a25fe678e3223cceac2c84e0041`
- date: 2026-07-24 CST

## Frozen structured method

The gold-free prompt contains only the TORQUE passage and question. It requires a
strict penultimate `TEMPORAL_GRAPH` JSON line followed by the existing terminal
`FINAL_ANSWER` JSON string-array line. Graph nodes use unique `E1`--`E999` IDs
and exact passage-substring event spans. Edges bind existing, distinct nodes and
use exactly one of `precedes/follows/overlaps/contains/during`. A non-empty final
answer must match a graph event under the frozen TORQUE normalizer. Empty graphs
and empty answers are allowed.

Malformed JSON, duplicate keys/IDs/edges, unbound edges, non-passage event spans,
missing/relocated graph lines and answers not bound to a graph event all fail the
entire record to the existing sentinel. The method is greedy, seed 13, batch 8,
`max_new_tokens=768`, with no gold or candidate injection. Raw graph and answer
responses stay only in the private evidence artifact; the offline verifier reloads
fixed TORQUE dev and reparses every record.

Implementation commit `6c30c83668095b246e64c9873c852ae5b06e0fb7` added
the module and six focused tests. A cleanup immediately after the tested snapshot
incorrectly removed the runtime `Tensor` import; the first GPU smoke therefore
failed at its post-generation shape check with no artifact. Commit
`99209b4445df3a25fe678e3223cceac2c84e0041` restored it, after which focused
6/6 and full 515/515 passed in 15.500 seconds. The incident is retained rather
than hidden.

## Preflight and resources

Full 1,483-record token preflight found 271--452 input tokens. The worst input
plus 768-token generation budget was 1,220/32,768 and no prompt exceeded the
context gate. `/data0` had 155 GiB free and system memory had 229 GiB available.
Existing VLLM processes on physical GPUs 1, 2, 3 and 6 were not touched.

After the fix and a fresh resource gate, an eight-record non-retained smoke took
17.876 seconds including model load, generated 1,733 tokens and peaked at
15,769,022,464 bytes. All eight failed the already-committed strict parser. The
prompt, schema and parser were not relaxed or retuned from those dev observations;
the formal run proceeded to measure the frozen method.

The production run used only physical GPU 4 and two CPU threads. It ran from
`2026-07-23T16:50:48Z` to `2026-07-23T17:22:55Z`, exit 0. Generation took
1,927.260 seconds, produced 348,766 tokens and peaked at 16,012,927,488 bytes.
GPU 4 stayed around 16.0/24.6 GB and 66 C, then returned to 11 MiB/0%.

## Parse audit

Of 1,483 records, 667 passed both graph and answer contracts and 816 used the
sentinel. A no-value aggregate audit over the frozen error messages found:

| Error category | Count |
|---|---:|
| graph not the penultimate non-empty line | 336 |
| event span not an exact passage substring | 293 |
| final answer invalid | 72 |
| final answer not bound to a graph event | 56 |
| graph JSON invalid | 38 |
| graph keys differ | 14 |
| relation invalid/duplicated/unbound | 5 |
| event ID invalid/duplicated | 1 |
| duplicate JSON key | 1 |

Only one response hit 768 tokens, so generation-budget truncation does not explain
the failure rate. No response, graph, answer, or sample identifier was printed.

## Prediction and metric artifacts

Prediction path:
`/data0/hk_data/kairos-zx/artifacts/20260723T165048Z-llm-graph-torque-dev-s13-d52c57809644`

| File | Bytes | SHA256 |
|---|---:|---|
| `config.json` | 663 | `d52c57809644bec378e607f13ebf0543dbcd5e8cb3db0a5d2b45323682ecec96` |
| `predictions.jsonl` | 445,989 | `64a6c2e7cfe8df700c48a07cee87016a9d83868b05272e1542bc987635f78286` |
| `generation-evidence.jsonl` | 2,052,845 | `f8a8293407e8d790e01261bf39e46ab277b537085eeecfa5958ee4439b8de5cf` |
| `manifest.json` | 1,435 | `c2573cfba4ed8ba73126743dff75c9e9f8304c9a3beaa675a7123fb194f01f28` |

Metrics path:
`/data0/hk_data/kairos-zx/artifacts/derived-metrics/20260723T165048Z-llm-graph-torque-dev-s13-d52c57809644`

- aggregation commit/time: `99209b4445df3a25fe678e3223cceac2c84e0041`,
  `2026-07-23T17:23:37Z`
- question set EM: `1.3486176668914363%`
- question set F1: `1.3486176668914363%`
- cluster exact and F1>=0.8 consistency: `0.0%`
- metrics SHA256:
  `6ce16c3a1d6af5a5a68acdbd86a751e2d73c6e6d7bc8acf6867c96c90bcfd6b1`
- metrics manifest SHA256:
  `cbe181d4e864753a4156a22c09d1801d6b8997d83b3f24e83bdddb8d92e2092c`

Separate CPU/offline processes replayed the source-bound graph parser, prediction
selection, all artifact hashes and exact metric aggregation.

## Paired inference and conclusion

Comparison ID: `paired-torque-dev-llm-graph-vs-direct-a623ea036fa7`

| Metric (%) | Direct | LLM-Graph | Difference | 95% CI | Raw p | Holm p |
|---|---:|---:|---:|---:|---:|---:|
| Question set EM | 15.643965 | 1.348618 | -14.295347 | [-16.155443, -12.516893] | 0.000200 | 0.000800 |
| Question set F1 | 16.069850 | 1.348618 | -14.721232 | [-16.574820, -12.936582] | 0.000200 | 0.000800 |
| Cluster exact | 1.576182 | 0.000000 | -1.576182 | [-2.626970, -0.700525] | 0.001200 | 0.002400 |
| Cluster F1>=0.8 | 1.576182 | 0.000000 | -1.576182 | [-2.626970, -0.700525] | 0.001200 | 0.002400 |

Statistics path:
`/data0/hk_data/kairos-zx/artifacts/derived-statistics/paired-torque-dev-llm-graph-vs-direct-a623ea036fa7`

- aggregation commit/time: `99209b4445df3a25fe678e3223cceac2c84e0041`,
  `2026-07-23T17:24:06Z`
- bootstrap: 571 contrast groups, 10,000 resamples, seed 20260723
- statistics SHA256:
  `234e2d7b8436e11b22807f50b0891f7792acd74d45cfefab4e0a2ba97b4441f4`
- manifest SHA256:
  `691b3259f4a2c6f622484e31507ae5361cdfef834dd8366a51b8e2b504d560e3`

A fresh process reproduced all values and hashes. The frozen structured prompt is
significantly below Direct on every reported metric. This is evidence that strict
one-pass graph serialization is a poor baseline implementation under this model,
not evidence against temporal graphs in general and not a Kairos comparison.
Relaxed parsing, graph repair, few-shot prompting or a separately validated graph
schema may be future sensitivity analyses, but cannot replace this primary result.
