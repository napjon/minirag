#!/usr/bin/env bash
# One command for everything.
#
#   ./run.sh            install what is missing, pull the models, index, calibrate, start the app
#   ./run.sh fixture    start the app with no model at all (deterministic stand-ins)
#   ./run.sh eval       run the golden set in the terminal        (extra args are passed on)
#   ./run.sh calibrate  set the score floor from the golden set
#   ./run.sh test       unit tests + golden set on the fixture provider
#   ./run.sh doctor     check that Ollama and both models are ready
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

ensure_uv() {
  command -v uv >/dev/null 2>&1 && return
  say "Installing uv (Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv was installed but is not on PATH; open a new terminal and run ./run.sh again"
}

ensure_env() {
  [ -f .env ] || { cp .env.example .env; say "Created .env from .env.example"; }
  set -a; . ./.env; set +a
  OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
  GEN_MODEL="${GEN_MODEL:-qwen2.5:0.5b}"
  EMBED_MODEL="${EMBED_MODEL:-all-minilm}"
  PORT="${PORT:-8130}"
}

ensure_ollama() {
  if ! command -v ollama >/dev/null 2>&1; then
    say "Installing Ollama"
    case "$(uname -s)" in
      Linux)  curl -fsSL https://ollama.com/install.sh | sh ;;
      Darwin) command -v brew >/dev/null 2>&1 || die "Install Ollama from https://ollama.com/download (or install Homebrew), then run ./run.sh again"
              brew install ollama ;;
      *)      die "Unsupported system. On Windows use WSL2, or install Ollama from https://ollama.com/download" ;;
    esac
  fi
  if ! curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1; then
    say "Starting Ollama in the background (log: .data/ollama.log)"
    mkdir -p .data
    nohup ollama serve >.data/ollama.log 2>&1 &
    for _ in $(seq 1 30); do
      curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1 && break
      sleep 1
    done
    curl -fsS "$OLLAMA_URL/api/version" >/dev/null 2>&1 || die "Ollama did not start; see .data/ollama.log"
  fi
  for model in "$GEN_MODEL" "$EMBED_MODEL"; do
    if ! ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx -e "$model" -e "$model:latest"; then
      say "Pulling $model"
      ollama pull "$model"
    fi
  done
}

cmd="${1:-up}"
[ $# -gt 0 ] && shift

case "$cmd" in
  up)
    ensure_uv; ensure_env
    [ "${PROVIDER:-ollama}" = "ollama" ] && ensure_ollama
    say "Installing Python dependencies"; uv sync --extra dev --quiet
    say "Indexing the corpus";            uv run minirag index
    say "Calibrating the score floor";    uv run python evals/runner.py --calibrate
    say "Open http://127.0.0.1:$PORT   (Ctrl+C to stop)"
    exec uv run minirag serve ;;
  fixture)
    ensure_uv; uv sync --extra dev --quiet
    say "Fixture provider: no model, deterministic answers. Open http://127.0.0.1:${PORT:-8130}"
    MINIRAG_NO_DOTENV=1 PROVIDER=fixture DATA_DIR=.data/fixture exec uv run minirag serve ;;
  eval)      ensure_uv; ensure_env; exec uv run python evals/runner.py "$@" ;;
  calibrate) ensure_uv; ensure_env; exec uv run python evals/runner.py --calibrate ;;
  doctor)    ensure_uv; ensure_env; exec uv run minirag doctor ;;
  test)
    ensure_uv; uv sync --extra dev --quiet
    export MINIRAG_NO_DOTENV=1 PROVIDER=fixture DATA_DIR=.data/test
    uv run ruff check .
    uv run pytest -q
    exec uv run python evals/runner.py ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
