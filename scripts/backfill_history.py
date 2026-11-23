#!/usr/bin/env python3
"""用腾讯日 K（前复权）回填近 22 个交易日的题材历史快照（写入 site/data/_daily/）
保留已有真实收盘快照，只补齐缺失的历史交易日，并重新生成 history.json。
"""
import concurrent.futures
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data")
DAILY = os.path.join(DATA, "_daily")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def sym_of(code):
    c = str(code or "").strip()
    if c.startswith(("6", "5", "900")):
        return "sh" + c
    if c.startswith(("8", "4", "92")):
        return "bj" + c
    return "sz" + c


def fetch_stock_pcts(code, days=26):
    sym = sym_of(code)
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{days},qfq"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
        d = json.loads(raw)
        node = (d.get("data") or {}).get(sym) or {}
        arr = node.get("qfqday") or node.get("day") or []
        out = {}
        prev_close = None
        for row in arr:
            dt = row[0]
            close = float(row[2])
            if prev_close and prev_close > 0:
                out[dt] = round((close - prev_close) / prev_close * 100.0, 2)
            prev_close = close
        return code, out
    except Exception:
        return code, {}


def main():
    os.makedirs(DAILY, exist_ok=True)
    with open(os.path.join(DATA, "sectors.json"), encoding="utf-8") as f:
        sec_doc = json.load(f)
    with open(os.path.join(DATA, "stocks.json"), encoding="utf-8") as f:
        stk_doc = json.load(f)

    sectors = sec_doc.get("data") or []
    stocks_map = stk_doc.get("data") or {}
    trade_date = sec_doc.get("data_date") or ""

    # 收集每个题材前 6 只成分股去重拉取日 K
    sec_reps = {}
    unique_codes = set()
    for s in sectors:
        code = s["code"]
        reps = [x["code"] for x in (stocks_map.get(code) or [])[:6] if x.get("code")]
        sec_reps[code] = reps
        unique_codes.update(reps)

    print(f"题材 {len(sectors)} 个，需拉取代表个股 {len(unique_codes)} 只的近 25 日 K 线...")
    pct_by_stock = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=14) as ex:
        for i, (code, mp) in enumerate(ex.map(fetch_stock_pcts, unique_codes), 1):
            if mp:
                pct_by_stock[code] = mp
            if i % 100 == 0 or i == len(unique_codes):
                print(f"  进度 {i}/{len(unique_codes)} (成功 {len(pct_by_stock)})")

    # 用上证指数成分/常见日期统计出真实交易日列表（取出现频率最高的前 22 个交易日）
    date_counts = {}
    for mp in pct_by_stock.values():
        for dt in mp:
            date_counts[dt] = date_counts.get(dt, 0) + 1
    valid_dates = sorted(
        [dt for dt, cnt in date_counts.items() if cnt >= max(30, len(pct_by_stock) // 3)]
    )[-22:]
    print(f"识别到有效交易日 {len(valid_dates)} 天: {valid_dates[0]} ~ {valid_dates[-1]}")

    written = 0
    for dt in valid_dates:
        p = os.path.join(DAILY, dt + ".json")
        if os.path.isfile(p):
            continue
        rows = {}
        for s in sectors:
            code = s["code"]
            vals = [pct_by_stock[c][dt] for c in sec_reps.get(code, [])
                    if c in pct_by_stock and dt in pct_by_stock[c]]
            pct = round(sum(vals) / len(vals), 2) if vals else None
            rows[code] = {
                "name": s["name"],
                "pct": pct,
                "count": s.get("count"),
                "lead_name": None,
                "lead_pct": None,
                "amount": None,
            }
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"date": dt, "backfilled": True, "rows": rows}, f, ensure_ascii=False)
        written += 1

    print(f"新补齐历史快照: {written} 天")

    # 重新汇总近 30 日 history.json
    fs = sorted([x[:-5] for x in os.listdir(DAILY) if x.endswith(".json")])[-30:]
    hist_rows = {}
    for d in fs:
        with open(os.path.join(DAILY, d + ".json"), encoding="utf-8") as f:
            dd = json.load(f)
        for code, v in (dd.get("rows") or {}).items():
            hist_rows.setdefault(code, {"name": v.get("name"), "cells": {}})
            hist_rows[code]["cells"][d] = {
                "pct_chg": v.get("pct"),
                "lead_name": v.get("lead_name"),
                "lead_pct": v.get("lead_pct"),
            }
    latest_d = trade_date or (fs[-1] if fs else "")
    out_rows = [{"code": k, "name": v["name"], "cells": v["cells"]} for k, v in hist_rows.items()]
    out_rows.sort(
        key=lambda r: (
            r["cells"].get(latest_d, {}).get("pct_chg") is not None,
            r["cells"].get(latest_d, {}).get("pct_chg", -99),
        ),
        reverse=True,
    )
    with open(os.path.join(DATA, "history.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": fs, "rows": out_rows}, f, ensure_ascii=False)

    print(f"已重建 history.json: {len(fs)} 个交易日 × {len(out_rows)} 个题材")
    return 0


if __name__ == "__main__":
    sys.exit(main())
