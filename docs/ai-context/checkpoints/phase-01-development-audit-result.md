# Phase 01 user-attested development audit result

- status: `PASSED_DEVELOPMENT / USER_ATTESTED / INDEPENDENCE_UNVERIFIED`
- implementation/execution commit: `06eff003309cb67e0b71167043e4a41b04351856`
- artifact: `/data0/hk_data/kairos-zx/artifacts/audit-results/gsm8k-relation-user-attested-development-20260725`
- manifest SHA256: `c501f37697e5254a274075e0a5d017472b960240b436e5a5acdd65c4d1c4afe7`
- projection SHA256: `ae8bc796147e7b7b9f87dcb1924501625ff6d2acdbd5e8175727bb64081ef230`
- result file/semantic SHA256: `df7310e8a5c9f85f9e4f7f1e635d24d92db173217ee25d97fba28c9de149f318` / `527e599c9c8f9c01b60a95da8f0486515e94b51fd22bd4c2d32b5bb34d814d29`

The additive D-038 evaluator preserves D-035 and emits a separately named
algorithmic agreement projection only when A/B have zero overall disagreements.
Any disagreement fails before publication. The strict replay result is 196/200
valid, observed/expected agreement 1.0/0.9608, conditional Cohen's kappa 1.0,
validity 0.98 and Wilson 95% interval `[0.9497129130941735,
0.9921955735836505]`.

Focused relation/audit tests passed 9/9. The final CPU-only full suite passed
569/569 in 18.773s with GPU hidden and two threads. Publication occurred once
from synchronized clean commit `06eff00`; a separate process replayed packet,
private intake, projection, statistics, result and manifest exactly. Directory
mode is 0700; all three output files are regular mode-0600, link-count-one
files. No sample text or reviewer notes enter result/manifest/Git.

This is not a formal two-human audit: `human_independence_verified=false` and
`paper_metric_eligible=false`. It authorizes only the frozen development path.
Next safe action is an immutable 366-record rebuild plus train330/internal-dev36
partition whose exclusions are reconstructed from this exact audit chain.
