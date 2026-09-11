import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_restore_script_is_executable():
    path = ROOT / "scripts" / "restore.sh"
    assert path.is_file()
    assert os.access(path, os.X_OK)
    text = path.read_text()
    assert "pg_dump" in text
    assert "pg_restore" in text
    assert "failover" in text


def test_load_capture_script_exists():
    path = ROOT / "scripts" / "load_capture.py"
    assert path.is_file()
    text = path.read_text()
    assert "/v1/questions" in text
    assert "p95_ms" in text


def test_uv_lock_is_tracked():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "uv.lock" not in gitignore.splitlines()
    assert (ROOT / "uv.lock").is_file()


def test_capacity_docs_are_pilot_scale():
    arch = (ROOT / "docs/architecture.md").read_text()
    assert "1.2 million" in arch or "1,200,000" in arch
    assert "OpenSearch is deferred" in arch
