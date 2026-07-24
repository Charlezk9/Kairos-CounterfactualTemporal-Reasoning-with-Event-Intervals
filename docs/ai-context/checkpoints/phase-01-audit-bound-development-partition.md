# Phase 01 audit-bound development partition

- status: `COMPLETE_DEVELOPMENT_ONLY / VERIFIED`
- implementation/execution commit: `3c02685845f54475b7bca834200aa584b02e4a6c`
- artifact: `/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/training-data-v2/audit-bound-user-attested-relation-only-v1-train`
- counts: source 370; excluded 4; retained 366; train 330; internal-dev 36
- data/train/internal-dev SHA256: `4b5fec2bf46b1b86df9639b0e2cea9bc355e77be04247f5f27fcef3cb725f788` / `073b4c65a5343ce459c9ecf89cfec844900e52cf7c7a8e6b563640a7468194ee` / `63041d7e589b7399d6aa4a129a3b604450d1b36d4e9e0bd2b0f8f1b8bf7e5f07`
- partition/manifest SHA256: `cfc1894eab909021b2a99f3423dd8ae898c3c517253b628f48b3b544d1c21fe3` / `0631e02c6ff0e61cfba616fc262198cf7578170f80733b7debcca5a770acf4d4`

The publisher replays the verified 370-record source, audit packet, private
D-038 artifact and algorithmic projection. The four exclusions are derived by
joining audit-item IDs to pair IDs; no caller-provided exclusion list is
accepted. All relation records undergo deterministic `RelationOnlyPair` replay.

The existing `split.internal` values are frozen before model output. The
optimizer-eligible namespace contains exactly 330 train records; the separate
36-record internal-dev file is gold-blind and cannot enter an optimizer,
ordinary gold injection, checkpoint selection or tuning. All five output files
are mode-0600/link-count-one beneath a mode-0700 target. A fresh process replayed
all bytes, counts, ordering, identities, hashes and manifests.

The 366-record full-data SHA exactly matches the prior development copy, while
the new artifact adds the missing audit chain and partition identity. It has no
CF answer and is not paper-eligible. Next safe action is the already frozen
protocol preflight and D-039 shared gold-blind candidate implementation.
