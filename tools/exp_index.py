#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exp_index.py —— 角色经验库：列 / 查 / 自检

规矩（用户 2026-09-22）：目录名 = 角色全名（`experiences/<场景>.<角色>/`）；
一条经验一个文件，文件头必须有 name / must / tags / when / verified；
**说身份时必须加载该角色 must: true 的全部经验**，其余按任务检索。

用法：
  python3 tools/exp_index.py list   --role pipeline.author
  python3 tools/exp_index.py must   --role pipeline.author       # 只列必读的
  python3 tools/exp_index.py search --q 消毒 [--role pipeline.renderer]
  python3 tools/exp_index.py check                                # 结构自检（CI 用）
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXP = os.path.join(ROOT, "experiences")
KEYS = ["name", "must", "tags", "when", "verified"]


def parse(path):
    txt = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", txt, re.S)
    if not m:
        return None, txt
    head = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            head[k.strip()] = v.strip()
    return head, m.group(2)


def load():
    out = []
    if not os.path.isdir(EXP):
        return out
    for role in sorted(os.listdir(EXP)):
        d = os.path.join(EXP, role)
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".md"):
                head, body = parse(os.path.join(d, f))
                out.append({"role": role, "file": f, "head": head or {}, "body": body, "path": os.path.join(d, f)})
    return out


def show(e):
    h = e["head"]
    print("%-28s must=%-5s tags=%-22s when=%s" % (
        e["role"] + "/" + e["file"], h.get("must", "?"), h.get("tags", "-"), h.get("when", "-")))


def check():
    bad = 0
    items = load()
    for e in items:
        h = e["head"]
        for k in KEYS:
            if k not in h:
                print("ERROR %s 缺字段 %s" % (e["path"], k)); bad += 1
        if h.get("must") not in ("true", "false"):
            print("ERROR %s must 必须是 true/false" % e["path"]); bad += 1
        if "." not in e["role"]:
            print("ERROR 目录名必须是角色全名 <场景>.<角色>：%s" % e["role"]); bad += 1
    print("---- 经验 %d 条，问题 %d 处" % (len(items), bad))
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "must", "search", "check"])
    ap.add_argument("--role", default=None)
    ap.add_argument("--q", default="")
    a = ap.parse_args()
    if a.cmd == "check":
        return check()
    items = load()
    if a.role:
        items = [e for e in items if e["role"] == a.role]
    if a.cmd == "must":
        items = [e for e in items if e["head"].get("must") == "true"]
    if a.q:
        k = a.q.lower()
        items = [e for e in items if k in (e["body"] or "").lower() or k in str(e["head"]).lower()]
    for e in items:
        show(e)
    print("---- %d 条" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
