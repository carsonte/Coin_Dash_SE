from __future__ import annotations

from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from coin_dash.api import app
from coin_dash.config import DatabaseCfg
from coin_dash.db.services import DatabaseServices


def test_api_decisions_with_committee_filter(monkeypatch):
    tmp = Path(tempfile.mkstemp(prefix="api_committee_", suffix=".db")[1])
    db_cfg = DatabaseCfg(enabled=True, dsn=f"sqlite:///{tmp}", auto_migrate=True, pool_size=5, echo=False)
    services = DatabaseServices(db_cfg, run_id="run-api")
    # Monkeypatch api services to in-memory DB
    import coin_dash.api as api_module

    monkeypatch.setattr(api_module, "services", services)

    logger = services.ai_logger
    assert logger is not None
    committee_id = "cid-123"
    payload = {"p": 1}
    result = {"r": 1}
    # three models + final
    logger.log_decision("decision", "BTCUSDm", payload, result, None, None, model_name="deepseek", committee_id=committee_id, weight=0.5)
    logger.log_decision("decision", "BTCUSDm", payload, result, None, None, model_name="gpt-4o-mini", committee_id=committee_id, weight=0.3)
    logger.log_decision("decision", "BTCUSDm", payload, result, None, None, model_name="glm-4.5-air", committee_id=committee_id, weight=0.2)
    logger.log_decision("decision", "BTCUSDm", payload, result, None, None, model_name="committee", committee_id=committee_id, weight=None, is_final=True)

    # sanity check rows exist
    with services.client.session() as session:
        rows = session.execute(text("SELECT count(*) FROM ai_decisions")).scalar_one()
    assert rows == 4

    client = TestClient(app)
    start = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = client.get("/api/decisions", params={"start": start, "end": end, "committee_id": committee_id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    models = {item["model_name"] for item in data["items"]}
    assert {"deepseek", "gpt-4o-mini", "glm-4.5-air", "committee"} <= models
    finals = [item for item in data["items"] if item["is_final"]]
    assert len(finals) == 1
