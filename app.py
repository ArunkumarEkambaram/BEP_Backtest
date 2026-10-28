"""
app.py — NiceGUI entry point for the BEP Backtest tool.

Layout:
  - header row: token input, date picker, Load Expiry, Run Backtest, Refresh BEP cache
  - summary cards
  - board replay grid: one row per leg, columns = each 5-min candle of the day
  - trade log table + CSV/XLSX downloads

No live polling, no scanner, no Telegram, no BEP upload.
"""
from nicegui import ui, run

import config
import upstox_client
import market_utils
import bep
import backtest_engine
import stats
import export_utils


client = upstox_client.UpstoxClient(config.UPSTOX_ACCESS_TOKEN)
token_connected = False
last_run = None


def _cell_char(state: str) -> str:
    return {
        "IDLE": "\u00b7",
        "ARM_NEXT_OPEN": "\u2192",
        "PARKED": "P",
        "IN_TRADE": "T",
        "DEAD": "\u2715",
        "DONE": "D",
    }.get(state, "")


def _build_board_columns(candle_times: list) -> list:
    cols = [{"name": "leg", "label": "Leg", "field": "leg",
             "align": "left", "headerClasses": "bt-leg-header"}]
    for t in candle_times:
        cols.append({"name": f"c_{t}", "label": t, "field": f"c_{t}", "align": "center"})
    return cols


def _build_board_rows(board: dict, legs: list) -> tuple:
    candle_times = sorted(board.keys())
    rows = []
    for leg_key in legs:
        row = {"id": leg_key, "leg": leg_key}
        for t in candle_times:
            cells = board.get(t) or []
            match = next((c for c in cells if c["key"] == leg_key), None)
            row[f"c_{t}"] = {
                "state": match["state"] if match else "IDLE",
                "label": _cell_char(match["state"]) if match else _cell_char("IDLE"),
                "tooltip": (f"{leg_key} @ {t}  BEP {match['bep']:.2f}  "
                            f"close {match['close']:.2f}  {match['label']}"
                            if match else f"{leg_key} @ {t}  no data"),
            }
        rows.append(row)
    return rows, candle_times


@ui.page("/")
def main_page():
    global token_connected, last_run

    ui.add_head_html("""
    <style>
      .bt-cell { text-align:center; font-weight:600; }
      .bt-idle     { background:#f4f4f4; color:#777; }
      .bt-armed    { background:#fff4cc; color:#7a5c00; }
      .bt-parked   { background:#e0ecff; color:#1e3a8a; }
      .bt-intrade  { background:#c8e6c9; color:#1b5e20; }
      .bt-dead     { background:#d0d0d0; color:#444; }
      .bt-done     { background:#ececec; color:#555; }
      .bt-leg-header { position:sticky; left:0; background:#fff; z-index:2; }
      .bt-board { overflow-x:auto; }
    </style>
    """)

    ui.label("BEP Backtest").classes("text-2xl font-bold")

    with ui.row().classes("items-center gap-3"):
        token_input = ui.input("Upstox Access Token",
                               value=config.UPSTOX_ACCESS_TOKEN,
                               password=True,
                               password_toggle_button=True).classes("w-96")
        conn_label = ui.label(
            "Status: not connected" if not config.UPSTOX_ACCESS_TOKEN else "Status: unverified"
        )

        def save_token():
            global token_connected
            tok = token_input.value.strip()
            if not tok:
                conn_label.set_text("Status: token is empty")
                token_connected = False
                return
            client.access_token = tok
            client.headers["Authorization"] = f"Bearer {tok}"
            ok, info = upstox_client.test_connection(tok)
            if ok:
                conn_label.set_text(f"Status: connected ({info})")
                token_connected = True
            else:
                conn_label.set_text(f"Status: connection failed \u2014 {info}")
                token_connected = False

        ui.button("Save & Test", on_click=save_token)

    ui.separator()

    with ui.row().classes("items-center gap-3"):
        date_select = ui.select([], label="Date").classes("w-48")
        expiry_label = ui.label("Expiry: not loaded").classes("text-gray-600")
        run_button = ui.button("Run Backtest")
        refresh_button = ui.button("Refresh BEP cache").props("outline")
        status_label = ui.label("").classes("text-sm text-gray-600")

    def load_dates():
        if not token_connected:
            status_label.set_text("Connect the Upstox token first.")
            return
        expiry_str, dates = market_utils.current_weekly_expiry_dates(client)
        if not expiry_str:
            expiry_label.set_text("Expiry: could not fetch")
            return
        expiry_label.set_text(f"Expiry: {expiry_str}")
        date_select.set_options(dates)
        if dates:
            date_select.set_value(dates[-1])
        status_label.set_text(f"{len(dates)} date(s) available in the current cycle.")

    ui.button("Load Expiry Dates", on_click=load_dates)

    cards = {}
    with ui.row().classes("gap-3"):
        for key, label in (
            ("trades", "Trades"), ("win_rate", "Win rate"),
            ("total_points", "Total points"), ("avg_points", "Avg points"),
            ("max_dd", "Max DD"), ("streak_w", "Longest win"),
            ("streak_l", "Longest loss"),
        ):
            with ui.card().classes("w-36 rounded-xl shadow-sm p-3"):
                ui.label(label).classes("text-xs text-gray-500")
                cards[key] = ui.label("--").classes("text-xl font-bold")

    def update_cards(st):
        if not st:
            for w in cards.values():
                w.set_text("--")
            return
        cards["trades"].set_text(str(st["trades"]))
        cards["win_rate"].set_text(f"{st['win_rate']}%")
        cards["total_points"].set_text(f"{st['total_points']:.2f}")
        cards["avg_points"].set_text(f"{st['avg_points']:.2f}")
        cards["max_dd"].set_text(f"{st['max_drawdown']:.2f}")
        cards["streak_w"].set_text(str(st["longest_win_streak"]))
        cards["streak_l"].set_text(str(st["longest_loss_streak"]))

    ui.separator()

    ui.label("Board replay").classes("text-md font-bold")
    ui.label("One row per leg, one column per 5-min candle. "
             "\u00b7 waiting  \u2192 armed for next open  P parked  T in trade  "
             "\u2715 ignored  D done").classes("text-xs text-gray-500")
    board_container = ui.column().classes("w-full bt-board")

    ui.separator()
    ui.label("Trade log").classes("text-md font-bold")
    trade_table = ui.table(columns=[
        {"name": k, "label": lbl, "field": k} for k, lbl in export_utils.TRADE_COLUMNS
    ], rows=[], row_key="id").classes("w-full").props("dense")

    def download_csv():
        if last_run is None:
            return
        rows = export_utils.flatten_trades(last_run["trades"])
        ui.download(export_utils.build_csv(rows), "bep_backtest_trades.csv")

    def download_xlsx():
        if last_run is None:
            return
        rows = export_utils.flatten_trades(last_run["trades"])
        ui.download(export_utils.build_xlsx(rows), "bep_backtest_trades.xlsx")

    with ui.row().classes("gap-3"):
        ui.button("Download CSV", on_click=download_csv)
        ui.button("Download XLSX", on_click=download_xlsx)

        # -------------------------------------------------- actions
    def render_board(run_result):
        board_container.clear()
        board = run_result["board"]
        trades = run_result["trades"]

        # Legs that "mattered" during the day: qualified at least once
        # (ARM_NEXT_OPEN, PARKED, IN_TRADE, DONE, or DEAD-after-qualify).
        # Legs that only ever sat in IDLE (never qualified) are hidden.
        qualifying_states = {"ARM_NEXT_OPEN", "PARKED", "IN_TRADE", "DONE"}
        qualifying_legs = set()
        for cells in board.values():
            for c in cells:
                if c["state"] in qualifying_states:
                    qualifying_legs.add(c["key"])
                # A leg that qualified and then went DEAD also matters
                elif c["state"] == "DEAD" and c.get("trades_taken", 0) >= 0 \
                        and c.get("label") == "ignored":
                    # Only count DEAD as qualifying if it also appeared as a
                    # non-IDLE, non-DEAD state in some earlier candle.
                    pass
        # Simpler, exact rule: a leg qualified if any candle for it shows a
        # state other than IDLE or DEAD, OR if it produced a trade.
        qualifying_legs = set()
        for cells in board.values():
            for c in cells:
                if c["state"] not in ("IDLE", "DEAD"):
                    qualifying_legs.add(c["key"])
        for t in trades:
            qualifying_legs.add(f"{t.strike}{t.leg}")

        legs = sorted(qualifying_legs)
        if not legs:
            with board_container:
                ui.label("No leg qualified on this date.").classes("text-gray-500")
            return
        rows, times = _build_board_rows(board, legs)
        if not times:
            with board_container:
                ui.label("No board data (no candles processed).").classes("text-gray-500")
            return

        # Attach the trade number to in-trade cells in the tooltip.
        trade_lookup = {}   # (leg_key, hhmm) -> trade_no
        for t in trades:
            trade_lookup[(f"{t.strike}{t.leg}", t.signal_time)] = t.trade_no
            if t.entry is not None:
                trade_lookup.setdefault((f"{t.strike}{t.leg}", t.entry.time), t.trade_no)

        for row in rows:
            for t in times:
                col = f"c_{t}"
                cell = row.get(col)
                if not cell:
                    continue
                if cell["state"] == "IN_TRADE":
                    tn = trade_lookup.get((row["id"], t))
                    if tn is not None:
                        cell["tooltip"] = cell["tooltip"] + f"  trade#{tn}"

        cols = _build_board_columns(times)
        with board_container:
            tbl = ui.table(columns=cols, rows=rows, row_key="id") \
                .classes("w-full").props("dense flat bordered")
            for c in cols[1:]:
                tbl.add_slot(
                    f"body-cell-{c['name']}",
                    '<q-td :props="props" '
                    ':class="\'bt-cell bt-\' + (props.value.state === \'ARM_NEXT_OPEN\' ? \'armed\' '
                    ': props.value.state === \'IN_TRADE\' ? \'intrade\' '
                    ': props.value.state === \'PARKED\' ? \'parked\' '
                    ': props.value.state === \'DEAD\' ? \'dead\' '
                    ': props.value.state === \'DONE\' ? \'done\' : \'idle\')">'
                    '<span :title="props.value.tooltip">{{ props.value.label }}</span>'
                    '</q-td>'
                )
                
    def render_trades(trades):
        trade_table.rows = [
            {**r, "id": i}
            for i, r in enumerate(export_utils.flatten_trades(trades))
        ]
        trade_table.update()

    def run_backtest_click():
        global last_run
        if not token_connected:
            status_label.set_text("Connect the Upstox token first.")
            return
        date_str = date_select.value
        expiry_text = expiry_label.text.replace("Expiry: ", "").strip()
        if not date_str or not expiry_text or expiry_text == "not loaded":
            status_label.set_text("Load expiry dates first.")
            return
        status_label.set_text("Running backtest...")

        async def do_run():
            global last_run
            try:
                result = await run.io_bound(
                    backtest_engine.run_backtest,
                    client, date_str, expiry_text, lambda m: None,
                )
            except Exception as ex:
                status_label.set_text(f"Backtest failed: {ex}")
                return
            last_run = result
            if result["errors"]:
                status_label.set_text(
                    f"Done with {len(result['errors'])} error(s): {result['errors'][0]}")
            else:
                status_label.set_text(
                    f"Done: {len(result['trades'])} trade(s) on {result['date']}.")
            update_cards(stats.summarize(result["trades"]))
            render_board(result)
            render_trades(result["trades"])

        ui.timer(0.05, do_run, once=True)

    run_button.on_click(run_backtest_click)

    def refresh_cache():
        bep.clear_cache()
        status_label.set_text("BEP cache cleared; the next run will recalculate.")

    refresh_button.on_click(refresh_cache)


ui.run(title="BEP Backtest", port=8082, reload=False)