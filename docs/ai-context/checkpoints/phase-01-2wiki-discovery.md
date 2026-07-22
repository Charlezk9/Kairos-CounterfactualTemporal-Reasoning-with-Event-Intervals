# Phase 01 2WikiMultihopQA Official Source Discovery

- status: `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`
- metadata discovery disposition: `METADATA_ONLY / HEAD_NOT_ATTEMPTED`
- branch: `experiment/reproduction-additional-evaluation`
- metadata discovery base HEAD: `22faa3005fd7f3145a210512e585a210624ec5ff`
- exact HEAD plan/audit base HEAD: `62d43a60c95eec294f2f0492a1e0242b747ea428`
- active run IDs: none
- running processes: none
- scope: documentation-only official-source and primary-paper metadata plus a non-executed exact HEAD plan/tooling disposition

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

## Exact metadata-only HEAD plan

The planned first process must be created by a native process API with the
following complete invocation boundary:

```text
executable: /usr/bin/curl
cwd: /home/yangbin/zx-tmp/kairos
envp: {}
inherit_env: false
```

The actual outer executable must be `/usr/bin/curl`, not a shell, `env`,
Python, Conda or another wrapper. Empty `envp` must be supplied at the first
process-creation boundary so the dynamic loader and curl cannot observe
inherited `LD_LIBRARY_PATH`, Conda or proxy variables. The exact argv, limited
to options supported by `/usr/bin/curl` 7.68, is:

```text
[
  "/usr/bin/curl",
  "--disable",
  "--head",
  "--silent",
  "--show-error",
  "--fail",
  "--proto", "=https",
  "--proxy", "",
  "--max-redirs", "0",
  "--retry", "0",
  "--connect-timeout", "10",
  "--max-time", "20",
  "--output", "/dev/null",
  "--write-out",
  "http_code=%{http_code}\\nnum_redirects=%{num_redirects}\\nurl_effective=%{url_effective}\\n",
  "https://www.dropbox.com/s/ms2m13252h6xubs/data_ids_april7.zip"
]
```

This is HEAD-only, no body, no redirect follow and zero retry. The caller must
capture the real curl exit code separately from stdout and stderr; no pipeline,
shell `$?` or curl write-out emulation may substitute for the process result.
Stdout has a 256-byte hard cap and must contain exactly these three fields in
order: three-digit `http_code`, `num_redirects` equal to exactly `0`, and the
unchanged query-free initial `url_effective`. Stderr is captured separately
with a 4 KiB hard cap, is diagnostic-only, and must not be interpreted as
source metadata or contain response headers, Location, credentials or
environment values.

For a 3xx response, the only reportable values are HTTP code, redirect count
and the unchanged effective initial URL. Location and raw headers must not be
printed or followed. Exit 0 with 2xx means only `HEAD_RESPONDED_METADATA_ONLY`;
exit 0 with 3xx means `REDIRECT_METADATA_REQUIRED`; exit 0 with any other HTTP
class is `UNEXPECTED_HTTP_STATUS` and fails closed. Exit 22 is
`HTTP_ERROR_METADATA_ONLY`; exit 28 is
`TRANSPORT_TIMEOUT / AVAILABILITY_UNVERIFIED`; explicitly classified
DNS/connect/TLS exits are transport failures. Any other nonzero curl exit is
`CURL_FAILURE / AVAILABILITY_UNVERIFIED`. Any output-cap, schema or URL
mismatch is `OUTPUT_CONTRACT_VIOLATION`. Every failure stops without retry,
fallback, GET, old-URL use or mirror substitution.

The resource envelope is 0 GPUs, one CPU/process, zero response-body bytes and
zero persistent-disk bytes. `/dev/null` is an existing device, not a created
artifact. The caller may provide only bounded transient process memory and
in-memory stdout/stderr capture; no file, log, approval, execution record,
stage, archive, data or experiment artifact may be created.

## Independent tooling disposition

This 2Wiki plan was assessed independently rather than by generalizing D-007.
The currently available `exec_command` interface has no native `envp` or
`inherit_env=false` parameter and launches a shell before curl. It therefore
cannot prove the identity of the first dynamically loaded process or exclude
inherited proxy, `LD_LIBRARY_PATH` and Conda state. Starting `env -i`, shell
cleanup, Python or another wrapper after that point does not repair the first
process boundary.

The exact plan is consequently `BLOCKED_PLAN / NO_NATIVE_EXEC_ENV`. It was not
executed: no new HEAD response, network access, approval or execution record
exists. The 2026-07-22 timeout remains historical non-availability evidence,
and availability, redirect authority, MIME, size and all archive properties
remain `UNVERIFIED`.

This checkpoint authorizes no network execution, approval/record creation,
helper implementation, test, download, clone, data path creation or archive
access. Any later download helper requires a separate design, code review,
offline synthetic tests, staged audit and production execution approval; it
must keep the corrected literal URL fixed and fail closed rather than falling
back to the disabled archive or a mirror.
