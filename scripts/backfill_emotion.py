#!/usr/bin/env python3
"""回填近 24 个交易日的 A 股短线情绪周期历史（写入 site/data/emotion_history.json）"""
import concurrent.futures
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import DATA, _em_pool


def fetch_one(dt):
    ymd = dt.replace("-", "")
    zt, zb, dt_p = [], [], []
    try:
        zt = _em_pool("getTopicZTPool", "lbc:desc", ymd)
    except Exception:
        pass
    try:
        zb = _em_pool("getTopicZBPool", "fbt:asc", ymd)
    except Exception:
        pass
    try:
        dt_p = _em_pool("getTopicDTPool", "fund:asc", ymd)
    except Exception:
        pass
    if not zt and not dt_p:
        return None
    zt_cnt, zb_cnt, dt_cnt = len(zt), len(zb), len(dt_p)
    zb_rate = round(zb_cnt / (zt_cnt + zb_cnt) * 100, 1) if (zt_cnt + zb_cnt) else 0.0
    max_board = max((int(x.get("lbc") or 1) for x in zt), default=0)
    lianban_cnt = sum(1 for x in zt if int(x.get("lbc") or 1) >= 2)
    total_seal = sum(float(x.get("fund") or 0) for x in zt)
    top = zt[0] if zt else None
    return {
        "date": dt,
        "zt_count": zt_cnt,
        "dt_count": dt_cnt,
        "zb_count": zb_cnt,
        "zb_rate": zb_rate,
        "max_board": max_board,
        "lianban_count": lianban_cnt,
        "total_seal": total_seal,
        "top_stock": (top.get("n") or "") if top else "",
        "top_code": str(top.get("c") or "") if top else "",
        "top_hybk": (top.get("hybk") or "") if top else "",
    }


def main():
    with open(os.path.join(DATA, "history.json"), encoding="utf-8") as f:
        dates = sorted(json.load(f).get("dates") or [])[-25:]
    print(f"回填 {len(dates)} 个交易日情绪周期 ({dates[0]} ~ {dates[-1]})...")
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for r in ex.map(fetch_one, dates):
            if r:
                out.append(r)
    out.sort(key=lambda x: x["date"])
    p = os.path.join(DATA, "emotion_history.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rows": out[-30:], "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)
    print(f"完成: 写入 {len(out)} 天情绪周期到 emotion_history.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
