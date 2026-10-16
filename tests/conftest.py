import pytest


@pytest.fixture(autouse=True)
def _rupa_log(tmp_path, monkeypatch):
    """Keep test runs out of the real failure log; tests can read it here."""
    path = tmp_path / "rupa-log.jsonl"
    monkeypatch.setenv("RUPA_LOG", str(path))
    return path
