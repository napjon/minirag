from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_clear_session_drops_draft_cache():
    api = (ROOT / "web/src/api.ts").read_text()
    assert "localStorage.removeItem(DRAFT_KEY)" in api
    assert "if (!session || !raw) return null" in api
    assert "persistableCachedDraft" in api


def test_planning_does_not_restore_body_after_forbidden():
    planning = (ROOT / "web/src/views/Planning.tsx").read_text()
    api = (ROOT / "web/src/api.ts").read_text()
    assert "shouldRestoreDraftCache" in api
    assert "content: null" in planning
    assert "status !== 401 && status !== 403 && status !== 404" in api


def test_catalog_does_not_mount_unbounded_list():
    catalog = (ROOT / "web/src/views/Catalog.tsx").read_text()
    assert "catalogProducts()" not in catalog
    assert "productSearch" in catalog
    api = (ROOT / "web/src/api.ts").read_text()
    assert "limit=${limit}" in api or "limit=" in api
