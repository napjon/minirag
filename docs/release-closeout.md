# Release closeout and evidence workflow

This repository includes a machine-readable closeout ledger at
[`release/ledger.json`](../release/ledger.json). It covers all 44 planning
criteria plus four cross-cutting release gates, for 48 release-blocking items.
Each row names the affected week, acceptance evidence, implementation status,
verification status, evidence command and artifact, owner role, assumption,
and release impact.

The ledger separates implementation from verification:

| Status | Meaning |
|---|---|
| `implemented_tested` | Code or configuration exists and a component check passed. The large acceptance gate may still be open. |
| `implemented_unverified` | Code or configuration exists, but the required acceptance evidence is missing. |
| `planned` | Required implementation or evidence has not been delivered. |
| `blocked` | A release-blocking gate cannot close with the current evidence. |

## Run the closeout verifier

The default command runs the available Python, evaluation, static, migration,
compose, shell, and web checks. It also writes a deterministic synthetic gate
manifest and the JSON/Markdown scorecard:

```bash
uv run python scripts/verify_release.py --demo
```

Artifacts are written to:

- `artifacts/release/scorecard.json`
- `artifacts/release/summary.md`
- `artifacts/release/synthetic-gates.json`
- `artifacts/release/evals.json`

The command's demo verdict can be green when the available checks pass. Its
production verdict remains open while any ledger row is `planned`,
`implemented_unverified`, or `blocked`.

Use `--strict` for a release job. It returns a non-zero status if any check is
not passed or any release blocker remains open:

```bash
uv run python scripts/verify_release.py --strict
```

When a review needs an explicit assumed closeout for a demo, add
`--assume-synthetic`. This writes `artifacts/release/assumed-closeout.json` with
one `assumed_pass` record for each of the 48 rows. The artifact is useful for
showing the demo's coverage under declared assumptions; it never changes the
ledger or production verdict.

```bash
uv run python scripts/verify_release.py --demo --assume-synthetic
```

For environments without the test database or web toolchain, `--no-tests` and
`--skip-web` make the missing evidence visible as skipped checks. They do not
turn those checks into a passing release result.

## Synthetic evidence boundary

[`scripts/synthetic_evidence.py`](../scripts/synthetic_evidence.py) produces
organization-neutral manifests at the population sizes in the serious-release
rubric. Labels are deterministic and internally consistent so the demo can
exercise case accounting, artifacts, and scorecard plumbing when real data is
unavailable. The manifest explicitly declares `scope: synthetic_contract`.

Synthetic data does not demonstrate real retrieval quality, classifier quality,
business value, authorization coverage, private-network behavior, capacity,
recovery, or a soak period. A synthetic pass is therefore never translated to
`verified` by the verifier.

## Closing an item

An owner may change a row only after the required evidence exists. The closeout
record must include a build identifier, configuration hash, dataset version,
environment, executed command or job ID, result artifact, observed value and
threshold, owner role, independent reviewer role, review date, and any exception
expiry. The artifact must identify its population and slice denominators. A
unit-test result can support `implemented_tested`; it cannot close a larger
population gate by itself.

The four cross-cutting gates are:

- `REL-QUAL-01`: representative quality and human-adjudication evidence.
- `REL-SEC-01`: authorization, injection, approval, and audit evidence.
- `REL-SCALE-01`: serious-pilot capacity, latency, concurrency, and cost evidence.
- `REL-OPS-01`: private profile, recovery, rollback, and soak evidence.

The ledger keeps every open item visible so a passing aggregate score cannot
hide a failed security, approval, audit, isolation, or evidence-integrity gate.
