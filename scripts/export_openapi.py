"""Write docs/openapi.json from the FastAPI app without running startup."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402


def main() -> None:
    target = ROOT / "docs" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
