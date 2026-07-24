# Phase 01 AI-assisted Development Training Copy

## Status

`COMPLETE / VERIFIED COPY / DEVELOPMENT TRAINING ONLY / FORMAL HUMAN ARTIFACT PENDING`

- user resolution commit: `4dba42a2765c8667576d87599269e836755888e8`
- source relation data SHA256: `525e3b09c6a6d03942a6bc3e03ebcd1722c3a68f4f224753dbc641f98465c12a`
- output training data SHA256: `4b5fec2bf46b1b86df9639b0e2cea9bc355e77be04247f5f27fcef3cb725f788`
- output manifest SHA256: `f24a8e8ef2ee3f5abf75938e620b43a8c2dcb52b52459ac000ba97bc87258b5a`
- formal run IDs: none

## Review basis and conditional statistic

Claude Code AI-A/B agreed on 194 overall labels and disagreed on six primitive
fields. The user resolved all six in source order. Recombining the five
primitive fields gives 196 valid and four invalid audit items, or 98% validity.

The user then stated that two local human reviews are fully consistent with
these final labels. Conditional on two exact, independent 196/4 submissions,
observed agreement is 1, expected agreement is
`0.98^2 + 0.02^2 = 0.9608`, and Cohen's kappa is 1.0. The allowed workspace
does not currently contain either raw formal submission: the web workbench
results directory contains only its README. Therefore κ=1.0 is user-attested
but not yet artifact-backed or D-035 verified.

## Derived training copy

The user authorized a copied training dataset with the state documented. The
derivation preserves the source order and complete canonical records from the
verified 370-pair relation-only official-train artifact, excluding the four
pairs corresponding to invalid audit lines 2, 6, 81 and 99. The result has 366
records, 777,256 bytes and no counterfactual answers; CF-answer loss remains
masked.

Target:
`/data0/hk_data/kairos-zx/data/processed/gsm8k/3101c7d5072418e28b9008a6636bde82a006892c/training-data-v1/ai-assisted-user-checked-relation-only-v1/train`.

The directory is mode 0700 and contains only mode-0600
`training-data.jsonl` and manifest. Offline verification checked exact
namespace, canonical manifest, hashes/bytes, source-order filtering, 366/4
counts and all review/status bindings.

## Use boundary

This artifact is user-authorized for development training so engineering can
continue. It is not a formal experiment input, does not make a paper metric
eligible, and must label every derived run `PRELIMINARY`. Formal status can be
reconsidered only after the two actual human files are copied into an allowed
path, hashed, schema/order validated and replayed by D-035. Relation-only v1
still cannot support CF-answer accuracy, update, stability or consistency.
