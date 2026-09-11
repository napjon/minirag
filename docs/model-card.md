# Model card

Rationale: [architecture.md](architecture.md) §2. Runtime selection is `backend/model_gateway/base.py` and `backend/config.py`.

There is **no silent fallback** between providers. A missing key or a forbidden hosted call fails closed.

## Profiles

| `MODEL_PROVIDER` | When to use | Generation | Embeddings / rerank today |
|---|---|---|---|
| `fixture` | Default local and CI | Deterministic `FixtureGateway` (`fixture-1`) | Hash embedding, dim 1024; token-overlap rerank |
| `hosted` | Hosted deployment profile | Configured OpenAI-compatible API | Still **fixture** vectors (multilingual embeddings **planned**) |
| `private` | Private deployment profile | vLLM-compatible OpenAI API | Still **fixture** vectors (multilingual embeddings **planned**) |

`DEPLOYMENT_PROFILE` is `hosted` or `private` (workspace/ops metadata). It does not by itself pick a gateway. Set `MODEL_PROVIDER` explicitly.

## Fixture provider

**implemented.** No network. Prompts containing `INTENT_JSON`, `QA_JSON`, `DRAFT_JSON`, or `VERIFY_JSON` return small structured objects used by tests and seed.

Vision: string containment check (`image_note` in listing text, or `"placeholder"`).

Use this provider unless you are measuring a real model.

## Hosted generation

| Setting | Value |
|---|---|
| Base URL | `HOSTED_MODEL_BASE_URL` (must be explicitly configured) |
| API key | `HOSTED_MODEL_API_KEY` (required; empty key raises `RuntimeError`) |
| Generation model | `HOSTED_GENERATION_MODEL` |
| Intent model setting | `HOSTED_INTENT_MODEL` (gateway currently uses the generation model for all `generate` calls) |
| Client | `OpenAICompatGateway` via the OpenAI-compatible Chat Completions API |
| Cost accounting | Configured input/output rates (`HOSTED_*_COST_PER_MILLION`) multiplied by provider-reported usage |

The endpoint and model are deployment configuration. A profile change requires review and a rerun of the quality, cost, privacy, and egress checks.

## Private generation via vLLM

| Setting | Value |
|---|---|
| Base URL | `PRIVATE_MODEL_BASE_URL` (default `http://127.0.0.1:18000/v1`) |
| Model | `PRIVATE_GENERATION_MODEL` |
| Vision model setting | `PRIVATE_VISION_MODEL` (hosted/private `vision_check` currently asks `generate` for JSON; dedicated VL wiring **planned**) |
| API key | `not-needed` on the local client |

Private profile must preload model weights, OCR assets, and images through a controlled import. Ordinary startup must not download them.

## Private egress — no silent fallback

If `DEPLOYMENT_PROFILE=private` and `PRIVATE_EGRESS_BLOCKED=true` and `MODEL_PROVIDER=hosted`:

```text
RuntimeError: hosted provider is forbidden in the private profile
```

Operator recipe for an air-gapped demo:

```text
DEPLOYMENT_PROFILE=private
MODEL_PROVIDER=private   # or fixture
PRIVATE_EGRESS_BLOCKED=true
```

`private` + `hosted` with `PRIVATE_EGRESS_BLOCKED=false` **will** call the configured hosted endpoint. That is not a fallback; it is a misconfiguration. `/health` exposes `egress_blocked`.

The application check is not a network policy. Prove isolation with a blocked-egress integration test (**planned**, architecture §6).

## Embeddings and reranking

| Piece | Plan | Now |
|---|---|---|
| Embeddings | Pinned multilingual model, 1024 dimensions, local in both profiles | `EMBEDDING_PROVIDER=fixture`; `fixture_embedding` even inside `OpenAICompatGateway.embed` |
| Rerank | Pinned multilingual reranker | Overlap scorer |
| Mixing models | Never mix embedding models in one vector field | Single fixture field |

`embedding_dim=1024` is already the column width. Switching embedding models requires a new index generation and re-embed, not an in-place mix.

## Failure and budget

- Do not retry validation or permission errors.
- Transient provider errors: max two retries with jitter (**planned** in workers).
- Never switch to an unvalidated model to save cost.
- Never switch a private workflow to a hosted model.

Pin revisions after compatibility testing. This card is not a claim that any selected model already passes the §6 quality gates.
