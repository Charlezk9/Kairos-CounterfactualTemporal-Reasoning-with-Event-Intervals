# Phase 01 TORQUE Official Source Discovery

- status: `METADATA_ONLY / DOCUMENTS_READ`
- branch: `experiment/reproduction-additional-evaluation`
- metadata discovery base HEAD: `b34b72bb2b873330d08087a65e2af6c953906551`
- active run IDs: none
- running processes: none
- scope: documentation-only fixed-revision README/LICENSE and primary-paper metadata

## Fixed provenance and documents read

- repository: `https://github.com/qiangning/TORQUE-dataset`
- revision: `ab27019cc6a317fde3c879900499f02acce8b16d`
- pinned README read:
  `https://raw.githubusercontent.com/qiangning/TORQUE-dataset/ab27019cc6a317fde3c879900499f02acce8b16d/README.md`
- pinned repository LICENSE read:
  `https://raw.githubusercontent.com/qiangning/TORQUE-dataset/ab27019cc6a317fde3c879900499f02acce8b16d/LICENSE`
- ACL Anthology primary page read:
  `https://aclanthology.org/2020.emnlp-main.88/`
- ACL Anthology primary PDF read:
  `https://aclanthology.org/2020.emnlp-main.88.pdf`
- primary-paper DOI: `10.18653/v1/2020.emnlp-main.88`

Only these four fixed documents were read. No GitHub API/tree, data file,
script, evaluator, model repository, third-party page or mirror was read.

## README-reported metadata

The pinned README names `./data` as containing the entire dataset and the
original train/dev/test split. It states that test annotations were removed by
the authors. It also names `question_clustering.json` and
`./basic_stats/basic_stats.py`; notebook paths are retained only as
`README_REPORTED` metadata and are not guessed or opened in this discovery.

These are `README_REPORTED` names and statements, not local source-tree or data
observations. The discovery did not verify whether any reported path exists at
the fixed commit, inspect member names, or observe train/dev/test payloads.
Future project evaluation may consider only the public dev gold after a
separate acquisition and audit. Test gold is unavailable and must never be
recovered from a fork, cache, historical copy or third-party mirror.

## Primary-paper reported metadata

The primary paper reports approximately 3.2K annotations, about 2.9K of them
unique; 24.9K events; 21.2K user-generated questions; 9.5K warm-up questions;
30.7K total questions; and 65K answers. It reports an article-disjoint
80%/5%/15% train/dev/test split. These quantities are `PAPER_REPORTED`; they
are not local file counts, archive observations or experiment results and must
not be used to assert snapshot completeness.

The paper reports Macro F1, exact match (EM) and consistency (`C`). Its prose
defines EM consistency as the percentage of contrast sets for which predictions
match exactly for every question, while the Table 4 caption defines `C` as the
percentage of contrast groups for which every question has F1 at least 80%.
This is a `SPEC_CONFLICT` in the reported consistency formulation, not an
ordinary per-question EM conflict. No definition is selected, normalized or
implemented at this checkpoint. Resolution requires a separately approved
official-evaluator/source audit and must preserve both formulations.

## License, schema and evaluator boundary

The pinned repository LICENSE is Apache License 2.0. It establishes only the
repository-level license observed in that document. Its applicability to data
blobs, annotations or derived artifacts, and any additional attribution or
notice requirements in the data, remain `UNVERIFIED`.

The actual fixed-revision tree, file existence, file names beyond the README
statements, byte sizes, SHA256 values, split realization, record counts, data
schema, event/question/answer representation, gold completeness, official
evaluator path/version/behavior and data-license applicability all remain
`UNVERIFIED`. Test gold is `UNAVAILABLE` by the author's current publication
boundary.

No data/API endpoint, script, evaluator, notebook, model repository, sample
content or third-party source was read. There was no clone, snapshot/archive
download, data blob access, upstream-code execution, raw/stage path creation,
approval, execution record, acquisition record or experiment artifact. This
checkpoint registers no formal run and provides no result for a paper claim.

## Next gate

The only next deliverable is an Agent 1 fixed-revision snapshot/acquisition
plan. It must distinguish repository code metadata from data blobs, freeze the
exact object/URL set, and define a native first-process executable/argv/env/cwd
boundary rather than inheriting proxy, Conda or loader state. It must also
specify no-replace paths, resource/download budgets, provenance hashes,
repository-license versus data-license handling, public-dev-gold validation,
test-gold non-recovery and failure preservation.

Agent 2 approval is required before any network request, code/helper change,
clone/snapshot, data access, approval/record creation or artifact. Any later
source acquisition, evaluator audit and dev-data validation require separate
implementation, offline-test, staged-audit and production-execution gates.
Hugging Face, forks and all third-party mirrors remain prohibited.
