#!/usr/bin/env python3
"""题材雷达 · 静态站数据生成器（GitHub Actions 每天收盘后运行）

产出（全部写进 site/data/）：
  home.json      首页盘后驾驶舱：交易日 + 市场广度 + 涨停情绪 + 强势题材
  limitup.json   涨停解读与连板梯队（涨停池 / 炸板池 / 跌停池 / 题材归因）
  sectors.json   全部题材当日行情 + 较上一交易日变化 + 真实热度
  stocks.json    每个题材涨幅靠前的成分股（前 20 只）
  indices.json   主要指数
  history.json   近 30 个交易日 × 题材 的涨幅矩阵（由 data/_daily/*.json 累积）
  _daily/YYYY-MM-DD.json  当日原始快照（用于累积历史）

数据来源：新浪财经、腾讯财经、东方财富公开行情接口。仅陈述事实，不预测涨跌。
"""
import json
import math
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
HDR_EM = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}

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


def http(url, headers=None, timeout=20, tries=4):
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


def write_json_safe(path, payload, is_valid=True, indent=None):
    """仅当新数据有效时才原子写入；接口抽风返回空数据时保留旧文件"""
    if (not is_valid) and os.path.isfile(path):
        print(f"WARN: {os.path.basename(path)} 新数据无效/为空，保留已有文件")
        return False
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)
    return True


def _qt_prefix(code):
    c = str(code).strip()
    if c.startswith(("6", "9", "5")):
        return "sh" + c
    if c.startswith(("4", "8")):
        return "bj" + c
    return "sz" + c


def fetch_tencent_quotes(codes):
    """批量拉取腾讯最新价与涨跌幅（用于计算昨日涨停今日溢价/核按钮）"""
    res = {}
    uniq = list(dict.fromkeys(str(c).strip() for c in codes if c))
    for i in range(0, len(uniq), 60):
        chunk = uniq[i:i + 60]
        syms = ",".join(_qt_prefix(c) for c in chunk)
        try:
            txt = gbk_text("https://qt.gtimg.cn/q=" + syms,
                           {"User-Agent": UA, "Referer": "https://gu.qq.com/"})
            for line in txt.split(";"):
                if "=" not in line:
                    continue
                f = line.split("=", 1)[1].strip().strip('"').split("~")
                if len(f) < 33:
                    continue
                code = str(f[2]).strip()
                try:
                    price = float(f[3])
                    pct = round(float(f[32]), 2)
                except Exception:
                    continue
                res[code] = {"price": price, "pct": pct, "name": f[1]}
        except Exception as e:
            print("批量行情拉取失败:", repr(e)[:100])
    return res


def gbk_text(url, headers=None):
    return http(url, headers).decode("gbk", "ignore")


def fmt_hhmmss(v):
    if not v:
        return ""
    s = str(int(v)).zfill(6)
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}"


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


# ---------- 东财涨停/炸板/跌停池 ----------
def _em_pool(endpoint, sort_expr, ymd):
    url = (f"https://push2ex.eastmoney.com/{endpoint}"
           f"?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           f"&Pageindex=0&pagesize=200&sort={sort_expr}&date={ymd}")
    raw = http(url, headers=HDR_EM, timeout=15, tries=2).decode("utf-8", "ignore")
    d = json.loads(raw)
    return (d.get("data") or {}).get("pool") or []


def fetch_limitup(trade_date, prev_date=None):
    ymd = trade_date.replace("-", "")
    zt_raw, zb_raw, dt_raw = [], [], []
    try:
        zt_raw = _em_pool("getTopicZTPool", "lbc:desc", ymd)
    except Exception as e:
        print("涨停池拉取失败:", repr(e)[:100])
    try:
        zb_raw = _em_pool("getTopicZBPool", "fbt:asc", ymd)
    except Exception as e:
        print("炸板池拉取失败:", repr(e)[:100])
    try:
        dt_raw = _em_pool("getTopicDTPool", "fund:asc", ymd)
    except Exception as e:
        print("跌停池拉取失败:", repr(e)[:100])

    zt_list = []
    for x in zt_raw:
        zttj = x.get("zttj") or {}
        days, ct = zttj.get("days") or 0, zttj.get("ct") or 0
        stat = f"{days}天{ct}板" if days > 1 and ct > 1 else ""
        zt_list.append({
            "code": str(x.get("c") or ""),
            "name": x.get("n") or "",
            "price": round((x.get("p") or 0) / 1000.0, 2),
            "pct": round(float(x.get("zdp") or 0), 2),
            "lbc": int(x.get("lbc") or 1),
            "hybk": (x.get("hybk") or "其他").strip() or "其他",
            "fund": float(x.get("fund") or 0),
            "amount": float(x.get("amount") or 0),
            "hs": round(float(x.get("hs") or 0), 2),
            "fbt": fmt_hhmmss(x.get("fbt")),
            "lbt": fmt_hhmmss(x.get("lbt")),
            "zbc": int(x.get("zbc") or 0),
            "stat": stat,
            "ltsz": float(x.get("ltsz") or 0),
        })

    # 连板天梯（按连板数分组）
    by_board = {}
    for s in zt_list:
        by_board.setdefault(s["lbc"], []).append(s)
    ladders = []
    for b in sorted(by_board.keys(), reverse=True):
        arr = sorted(by_board[b], key=lambda x: (x["fbt"] or "99:99:99", -x["fund"]))
        ladders.append({
            "board": b,
            "label": "首板" if b == 1 else f"{b}连板",
            "count": len(arr),
            "stocks": arr,
        })

    # 按所属题材/行业归因
    by_theme = {}
    for s in zt_list:
        by_theme.setdefault(s["hybk"], []).append(s)
    theme_groups = []
    for tname, arr in by_theme.items():
        arr_sorted = sorted(arr, key=lambda x: (-x["lbc"], x["fbt"] or "99:99:99"))
        theme_groups.append({
            "name": tname,
            "count": len(arr_sorted),
            "max_board": max(x["lbc"] for x in arr_sorted),
            "total_seal": sum(x["fund"] for x in arr_sorted),
            "total_amount": sum(x["amount"] for x in arr_sorted),
            "leader": arr_sorted[0]["name"] if arr_sorted else "",
            "stocks": arr_sorted,
        })
    theme_groups.sort(key=lambda g: (-g["count"], -g["max_board"], -g["total_seal"]))

    # 炸板池
    zb_list = []
    for x in zb_raw:
        zb_list.append({
            "code": str(x.get("c") or ""),
            "name": x.get("n") or "",
            "price": round((x.get("p") or 0) / 1000.0, 2),
            "pct": round(float(x.get("zdp") or 0), 2),
            "hybk": (x.get("hybk") or "其他").strip() or "其他",
            "fbt": fmt_hhmmss(x.get("fbt")),
            "zbc": int(x.get("zbc") or 1),
            "amount": float(x.get("amount") or 0),
            "hs": round(float(x.get("hs") or 0), 2),
            "zf": round(float(x.get("zf") or 0), 2),
        })

    # 跌停池
    dt_list = []
    for x in dt_raw:
        dt_list.append({
            "code": str(x.get("c") or ""),
            "name": x.get("n") or "",
            "price": round((x.get("p") or 0) / 1000.0, 2),
            "pct": round(float(x.get("zdp") or 0), 2),
            "hybk": (x.get("hybk") or "其他").strip() or "其他",
            "days": int(x.get("days") or 1),
            "oc": int(x.get("oc") or 0),
            "amount": float(x.get("amount") or 0),
            "hs": round(float(x.get("hs") or 0), 2),
            "fund": float(x.get("fund") or 0),
        })

    zt_cnt = len(zt_list)
    zb_cnt = len(zb_list)
    dt_cnt = len(dt_list)
    zb_rate = round(zb_cnt / (zt_cnt + zb_cnt) * 100, 1) if (zt_cnt + zb_cnt) else 0.0
    max_board = max((x["lbc"] for x in zt_list), default=0)
    lianban_cnt = sum(1 for x in zt_list if x["lbc"] >= 2)
    total_seal = sum(x["fund"] for x in zt_list)
    zt_amount = sum(x["amount"] for x in zt_list)

    # 晋级率 & 昨日涨停今日溢价 / 核按钮清单
    promotion = {
        "prev_date": prev_date,
        "tiers": [],
        "prev_total": 0,
        "promoted_total": 0,
        "overall_rate": None,
        "prev_zt_avg_pct": None,
        "prev_zt_up_rate": None,
    }
    nuke_pool = []
    if prev_date and zt_list:
        try:
            prev_raw = _em_pool("getTopicZTPool", "lbc:desc", prev_date.replace("-", ""))
        except Exception as e:
            print("昨日涨停池拉取失败:", repr(e)[:100])
            prev_raw = []
        if prev_raw:
            today_zt_codes = {x["code"] for x in zt_list}
            prev_by_tier = {1: [], 2: [], 3: []}  # 3 代表 3板及以上
            prev_items = []
            for x in prev_raw:
                c = str(x.get("c") or "")
                lbc = int(x.get("lbc") or 1)
                if not c:
                    continue
                bucket = 1 if lbc == 1 else (2 if lbc == 2 else 3)
                prev_by_tier[bucket].append(c)
                prev_items.append({
                    "code": c,
                    "name": x.get("n") or "",
                    "prev_lbc": lbc,
                    "hybk": (x.get("hybk") or "其他").strip() or "其他",
                })
            tiers_out = []
            for b, lbl in [(1, "1进2"), (2, "2进3"), (3, "3进4+")]:
                arr = prev_by_tier[b]
                if not arr:
                    continue
                prom = sum(1 for c in arr if c in today_zt_codes)
                tiers_out.append({
                    "label": lbl,
                    "prev_count": len(arr),
                    "promoted": prom,
                    "rate": round(prom / len(arr) * 100, 1),
                })
            prev_total = len(prev_items)
            prom_total = sum(1 for x in prev_items if x["code"] in today_zt_codes)
            promotion["tiers"] = tiers_out
            promotion["prev_total"] = prev_total
            promotion["promoted_total"] = prom_total
            promotion["overall_rate"] = round(prom_total / prev_total * 100, 1) if prev_total else None

            # 拉取昨日涨停股今日收盘涨跌幅（计算溢价率 & 核按钮）
            qt = fetch_tencent_quotes([x["code"] for x in prev_items])
            pcts = []
            for it in prev_items:
                q = qt.get(it["code"])
                if not q:
                    continue
                pcts.append(q["pct"])
                if q["pct"] <= -4.0:
                    nuke_pool.append({
                        "code": it["code"],
                        "name": it["name"] or q["name"],
                        "prev_lbc": it["prev_lbc"],
                        "hybk": it["hybk"],
                        "price": q["price"],
                        "pct": q["pct"],
                    })
            if pcts:
                promotion["prev_zt_avg_pct"] = round(sum(pcts) / len(pcts), 2)
                promotion["prev_zt_up_rate"] = round(sum(1 for v in pcts if v > 0) / len(pcts) * 100, 1)
            nuke_pool.sort(key=lambda x: (x["pct"], -x["prev_lbc"]))
            nuke_pool = nuke_pool[:25]

    return {
        "data_date": trade_date,
        "summary": {
            "zt_count": zt_cnt,
            "zb_count": zb_cnt,
            "dt_count": dt_cnt,
            "zb_rate": zb_rate,
            "max_board": max_board,
            "lianban_count": lianban_cnt,
            "total_seal": total_seal,
            "zt_amount": zt_amount,
            "prev_zt_avg_pct": promotion["prev_zt_avg_pct"],
            "overall_promote_rate": promotion["overall_rate"],
        },
        "promotion": promotion,
        "nuke_pool": nuke_pool,
        "ladders": ladders,
        "themes": theme_groups,
        "zb_pool": zb_list,
        "dt_pool": dt_list,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------- 题材 ----------
def fetch_sectors():
    """新浪概念板块（172 个）
    字段顺序：
      0:code 1:name 2:count 3:avg_price 4:avg_chg_yuan 5:pct(%)
      6:volume 7:amount 8:lead_code 9:lead_pct(%) 10:lead_price 11:lead_chg_yuan 12:lead_name
    """
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
            pct = round(float(p[5]), 2)
        except Exception:
            pct = None
        try:
            lead_pct = round(float(p[9]), 2) if p[9] else None
        except Exception:
            lead_pct = None
        out.append({
            "code": p[0], "name": p[1],
            "count": int(p[2]) if p[2].isdigit() else None,
            "amount": float(p[7]) if p[7] else None,
            "pct": pct,
            "lead_code": re.sub(r"^[a-z]{2}", "", p[8]),
            "lead_name": p[12] if len(p) > 12 else None,
            "lead_pct": lead_pct,
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


# ---------- 东财板块主力资金流向 ----------
def _em_flow_list(fs, po=1, pz=25):
    url = (f"https://push2.eastmoney.com/api/qt/clist/get"
           f"?pn=1&pz={pz}&po={po}&np=1&fltt=2&invt=2&fid=f62&fs={fs}"
           f"&fields=f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f204,f205")
    raw = http(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
               timeout=15, tries=2).decode("utf-8", "ignore")
    d = json.loads(raw)
    diff = (d.get("data") or {}).get("diff") or []
    out = []
    for x in diff:
        def num(k):
            v = x.get(k)
            if v is None or v == "-":
                return None
            try:
                return float(v)
            except Exception:
                return None
        out.append({
            "code": str(x.get("f12") or ""),
            "name": str(x.get("f14") or ""),
            "pct": num("f3"),
            "main_inflow": num("f62"),
            "main_ratio": num("f184"),
            "super_inflow": num("f66"),
            "big_inflow": num("f72"),
            "lead_name": str(x.get("f204") or ""),
            "lead_code": str(x.get("f205") or ""),
        })
    return out


def fetch_fund_flow(trade_date):
    res = {
        "data_date": trade_date,
        "concept_in": [], "concept_out": [],
        "industry_in": [], "industry_out": [],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    for key, fs, po in [
        ("concept_in", "m:90+t:3", 1),
        ("concept_out", "m:90+t:3", 0),
        ("industry_in", "m:90+t:2", 1),
        ("industry_out", "m:90+t:2", 0),
    ]:
        try:
            res[key] = _em_flow_list(fs, po=po, pz=25)
        except Exception as e:
            print(f"资金流 {key} 拉取失败:", repr(e)[:100])
    return res


def _tag_seat(name):
    if "机构专用" in name:
        return "机构"
    if "深股通" in name or "沪股通" in name:
        return "北向"
    if "拉萨" in name or "东方财富证券" in name:
        return "拉萨"
    if "量化" in name or "开源证券西安西大街" in name or "中国国际金融上海分公司" in name or "瑞银证券" in name:
        return "量化"
    return "游资"


def _short_seat(name):
    s = str(name or "")
    for rm in ("有限责任公司", "股份有限公司", "证券营业部", "营业部"):
        s = s.replace(rm, "")
    return s.strip()


def _fetch_lhb_seats(trade_date, code):
    params = urllib.parse.urlencode({
        "sortColumns": "BUY",
        "sortTypes": "-1",
        "pageSize": 5,
        "pageNumber": 1,
        "reportName": "RPT_BILLBOARD_DAILYDETAILSBUY",
        "columns": "OPERATEDEPT_NAME,BUY,SELL,NET",
        "filter": f'(TRADE_DATE=\'{trade_date}\')(SECURITY_CODE="{code}")',
    })
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + params
    try:
        raw = http(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
                   timeout=12, tries=2).decode("utf-8", "ignore")
        rows = (json.loads(raw).get("result") or {}).get("data") or []
        seats = []
        for r in rows[:5]:
            nm = str(r.get("OPERATEDEPT_NAME") or "")
            if not nm:
                continue
            seats.append({
                "name": _short_seat(nm),
                "tag": _tag_seat(nm),
                "buy": float(r.get("BUY") or 0),
                "sell": float(r.get("SELL") or 0),
                "net": float(r.get("NET") or 0),
            })
        return seats
    except Exception:
        return []


# ---------- 东财龙虎榜 ----------
def fetch_lhb(trade_date):
    """拉取最近一个已公布龙虎榜交易日的净买卖明细（收盘后约 17:30 发布，未发布则自动取前一交易日）"""
    from datetime import timedelta
    d0 = datetime.strptime(trade_date, "%Y-%m-%d")
    since = (d0 - timedelta(days=7)).strftime("%Y-%m-%d")
    params = urllib.parse.urlencode({
        "sortColumns": "TRADE_DATE,BILLBOARD_NET_AMT",
        "sortTypes": "-1,-1",
        "pageSize": 120,
        "pageNumber": 1,
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,TURNOVERRATE,EXPLANATION",
        "filter": f"(TRADE_DATE>='{since}')",
    })
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + params
    out = {"data_date": trade_date, "net_buy": [], "net_sell": [], "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    try:
        raw = http(url, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"},
                   timeout=15, tries=2).decode("utf-8", "ignore")
        rows = (json.loads(raw).get("result") or {}).get("data") or []
        if not rows:
            return out
        latest_dt = str(rows[0].get("TRADE_DATE") or "")[:10]
        out["data_date"] = latest_dt or trade_date
        by_code = {}
        for x in rows:
            if str(x.get("TRADE_DATE") or "")[:10] != latest_dt:
                continue
            code = str(x.get("SECURITY_CODE") or "")
            if not code or code in by_code:
                continue
            def fnum(k):
                v = x.get(k)
                try:
                    return float(v) if v is not None else None
                except Exception:
                    return None
            by_code[code] = {
                "code": code,
                "name": str(x.get("SECURITY_NAME_ABBR") or ""),
                "close": fnum("CLOSE_PRICE"),
                "pct": round(fnum("CHANGE_RATE"), 2) if fnum("CHANGE_RATE") is not None else None,
                "net_amt": fnum("BILLBOARD_NET_AMT") or 0.0,
                "buy_amt": fnum("BILLBOARD_BUY_AMT") or 0.0,
                "sell_amt": fnum("BILLBOARD_SELL_AMT") or 0.0,
                "hs": round(fnum("TURNOVERRATE"), 2) if fnum("TURNOVERRATE") is not None else None,
                "reason": str(x.get("EXPLANATION") or ""),
            }
        all_rows = list(by_code.values())
        out["net_buy"] = sorted([r for r in all_rows if r["net_amt"] > 0], key=lambda r: -r["net_amt"])[:30]
        out["net_sell"] = sorted([r for r in all_rows if r["net_amt"] < 0], key=lambda r: r["net_amt"])[:30]

        # 并发拉取净买前 15 / 净卖前 10 的买五席位明细
        from concurrent.futures import ThreadPoolExecutor
        targets = out["net_buy"][:15] + out["net_sell"][:10]
        if targets:
            with ThreadPoolExecutor(max_workers=6) as ex:
                futs = {ex.submit(_fetch_lhb_seats, out["data_date"], r["code"]): r for r in targets}
                for fut, row in futs.items():
                    seats = fut.result()
                    if seats:
                        row["seats"] = seats
                        row["seat_tags"] = list(dict.fromkeys(s["tag"] for s in seats))
    except Exception as e:
        print("龙虎榜拉取失败:", repr(e)[:100])
    return out


# ---------- 隔夜外盘 → A 股映射 ----------
GLOBAL_MAP = [
    ("usSOXX", "费城半导体ETF", "半导体/芯片", [("gn_bdt", "半导体"), ("gn_gcxp", "国产芯片"), ("gn_hwhs", "华为海思")]),
    ("usNVDA", "英伟达 NVDA", "AI算力", [("gn_rgzn", "人工智能"), ("gn_slgn", "算力概念"), ("gn_gmk", "光模块")]),
    ("usXLK", "美股科技ETF", "科技成长", [("gn_rgzn", "人工智能"), ("gn_xc", "信创"), ("gn_sjys", "数据要素")]),
    ("usTSLA", "特斯拉 TSLA", "智能汽车/机器人", [("gn_tslgn", "特斯拉概念"), ("gn_xnyc", "新能源车"), ("gn_jqrgn", "机器人概念")]),
    ("usAAPL", "苹果 AAPL", "消费电子", [("gn_pggn", "苹果概念"), ("gn_xfdz", "消费电子")]),
    ("usKWEB", "中概互联ETF", "互联网/传媒", [("gn_cm", "传媒"), ("gn_yxgn", "游戏概念")]),
    ("usGLD", "黄金ETF", "贵金属", [("gn_hjgn", "黄金概念"), ("gn_ysjs", "有色金属")]),
    ("usXLE", "美股能源ETF", "传统能源", [("gn_mt", "煤炭")]),
    ("usXLV", "美股医疗ETF", "医药医疗", [("gn_cxy", "创新药"), ("gn_ylqx", "医疗器械")]),
]


def fetch_global_map(trade_date):
    syms = [x[0] for x in GLOBAL_MAP]
    meta = {x[0].replace("us", ""): x for x in GLOBAL_MAP}
    items = []
    try:
        txt = gbk_text("https://qt.gtimg.cn/q=" + ",".join(syms),
                       {"User-Agent": UA, "Referer": "https://gu.qq.com/"})
        for line in txt.split(";"):
            if "=" not in line:
                continue
            f = line.split("=", 1)[1].strip().strip('"').split("~")
            if len(f) < 33:
                continue
            raw_code = f[2].split(".")[0]
            m = meta.get(raw_code)
            if not m:
                continue
            try:
                pct = round(float(f[32]), 2)
            except Exception:
                pct = None
            items.append({
                "symbol": raw_code,
                "name": m[1],
                "sector": m[2],
                "price": f[3],
                "pct": pct,
                "a_themes": [{"code": c, "name": n} for c, n in m[3]],
            })
    except Exception as e:
        print("外盘映射拉取失败:", repr(e)[:100])
    return {
        "data_date": trade_date,
        "items": items,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


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
    key = name.replace("概念", "").replace("板块", "").replace("指数", "").replace("Ⅱ", "").replace("Ⅲ", "").strip()
    if len(key) < 2:
        return None
    for n in news:
        if key in n["title"]:
            return n
    return None


def update_emotion_history(trade_date, limitup):
    """把当日情绪指标增量写入 site/data/emotion_history.json（保留近 30 个交易日）"""
    p = os.path.join(DATA, "emotion_history.json")
    rows = []
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                rows = (json.load(f).get("rows") or [])
        except Exception:
            rows = []
    by_date = {r["date"]: r for r in rows if r.get("date")}
    sm = limitup.get("summary") or {}
    ladders = limitup.get("ladders") or []
    top_st = ladders[0]["stocks"][0] if (ladders and ladders[0].get("stocks")) else None
    by_date[trade_date] = {
        "date": trade_date,
        "zt_count": sm.get("zt_count", 0),
        "dt_count": sm.get("dt_count", 0),
        "zb_count": sm.get("zb_count", 0),
        "zb_rate": sm.get("zb_rate", 0.0),
        "max_board": sm.get("max_board", 0),
        "lianban_count": sm.get("lianban_count", 0),
        "total_seal": sm.get("total_seal", 0),
        "top_stock": top_st["name"] if top_st else "",
        "top_code": top_st["code"] if top_st else "",
        "top_hybk": top_st["hybk"] if top_st else "",
    }
    out_rows = [by_date[d] for d in sorted(by_date.keys())[-30:]]
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"rows": out_rows, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False)
    return out_rows


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


def calc_hot(pct, amount, zt_hits=0):
    """综合热度分（0-100+）：涨幅动量 + 成交规模 + 涨停催化"""
    score = 0.0
    if pct is not None:
        score += max(-20.0, min(50.0, (pct + 2.0) * 7.0))
    if amount and amount > 0:
        score += min(30.0, max(0.0, (math.log10(amount) - 7.5) * 9.0))
    score += zt_hits * 15.0
    return max(0, int(round(score)))


def main():
    os.makedirs(DAILY, exist_ok=True)
    try:
        trade_date = market_trade_date()
    except Exception as e:
        print("WARN: 交易日接口暂时不可达，保留已有数据并跳过本次运行:", repr(e)[:120])
        return 0
    print("交易日:", trade_date)

    force = "--force" in sys.argv
    existing = load_daily(trade_date)
    if (not force) and existing and len((existing.get("rows") or {})) >= 150:
        if all(os.path.isfile(os.path.join(DATA, fn)) for fn in ("limitup.json", "flow.json", "global.json", "home.json")):
            print("当天数据已存在（%d 个题材），跳过。需要重抓请加 --force" % len(existing.get("rows") or {}))
            return 0

    try:
        sectors = fetch_sectors()
    except Exception as e:
        print("WARN: 新浪题材接口暂时不可达，保留已有数据并跳过本次运行:", repr(e)[:120])
        return 0
    if not sectors:
        print("WARN: 题材数据为空，放弃本次生成（保留上次数据）")
        return 0
    print("题材数:", len(sectors))

    dates_pre = recent_dates(30)
    prev_date = next((d for d in dates_pre if d < trade_date), None)

    # ---- limitup.json + 快讯归因 + 情绪历史 ----
    news = fetch_news(limit=200)
    limitup = fetch_limitup(trade_date, prev_date=prev_date)
    for g in limitup.get("themes") or []:
        g["catalyst"] = match_news(g["name"], news)
    for tier in limitup.get("ladders") or []:
        for s in tier.get("stocks") or []:
            s["catalyst"] = match_news(s["name"], news) or match_news(s["hybk"], news)
    limitup["news_feed"] = news[:20]
    lu_ok = (limitup["summary"]["zt_count"] > 0 or limitup["summary"]["zb_count"] > 0)
    write_json_safe(os.path.join(DATA, "limitup.json"), limitup, is_valid=lu_ok)
    sm = limitup["summary"]
    emo_hist = update_emotion_history(trade_date, limitup) if lu_ok else []
    print("涨停池: 涨停 %d / 炸板 %d (%.1f%%) / 跌停 %d / 最高 %d 板 / 昨涨停溢价 %s%% | 情绪历史 %d 天"
          % (sm["zt_count"], sm["zb_count"], sm["zb_rate"], sm["dt_count"], sm["max_board"],
             sm.get("prev_zt_avg_pct"), len(emo_hist)))

    # ---- flow.json ----
    flow = fetch_fund_flow(trade_date)
    flow_ok = bool(flow["concept_in"] or flow["industry_in"])
    write_json_safe(os.path.join(DATA, "flow.json"), flow, is_valid=flow_ok)
    print("资金流: 概念流入 %d / 行业流入 %d" % (len(flow["concept_in"]), len(flow["industry_in"])))

    # ---- lhb.json ----
    lhb = fetch_lhb(trade_date)
    write_json_safe(os.path.join(DATA, "lhb.json"), lhb, is_valid=bool(lhb["net_buy"] or lhb["net_sell"]))
    print("龙虎榜(%s): 净买 %d / 净卖 %d" % (lhb["data_date"], len(lhb["net_buy"]), len(lhb["net_sell"])))

    # ---- global.json ----
    global_map = fetch_global_map(trade_date)
    write_json_safe(os.path.join(DATA, "global.json"), global_map, is_valid=bool(global_map["items"]))
    print("外盘映射: %d 项" % len(global_map["items"]))

    zt_codes = {s["code"] for l in limitup["ladders"] for s in l["stocks"]}

    # 当日快照落盘
    write_json_safe(
        os.path.join(DAILY, trade_date + ".json"),
        {"date": trade_date,
         "rows": {s["code"]: {"name": s["name"], "pct": s["pct"],
                              "count": s["count"], "lead_name": s["lead_name"],
                              "lead_pct": s["lead_pct"], "amount": s["amount"]}
                  for s in sectors}},
        is_valid=len(sectors) >= 100,
    )

    dates = recent_dates(30)
    prev_date = next((d for d in dates if d < trade_date), None)
    prev = {}
    if prev_date:
        pd = load_daily(prev_date)
        if pd:
            prev = {k: v.get("pct") for k, v in (pd.get("rows") or {}).items()}

    # ---- stocks.json（每个题材前 20 只） ----
    all_stocks = {}
    for i, s in enumerate(sectors, 1):
        all_stocks[s["code"]] = sector_stocks(s["code"], 20)
        if i % 30 == 0:
            print("  成分股进度 %d/%d" % (i, len(sectors)))
    with open(os.path.join(DATA, "stocks.json"), "w", encoding="utf-8") as f:
        json.dump({"data_date": trade_date, "data": all_stocks}, f, ensure_ascii=False)

    # ---- sectors.json ----
    data_rows = []
    for s in sectors:
        code = s["code"]
        d = None
        if prev_date and s["pct"] is not None and prev.get(code) is not None:
            d = round(s["pct"] - prev[code], 2)
        st_list = all_stocks.get(code) or []
        zt_hits = sum(1 for x in st_list if x["code"] in zt_codes)
        hot = calc_hot(s["pct"], s["amount"], zt_hits)
        data_rows.append({
            "id": code, "code": code, "name": s["name"],
            "name_code": code.upper(),
            "pct": s["pct"], "pct_chg": s["pct"], "pct_src": "sina",
            "delta": d,
            "count": s["count"], "stock_count": s["count"],
            "amount": s["amount"],
            "lead_code": s["lead_code"], "lead_name": s["lead_name"],
            "lead_pct": s["lead_pct"],
            "leader": {"name": s["lead_name"], "pctChg": s["lead_pct"]},
            "hot": hot, "limit_up": zt_hits,
        })
    with open(os.path.join(DATA, "sectors.json"), "w", encoding="utf-8") as f:
        json.dump({"data_date": trade_date, "prev_date": prev_date,
                   "data": data_rows}, f, ensure_ascii=False)

    # ---- indices.json ----
    try:
        idx = fetch_indices()
    except Exception as e:
        print("指数失败:", repr(e)[:100])
        idx = []
    write_json_safe(os.path.join(DATA, "indices.json"), {"data": idx}, is_valid=bool(idx))

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

    # ---- home.json（盘后驾驶舱） ----
    cand = [r for r in data_rows if r["name"] not in SKIP and r["pct"] is not None]
    cand.sort(key=lambda r: r["pct"], reverse=True)
    themes = []
    for s in cand[:8]:
        code = s["code"]
        prev_pct = prev.get(code) if prev_date else None
        themes.append({
            "code": code, "name": s["name"], "pct": s["pct"],
            "delta": s["delta"], "prev_pct": prev_pct,
            "stock_count": s["count"], "amount": s["amount"],
            "lead_name": s["lead_name"], "lead_pct": s["lead_pct"],
            "hot": s["hot"], "limit_up": s["limit_up"],
            "desc": DESC.get(s["name"]) or f"题材分类，包含 {s['count']} 只股票。",
            "stocks": [{"code": x["code"], "name": x["name"], "pct": x["pctChg"]}
                       for x in (all_stocks.get(code) or [])[:3]],
            "news": match_news(s["name"], news),
        })

    # 近 5 日持续性最强题材
    last5 = hist_dates[-5:]
    sustained = []
    for r in rows:
        if r["name"] in SKIP:
            continue
        up_days = sum(1 for d in last5 if (r["cells"].get(d) or {}).get("pct_chg") is not None and r["cells"][d]["pct_chg"] > 0)
        latest = (r["cells"].get(trade_date) or {}).get("pct_chg")
        if up_days >= 2 and latest is not None:
            sustained.append({
                "code": r["code"], "name": r["name"],
                "up_days": up_days, "window": len(last5), "latest": latest,
                "series": [(r["cells"].get(d) or {}).get("pct_chg") for d in last5],
            })
    sustained.sort(key=lambda x: (-x["up_days"], -(x["latest"] or -99)))

    total = len([s for s in sectors if s["pct"] is not None])
    up = len([s for s in sectors if (s["pct"] or 0) > 0])
    down = len([s for s in sectors if (s["pct"] or 0) < 0])
    home = {
        "ok": True, "data_date": trade_date, "prev_date": prev_date,
        "market_trade_date": trade_date, "is_latest": True,
        "stats": {"total": total, "up": up, "down": down, "flat": total - up - down},
        "emotion": limitup["summary"],
        "top_ladders": [l for l in limitup["ladders"] if l["board"] >= 2][:4],
        "zt_themes": limitup["themes"][:8],
        "top_inflow": flow["concept_in"][:6],
        "global_items": global_map["items"][:6],
        "themes": themes,
        "sustained": sustained[:6],
        "sustained_dates": last5,
        "note": None,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(os.path.join(DATA, "home.json"), "w", encoding="utf-8") as f:
        json.dump(home, f, ensure_ascii=False, indent=1)

    print("完成: 题材 %d / 成分股题材 %d / 历史 %d 天 / 首页题材 %d 条"
          % (len(sectors), len(all_stocks), len(hist_dates), len(themes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
