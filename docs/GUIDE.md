# minirag 2.0 guide

Local RAG with full evaluation monitoring. This document covers the use case, the architecture, how to run it, how to read every number, and what to build next.

Contents

1. [The use case](#1-the-use-case)
2. [What changed from version 1](#2-what-changed-from-version-1)
3. [Run it](#3-run-it)
4. [How a question becomes an answer](#4-how-a-question-becomes-an-answer)
5. [Code map: Quest level to file](#5-code-map-quest-level-to-file)
6. [The Monitor page](#6-the-monitor-page)
7. [The Evals page and the golden set](#7-the-evals-page-and-the-golden-set)
8. [Metric reference](#8-metric-reference)
9. [Models and providers](#9-models-and-providers)
10. [Settings](#10-settings)
11. [Change the corpus or the golden set](#11-change-the-corpus-or-the-golden-set)
12. [API](#12-api)
13. [Troubleshooting](#13-troubleshooting)
14. [What was verified, and what was not](#14-what-was-verified-and-what-was-not)
15. [Plan: what comes next](#15-plan-what-comes-next)

## 1. The use case

Corvane Bank is an invented retail bank. Its employees keep asking the People Team, Finance and the Service Desk the same questions: how many leave days carry over, what the hotel limit is, how fast a lost laptop must be reported. The answers are in nine internal policy documents that few people read.

The bank wants an assistant that:

- answers only from the policy library, and shows the document, section and version behind each sentence;
- refuses when the library does not cover the question, instead of guessing;
- keeps a tamper-evident record of every question and answer;
- can be measured, so that a change to chunking, models or prompts is judged by numbers and not by feel.

Everything here is fictional: the bank, the policies in `corpus/`, the amounts, the phone numbers and the golden set.

| Document | Id | Topics |
| --- | --- | --- |
| Leave and Time Off Policy | `hr-01` | annual leave, carry-over, sick leave, parental leave |
| Hybrid Working Policy | `hr-02` | office days, core hours, allowances, working abroad |
| Learning and Development Policy | `hr-03` | learning budget, certifications, mentoring |
| Code of Conduct and Gifts Policy | `hr-04` | gifts, conflicts of interest, personal trading |
| Onboarding and Probation Guide | `hr-05` | probation, notice, pay and pension |
| Travel and Expenses Policy | `fin-01` | claims, meals, hotels, flights, mileage |
| Information Security Standard | `it-01` | passwords, devices, data classes, phishing |
| Service Desk and Equipment Guide | `it-02` | hours, response times, equipment refresh |
| Branch Operations Manual | `ops-01` | dual control, cash handling, identification, complaints |

## 2. What changed from version 1

Version 1 (a multi-module service on PostgreSQL, object storage, a React front end and hosted model endpoints) was removed. It is still in the git history. Version 2 is a rewrite with one goal: evaluate and monitor RAG on a laptop.

| | Version 1 | Version 2 |
| --- | --- | --- |
| Models | hosted endpoint or private server | Ollama on localhost, or a model-free fixture |
| Storage | PostgreSQL + pgvector, MinIO, Redis | one SQLite file and cached NumPy vectors in `.data/` |
| Front end | React, built with bun | three static pages, no build step |
| Setup | Docker Compose, migrations, seed | `./run.sh` |
| Monitoring | metrics endpoints | a trace per question, a monitor page, an evals page |

## 3. Run it

You need macOS or Linux (Windows: WSL2), `curl`, and about 1 GB of free disk for the models.

```bash
./run.sh
```

What it does, in order:

1. Installs `uv` if it is missing. `uv` also provides Python.
2. Creates `.env` from `.env.example`.
3. Installs Ollama if it is missing (the official install script on Linux, Homebrew on macOS).
4. Starts `ollama serve` in the background if it is not already running.
5. Pulls `qwen2.5:0.5b` (generation) and `all-minilm` (embeddings) if they are not present.
6. Installs the Python packages into `.venv`.
7. Chunks and embeds the corpus. The vectors are cached.
8. Calibrates the score floor from the golden set (section 7).
9. Starts the app on <http://127.0.0.1:8130>.

On Linux the Ollama install script asks for your password, because it installs a system service.

To run without any model:

```bash
./run.sh fixture
```

To stop: Ctrl+C stops the app. Ollama keeps running in the background; stop it with `pkill ollama` if you want the memory back.

To start again from nothing, delete the local state:

```bash
rm -rf .data .env
```

## 4. How a question becomes an answer

```
question (+ chat history)
   │
   ▼
rewrite ──── only when there is history: make the follow-up a standalone question
   │
   ▼
retrieve ─── BM25 keyword search  ┐
             vector search        ┴─ fused with RRF into 20 candidates
   │
   ▼
rerank ───── score each candidate 0..1, keep the top 4
   │
   ▼
gate ─────── best score under the floor?  ──► refuse (the model is never called)
   │
   ▼
generate ─── model returns JSON: claims, each with a source id (S1..S4)
   │
   ▼
ground ───── drop every claim whose numbers or words are not in its source
   │           no claim left?  ──► refuse
   ▼
score ────── label-free quality scores; golden-set check if the question is known
   │
   ▼
audit ────── hash-chained row written before the answer is returned
   │
   ▼
answer with citations  +  a stored trace
```

Three design rules:

- **Fail closed.** Invalid JSON, a claim the source does not support, or a failed audit write all end in a refusal or an error, never in an unchecked answer.
- **The model cannot cite what it was not given.** Ollama's structured output restricts `source_id` to the ids of the chunks in the prompt.
- **Everything is traced.** `Engine.answer` in `minirag/pipeline.py` is the only path to an answer, and it always writes a trace.

## 5. Code map: Quest level to file

The code follows the course's build steps, with the fictional bank in place of the original customer and Ollama in place of the hosted model.

| Quest level | Idea | Where it lives |
| --- | --- | --- |
| 1 Hello, RAG | load, chunk, embed, search, generate | `minirag/corpus.py`, `minirag/index.py`, `minirag/pipeline.py` |
| 2 Measure before you fix | golden set, recall@k, accuracy, refusal rate | `evals/golden.json`, `minirag/evals.py`, `evals/runner.py` |
| 3 Better chunks | split by section, prefix the section name | `chunk_docs` in `minirag/corpus.py` |
| 4 Hybrid search | BM25 + vectors + RRF | `keyword_search`, `vector_search`, `rrf` in `minirag/index.py` |
| 5 Rerank | rescore candidates, keep the top k | `Index.rerank` (a light scorer; see section 9) |
| 6 Ground or refuse | JSON claims, score floor, number check | `minirag/grounding.py`, `_generate_and_ground` in `minirag/pipeline.py` |
| 7 Ready for auditors | hash-chained log, document versions | `log_audit`, `verify_chain` in `minirag/store.py` |
| 8 Understand the question | rewrite follow-ups, search with both | the `rewrite` stage and `Engine.retrieve` |
| 9 Fast and cheap enough | time every stage, p50 and p95 | `stage()` in `minirag/pipeline.py`, latency table in `minirag/evals.py` |
| 10 Agents and tools | trajectory evals | `trajectory` in each trace, `trajectory_match` in `minirag/evals.py` |
| 12 A real service | `/ask`, `/feedback`, `/healthz`, `/readyz` | `minirag/app.py` |
| 13 Private models | one interface, two providers | `minirag/llm.py` |

Not included, on purpose: Level 11 (PostgreSQL as the vector store) and the levels about hosted cloud products. With 41 chunks a NumPy array is enough, and this version uses no cloud service.

Differences from the course code that are worth knowing:

- The corpus is markdown, so citations name a document, section and version instead of a page.
- `all-minilm` needs no `passage:` / `query:` prefixes (the e5 models do).
- Thousands separators are handled in the number check: `5,000` in a source matches `5000` in a claim.
- The ground check adds a word-support test next to the number check, so a claim with no numbers is still checked.

## 6. The Monitor page

Open <http://127.0.0.1:8130/#/monitor>, type a question, press **Run and trace**.

**Top strip (live traffic only).** Number of questions, answered / refused / errors, refusal reasons, p50 and p95 latency, mean groundedness, helpful votes, whether the audit chain is intact, and the score floor in use. Evaluation runs are excluded so they do not distort the live numbers.

**Left: recent traces.** Green dot = answered, amber = refused, red = error. A ✓ or ✗ appears when the question is in the golden set. Switch between live, eval and all.

**Right: one trace, top to bottom.**

| Section | What you see | What to look for |
| --- | --- | --- |
| Header | question, answer, citations, outcome and why | the refusal reason tells you which stage to open |
| Score tiles | top retrieval score and margin over the floor, groundedness, context used, answer-to-question similarity, golden check, total time, generation speed | a thin margin means the gate is close to flipping |
| Time per stage | a waterfall of every stage, with a one-line note each | generation should dominate; anything else that is slow is a bug |
| 1 Question understanding | the original question and the rewritten one | a bad rewrite ruins everything after it |
| 2 Retrieval | every candidate chunk: BM25 rank and score, vector rank and cosine, RRF score, rerank score. ● = sent to the model, ★ = the section the golden set expects | ★ without ● means retrieval found it and the reranker lost it |
| 3 Gate | the top score against the floor | refusals here cost no tokens |
| 4 Model generation | model, prompt and output tokens, tokens per second, model load time, raw output, the full prompt | invalid JSON, or a status of `not_in_sources` |
| 5 Ground check | each claim, the source it cites, whether its numbers are in that source, word support, kept or dropped | a dropped claim is a hallucination that was caught |
| 6 Accuracy against the golden set | expected value, expected source, retrieval rank, citation, pass or fail | only for questions that are in `evals/golden.json` |
| 7 Audit log | this row's hash and the previous one | the chain status is in the top strip |

Accuracy needs a known right answer, so it only appears for golden-set questions. For any other question the monitor shows the label-free scores: groundedness, context used and answer-to-question similarity.

## 7. The Evals page and the golden set

`evals/golden.json` holds 35 cases:

| Type | Count | Checked how |
| --- | --- | --- |
| `in_scope` | 24 | the answer must contain `must`; the expected `docs` / `section` must be retrieved |
| `follow_up` | 3 | same, but the question only makes sense with its `history`, so the rewrite is tested |
| `out_of_scope` | 8 | the assistant must refuse |

Press **Run golden set** on the Evals page, or use the terminal:

```bash
./run.sh eval
```

Every case goes through the real pipeline and leaves a trace. Click a case to open it in the monitor.

**Gates.** The `gates` block in `golden.json` sets the pass marks: recall@k ≥ 90%, answer accuracy ≥ 80%, refusal rate ≥ 90%, false refusals ≤ 10%, groundedness ≥ 95%, path match ≥ 90%. `./run.sh eval` exits with code 1 if any gate fails, so it can guard a change.

**Calibrating the score floor.** The gate refuses when the best rerank score is under a floor. That floor depends on the embedding model, so it is measured, not guessed:

```bash
./run.sh calibrate
```

This runs retrieval only (no generation) for every golden question, then puts the floor halfway between the weakest in-scope top score and the strongest out-of-scope one. The result is stored in `.data/calibration.json` and used until the embedding model changes. Setting `SCORE_FLOOR` in `.env` overrides it.

The floor is tuned on the same questions it is then scored on. That is fine for learning; for a real project, calibrate on one half of the golden set and report on the other.

## 8. Metric reference

Per question (shown on the Monitor page):

| Metric | Definition | Needs a golden answer? |
| --- | --- | --- |
| Top retrieval score | rerank score of the best chunk, 0 to 1 | no |
| Score margin | top score minus the floor | no |
| Groundedness | claims kept ÷ claims the model made | no |
| Context used | chunks cited by a kept claim ÷ chunks sent to the model | no |
| Answer ↔ question | cosine similarity between the question and the kept claims | no |
| Golden check | answer contains the expected value (or, for out-of-scope, is a refusal) | yes |
| Tokens per second | output tokens ÷ generation time reported by Ollama | no |

Per evaluation run (shown on the Evals page):

| Metric | Definition |
| --- | --- |
| Recall@k | share of in-scope cases whose expected section is among the k chunks sent to the model |
| Candidate recall | the same, measured on the 20 candidates before reranking. High here but low recall@k means the reranker is the problem |
| MRR | mean of 1 ÷ rank of the expected section |
| Answer accuracy | share of in-scope cases whose answer contains the expected value |
| Citation accuracy | share of answered cases that cite the expected document |
| Groundedness | mean share of claims that survive the ground check |
| Refusal rate | share of out-of-scope cases refused |
| Refused at gate | share of out-of-scope cases refused before the model was called |
| False refusals | share of in-scope cases not answered |
| Path match | share of cases whose stages ran in the expected order (the trajectory eval) |
| p50 / p95 | median and 95th-percentile time per stage and in total |

Refusal reasons:

| Reason | Meaning |
| --- | --- |
| `below_score_floor` | nothing relevant was retrieved; the model was not called |
| `model_declined` | the model said the sources do not answer the question |
| `no_grounded_claims` | the model answered, and every claim failed the ground check |
| `invalid_json` | the model's output could not be parsed |
| `provider_error: …` | Ollama was unreachable or timed out (status `error`) |

## 9. Models and providers

`PROVIDER` in `.env` picks one. There is no automatic fallback.

**`ollama`** uses Ollama's native HTTP API on `OLLAMA_URL`: `/api/embed` for embeddings, and `/api/chat` with a JSON schema in `format` for generation. The native API is used because it reports token counts and timings, which the monitor shows.

| Role | Default | Size | Notes |
| --- | --- | --- | --- |
| Generation | `qwen2.5:0.5b` | about 400 MB | the smallest model that usually follows a JSON schema |
| Embeddings | `all-minilm` | about 46 MB | 384 dimensions, 256-token input, English |

A half-billion-parameter model is a starting point, not a recommendation. Expect it to miss some questions; the monitor is there to show you which and why. To compare a stronger model, set `GEN_MODEL=qwen2.5:1.5b` or `GEN_MODEL=llama3.2:3b` in `.env`, run `./run.sh`, run the golden set again and read the two rows in the run history.

**`fixture`** needs no model. Embeddings are hashed bags of words, and "generation" quotes the source line that best matches the question. It is deterministic, so the tests and CI use it. Its follow-up rewrite just joins the previous question to the new one, which is why two of the three follow-up cases fail on it. That is expected, and a useful example of a failing case to open in the monitor.

**The reranker.** The course's Level 5 uses a cross-encoder, which is a 2 GB download. This version starts with a light scorer: half cosine similarity, half the share of the question's rare words that the chunk contains. Both parts are between 0 and 1, so the score floor has a stable meaning. Swapping in a cross-encoder is the first item in the plan.

## 10. Settings

All in `.env`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `PROVIDER` | `ollama` in `.env.example` | `ollama` or `fixture` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | where Ollama listens |
| `GEN_MODEL` | `qwen2.5:0.5b` | generation model |
| `EMBED_MODEL` | `all-minilm` | embedding model. Changing it re-embeds the corpus; calibrate again afterwards |
| `PORT` | `8130` | API and pages |
| `TOP_K` | `4` | chunks sent to the model |
| `CANDIDATES` | `20` | chunks fused before reranking |
| `BUDGET_S` | `60` | seconds a model call may take before the question ends as an error |
| `REWRITE` | `auto` | `auto` (only with history), `always`, `off` |
| `SCORE_FLOOR` | unset | overrides the calibrated floor |
| `SUPPORT_FLOOR` | `0.5` | share of a claim's content words that must be in its source |

## 11. Change the corpus or the golden set

Add a policy: put a markdown file in `corpus/` with this shape.

```markdown
---
id: fin-02
title: Procurement Policy
owner: Finance Operations
version: 1.0
effective: 2026-06-01
---
# Procurement Policy

## Purchase approval
Purchases above USD 2,000 need two quotes.
```

One fact per line works best. Each `##` heading starts a new chunk; a section longer than 800 characters is split.

Then add golden cases for it in `evals/golden.json`:

```json
{"id": "g25", "type": "in_scope", "q": "Above what amount do purchases need two quotes?",
 "must": "2,000", "docs": ["fin-02"], "section": "Purchase approval",
 "evidence": "Purchases above USD 2,000 need two quotes."}
```

`evidence` must be an exact line from the document, and must contain `must`; a unit test checks both. Restart the app (the index is rebuilt automatically because the cache key includes the chunk text), then recalibrate and run the golden set.

## 12. API

| Method and path | Purpose |
| --- | --- |
| `POST /api/ask` | `{"question": "...", "history": [{"role": "user", "text": "..."}]}` → answer, citations, `trace_id` |
| `GET /api/traces?kind=live` | recent traces (`live`, `eval`, or all) |
| `GET /api/traces/{id}` | one full trace |
| `POST /api/feedback` | `{"trace_id": "...", "helpful": true}` |
| `GET /api/overview` | totals for live traffic, audit chain status |
| `POST /api/evals/run` | start a golden-set run in the background |
| `GET /api/evals/status` | progress of the running evaluation |
| `GET /api/evals`, `GET /api/evals/{id}` | run history, one run with its cases |
| `POST /api/calibrate` | recalibrate the score floor |
| `GET /healthz`, `GET /readyz` | the process runs / it can really answer |

Local state, all under `.data/`: `minirag.db` (traces, audit log, feedback, evaluation runs), `vectors-*.npy` (embedding cache), `calibration.json`, `last-eval.json`, `ollama.log`.

## 13. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Every answer is `error: provider_error … cannot reach Ollama` | Ollama is not running. Run `./run.sh doctor`, then `./run.sh` |
| `missing models: [...]` from doctor | `ollama pull qwen2.5:0.5b` and `ollama pull all-minilm`, or just `./run.sh` |
| First answer takes many seconds | the model is being loaded into memory; see "loading the model" in section 4 of the trace. Later answers are faster |
| Many `invalid_json` or `no_grounded_claims` refusals | the model is too small for the task. Try `GEN_MODEL=qwen2.5:1.5b` |
| In-scope questions refused with `below_score_floor` | run `./run.sh calibrate`; if you changed `EMBED_MODEL`, this is required |
| Port 8130 is busy | set `PORT` in `.env` (not 3000 or 8000) |
| Ollama's structured output is ignored | update Ollama; JSON-schema `format` needs version 0.5 or newer |

## 14. What was verified, and what was not

Verified on the build machine, with the fixture provider:

- 17 unit and API tests pass, lint is clean, and the golden set passes all six gates (recall@k 100%, accuracy 93%, groundedness 100%, refusal rate 100%).
- The three pages were loaded in a real browser, a question was traced end to end, and a golden-set run was started from the Evals page, with no console errors.
- `./run.sh test` and `./run.sh fixture` ran.
- The Ollama client was tested against a mock of Ollama's API (request shape, schema, token and timing fields, the unreachable-server path).

Not verified: a real Ollama install, model pull and generation. The build machine's network blocks `ollama.com`, so the default `./run.sh` path, the two model names, and the quality and speed of `qwen2.5:0.5b` on this corpus have not been exercised. Treat the first real run as the test, and expect to adjust the prompt or the model.

## 15. Plan: what comes next

Done in 2.0: a local pipeline covering Quest levels 1 to 9, 12 and 13, a trace per question, the Monitor and Evals pages, a golden set with gates, calibration, a one-command runner.

Suggested order for what follows. Each step is a change you can judge with the Evals page: run before, change one thing, run after.

| Step | Change | What to watch |
| --- | --- | --- |
| 1 | Run the golden set on real Ollama with `qwen2.5:0.5b`, then with a 1.5b and a 3b model | answer accuracy, groundedness, p95 of `generate` |
| 2 | Tune the prompt for the smallest model that passes the gates | `invalid_json` and `no_grounded_claims` counts |
| 3 | Optional cross-encoder reranker (Level 5) behind a setting | recall@k against candidate recall, p95 of `rerank` |
| 4 | Grow the golden set to 60+ cases: paraphrases, multi-fact questions, questions that span two documents; split into calibration and test halves | whether the gates still pass on the held-out half |
| 5 | An LLM-judge score for answers without a golden value, run by a larger local model | agreement between the judge and the must-contain check |
| 6 | Prompt-injection cases: a document line that tries to give instructions | the answer must ignore it; add a gate |
| 7 | Drift view: trend lines across runs, and an alert when a gate flips | run history |
| 8 | Tools (Level 10): a router with a second tool, such as a leave-balance lookup, and trajectory cases for it | path match |
| 9 | PostgreSQL + pgvector (Level 11) when the corpus outgrows memory | recall@k must not move |
