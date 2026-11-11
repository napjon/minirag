# minirag 2.0

A small RAG system that runs entirely on your laptop, with every step monitored.

The use case is invented: **Corvane Bank** wants an assistant that answers employees' questions from its internal policy library (leave, expenses, security, branch operations, and so on). The bank, the nine policy documents in `corpus/` and the golden set in `evals/golden.json` are all fictional.

No cloud services are used. Models run through [Ollama](https://ollama.com) on localhost.

## Run it

```bash
git clone https://github.com/napjon/minirag.git
```

```bash
cd minirag
```

```bash
./run.sh
```

Then open <http://127.0.0.1:8130>.

`./run.sh` does everything in one go: installs `uv` and Ollama if they are missing, starts Ollama, pulls the two smallest useful models (`qwen2.5:0.5b`, about 400 MB, and `all-minilm`, about 46 MB), installs the Python packages, indexes the corpus, calibrates the refusal threshold and starts the app. Run it again any time; finished steps are skipped.

Works on macOS and Linux. On Windows, use WSL2.

No model, no download? This starts the same app with deterministic stand-ins:

```bash
./run.sh fixture
```

## The three pages

| Page | What it is for |
| --- | --- |
| **Ask** | What an employee sees: a question, a cited answer or a refusal, a thumbs up/down. |
| **Monitor** | Type a question and see everything behind the answer: which chunks keyword and vector search fetched, their scores, the refusal gate, the exact prompt and raw model output, token counts and speed, the ground check on every claim, accuracy against the golden set, time per stage, and the audit hash. Totals for live traffic sit at the top. |
| **Evals** | Run the golden set (35 questions) with one button. Shows recall@k, answer accuracy, groundedness, refusal rate, path match, p50/p95 per stage, every case with a link to its trace, and the history of runs. |

## Other commands

| Command | What it does |
| --- | --- |
| `./run.sh eval` | Golden set in the terminal. Exit code 1 if a gate fails; add `--no-gate` to only report. |
| `./run.sh calibrate` | Set the refusal threshold from the golden set. |
| `./run.sh test` | Lint, unit tests and the golden set on the fixture provider. |
| `./run.sh doctor` | Check that Ollama and both models are ready. |
| `uv run minirag ask "How many days of annual leave do I get?"` | One question in the terminal, with the chunks used. |

Settings live in `.env` (created from `.env.example`). To try a stronger model, change `GEN_MODEL` (for example `qwen2.5:1.5b` or `llama3.2:3b`) and run `./run.sh` again.

## Read next

[docs/GUIDE.md](docs/GUIDE.md) is the full document: the use case, how the code maps to the Quest levels, what every number on the monitor means, how to extend the corpus and golden set, and the plan for what comes after.
