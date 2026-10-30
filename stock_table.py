#!/usr/bin/env python3
"""Daily Gaming Digest - Markets table.

Pulls daily closes from Yahoo Finance's chart API and computes
Day / MTD / YTD % changes from completed sessions only.
Stdlib only. Prints a Markdown table, then a JSON line prefixed "JSON:".
With --write, also saves markets.md and markets.json next to the script
(used by the GitHub Actions workflow).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

TICKERS = [
    ("S&P 500", "^GSPC"),
    ("Dow Jones", "^DJI"),
    ("Roblox", "RBLX"),
    ("Sony Group (ADR)", "SONY"),
    ("Unity", "U"),
    ("Take-Two", "TTWO"),
    ("Nintendo (ADR)", "NTDOY"),
    ("Playtika", "PLTK"),
    ("NetEase (ADR)", "NTES"),
    ("Tencent (ADR)", "TCEHY"),
    ("Sea Ltd", "SE"),
    ("CD Projekt", "CDR.WA"),
    ("Capcom", "9697.T"),
    ("Hasbro", "HAS"),
    ("Mattel", "MAT"),
]
HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
UA = {"User-Agent": "Mozilla/5.0 (DailyGamingDigest)"}


def fetch(symbol, start, end):
    sym = urllib.parse.quote(symbol, safe="")
    last_err = None
    for host in HOSTS:
        url = (f"https://{host}/v8/finance/chart/{sym}"
               f"?period1={start}&period2={end}&interval=1d&includePrePost=false")
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.load(r)
            res = data["chart"]["result"][0]
            return res
        except Exception as e:  # try next host
            last_err = e
    raise RuntimeError(f"{symbol}: {last_err}")


def bars(res, now_ts):
    """Completed daily closes as [(local_date, close)], oldest first."""
    meta = res["meta"]
    off = meta.get("gmtoffset", 0)
    ts = res.get("timestamp") or []
    closes = res["indicators"]["quote"][0].get("close") or []
    out = [(datetime.fromtimestamp(t + off, timezone.utc).date(), c)
           for t, c in zip(ts, closes) if c is not None]
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    session_date = (datetime.fromtimestamp(reg["start"] + off, timezone.utc).date()
                    if reg.get("start") else None)
    in_session = session_date is not None and now_ts < reg.get("end", 0)
    # Yahoo sometimes leaves the newest daily bar's close empty for hours after
    # the session ends (seen on Tokyo listings). Fill it from the official
    # regularMarketPrice once that session is over.
    rm_t, rm_p = meta.get("regularMarketTime"), meta.get("regularMarketPrice")
    if rm_t and rm_p:
        rm_date = datetime.fromtimestamp(rm_t + off, timezone.utc).date()
        if not (in_session and rm_date == session_date):
            out = [b for b in out if b[0] != rm_date] + [(rm_date, rm_p)]
            out.sort(key=lambda b: b[0])
    # Drop today's bar if that market's regular session hasn't closed yet.
    if out and in_session and out[-1][0] == session_date:
        out.pop()
    return out, meta.get("currency", "")


def last_before(series, day):
    prior = [c for d, c in series if d < day]
    return prior[-1] if prior else None


def pct(a, b):
    return None if a is None or b in (None, 0) else (a / b - 1) * 100


def fmt_pct(x):
    return "n/a" if x is None else f"{x:+.1f}%"


def fmt_px(x, cur, is_index):
    if x is None:
        return "n/a"
    if is_index:
        return f"{x:,.2f}"
    if cur == "JPY":
        return f"¥{x:,.0f}"
    sym = {"USD": "$", "PLN": "zł "}.get(cur, cur + " ")
    return f"{sym}{x:,.2f}"


def main():
    now = int(time.time())
    today = datetime.now(timezone.utc).date()
    start = int(datetime(today.year - 1, 12, 1, tzinfo=timezone.utc).timestamp())
    rows, out = [], []
    for name, sym in TICKERS:
        rec = {"name": name, "ticker": sym}
        try:
            series, cur = bars(fetch(sym, start, now + 86400), now)
            if len(series) < 2:
                raise RuntimeError("not enough history")
            last_d, last = series[-1]
            prev = series[-2][1]
            mtd_base = last_before(series, last_d.replace(day=1))
            ytd_base = last_before(series, last_d.replace(month=1, day=1))
            rec.update(close_date=str(last_d), currency=cur, close=last,
                       day=pct(last, prev), mtd=pct(last, mtd_base), ytd=pct(last, ytd_base))
            stale = (today - last_d).days > 4
            rows.append(f"| {name} | {sym} | {fmt_px(last, cur, sym.startswith('^'))} "
                        f"| {fmt_pct(rec['day'])} | {fmt_pct(rec['mtd'])} | {fmt_pct(rec['ytd'])} "
                        f"| {last_d:%b %d}{' ⚠️ stale' if stale else ''} |")
        except Exception as e:
            rec["error"] = str(e)[:200]
            rows.append(f"| {name} | {sym} | n/a | n/a | n/a | n/a | fetch failed |")
        out.append(rec)
    table = "\n".join(["| Name | Ticker | Last close | Day | MTD | YTD | As of |",
                       "|---|---|---|---|---|---|---|"] + rows)
    print(table)
    print("JSON:" + json.dumps(out, default=str))
    if "--write" in sys.argv:
        here = os.path.dirname(os.path.abspath(__file__))
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        with open(os.path.join(here, "markets.md"), "w", encoding="utf-8") as f:
            f.write(f"<!-- generated {stamp} -->\n{table}\n")
        with open(os.path.join(here, "markets.json"), "w", encoding="utf-8") as f:
            json.dump({"generated_at": stamp, "rows": out}, f, default=str, indent=1)


if __name__ == "__main__":
    main()
