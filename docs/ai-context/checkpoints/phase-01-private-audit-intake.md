# Phase 01 private audit intake

- status: `COMPLETE / USER_ATTESTED / INDEPENDENCE_UNVERIFIED`
- source clean commit: `c68db206e58bff38fca5dae326d7b8969489d50f`
- private artifact: `/data0/hk_data/kairos-zx/artifacts/audit-intake/gsm8k-relation-v1/user-attested-20260725`
- metadata SHA256: `a518d5076248ab3c137744308eea0c332e2103c98dccfd47bf024f618e786c13`
- reviewer A SHA256: `99b95522c1f57156bd8f904c6d66e13b1ee9c6f6154988392b32ffdd8d5941ba`
- reviewer B SHA256: `96c9c53561730d776834b5e7cc705a3274af82b2b2afd08faf1f1dc63cc67e67`
- packet/items SHA256: `da5d7fb0659e1bb13aa1d6b03e59e83c5ddb42c05535932313552af7dcc19ecb` / `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`

The target was absent before creation. Its directory is mode 0700 and all five
regular files are mode 0600, link count one. All copied bytes and sidecars were
reopened and re-hashed after `sync -d`; metadata contains no sample text, names,
notes or secrets. Human independence remains unverified, so this intake only
authorizes the development path frozen in D-038.

The four raw JSONL/sidecar files were introduced to remote history by
`4d0cfa19ee8ac29f2176ba173d6491a0853ab2e4`. After private verification they
were removed from the branch tip by an ordinary staged deletion. The private
copy and existing Git history make the deletion recoverable; shared history was
not rewritten. Actual review bytes must not be added to Git again.

Next safe action: commit/push the branch-tip deletion and this checkpoint, then
implement D-038 using synthetic tests before publishing one immutable
`PASSED_DEVELOPMENT` artifact from the private intake.
