# Phase 01 2WikiMultihopQA Official Source Discovery

- status: `METADATA_ONLY / HEAD_NOT_ATTEMPTED`
- branch: `experiment/reproduction-additional-evaluation`
- Git HEAD verified with upstream: `22faa3005fd7f3145a210512e585a210624ec5ff`
- active run IDs: none
- running processes: none
- scope: documentation-only official-source and primary-paper metadata

## Fixed provenance

- repository: `https://github.com/Alab-NII/2wikimultihop`
- revision: `13800e5be57df1b4040b9b1588c6c811779e69e9`
- pinned README:
  `https://raw.githubusercontent.com/Alab-NII/2wikimultihop/13800e5be57df1b4040b9b1588c6c811779e69e9/README.md`
- pinned repository LICENSE:
  `https://raw.githubusercontent.com/Alab-NII/2wikimultihop/13800e5be57df1b4040b9b1588c6c811779e69e9/LICENSE`
- ACL Anthology primary paper:
  `https://aclanthology.org/2020.coling-main.580/`
- paper DOI:
  `https://doi.org/10.18653/v1/2020.coling-main.580`

The only permitted archive identity for later planning is the corrected literal
README URL:

`https://www.dropbox.com/s/ms2m13252h6xubs/data_ids_april7.zip`

The fixed README describes this April 7 archive as correcting sentence
segmentation. The older URL
`https://www.dropbox.com/s/7ep3h8unu2njfxv/data_ids.zip?dl=0` is permanently
disabled for this project. It must not be requested, used as fallback or
replaced by a mirror or third-party copy.

## README and repository metadata boundary

The pinned README's December 2020 update records `evidences_id` and
`answer_id`, and identifies the v1.1 evaluator. These facts are revision-bound
README metadata; they are not observations of the corrected ZIP or its member
schema.

The pinned repository LICENSE is Apache License 2.0. This establishes the
repository-level license only. Whether that license applies to every file in
the corrected archive, and whether the archive carries additional attribution,
notice or redistribution terms, remains `UNVERIFIED` until a separately
approved archive acquisition and offline inspection.

## Primary-paper reported metadata

The primary paper defines a multi-hop task covering answers, supporting facts
(SF) and reasoning evidence. It reports Answer EM/F1, Supporting-Fact EM/F1
and Joint EM/F1, and groups questions into comparison, inference,
compositional and bridge-comparison categories.

The paper reports the following dataset sizes:

| Split | Paper-reported examples |
|---|---:|
| train-medium | 154,878 |
| train-hard | 12,576 |
| dev | 12,576 |
| test | 12,576 |
| total | 192,606 |

These are paper-reported metadata associated with DOI
`10.18653/v1/2020.coling-main.580`. They are not local archive observations,
locally reproduced counts or experiment results. They must not be used to
assert the corrected archive's actual member set, split layout or schema.

## Unverified source properties

No new Dropbox request was made during the 2026-07-23 primary-source metadata
discovery. `HEAD_NOT_ATTEMPTED` means specifically that no HEAD has been run
under the current corrected-literal-URL exact gate. A historical bounded HEAD
preflight on 2026-07-22 timed out without a response usable to establish
availability, byte size, MIME type, redirect authority or archive content; it
is retained as timeout evidence only and is not retried by this checkpoint.

Accordingly, availability, redirect authority, byte size, MIME type,
ETag/Last-Modified, SHA256, magic, member list, member paths, member counts,
extracted schema, archive split realization and license applicability all
remain `UNVERIFIED`.

There has also been no repository clone, archive download, upstream-code or
evaluator execution, raw/stage directory creation, data read, approval record,
execution record, acquisition record or experiment artifact. This checkpoint
does not register a formal run and contains no result that may support a paper
claim.

## Next approval gate

The next allowed deliverable is only an Agent 1 draft of an exact no-body,
no-follow Dropbox HEAD plan for the corrected literal URL. It must freeze the
actual executable and argv, zero-body output schema, allowed initial host,
redirect non-follow behavior, sensitive-header suppression, CPU/GPU/disk
budget, timeout, curl exit handling and failure classifications. Agent 2 must
approve that exact plan before any request.

This checkpoint authorizes no network execution, approval/record creation,
helper implementation, test, download, clone, data path creation or archive
access. Any later download helper requires a separate design, code review,
offline synthetic tests, staged audit and production execution approval; it
must keep the corrected literal URL fixed and fail closed rather than falling
back to the disabled archive or a mirror.
