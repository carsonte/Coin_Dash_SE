from __future__ import annotations







import argparse



import os



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



from .ai.usage_tracker import BudgetExceeded, BudgetInfo



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











def _build_db_services(cfg):



    return build_database_services(cfg.database)











def _apply_notification_config(cfg) -> None:

    configure_lark_signing(getattr(cfg.notifications, "lark_signing_secret", None))





def cmd_backtest(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    services = _build_db_services(cfg)



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

    services = _build_db_services(cfg)



    target = args.symbols.split(",") if args.symbols else cfg.symbols



    orchestrator = LiveOrchestrator(cfg, db_services=services)







    # 涓枃璇存槑锟?

    # 褰撳惎锟?--align 鏃讹紝live 寰幆浼氣€滃榻愬埌鍛ㄦ湡杈圭晫鈥濓紙渚嬪 15/30/60 鍒嗛挓鏁寸偣锛夛紝



    # 骞跺湪杈圭晫鍚庣殑瀵归綈鍋忕Щ绉掞紙--align-skew锛夊悗鍐嶆墽琛屼竴娆★紝浠ョ‘淇滽绾垮凡鏀剁洏钀界洏锟?

    # 鏈惎鐢ㄦ椂锛屼粛鎸夊浐锟?--interval 绉掓暟鐫＄湢锟?





    def _label_to_minutes(label: str) -> int:
        """Parse timeframe label like '30m'/'1h'/'4h'/'1d' into minutes."""
        s = (label or "").strip().lower()



        if s.endswith("m"):



            return int(s[:-1])



        if s.endswith("h"):



            return int(s[:-1]) * 60



        if s.endswith("d"):



            return int(s[:-1]) * 1440



        raise ValueError(f"鏃犳硶瑙ｆ瀽鍛ㄦ湡鏍囩: {label}")







    def _sleep_align(period_minutes: int, skew_seconds: int) -> None:
        """Align to the next period boundary then sleep with an extra skew."""
        now = datetime.now(timezone.utc)



        # 锟?UTC 璁＄畻涓嬩竴鍛ㄦ湡杈圭晫鍒嗛挓



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



                    # 涓枃锟? 鍒嗛挓蹇冭烦锛涘湪鈥滃父瑙勫璇勯棿闅旓紙signals.review_interval_minutes锛夆€濈殑鏁寸偣杈圭晫鎵ц瀹屾暣鍛ㄦ湡



                    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)



                    period = max(5, int(cfg.signals.review_interval_minutes))  # 榛樿 60 鍒嗛挓鍙敱閰嶇疆鎺у埗



                    if (now.minute % period) == 0:



                        orchestrator.run_cycle(target)  # 甯歌澶嶈瘎 + 鏂颁俊锟?

                    else:



                        orchestrator.run_heartbeat(target)  # 5m 蹇冭烦锛氬競锟?TP/SL/涓存椂澶嶈瘎



                    # 瀵归綈鍒颁笅涓€锟?5 鍒嗛挓杈圭晫锟?3s 缂撳啿



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



        raise SystemExit("璇峰厛璁剧疆 Lark Webhook")







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

    def budget_log(info: BudgetInfo) -> None:
        level = 'warn' if info.level == 'warn' else 'exceed'
        print(f"[yellow]DeepSeek budget {level}: {info.total_tokens}/{info.budget} tokens (date {info.date})[/yellow]")

    client = DeepSeekClient(cfg.deepseek, budget_callback=budget_log)
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
    }

    print('[cyan]调用 DeepSeek 决策接口...[/cyan]')
    try:
        decision = client.decide_trade(args.symbol, decision_payload)
    except BudgetExceeded as exc:
        info = exc.info
        print(f"[red]决策触发预算超限：{info.total_tokens}/{info.budget}（{info.date}）[/red]")
        return
    except Exception as exc:
        print(f"[red]DeepSeek 调用失败: {exc}")
        return

    print(
        f"决策成功: action={decision.decision}, entry={decision.entry_price:.2f}, stop={decision.stop_loss:.2f}, "
        f"take={decision.take_profit:.2f}, \nrr={decision.risk_reward:.2f}, confidence={decision.confidence:.1f}"
    )

    if args.review:
        review_payload = {
            'context_note': '测试复评',
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
        }
        print('[cyan]调用 DeepSeek 复评接口...[/cyan]')
        try:
            review = client.review_position(args.symbol, 'test-position', review_payload)
        except BudgetExceeded as exc:
            info = exc.info
            print(f"[red]复评触发预算超限：{info.total_tokens}/{info.budget}（{info.date}）[/red]")
            return
        print(f"[green]复评成功[/green]: action={review.action}, reason={review.reason}")

    print('[bold green]DeepSeek API 测试完成[/bold green]')

def cmd_healthcheck(args: argparse.Namespace) -> None:

    cfg = load_config(args.config)

    _apply_notification_config(cfg)

    webhook = args.webhook or os.getenv("LARK_WEBHOOK") or cfg.notifications.lark_webhook



    if not webhook:



        raise SystemExit("请配置 Lark Webhook 或使用 --webhook 传入")







    checks: List[Dict[str, str | bool]] = []







    # Lark 杩為€氭€ф祴锟?

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







    # DeepSeek 杩為€氾拷?

    deepseek_status: bool | None = None



    deepseek_detail = ""



    if not cfg.deepseek.enabled:



        deepseek_status = None



        deepseek_detail = "config.deepseek.enabled = false"



    else:



        client = DeepSeekClient(cfg.deepseek)



        if not client.enabled():



            deepseek_status = False



            deepseek_detail = "鏈厤锟?DEEPSEEK_API_KEY 鎴栫幆澧冨彉閲忎笉鍙敤"



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



            except BudgetExceeded as exc:



                info = exc.info



                deepseek_status = False



                deepseek_detail = f"预算超限：{info.total_tokens}/{info.budget}（{info.date}）"



            except Exception as exc:  # noqa: BLE001



                deepseek_status = False



                deepseek_detail = f"调用失败：{exc}"



    checks.append({"name": "DeepSeek API", "status": deepseek_status, "detail": deepseek_detail})







    # 杈撳嚭鍒扮粓锟?

    for item in checks:



        status = item.get("status")



        icon = "?" if status is True else ("?" if status is False else "??")



        print(f"{icon} {item['name']}: {item.get('detail','')}")







    # 姹囨€诲崱鐗囷紝浠呭綋 webhook 娴嬭瘯鎴愬姛鎵嶆帹锟?

    if lark_ok:



        try:



            send_healthcheck_card(webhook, "閮ㄧ讲鑷缁撴灉", checks)



            print("[green]宸插彂閫侀儴缃茶嚜妫€鍗＄墖锟?Lark銆俒/green]")

        except Exception as exc:  # noqa: BLE001



            print(f"[red]发送自检结果失败：{exc}[/red]")



    else:



        print("[yellow]Lark Webhook 娴嬭瘯鏈€氳繃锛岃烦杩囩粨鏋滃崱鐗囨帹閫併€俒/yellow]")











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







    p_backtest = sub.add_parser("backtest", help="杩愯鏈湴 CSV 鍥炴祴")



    p_backtest.add_argument("--symbol", default="BTCUSDT")



    p_backtest.add_argument("--timeframe", default="1h")



    p_backtest.add_argument("--csv", type=Path, required=True)



    p_backtest.add_argument("--config", type=Path, default=None)



    p_backtest.add_argument("--deepseek", action="store_true", help="鍚敤 DeepSeek 鍐崇瓥")



    p_backtest.set_defaults(func=cmd_backtest)







    p_live = sub.add_parser("live", help="执行实时流程一次或循环")
    p_live.add_argument("--symbols", help="逗号分隔交易对", default=None)
    p_live.add_argument("--config", type=Path, default=None)
    p_live.add_argument("--loop", action="store_true", help="循环运行")
    p_live.add_argument("--interval", type=int, default=300, help="循环模式下间隔秒数")
    p_live.set_defaults(func=cmd_live)







    p_cards = sub.add_parser("cards-test", help="发送示例 Lark 卡片")



    p_cards.add_argument("--symbol", default="BTCUSDT")



    p_cards.add_argument("--config", type=Path, default=None)



    p_cards.add_argument("--webhook", default=None)



    p_cards.add_argument("--correlated", action="store_true", help="模拟高相关风险提示")



    p_cards.set_defaults(func=cmd_cards_test)







    p_deepseek = sub.add_parser("deepseek-test", help="娴嬭瘯 DeepSeek 鍐崇瓥/澶嶈瘎鎺ュ彛")



    p_deepseek.add_argument("--symbol", default="BTCUSDT")



    p_deepseek.add_argument("--config", type=Path, default=None)



    p_deepseek.add_argument("--review", action="store_true", default=False, help="鍚屾椂娴嬭瘯澶嶈瘎鎺ュ彛")



    p_deepseek.set_defaults(func=cmd_deepseek_test)



    p_health = sub.add_parser("healthcheck", help="閮ㄧ讲鑷锛氬悓鏃堕獙锟?Lark Webhook 锟?DeepSeek API")

    p_health.add_argument("--symbol", default="BTCUSDT")

    p_health.add_argument("--config", type=Path, default=None)

    p_health.add_argument("--webhook", default=None, help="鍙€夛細鏄惧紡瑕嗙洊閰嶇疆涓殑 Lark Webhook")

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





