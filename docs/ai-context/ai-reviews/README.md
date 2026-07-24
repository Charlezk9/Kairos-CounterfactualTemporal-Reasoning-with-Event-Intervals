# Independent AI Pre-review Files

This directory contains user-requested AI pre-reviews for manual accuracy
checking. They are not the two human Reviewer A/B submissions required by the
frozen audit protocol and cannot unlock training.

Both agents independently read the immutable packet identified by:

- audit items SHA256: `0f37bc96928e16c26ecd5669c3148d97048b87745fc601e4343781f689a39113`
- instructions SHA256: `8ee14494cded53ee8d523521e7f31b2b80cb21faef8da498f5b6812437e51038`
- item count: 200

Each JSONL uses schema `gsm8k-relation-ai-pre-review-v1`, preserves exact item
order, and contains only item IDs, five Boolean judgments, their logical-AND
`overall_valid`, nullable notes and the provenance slot `AI-A` or `AI-B`.
Sample text is not copied into Git. The agents must not read each other's file.

`summary.json` is produced only after both files are complete. It records input
and output hashes plus aggregate agreement/counts; it is diagnostic AI
agreement, not human Cohen's kappa or a D-035 result artifact.
