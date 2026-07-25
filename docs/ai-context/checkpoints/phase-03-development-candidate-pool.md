# Phase 03 GSM8K Development Candidate Pool

## Status

`COMPLETE / DEVELOPMENT ONLY / FRESH REPLAY VERIFIED`

- execution commit: `67f995d1fe6082837c02fab2899c70f2449a888d`
- artifact ID: `gsm8k-relation-qwen25-7b-pool-v1`
- model: `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28`
- resource-gate SHA256: `773adb1bca5497968594b0bd1f06db57aa697492f0fd61840f346911b05d059d`
- paper eligibility: false

## Execution and verification

The first eight-record mechanics smoke failed at the first CUDA cumulative-sum
sampling call and published no artifact. D-042 replaced only stochastic token
selection with the independently approved deterministic CPU sampler. The
second eight-record smoke completed without an artifact: 15,296 generated
tokens, 25 parse errors, candidate/evidence SHA256 `813d595d...` /
`7d2ce654...`.

The production foreground run used physical GPU 5, UUID
`GPU-1389a4f1-ca5a-d380-1de3-ebb3f55c9b29`, from the clean synchronized
execution commit. It generated the frozen Direct, CoT and eight
Self-Consistency positions for train330/internal-dev36, then published once
with manifest last. Total generated tokens were 726,637; 1,334/3,660 position
responses were retained as typed parse errors. The process exited 0 and the GPU
returned to 11 MiB. `/data0` retained 169 GiB free.

A fresh GPU-hidden process replayed the source partition, all raw evidence,
parser, pool order, three protocols, model namespace/checksums, resource gate
and manifest. Directory/file modes are 0700/0600, regular files have link count
one, and the exact six-file namespace totals 4,099,459 bytes.

## Artifact identities

- config: `2224a5347beb315fe554405c99576b975bc968a41ae09dfe11f5ce4c4d34ebfe`
- train candidates: `e5955a6a1320bf7e3046c86f424a24ae3b6572eb06cbb5ea6efbd69662a29d86`
- train evidence: `928bb79528e4d94f6ddd980d3f5048aa7fa06d0bbd5f0f1713fb05c47859e469`
- internal-dev candidates: `101fd8216d67efccaf109c8e01fe09f68de39009bdb4e15e968432f89ea4f01a`
- internal-dev evidence: `d9e1d72be6651225dbfc67728374683d5a4c03f966c472502c72d5fafcb0de51`
- manifest: `bdf45755a08dae3e0cb4478f2c5c038c8eb519f57b34d8f8e007d0de20581e2e`
- path: `/data0/hk_data/kairos-zx/artifacts/relation-candidates/gsm8k-relation-qwen25-7b-pool-v1`

## Training gate discovered after publication

Train has three empty generated pools (minimum/maximum candidate count 0/7);
internal-dev has none (minimum/maximum 2/6). The source-order canonical list of
the three train pair IDs hashes to
`22b4edc8c53acf2971d1d618da17388ea34c759188fab4b32ed41f384d22161a`.
The candidate artifact remains immutable and gold-blind. D-043 freezes a
train-only, explicitly versioned gold-only materialization rule. Independent
strict re-audit returned `APPROVED_AMENDMENT`; implementation, golden tests and
the remaining production gates are still required before training.
