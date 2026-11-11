"""Settings come from the environment, then .env, then the defaults below."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FLOOR = {"fixture": 0.43, "ollama": 0.25}


def _load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists() or os.environ.get("MINIRAG_NO_DOTENV"):
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class Settings:
    provider: str
    ollama_url: str
    gen_model: str
    embed_model: str
    port: int
    top_k: int
    candidates: int
    budget_s: float
    rewrite: str
    score_floor: float | None
    support_floor: float
    data_dir: Path
    corpus_dir: Path
    golden_path: Path


def settings() -> Settings:
    _load_dotenv()
    env = os.environ.get
    floor = env("SCORE_FLOOR")
    return Settings(
        provider=env("PROVIDER", "fixture"),
        ollama_url=env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
        gen_model=env("GEN_MODEL", "qwen2.5:0.5b"),
        embed_model=env("EMBED_MODEL", "all-minilm"),
        port=int(env("PORT", "8130")),
        top_k=int(env("TOP_K", "4")),
        candidates=int(env("CANDIDATES", "20")),
        budget_s=float(env("BUDGET_S", "60")),
        rewrite=env("REWRITE", "auto"),
        score_floor=float(floor) if floor else None,
        support_floor=float(env("SUPPORT_FLOOR", "0.5")),
        data_dir=Path(env("DATA_DIR", str(ROOT / ".data"))),
        corpus_dir=Path(env("CORPUS_DIR", str(ROOT / "corpus"))),
        golden_path=Path(env("GOLDEN_PATH", str(ROOT / "evals" / "golden.json"))),
    )
