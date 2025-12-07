from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, cast, String

from .config import load_config
from .db import build_database_services, DatabaseServices
from .db.models import AIDecisionLog, SystemEvent, TradeRecord, SignalEntry


cfg = load_config(None)
services: Optional[DatabaseServices] = build_database_services(cfg.database, run_id=None)

if services is None:
    raise RuntimeError("Database is disabled; enable database in config to use API")


def get_session():
    with services.client.session() as session:
        if session is None:
            raise HTTPException(status_code=500, detail="DB session unavailable")
        yield session


app = FastAPI(title="Coin Dash Logs API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


def _apply_time_filter(query, model, start: str, end: str):
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    if not hasattr(model, "created_at"):
        raise HTTPException(status_code=400, detail="Model missing created_at for filtering")
    return query.filter(model.created_at >= start_dt).filter(model.created_at <= end_dt)


def _paginate(query, limit: int, offset: int):
    return query.limit(limit).offset(offset)


def _require_time_params(start: Optional[str], end: Optional[str]) -> Tuple[str, str]:
    if not start or not end:
        raise HTTPException(status_code=400, detail="start and end are required (ISO datetime)")
    return start, end


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/decisions")
def list_decisions(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    symbol: Optional[str] = None,
    run_id: Optional[str] = None,
    committee_id: Optional[str] = None,
    model_name: Optional[str] = None,
    decision_type: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    start, end = _require_time_params(start, end)
    q = session.query(AIDecisionLog)
    q = _apply_time_filter(q, AIDecisionLog, start, end)
    if symbol:
        q = q.filter(AIDecisionLog.symbol == symbol)
    if run_id:
        q = q.filter(AIDecisionLog.run_id == run_id)
    if committee_id:
        q = q.filter(AIDecisionLog.committee_id == committee_id)
    if model_name:
        q = q.filter(AIDecisionLog.model_name == model_name)
    if decision_type:
        q = q.filter(AIDecisionLog.decision_type == decision_type)
    if keyword:
        pattern = f"%{keyword}%"
        q = q.filter(cast(AIDecisionLog.result, String).ilike(pattern))
    total = q.count()
    items = (
        _paginate(q.order_by(AIDecisionLog.created_at.desc()), limit, offset)
        .with_entities(
            AIDecisionLog.id,
            AIDecisionLog.run_id,
            AIDecisionLog.committee_id,
            AIDecisionLog.model_name,
            AIDecisionLog.is_final,
            AIDecisionLog.weight,
            AIDecisionLog.symbol,
            AIDecisionLog.decision_type,
            AIDecisionLog.confidence,
            AIDecisionLog.tokens_used,
            AIDecisionLog.latency_ms,
            AIDecisionLog.created_at,
            AIDecisionLog.result,
        )
        .all()
    )
    def _snippet(result: Dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return ""
        reason = result.get("reason") or ""
        text = str(reason)
        return text[:160]
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "committee_id": row.committee_id,
                "model_name": row.model_name,
                "is_final": row.is_final,
                "weight": row.weight,
                "symbol": row.symbol,
                "decision_type": row.decision_type,
                "confidence": row.confidence,
                "tokens_used": row.tokens_used,
                "latency_ms": row.latency_ms,
                "created_at": row.created_at,
                "reason_snippet": _snippet(row.result),
            }
            for row in items
        ],
    }


@app.get("/api/decisions/{decision_id}")
def decision_detail(decision_id: int, session: Session = Depends(get_session)):
    row = session.get(AIDecisionLog, decision_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": row.id,
        "run_id": row.run_id,
        "symbol": row.symbol,
        "decision_type": row.decision_type,
        "payload": row.payload,
        "result": row.result,
        "tokens_used": row.tokens_used,
        "latency_ms": row.latency_ms,
        "confidence": row.confidence,
        "created_at": row.created_at,
    }


@app.get("/api/system-events")
def list_events(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    event_type: Optional[str] = None,
    run_id: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    start, end = _require_time_params(start, end)
    q = session.query(SystemEvent)
    q = _apply_time_filter(q, SystemEvent, start, end)
    if event_type:
        q = q.filter(SystemEvent.event_type == event_type)
    if run_id:
        q = q.filter(SystemEvent.run_id == run_id)
    if keyword:
        pattern = f"%{keyword}%"
        q = q.filter(SystemEvent.description.ilike(pattern))
    total = q.count()
    items = (
        _paginate(q.order_by(SystemEvent.created_at.desc()), limit, offset)
        .with_entities(
            SystemEvent.id,
            SystemEvent.run_id,
            SystemEvent.event_type,
            SystemEvent.severity,
            SystemEvent.description,
            SystemEvent.created_at,
        )
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "event_type": row.event_type,
                "severity": row.severity,
                "description": row.description,
                "created_at": row.created_at,
            }
            for row in items
        ],
    }


@app.get("/api/system-events/{event_id}")
def event_detail(event_id: int, session: Session = Depends(get_session)):
    row = session.get(SystemEvent, event_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "id": row.id,
        "run_id": row.run_id,
        "event_type": row.event_type,
        "severity": row.severity,
        "description": row.description,
        "payload": row.payload,
        "created_at": row.created_at,
    }


@app.get("/api/trades")
def list_trades(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    symbol: Optional[str] = None,
    run_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    start, end = _require_time_params(start, end)
    q = session.query(TradeRecord)
    q = q.filter(TradeRecord.opened_at >= _parse_dt(start)).filter(TradeRecord.opened_at <= _parse_dt(end))
    if symbol:
        q = q.filter(TradeRecord.symbol == symbol)
    if run_id:
        q = q.filter(TradeRecord.run_id == run_id)
    total = q.count()
    items = (
        _paginate(q.order_by(TradeRecord.opened_at.desc()), limit, offset)
        .with_entities(
            TradeRecord.id,
            TradeRecord.run_id,
            TradeRecord.trade_id,
            TradeRecord.symbol,
            TradeRecord.side,
            TradeRecord.entry_price,
            TradeRecord.stop_loss,
            TradeRecord.take_profit,
            TradeRecord.exit_price,
            TradeRecord.exit_reason,
            TradeRecord.rr,
            TradeRecord.status,
            TradeRecord.opened_at,
            TradeRecord.exit_at,
        )
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "trade_id": row.trade_id,
                "symbol": row.symbol,
                "side": row.side,
                "entry_price": row.entry_price,
                "stop_loss": row.stop_loss,
                "take_profit": row.take_profit,
                "exit_price": row.exit_price,
                "exit_reason": row.exit_reason,
                "rr": row.rr,
                "status": row.status,
                "opened_at": row.opened_at,
                "exit_at": row.exit_at,
            }
            for row in items
        ],
    }


@app.get("/api/signals")
def list_signals(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    symbol: Optional[str] = None,
    run_id: Optional[str] = None,
    direction: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    start, end = _require_time_params(start, end)
    q = session.query(SignalEntry)
    q = _apply_time_filter(q, SignalEntry, start, end)
    if symbol:
        q = q.filter(SignalEntry.symbol == symbol)
    if run_id:
        q = q.filter(SignalEntry.run_id == run_id)
    if direction:
        q = q.filter(SignalEntry.direction == direction)
    total = q.count()
    items = (
        _paginate(q.order_by(SignalEntry.created_at.desc()), limit, offset)
        .with_entities(
            SignalEntry.id,
            SignalEntry.run_id,
            SignalEntry.signal_id,
            SignalEntry.symbol,
            SignalEntry.direction,
            SignalEntry.entry_price,
            SignalEntry.stop_loss,
            SignalEntry.take_profit,
            SignalEntry.risk_reward,
            SignalEntry.status,
            SignalEntry.created_at,
        )
        .all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "run_id": row.run_id,
                "signal_id": row.signal_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "entry_price": row.entry_price,
                "stop_loss": row.stop_loss,
                "take_profit": row.take_profit,
                "risk_reward": row.risk_reward,
                "status": row.status,
                "created_at": row.created_at,
            }
            for row in items
        ],
    }


@app.get("/api/stats")
def stats(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    session: Session = Depends(get_session),
):
    start, end = _require_time_params(start, end)
    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end)
    q = session.query(AIDecisionLog).filter(
        and_(AIDecisionLog.created_at >= start_dt, AIDecisionLog.created_at <= end_dt)
    )
    total = q.count()
    avg_latency = q.with_entities(func.avg(AIDecisionLog.latency_ms)).scalar() or 0.0
    total_tokens = q.with_entities(func.sum(AIDecisionLog.tokens_used)).scalar() or 0
    per_symbol = (
        q.with_entities(AIDecisionLog.symbol, func.count(AIDecisionLog.id))
        .group_by(AIDecisionLog.symbol)
        .all()
    )
    per_run = (
        q.with_entities(AIDecisionLog.run_id, func.count(AIDecisionLog.id))
        .group_by(AIDecisionLog.run_id)
        .all()
    )
    return {
        "total": total,
        "avg_latency_ms": float(avg_latency),
        "total_tokens": int(total_tokens),
        "by_symbol": {sym: cnt for sym, cnt in per_symbol if sym},
        "by_run_id": {rid: cnt for rid, cnt in per_run if rid},
    }


@app.get("/api/enums/system-events")
def event_enum():
    from .db.system_monitor import STANDARD_EVENT_TYPES

    return {"event_types": sorted(STANDARD_EVENT_TYPES)}
