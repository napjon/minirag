import os

import pytest

os.environ["MINIRAG_NO_DOTENV"] = "1"      # tests never read the developer's .env


@pytest.fixture()
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("PROVIDER", "fixture")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SCORE_FLOOR", raising=False)
    from minirag.pipeline import Engine
    return Engine()
