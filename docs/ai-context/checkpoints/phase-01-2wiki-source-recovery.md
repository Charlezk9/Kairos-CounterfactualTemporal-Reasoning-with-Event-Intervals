# Phase 01 2Wiki Frozen-Source Recovery

- status: `DEFERRED_NETWORK / ALL_FROZEN_ROUTES_UNREACHABLE`
- execution_commit: `08d847b1e0faf2943ea6af8ea3bc30709348b80d`
- date: 2026-07-24 CST
- GPU/model/upstream-code execution: none
- formal raw publication: none

## Scope and gate

D-027 fixed the source order before any new response body was inspected. The
working tree was clean at the execution commit. Before every request,
`nvidia-smi`, `free -h` and `df -h` were checked. `/data0` had about 145 GiB
free, above the 120 GiB stop threshold. Requests were foreground and bounded;
no GPU, model, upstream script, mirror code or existing raw artifact was used.

Each attempt used a new mode-0700 directory below
`/data0/hk_data/kairos-zx/.tmp`. Empty header evidence and mode-0600 attempt
manifests were retained. The previous
`ACQ-2WIKI-20260723` raw failure record was not modified or deleted.

## Results

| Attempt | Source/route | Terminal state | Response |
|---|---|---|---|
| `ACQ-2WIKI-RECOVERY-20260724-APRIL-SCL-WWW` | official April 2021 corrected object, `www.dropbox.com` SCL | curl 28 after 30 s connect timeout | HTTP 000, 0 redirects, 0 header/body bytes |
| `ACQ-2WIKI-RECOVERY-20260724-APRIL-CONTENT` | same official object, `dl.dropboxusercontent.com` | curl 28 after 30 s connect timeout | HTTP 000, 0 redirects, 0 header/body bytes |
| `ACQ-2WIKI-RECOVERY-20260724-DATA-IDS-OFFICIAL` | official older `data_ids.zip`, bounded range probe | curl 28 after 20 s connect timeout | HTTP 000, 0 redirects, 0 header/body bytes |
| `ACQ-2WIKI-RECOVERY-20260724-DATA-ORIGINAL-OFFICIAL` | official original `data.zip`, bounded range probe | curl 28 after 20 s connect timeout | HTTP 000, 0 redirects, 0 header/body bytes |
| `ACQ-2WIKI-RECOVERY-20260724-HF-UNOFFICIAL` | pinned unofficial `xanhho/2WikiMultihopQA@6ef4eb1...` | `huggingface_hub` exit 1, OS `Network is unreachable` | repository metadata unavailable; 0 data bytes |

The four empty curl header files all hash to
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Attempt-manifest SHA256 values, in the table order, are:

- `47a72d5328bdfc30c2b4da4db7d55cc9cebbed501c8ea4077e0e57f4163af4cd`
- `61cb88dea0a8995aea491057ea8cde8e16325af454e6f64d41c443fb45845da1`
- `7777d531b4142ccaa1b07a586408f59ce9be6e627c3dfaa996af169d072b5b3c`
- `acebe3589b945de5abd3a2b158018571d58fdf08267e7b866a74589662e84743`
- `69416fdbe371cc44759e42a55062b483ea00d652c915d1ba7ad2e843d2b725dc`

## Interpretation and disposition

No route returned an HTTP response or dataset byte, so this work cannot
validate availability, archive identity, license, schema, split counts or
semantic equivalence. The common failure across Dropbox and Hugging Face is
evidence of current server network unreachability, not evidence that the
official dataset is permanently unavailable.

2Wiki is therefore `DEFERRED_NETWORK / SOURCE_UNVERIFIED`. It remains required
for complete reproduction of the original four-dataset evaluation but is not
on the minimum TORQUE reviewer-response critical path. A future retry requires
a network-state change or a user-supplied file placed directly inside an
allowed project root; D-027 provenance and equivalence gates remain unchanged.
No third-party mirror may enter a formal experiment based on counts or samples.

The next safe task is Stage 2 synthetic-only resumable training execution. It
uses no production data, 7B weights, GPU or network and does not relax the human
audit gate.
