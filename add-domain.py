"""给 GitHub Pages 写入自定义域名（CNAME），并推送到仓库

用法:
  python add-domain.py 你的域名             # 写入并推送
  python add-domain.py 你的域名 --dry-run   # 只看会做什么

注意：域名需要先在域名商那里配好 DNS 解析（见 docs/自定义域名接入.md）。
写入 CNAME 后，github.io 地址会自动跳转到你的域名；如果 DNS 没配好，
站点会打不开。所以脚本会在写入前提示确认。
"""
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = r"D:\work\stocklab-deploy\.ghtoken"
OWNER, REPO = "x3527977923-netizen", "theme-radar"
API = "https://api.github.com"


def call(path, method="GET", body=None):
    token = open(TOKEN_FILE, encoding="utf-8").read().strip()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "stocklab-domain",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read().decode("utf-8", "ignore")
            return r.status, (json.loads(t) if t else {})
    except urllib.error.HTTPError as e:
        t = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(t or "{}")
        except Exception:
            return e.code, {"raw": t[:300]}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if not args:
        print(__doc__)
        return 1
    domain = args[0].strip().lower().replace("https://", "").replace("http://", "").strip("/")

    print("目标域名:", domain)
    print()
    print("检查清单（请先在域名商处完成）：")
    print("  1) A 记录 @  → 185.199.108.153 / .109.153 / .110.153 / .111.153")
    print("  2) CNAME   www → %s.github.io" % OWNER)
    print("  3) 等 DNS 生效（10 分钟 ~ 2 小时）")
    print()
    if dry:
        print("[dry-run] 会写 CNAME 文件并推送到仓库，实际未执行")
        return 0

    # 写本地 CNAME（deploy.py 会把整个 site 目录推上去）
    cname_path = os.path.join(ROOT, "site", "CNAME")
    with open(cname_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(domain + "\n")
    print("已写入:", cname_path)

    # 设置 GitHub Pages 的自定义域名
    s, d = call(f"/repos/{OWNER}/{REPO}/pages", "PUT",
                {"cname": domain, "build_type": "workflow"})
    print("设置 Pages 自定义域名:", s, str(d)[:200] if s not in (200, 204) else "ok")

    print()
    print("下一步：")
    print("  1) 运行 python deploy.py \"chore: 绑定域名 %s\"" % domain)
    print("  2) 等 GitHub Pages 的 DNS 校验通过，勾上 Enforce HTTPS")
    print("  3) 验证: curl -I https://%s/" % domain)
    return 0


if __name__ == "__main__":
    sys.exit(main())