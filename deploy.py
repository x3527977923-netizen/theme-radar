"""把本地 static/ 全量同步到 GitHub 仓库（整棵树替换），再触发部署"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:\Users\LEGION\Documents\deepseek-harness\default-workspace\stocklab\static"
TOKEN = open(os.path.join(r"D:\work\stocklab-deploy", ".ghtoken"), encoding="utf-8").read().strip()
OWNER, REPO = "x3527977923-netizen", "theme-radar"
API = "https://api.github.com"
SKIP_NAMES = {".ghtoken", "publish.py", ".runid"}
SKIP_DIRS = {".git", "node_modules", "__pycache__"}


def call(path, method="GET", body=None, tries=4):
    data = json.dumps(body).encode() if body is not None else None
    last_err = None
    for attempt in range(tries):
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": "token " + TOKEN,
            "Accept": "application/vnd.github+json",
            "User-Agent": "stocklab-publisher",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                t = r.read().decode("utf-8", "ignore")
                return r.status, (json.loads(t) if t else {})
        except urllib.error.HTTPError as e:
            t = e.read().decode("utf-8", "ignore")
            try:
                return e.code, json.loads(t or "{}")
            except Exception:
                return e.code, {"raw": t[:300]}
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise last_err


def files():
    out = []
    for root, dirs, fs in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in fs:
            if f in SKIP_NAMES:
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, ROOT).replace("\\", "/")
            out.append((rel, p))
    return out


def main():
    commit_msg = sys.argv[1] if len(sys.argv) > 1 else "update site"

    # 0) 先把云端已有的每日快照拉回本地，避免全量推送时把历史覆盖掉
    s0, tree0 = call(f"/repos/{OWNER}/{REPO}/git/trees/main?recursive=1")
    if s0 == 200:
        daily_dir = os.path.join(ROOT, "site", "data", "_daily")
        os.makedirs(daily_dir, exist_ok=True)
        pulled = 0
        for item in tree0.get("tree") or []:
            pth = item.get("path", "")
            if not pth.startswith("site/data/_daily/") or not pth.endswith(".json"):
                continue
            local = os.path.join(ROOT, pth.replace("/", os.sep))
            if os.path.exists(local):
                continue
            s1, blob = call(f"/repos/{OWNER}/{REPO}/git/blobs/{item['sha']}")
            if s1 == 200:
                with open(local, "wb") as f:
                    f.write(base64.b64decode(blob["content"]))
                pulled += 1
        if pulled:
            print("从云端补回历史快照:", pulled, "天")
    s, ref = call(f"/repos/{OWNER}/{REPO}/git/refs/heads/main")
    if s != 200:
        print("取分支失败:", s, str(ref)[:200])
        return 1
    parent = ref["object"]["sha"]
    print("当前 main:", parent[:10])

    tree = []
    for rel, p in sorted(files()):
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        s, d = call(f"/repos/{OWNER}/{REPO}/git/blobs", "POST",
                    {"content": b64, "encoding": "base64"})
        if s not in (200, 201):
            print("blob 失败:", rel, s, str(d)[:150])
            return 1
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": d["sha"]})
    print("文件数:", len(tree))

    s, d = call(f"/repos/{OWNER}/{REPO}/git/trees", "POST", {"tree": tree})
    if s not in (200, 201):
        print("tree 失败:", s, str(d)[:200])
        return 1

    s, d = call(f"/repos/{OWNER}/{REPO}/git/commits", "POST",
                {"message": commit_msg, "tree": d["sha"], "parents": [parent]})
    if s not in (200, 201):
        print("commit 失败:", s, str(d)[:200])
        return 1
    new_sha = d["sha"]

    s, d = call(f"/repos/{OWNER}/{REPO}/git/refs/heads/main", "PATCH",
                {"sha": new_sha, "force": False})
    if s not in (200, 201):
        print("更新分支失败:", s, str(d)[:200])
        return 1
    print("已提交:", new_sha[:10])

    # 触发部署
    s, d = call(f"/repos/{OWNER}/{REPO}/actions/workflows/daily.yml/dispatches",
                "POST", {"ref": "main"})
    print("触发部署:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())