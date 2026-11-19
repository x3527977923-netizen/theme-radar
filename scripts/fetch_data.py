#!/usr/bin/env python3
"""题材雷达 · 静态站数据生成器（GitHub Actions 每天收盘后运行）

产出（全部写进 site/data/）：
  home.json      首页：最近交易日 + 3~5 个值得看的题材（含涨幅靠前个股、公开消息）
  sectors.json   全部题材当日行情 + 较上一交易日变化
  stocks.json    每个题材涨幅靠前的成分股（前 20 只）
  indices.json   主要指数
  history.json   近 30 个交易日 × 题材 的涨幅矩阵（由 data/_daily/*.json 累积）
  _daily/YYYY-MM-DD.json  当日原始快照（用于累积历史）

数据来源：新浪财经、腾讯财经公开行情接口。仅陈述事实，不预测涨跌。
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data")
DAILY = os.path.join(DATA, "_daily")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HDR_SINA = {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"}

SKIP = {
    "融资融券", "转融券标的", "基金重仓", "QFII重仓", "保险重仓", "社保重仓",
    "券商重仓", "信托重仓", "超大盘", "大盘", "中盘", "小盘", "微盘",
    "含H股", "含B股", "含GDR", "央企50", "证金持股", "汇金持股",
    "预盈预增", "预亏预减", "破净股", "次新股", "股权转让", "参股新股",
    "本月解禁", "股权激励", "机构调研", "昨日涨停", "举牌概念",
}

DESC = {
    "白酒概念": "白酒生产与销售相关的上市公司，代表高端消费品的一类资产。",
    "猪肉": "生猪养殖、屠宰与肉制品加工相关公司，价格周期跟随猪价波动。",
    "鸡肉": "白羽鸡、黄羽鸡养殖与禽肉加工相关公司。",
    "奢侈品": "高端消费与奢侈品牌代理、销售相关的公司。",
    "华为海思": "与华为海思在芯片、模组或供应链上有合作关系的公司。",
    "华为汽车": "与华为在智能汽车方案上有合作关系的公司。",
    "新能源车": "整车、电池、电机电控及充电设施相关公司。",
    "锂电池": "锂矿、正负极材料、电解液、隔膜与电芯制造相关公司。",
    "光伏概念": "硅料、硅片、电池片、组件与逆变器相关公司。",
    "半导体": "芯片设计、制造、封测与设备材料相关公司。",
    "国产芯片": "以国产替代为主线的芯片设计、制造与设备公司。",
    "人工智能": "大模型、算力、算法与应用落地相关公司。",
    "算力概念": "数据中心、服务器、光模块与算力租赁相关公司。",
    "光模块": "光通信器件与高速光模块制造相关公司。",
    "军工": "航空、航天、兵器、船舶与军工电子相关公司。",
    "创新药": "以创新药研发为主线的医药公司。",
    "医疗器械": "医疗设备、耗材与体外诊断相关公司。",
    "房地产": "住宅与商业地产开发、运营相关公司。",
    "煤炭": "动力煤、焦煤开采与销售相关公司。",
    "有色金属": "铜、铝、锌、黄金等金属采选与冶炼相关公司。",
    "黄金概念": "黄金采选、冶炼与销售相关公司。",
    "稀土永磁": "稀土开采、分离与永磁材料相关公司。",
    "风电": "风机整机、叶片、塔筒与海上风电相关公司。",
    "储能": "电化学储能、抽水蓄能与储能系统集成相关公司。",
    "氢能源": "制氢、储运氢、加氢站与燃料电池相关公司。",
    "食品饮料": "食品加工、饮料制造与调味品相关公司。",
    "养殖业": "生猪、禽类与水产养殖相关公司。",
    "游戏概念": "游戏研发、发行与运营相关公司。",
    "传媒": "影视、出版、广告与内容平台相关公司。",
    "数据要素": "数据确权、交易、治理与安全相关公司。",
    "信创": "基础软硬件国产化替代相关公司。",
    "机器人概念": "工业机器人、人形机器人与核心零部件相关公司。",
    "充电桩": "充电设备制造与充电运营相关公司。",
    "特斯拉概念": "特斯拉供应链上的零部件与材料公司。",
    "苹果概念": "苹果供应链上的零部件与组装公司。",
    "消费电子": "手机、可穿戴与消费电子零组件相关公司。",
    "聚氨酯": "聚氨酯原料（MDI、TDI 等）生产与应用相关公司。",
    "仿制药": "以仿制药品生产与销售为主的公司。",
    "股期概念": "与股指期货、期权等衍生品相关的标的集合。",
}


def http(url, headers=None, timeout=20, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or HDR_SINA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def gbk_text(url, headers=None):
    return http(url, headers).decode("gbk", "ignore")


def cache_json(url):
    raw = http(url).decode("utf-8", "ignore")
    return json.loads(raw)


# ---------- 交易日 ----------
def market_trade_date():
    txt = gbk_text("https://qt.gtimg.cn/q=sh000001",
                   {"User-Agent": UA, "Referer": "https://gu.qq.com/"})
    f = txt.split("=", 1)[1].strip().strip('"').split("~")
    ts = f[30] if len(f) > 30 else ""
    if len(ts) >= 8 and ts[:8].isdigit():
        d = ts[:8]
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return datetime.now().strftime("%Y-%m-%d")


# ---------- 题材 ----------
def fetch_sectors():
    """新浪概念板块（172 个）"""
    url = "https://vip.stock.finance.sina.com.cn/q/view/newFLJK.php?param=class"
    txt = gbk_text(url)
    body = txt.split("=", 1)[1].strip().strip(";").strip()
    obj = json.loads(body)
    out = []
    for k, v in obj.items():
        p = v.split(",")
        if len(p) < 13:
            continue
        try:
            pct = round(float(p[4]), 2)
        except Exception:
            pct = None
        out.append({
            "code": p[0], "name": p[1],
            "count": int(p[2]) if p[2].isdigit() else None,
            "amount": float(p[7]) if p[7] else None,
            "pct": pct,
            "lead_code": re.sub(r"^[a-z]{2}", "", p[8]),
            "lead_name": p[12] if len(p) > 12 else None,
            "lead_pct": round(float(p[11]), 2) if len(p) > 11 and p[11] else None,
        })
    out.sort(key=lambda x: (x["pct"] is not None, x["pct"] or -99), reverse=True)
    return out


def sector_stocks(code, num=20):
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"Market_Center.getHQNodeData?page=1&num={num}&sort=changepercent&asc=0&node={code}")
    try:
        raw = http(url).decode("utf-8", "ignore")
        raw = re.sub(r"([{,])(\w+):", r'\1"\2":', raw)
        arr = json.loads(raw)
    except Exception:
        return []
    out = []
    for x in arr:
        nm = x.get("name") or ""
        # 过滤退市股、停牌无价股，避免把噪音当成「涨幅靠前」
        if "退市" in nm:
            continue
        try:
            price = float(x.get("trade"))
        except Exception:
            continue
        if not price or price <= 0:
            continue
        try:
            pct = round(float(x.get("changepercent")), 2)
        except Exception:
            pct = None
        if pct is None:
            continue
        out.append({
            "code": str(x.get("code", "")).replace("sh", "").replace("sz", ""),
            "name": x.get("name"),
            "price": x.get("trade"),
            "pctChg": pct,
            "amount": x.get("amount"),
        })
    return out


def fetch_indices():
    syms = ["sh000001", "sz399001", "sz399006", "sh000688", "hkHSI", "usDJI", "usIXIC"]
    names = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
             "000688": "科创50", "HSI": "恒生指数", "DJI": "道琼斯", "IXIC": "纳斯达克"}
    txt = gbk_text("https://qt.gtimg.cn/q=" + ",".join(syms),
                   {"User-Agent": UA, "Referer": "https://gu.qq.com/"})
    out = []
    for line in txt.split(";"):
        if "=" not in line:
            continue
        f = line.split("=", 1)[1].strip().strip('"').split("~")
        if len(f) < 33:
            continue
        code = f[2]
        out.append({"code": code, "name": names.get(code, f[1]),
                    "value": f[3], "pctChg": f[32]})
    return out


# ---------- 快讯（用于给题材找公开背景） ----------
def fetch_news(limit=100):
    try:
        u = ("https://zhibo.sina.com.cn/api/zhibo/feed"
             f"?page=1&page_size={limit}&zhibo_id=152&tag_id=0&dire=f&dpc=1")
        d = json.loads(http(u, {"User-Agent": UA, "Referer": "https://finance.sina.com.cn/"}))
        items = (((d.get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
        out = []
        for it in items:
            t = re.sub(r"<[^>]+>", "", str(it.get("rich_text") or it.get("text") or "")).strip()
            if t:
                out.append({"title": t[:120], "time": it.get("create_time") or "",
                            "url": (it.get("docurl") or "").strip() or None})
        return out
    except Exception:
        return []


def match_news(name, news):
    key = name.replace("概念", "").replace("板块", "").replace("指数", "").strip()
    if len(key) < 2:
        return None
    for n in news:
        if key in n["title"]:
            return n
    return None


def load_daily(date):
    p = os.path.join(DAILY, date + ".json")
    if os.path.isfile(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def recent_dates(n=30):
    if not os.path.isdir(DAILY):
        return []
    fs = [x[:-5] for x in os.listdir(DAILY) if x.endswith(".json")]
    return sorted(fs, reverse=True)[:n]


def main():
    os.makedirs(DAILY, exist_ok=True)
    trade_date = market_trade_date()
    print("交易日:", trade_date)

    # 幂等：当天收盘数据已抓过就跳过，避免多次 cron 产生重复提交
    force = '--force' in sys.argv
    existing = load_daily(trade_date)
    if (not force) and existing and len((existing.get("rows") or {})) >= 150:
        print("当天数据已存在（%d 个题材），跳过。需要重抓请加 --force" % len(existing.get("rows") or {}))
        # 仍然刷新首页/矩阵（成本很低），保证 generated_at 更新
        if os.path.isfile(os.path.join(DATA, "home.json")):
            return 0

    sectors = fetch_sectors()
    if not sectors:
        print("ERROR: 题材数据为空，放弃本次生成（保留上次数据）")
        return 1
    print("题材数:", len(sectors))

    # 当日快照落盘（幂等）
    with open(os.path.join(DAILY, trade_date + ".json"), "w", encoding="utf-8") as f:
        json.dump({"date": trade_date,
                   "rows": {s["code"]: {"name": s["name"], "pct": s["pct"],
                                        "count": s["count"], "lead_name": s["lead_name"],
                                        "lead_pct": s["lead_pct"], "amount": s["amount"]}
                            for s in sectors}},
                  f, ensure_ascii=False)

    dates = recent_dates(30)
    prev_date = next((d for d in dates if d < trade_date), None)
    prev = {}
    if prev_date:
        pd = load_daily(prev_date)
        if pd:
            prev = {k: v.get("pct") for k, v in (pd.get("rows") or {}).items()}

    # ---- sectors.json ----
    data_rows = []
    for s in sectors:
        d = None
        if prev_date and s["pct"] is not None and prev.get(s["code"]) is not None:
            d = round(s["pct"] - prev[s["code"]], 2)
        data_rows.append({
            "id": s["code"], "code": s["code"], "name": s["name"],
            "name_code": s["code"].upper().replace("GN_", "GN_"),
            "pct": s["pct"], "pct_chg": s["pct"], "pct_src": "sina",
            "delta": d,
            "count": s["count"], "stock_count": s["count"],
            "amount": s["amount"],
            "lead_code": s["lead_code"], "lead_name": s["lead_name"],
            "lead_pct": s["lead_pct"],
            "leader": {"name": s["lead_name"], "pctChg": s["lead_pct"]},
            "hot": 0, "limit_up": None,
        })
    with open(os.path.join(DATA, "sectors.json"), "w", encoding="utf-8") as f:
        json.dump({"data_date": trade_date, "prev_date": prev_date,
                   "data": data_rows}, f, ensure_ascii=False)

    # ---- stocks.json（每个题材前 20 只） ----
    all_stocks = {}
    for i, s in enumerate(sectors, 1):
        all_stocks[s["code"]] = sector_stocks(s["code"], 20)
        if i % 20 == 0:
            print("  成分股进度 %d/%d" % (i, len(sectors)))
    with open(os.path.join(DATA, "stocks.json"), "w", encoding="utf-8") as f:
        json.dump({"data_date": trade_date, "data": all_stocks}, f, ensure_ascii=False)

    # ---- indices.json ----
    try:
        idx = fetch_indices()
    except Exception as e:
        print("指数失败:", repr(e)[:100])
        idx = []
    with open(os.path.join(DATA, "indices.json"), "w", encoding="utf-8") as f:
        json.dump({"data": idx}, f, ensure_ascii=False)

    # ---- history.json ----
    hist_dates = sorted(recent_dates(30))
    hist_rows = {}
    for d in hist_dates:
        dd = load_daily(d)
        if not dd:
            continue
        for code, v in (dd.get("rows") or {}).items():
            hist_rows.setdefault(code, {"name": v.get("name"), "cells": {}})
            hist_rows[code]["cells"][d] = {"pct_chg": v.get("pct"),
                                           "lead_name": v.get("lead_name"),
                                           "lead_pct": v.get("lead_pct")}
    rows = [{"code": k, "name": v["name"], "cells": v["cells"]} for k, v in hist_rows.items()]
    rows.sort(key=lambda r: (r["cells"].get(trade_date, {}).get("pct_chg") is not None,
                             r["cells"].get(trade_date, {}).get("pct_chg", -99)), reverse=True)
    with open(os.path.join(DATA, "history.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": hist_dates, "rows": rows}, f, ensure_ascii=False)

    # ---- home.json ----
    cand = [s for s in sectors if s["name"] not in SKIP and s["pct"] is not None]
    cand.sort(key=lambda s: s["pct"], reverse=True)
    news = fetch_news()
    themes = []
    for s in cand[:5]:
        code = s["code"]
        prev_pct = prev.get(code) if prev_date else None
        delta = round(s["pct"] - prev_pct, 2) if (prev_pct is not None and s["pct"] is not None) else None
        themes.append({
            "code": code, "name": s["name"], "pct": s["pct"],
            "delta": delta, "prev_pct": prev_pct,
            "stock_count": s["count"], "amount": s["amount"],
            "lead_name": s["lead_name"], "lead_pct": s["lead_pct"],
            "desc": DESC.get(s["name"]) or f"题材分类，包含 {s['count']} 只股票。",
            "stocks": [{"code": x["code"], "name": x["name"], "pct": x["pctChg"]}
                       for x in (all_stocks.get(code) or [])[:3]],
            "news": match_news(s["name"], news),
        })

    total = len([s for s in sectors if s["pct"] is not None])
    up = len([s for s in sectors if (s["pct"] or 0) > 0])
    down = len([s for s in sectors if (s["pct"] or 0) < 0])
    home = {
        "ok": True, "data_date": trade_date, "prev_date": prev_date,
        "market_trade_date": trade_date, "is_latest": True,
        "stats": {"total": total, "up": up, "down": down, "flat": total - up - down},
        "themes": themes, "note": None,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(DATA, "home.json"), "w", encoding="utf-8") as f:
        json.dump(home, f, ensure_ascii=False, indent=1)

    print("完成: 题材 %d / 成分股题材 %d / 历史 %d 天 / 首页 %d 条"
          % (len(sectors), len(all_stocks), len(hist_dates), len(themes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())