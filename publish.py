"""用 GitHub API 发布静态站（无需 git）
1) 建仓库 theme-radar
2) 用 Git Data API 一次性提交所有文件
3) 开启 Pages（workflow 模式）
4) 触发 workflow 并等待完成
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:\Users\LEGION\Documents\deepseek-harness\default-workspace\stocklab\static"
TOKEN = open(os.path.join(ROOT, ".ghtoken"), encoding="utf-8").read().strip()
OWNER = "x3527977923-netizen"
REPO = "theme-radar"
API = "https://api.github.com"


def call(path, method="GET", body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "token " + TOKEN,
        "Accept": "application/vnd.github+json",
        "User-Agent": "stocklab-publisher",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read().decode("utf-8", "ignore")
            return r.status, (txt if raw else json.loads(txt or "{}"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(txt or "{}")
        except Exception:
            return e.code, {"raw": txt[:400]}


def collect_files():
    skip = {".ghtoken"}
    out = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("node_modules", ".git")]
        for f in files:
            if f in skip:
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            out.append((rel, p))
    return out


def main():
    # 1) 仓库
    s, d = call(f"/repos/{OWNER}/{REPO}")
    if s == 404:
        s, d = call("/user/repos", "POST", {
            "name": REPO,
            "description": "题材雷达 · 收盘后三分钟看懂今天哪些题材表现突出（公开行情整理，不构成投资建议）",
            "private": False,
            "has_issues": True,
            "has_wiki": False,
            "auto_init": False,
        })
        print("建仓库:", s, d.get("full_name") or d.get("message"))
    else:
        print("仓库已存在:", d.get("full_name"))

    # 1.5) 空仓库要先有一个 commit，否则 blobs API 会 409
    s, d = call(f"/repos/{OWNER}/{REPO}/contents/.gitkeep")
    if s == 404:
        s2, d2 = call(f"/repos/{OWNER}/{REPO}/contents/.gitkeep", "PUT", {
            "message": "init",
            "content": "",
        })
        print("初始化仓库:", s2, str(d2)[:120] if s2 not in (200,201) else "ok")
        # 建 main 分支（Contents API 默认可能建 master）
        time.sleep(2)

    # 2) 所有文件 → blobs → tree → commit
    files = collect_files()
    print("文件数:", len(files))
    blobs = []
    for rel, p in files:
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        s, d = call(f"/repos/{OWNER}/{REPO}/git/blobs", "POST",
                    {"content": b64, "encoding": "base64"})
        if s not in (200, 201):
            print("blob 失败:", rel, s, str(d)[:200])
            return 1
        blobs.append({"path": rel, "mode": "100644", "type": "blob", "sha": d["sha"]})
        print("  +", rel, round(os.path.getsize(p) / 1024, 1), "KB")

    s, d = call(f"/repos/{OWNER}/{REPO}/git/trees", "POST",
                {"tree": blobs})
    if s not in (200, 201):
        print("tree 失败:", s, str(d)[:300])
        return 1
    tree_sha = d["sha"]

    s, d = call(f"/repos/{OWNER}/{REPO}/git/commits", "POST", {
        "message": "init: 题材雷达静态站 + 每日数据流水线",
        "tree": tree_sha,
        "parents": [],
    })
    if s not in (200, 201):
        print("commit 失败:", s, str(d)[:300])
        return 1
    commit_sha = d["sha"]

    # main 分支指向这个 commit
    s, d = call(f"/repos/{OWNER}/{REPO}/git/refs", "POST",
                {"ref": "refs/heads/main", "sha": commit_sha})
    if s not in (200, 201):
        s2, d2 = call(f"/repos/{OWNER}/{REPO}/git/refs/heads/main", "PATCH",
                      {"sha": commit_sha, "force": True})
        print("更新分支:", s2, str(d2)[:150])
    else:
        print("建分支 main:", s)

    # 3) 开启 Pages（GitHub Actions 模式）
    s, d = call(f"/repos/{OWNER}/{REPO}/pages", "POST", {"build_type": "workflow"})
    if s in (200, 201):
        print("Pages 已开启:", d.get("html_url"))
    else:
        s2, d2 = call(f"/repos/{OWNER}/{REPO}/pages", "PUT", {"build_type": "workflow"})
        print("Pages 状态:", s, str(d)[:150], "| 重试:", s2, str(d2)[:150])

    print("仓库地址: https://github.com/%s/%s" % (OWNER, REPO))
    print("站点地址: https://%s.github.io/%s/" % (OWNER.lower(), REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())