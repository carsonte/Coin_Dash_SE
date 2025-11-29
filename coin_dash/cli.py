from __future__ import annotations







import argparse



import os
import socket



import sys



import time



from datetime import datetime, timezone, timedelta



from pathlib import Path



from typing import List, Optional







import pandas as pd



from dotenv import load_dotenv



from rich import print







from .ai.deepseek_adapter import DeepSeekClient



from .ai.models import Decision






from .backtest.engine import run_backtest



from .config import load_config



from .db import build_database_services



from .features.market_mode import MODE_WEIGHTS, MarketMode



from .features.structure import StructureBundle, StructureLevels



from .features.trend import TrendProfile, TrendSnapshot



from .notify.lark import (

    AnomalyAlertPayload,

    ExitEventPayload,

    ModeSwitchAlertPayload,

    ReviewAdjustPayload,

    ReviewClosePayload,

    WatchPayload,

    configure_lark_signing,

    send_healthcheck_card,

    send_anomaly_card,

    

    send_exit_card,

    

    send_mode_alert_card,

    

    send_performance_card,

    

    send_review_adjust_card,

    

    send_review_close_card,

    

    send_signal_card,

    

    send_watch_card,

    

    )



from .runtime.orchestrator import LiveOrchestrator



from .signals.manager import SignalRecord


def _force_utf8() -> None:
    try:
        import locale
        enc = locale.getpreferredencoding(False) or "utf-8"
        sys.stdout.reconfigure(encoding=enc, errors="replace")
        sys.stderr.reconfigure(encoding=enc, errors="replace")
    except Exception:
        pass


_force_utf8()


ROOT = Path(__file__).resolve().parents[1]



load_dotenv(ROOT / ".env", override=False)










def _generate_run_id() -> str:
    host = socket.gethostname()
    return f"{host}-{int(time.time())}"


def _build_db_services(cfg, run_id: str | None = None):



    return build_database_services(cfg.database, run_id=run_id)











def _apply_notification_config(cfg) -> None:

    configure_lark_signing(getattr(cfg.notifications, "lark_signing_secret", None))





def cmd_backtest(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    run_id = args.run_id or _generate_run_id()

    services = _build_db_services(cfg, run_id=run_id)



    if args.csv is None:



        raise SystemExit("--csv is required")







    df = pd.read_csv(args.csv)



    if "timestamp" not in df.columns:



        raise SystemExit("CSV must contain timestamp column")



    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")



    df = df.set_index("timestamp").sort_index()







    try:



        report = run_backtest(df, args.symbol, cfg, use_deepseek=args.deepseek, db_services=services)



    finally:



        if services:



            services.dispose()



    print("[bold green]Backtest Summary[/bold green]", report.summary)



    if report.modes:



        print("Mode stats:", report.modes)



    if report.trade_types:



        print("Trade-type stats:", report.trade_types)



    print(f"Logs: {len(report.logs)} events (showing last 10)")



    for line in report.logs[-10:]:



        print(line)











def cmd_live(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    run_id = args.run_id or _generate_run_id()

    services = _build_db_services(cfg, run_id=run_id)



    live_symbols = []
    if args.symbols:
        live_symbols = args.symbols.split(",")
    elif getattr(cfg, "live", None) and getattr(cfg.live, "symbols", None):
        live_symbols = list(cfg.live.symbols)
    else:
        live_symbols = cfg.symbols
    target = live_symbols



    orchestrator = LiveOrchestrator(cfg, db_services=services, run_id=run_id)







    # 中文说明：
    # 开启 --align 时，live 循环会对齐到周期边界（如 15/30/60 分钟整点），
    # 在边界后的偏移（--align-skew）再执行一次，确保行情/特征已刷新；
    # 如果未开启，对齐逻辑关闭，按 --interval 秒数常规轮询。





    def _label_to_minutes(label: str) -> int:
        """Parse timeframe label like '30m'/'1h'/'4h'/'1d' into minutes."""
        s = (label or "").strip().lower()



        if s.endswith("m"):



            return int(s[:-1])



        if s.endswith("h"):



            return int(s[:-1]) * 60



        if s.endswith("d"):



            return int(s[:-1]) * 1440



        raise ValueError(f"无法解析周期标签: {label}")







    def _sleep_align(period_minutes: int, skew_seconds: int) -> None:
        """Align to the next period boundary then sleep with an extra skew."""
        now = datetime.now(timezone.utc)



        # 按 UTC 计算下一周期边界分钟



        total_min = now.hour * 60 + now.minute



        rem = total_min % period_minutes



        add_min = (period_minutes - rem) % period_minutes



        if add_min == 0:



            add_min = period_minutes



        next_dt = now.replace(second=0, microsecond=0) + timedelta(minutes=add_min)



        sleep_s = max(1.0, (next_dt - now).total_seconds() + max(0, skew_seconds))



        time.sleep(sleep_s)







    try:



        if args.loop:



            try:



                while True:



                    # 中文：在复评间隔（signals.review_interval_minutes）的整数边界跑完整周期，其余时间跑轻量心跳



                    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)



                    period = max(5, int(cfg.signals.review_interval_minutes))  # 默认 60 分钟，可通过配置调整



                    if (now.minute % period) == 0:



                        orchestrator.run_cycle(target)  # 全量复评 + 新信号生成

                    else:



                        orchestrator.run_heartbeat(target)  # 5m 心跳：检查 TP/SL / 临时复评



                    # 对齐到下一个 5 分钟边界，并加 3s 缓冲



                    _sleep_align(5, 3)



            except KeyboardInterrupt:



                print("[yellow]Loop interrupted by user[/yellow]")



        else:



            orchestrator.run_cycle(target)



    finally:



        if services:



            services.dispose()











def cmd_cards_test(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    webhook = args.webhook or os.getenv("LARK_WEBHOOK") or cfg.notifications.lark_webhook



    if not webhook:



        raise SystemExit("请先设置 Lark Webhook")







    trend = TrendProfile(



        snapshots={



            "1d": TrendSnapshot(1, 20, 48200, 47000),



            "4h": TrendSnapshot(1, 15, 48000, 47200),



            "1h": TrendSnapshot(1, 10, 47900, 47400),



            "30m": TrendSnapshot(1, 5, 47850, 47550),



        },



        score=88.0,



        grade="strong",



        global_direction=1,



    )



    structure = StructureBundle(



        levels={



            "4h": StructureLevels(47500, 48800, "4h"),



            "1d": StructureLevels(47000, 49000, "1d"),



        }



    )



    market_mode = MarketMode(



        name="trending",



        confidence=0.82,



        reasons={"atr_pct": 0.72},



        cycle_weights=MODE_WEIGHTS["trending"],



    )



    decision = Decision(
        decision="open_long",
        entry_price=48200.0,
        stop_loss=47600.0,
        take_profit=49200.0,
        risk_reward=2.0,
        confidence=86.0,
        reason="cards-test",
        position_size=1.0,
        meta={"adapter": "cards-test"},
    )



    record = SignalRecord(



        symbol=args.symbol,



        decision=decision,



        trade_type="trend",



        market_mode=market_mode,



        trend=trend,



        structure=structure,



        created_at=datetime.utcnow(),



        expires_at=datetime.utcnow(),



        notes=["cards-test"],



    )



    send_signal_card(webhook, record, args.correlated)







    review_close = ReviewClosePayload(



        symbol=args.symbol,



        side="多头",



        entry_price=48000.0,



        close_price=48750.0,



        pnl=150.0,



        rr=1.2,



        reason="样例复评平仓",



        context="cards-test",



        confidence=85.0,



        action="提前平仓",



    )



    send_review_close_card(webhook, review_close)







    review_adjust = ReviewAdjustPayload(



        symbol=args.symbol,



        side="多头",



        entry_price=48000.0,



        old_stop=47500.0,



        new_stop=47800.0,



        old_take=49200.0,



        new_take=49500.0,



        old_rr=2.0,



        new_rr=2.3,



        reason="复评建议收紧止损",



        market_update="cards-test",



        next_review=datetime.utcnow(),



    )



    send_review_adjust_card(webhook, review_adjust)
    watch_payload = WatchPayload(
        symbol=args.symbol,
        reason="暂无高质量信号，等待动能与结构共振",
        market_note="趋势分歧，价量动能不足",
        confidence=78.0,
        next_check=datetime.utcnow() + timedelta(minutes=30),
    )
    send_watch_card(webhook, watch_payload)

    exit_payload = ExitEventPayload(



        symbol=args.symbol,



        side="多头",



        entry_price=48000.0,



        exit_price=49000.0,



        pnl=200.0,



        rr=2.0,



        duration="3h",



        reason="样例止盈",



        exit_type="take_profit",



    )



    send_exit_card(webhook, exit_payload)







    mode_alert = ModeSwitchAlertPayload(
        symbol=args.symbol,
        from_mode="ranging",
        to_mode="trending",
        confidence=80.0,
        affected_symbols=[args.symbol],
        risk_level="中",
        suggestion="关注顺势信号",
        indicators="ATR↑, 成交量放大",
    )



    send_mode_alert_card(webhook, mode_alert)







    anomaly = AnomalyAlertPayload(
        event_type="cards-test",
        severity="中",
        occurred_at=datetime.utcnow(),
        impact="示例异常",
        status="降级运行",
        actions="无需处理",
    )



    send_anomaly_card(webhook, anomaly)







    performance_summary = {



        "equity": 10500,



        "closed": 8,



        "trades": 10,



        "wins": 6,



        "win_rate": 0.6,



        "pnl_total": 520,



        "profit_factor": 1.8,



    }



    send_performance_card(



        webhook,



        performance_summary,



        {"trending": {"count": 4, "win_rate": 0.6, "avg_rr": 1.8, "pnl": 320}},



        {"trend": {"count": 6, "win_rate": 0.5, "avg_rr": 1.7, "pnl": 210}},



        {"BTCUSDT": {"count": 5, "win_rate": 0.6, "pnl": 280}, "ETHUSDT": {"count": 3, "win_rate": 0.33, "pnl": -60}},



    )



    print("[green]Test cards sent (errors ignored).[/green]")











def cmd_deepseek_test(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    _apply_notification_config(cfg)

    client = DeepSeekClient(cfg.deepseek)
    if not client.enabled():
        raise SystemExit("DeepSeek 未启用或缺少 DEEPSEEK_API_KEY，请在 .env/config 设置并启用 deepseek.enabled=true")

    decision_payload = {
        'market_mode': 'trending',
        'mode_confidence': 0.82,
        'trend_score': 84,
        'trend_grade': 'strong',
        'features': {
            'price_30m': 48200.0,
            'ema20_30m': 48050.0,
            'ema60_30m': 47680.0,
            'rsi_30m': 63.0,
            'atr_30m': 180.0,
        },
        'cycle_weights': {'1d': 0.4, '4h': 0.3, '1h': 0.2, '30m': 0.1},
        'structure': {
            '4h': {'support': 47400.0, 'resistance': 48800.0},
            '1d': {'support': 46800.0, 'resistance': 49200.0},
        },
        'environment': {'volatility': 'normal', 'regime': 'trending_up', 'noise_level': 'normal', 'liquidity': 'normal'},
        'global_temperature': {'market_risk': 'medium', 'temperature': 'warm'},
        'recent_ohlc': {
            '30m': [
                {'open': 48100.0, 'high': 48250.0, 'low': 48000.0, 'close': 48200.0, 'volume': 3.2},
                {'open': 48200.0, 'high': 48320.0, 'low': 48120.0, 'close': 48300.0, 'volume': 3.4},
            ],
            '1h': [
                {'open': 47850.0, 'high': 48350.0, 'low': 47700.0, 'close': 48250.0, 'volume': 3.6},
            ],
            '4h': [
                {'open': 47000.0, 'high': 48400.0, 'low': 46800.0, 'close': 48200.0, 'volume': 3.8},
            ],
        },
    }

    print('[cyan]调用 DeepSeek 决策接口...[/cyan]')
    try:
        decision = client.decide_trade(args.symbol, decision_payload)
    except Exception as exc:
        print(f"[red]DeepSeek 调用失败: {exc}")
        return

    print(
        f"决策成功: action={decision.decision}, entry={decision.entry_price:.2f}, stop={decision.stop_loss:.2f}, "
        f"take={decision.take_profit:.2f}, \nrr={decision.risk_reward:.2f}, confidence={decision.confidence:.1f}"
    )

    if args.review:
        review_payload = {
            'context_note': 'demo review',
            'position': {
                'symbol': args.symbol,
                'side': decision.decision,
                'entry': decision.entry_price,
                'stop': decision.stop_loss,
                'take': decision.take_profit,
                'rr': decision.risk_reward,
            },
            'market': {
                'mode': 'trending',
                'trend_score': 84,
                'trend_grade': 'strong',
                'price': decision.entry_price,
            },
            'environment': decision_payload['environment'],
            'global_temperature': decision_payload['global_temperature'],
            'recent_ohlc': decision_payload['recent_ohlc'],
        }
        print('[cyan]DeepSeek review API...[/cyan]')
        review = client.review_position(args.symbol, 'test-position', review_payload)
        print(f"[green]复评成功[/green]: action={review.action}, reason={review.reason}")

    print('[bold green]DeepSeek API 测试完成[/bold green]')

def cmd_healthcheck(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    webhook = args.webhook or os.getenv("LARK_WEBHOOK") or cfg.notifications.lark_webhook



    if not webhook:



        raise SystemExit("请配置 Lark Webhook 或使用 --webhook 传入")







    checks: List[Dict[str, str | bool]] = []







    # Lark 连通性预检

    lark_ok = False



    lark_detail = ""



    try:



        send_healthcheck_card(
            webhook,
            '部署自检 · Lark 预检',
            [{"name": "Lark Webhook", "status": True, "detail": "测试卡片发送成功"}],
        )



        lark_ok = True
        lark_detail = "测试卡片发送成功"



    except Exception as exc:  # noqa: BLE001



        lark_detail = f"发送失败：{exc}"



    checks.append({"name": "Lark Webhook", "status": lark_ok, "detail": lark_detail})







    # DeepSeek 连通性预检

    deepseek_status: bool | None = None



    deepseek_detail = ""



    if not cfg.deepseek.enabled:



        deepseek_status = None



        deepseek_detail = "config.deepseek.enabled = false"



    else:



        client = DeepSeekClient(cfg.deepseek)



        if not client.enabled():



            deepseek_status = False



            deepseek_detail = "未配置 DEEPSEEK_API_KEY，或环境变量不可用"



        else:



            payload = {



                "market_mode": "trending",



                "mode_confidence": 0.8,



                "trend_score": 80,



                "trend_grade": "strong",



                "features": {



                    "price_30m": 48200.0,



                    "ema20_30m": 48050.0,



                    "ema60_30m": 47680.0,



                    "rsi_30m": 63.0,



                    "atr_30m": 180.0,



                },



                "cycle_weights": {"1d": 0.4, "4h": 0.3, "1h": 0.2, "30m": 0.1},



                "structure": {



                    "4h": {"support": 47400.0, "resistance": 48800.0},



                    "1d": {"support": 46800.0, "resistance": 49200.0},



                },



            }



            try:



                decision = client.decide_trade(args.symbol, payload)



                deepseek_status = True



                deepseek_detail = f"action={decision.decision}, rr={decision.risk_reward:.2f}, confidence={decision.confidence:.1f}"



            except Exception as exc:  # noqa: BLE001



                deepseek_status = False



                deepseek_detail = f"调用失败：{exc}"



    checks.append({"name": "DeepSeek API", "status": deepseek_status, "detail": deepseek_detail})







    # 输出到终端

    for item in checks:



        status = item.get("status")



        icon = "?" if status is True else ("?" if status is False else "??")



        print(f"{icon} {item['name']}: {item.get('detail','')}")







    # 仅在 webhook 测试成功时推送自检卡片

    if lark_ok:



        try:



            send_healthcheck_card(webhook, "全量自检结果", checks)



            print("[green]已发送部署自检卡片到 Lark[/green]")

        except Exception as exc:  # noqa: BLE001



            print(f"[red]发送自检结果失败：{exc}[/red]")



    else:



        print("[yellow]Lark Webhook 测试未通过，暂不发送自检卡片[/yellow]")











def cmd_close_all(args: argparse.Namespace) -> None:
    """One-key close: mark all open positions closed and notify manual close."""
    cfg = load_config(args.config)
    _apply_notification_config(cfg)
    services = _build_db_services(cfg)
    from .runtime.orchestrator import STATE_PATH
    symbols = [s.strip() for s in (args.symbols.split(",") if args.symbols else cfg.symbols)]
    state = StateManager(STATE_PATH)
    webhook = cfg.notifications.lark_webhook
    for symbol in symbols:
        for pos in list(state.list_positions(symbol)):
            payload = state.close_position(
                symbol=symbol,
                position_id=pos.id,
                exit_price=pos.entry,
                exit_type="manual_close",
                reason="一键平仓，请手动市价平仓",
                duration="0m",
            )
            if payload:
                send_exit_card(webhook, payload)
                if services and services.trading:
                    services.trading.upsert_position(pos, status="closed")
                    services.trading.record_manual_close(
                        position_id=pos.id,
                        symbol=symbol,
                        side=pos.side,
                        entry_price=pos.entry,
                        exit_price=pos.entry,
                        reason="manual_close",
                        rr=pos.rr,
                    )


def build_parser() -> argparse.ArgumentParser:



    parser = argparse.ArgumentParser(prog="python -m coin_dash.cli", description="Coin Dash command line tools")



    sub = parser.add_subparsers(dest="command", required=True)







    p_backtest = sub.add_parser("backtest", help="运行本地 CSV 回测")



    p_backtest.add_argument("--symbol", default="BTCUSDT")



    p_backtest.add_argument("--timeframe", default="1h")



    p_backtest.add_argument("--csv", type=Path, required=True)



    p_backtest.add_argument("--config", type=Path, default=None)



    p_backtest.add_argument("--deepseek", action="store_true", help="启用 DeepSeek 决策")



    p_backtest.add_argument("--run-id", default=None, help="可选，指定本次回测的 run_id（默认自动生成）")

    p_backtest.set_defaults(func=cmd_backtest)







    p_live = sub.add_parser("live", help="执行实时流程一次或循环")
    p_live.add_argument("--symbols", help="逗号分隔交易对", default=None)
    p_live.add_argument("--config", type=Path, default=None)
    p_live.add_argument("--loop", action="store_true", help="循环运行")
    p_live.add_argument("--interval", type=int, default=300, help="循环模式下间隔秒数")
    p_live.add_argument("--run-id", default=None, help="可选，指定本次 live 的 run_id（默认自动生成）")
    p_live.set_defaults(func=cmd_live)







    p_cards = sub.add_parser("cards-test", help="发送示例 Lark 卡片")



    p_cards.add_argument("--symbol", default="BTCUSDT")



    p_cards.add_argument("--config", type=Path, default=None)



    p_cards.add_argument("--webhook", default=None)



    p_cards.add_argument("--correlated", action="store_true", help="模拟高相关风险提示")



    p_cards.set_defaults(func=cmd_cards_test)







    p_deepseek = sub.add_parser("deepseek-test", help="测试 DeepSeek 决策/复评接口")



    p_deepseek.add_argument("--symbol", default="BTCUSDT")



    p_deepseek.add_argument("--config", type=Path, default=None)



    p_deepseek.add_argument("--review", action="store_true", default=False, help="同时测试复评接口")



    p_deepseek.set_defaults(func=cmd_deepseek_test)



    p_health = sub.add_parser("healthcheck", help="全量自检：同时校验 Lark Webhook 和 DeepSeek API")

    p_health.add_argument("--symbol", default="BTCUSDT")

    p_health.add_argument("--config", type=Path, default=None)

    p_health.add_argument("--webhook", default=None, help="可选：临时覆盖配置中的 Lark Webhook")

    p_health.set_defaults(func=cmd_healthcheck)







    p_close = sub.add_parser("close-all", help="一键平仓并推送手动平仓提示")
    p_close.add_argument("--symbols", help="逗号分隔；默认读取配置里的 symbols")
    p_close.add_argument("--config", type=Path, default=None)
    p_close.set_defaults(func=cmd_close_all)

    return parser











def main(argv: Optional[List[str]] = None) -> None:



    parser = build_parser()



    args = parser.parse_args(argv)



    args.func(args)











if __name__ == "__main__":



    main()





