"""
export_utils.py — CSV/XLSX for the backtest trade log.
"""
import csv
import io

from openpyxl import Workbook


TRADE_COLUMNS = [
    ("strike",     "Strike"),
    ("leg",        "Leg"),
    ("branch",     "Branch"),
    ("bep",        "BEP"),
    ("trade_no",   "Trade #"),
    ("signal",     "Signal"),
    ("entry_time", "Entry Time"),
    ("entry_px",   "Entry Price"),
    ("exit_time",  "Exit Time"),
    ("exit_px",    "Exit Price"),
    ("exit_rsn",   "Exit Reason"),
    ("points",     "Points"),
]


def flatten_trades(trades: list) -> list:
    out = []
    for t in trades:
        out.append({
            "strike": t.strike,
            "leg": t.leg,
            "branch": t.branch or "",
            "bep": round(t.bep, 2) if t.bep is not None else "",
            "trade_no": t.trade_no,
            "signal": t.signal_time or "",
            "entry_time": t.entry.time if t.entry else "",
            "entry_px": round(t.entry.price, 2) if t.entry else "",
            "exit_time":  t.exit.time  if t.exit  else "",
            "exit_px":    round(t.exit.price, 2)  if t.exit  else "",
            "exit_rsn":  t.exit.reason if t.exit  else "",
            "points":    t.points if t.points is not None else "",
        })
    return out


def build_csv(rows: list, columns: list = None) -> bytes:
    columns = columns or TRADE_COLUMNS
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in columns])
    for r in rows:
        w.writerow([r.get(k, "") for k, _ in columns])
    return buf.getvalue().encode("utf-8")


def build_xlsx(rows: list, columns: list = None) -> bytes:
    columns = columns or TRADE_COLUMNS
    wb = Workbook()
    ws = wb.active
    ws.title = "Trades"
    ws.append([label for _, label in columns])
    for r in rows:
        ws.append([r.get(k, "") for k, _ in columns])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()