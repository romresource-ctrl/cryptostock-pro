"""v10.7.14 — label penutup posisi dari luar bot (bukan Break-Even palsu)."""
import sys
sys.path.insert(0, "/app/backend")
from asi_bot import binance_rest as br  # noqa: E402


def test_classify_manual_app_and_liquidation():
    assert br.classify_close_origin({"client_id": "android_abc"}) == "Manual on Binance app"
    assert br.classify_close_origin({"client_id": "web_x1"}) == "Manual on Binance app"
    assert br.classify_close_origin({"client_id": "autoclose-123"}) == "Liquidation"
    assert br.classify_close_origin({"client_id": "adl_autoclose"}) == "ADL"


def test_bot_orders_not_relabeled():
    assert br.classify_close_origin({"client_id": "x-Cb7ytekJ123"}) is None
    assert br.classify_close_origin({"client_id": ""}) is None
    assert br.classify_close_origin(None) is None


def test_stale_exit_label_kept_over_break_even():
    import inspect
    from asi_bot import engine
    src = inspect.getsource(engine)
    i = src.index('if reason is None and trade.get("stale_exit_at"):')
    assert i < src.index('reason = "BREAK_EVEN"')
    assert "await close_position(\n                        doc, symbol, trade.get(\"side\") or \"BUY\", abs(amt))\n                    _native_partial_upd[\"stale_exit_at\"]" not in src
