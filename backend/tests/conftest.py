import pytest
from app.db import init_schema


@pytest.fixture(autouse=True)
def isolated_sqlite_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr("app.config.settings.packages_web_db_path", str(db_path))
    init_schema()
    yield db_path
