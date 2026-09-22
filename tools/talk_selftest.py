#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""talk.py 的自检：证明"三类消息 + SQLite 层面的角色权限"真的成立，跑完自清并落 evidence。"""
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import talk  # noqa: E402

ROOT = talk.ROOT
EVID = os.path.join(ROOT, "evidence")
WORD = "selftest%d" % int(time.time())
RESULTS = []


def check(name, ok, got=""):
    RESULTS.append((name, bool(ok), got))
    print(("OK   " if ok else "FAIL ") + name + (" | " + str(got) if got != "" else ""))


def run():
    os.makedirs(EVID, exist_ok=True)
    admin = talk.Talk(None)
    ids = []
    files = []
    try:
        # --- 角色名册 ---
        for full, title in [("pipeline.author", "功能创造者"), ("pipeline.tester", "测试者"),
                            ("pipeline.renderer", "渲染者"), ("pipeline.auditor", "审计者")]:
            admin.conn.execute("INSERT OR REPLACE INTO role(full_name,scene,name,title,created_at) VALUES(?,?,?,?,?)",
                               (full, full.split(".")[0], full.split(".")[1], title, talk.now_ts()))
        admin.conn.commit()
        n = admin.conn.execute("SELECT COUNT(*) FROM role").fetchone()[0]
        check("角色名册登记成功（≥4）", n >= 4, n)

        # --- 三类消息 ---
        a = talk.Talk("pipeline.author")
        i1 = a.send("pipeline.author", None, "default", "公告-" + WORD, "default 消息：谁都看得见 " + WORD)
        i2 = a.send("pipeline.author", "全体", "broadcast", "广播-" + WORD,
                    "broadcast 消息：对全体 " + WORD, must_reply=True)
        i3 = a.send("pipeline.author", "pipeline.tester", "private", "私信-" + WORD,
                    "private 消息：只给测试者 " + WORD)
        ids = [i1, i2, i3]
        check("三类消息都写进日志了（default/broadcast/private）", len(ids) == 3, ids)

        # --- 收件人看得到 ---
        t = talk.Talk("pipeline.tester")
        check("tester 搜到 default", len(t.search(WORD)) >= 1)
        check("tester 搜到 broadcast", len(t.search("广播-" + WORD)) >= 1)
        check("tester 搜到 private（它是收件人）", len(t.search("私信-" + WORD)) == 1)

        # --- 第三方看不到私信（这才是关键）---
        r = talk.Talk("pipeline.renderer")
        check("renderer 搜到 default（default 不看权限）", len(r.search(WORD)) >= 1)
        got_priv = len([x for x in r.search(WORD) if x[1] == "private"])
        check("renderer 搜不到私信（0 条）", got_priv == 0, got_priv)

        # --- 绕过视图直接读表：库拒绝 ---
        try:
            r.conn.execute("SELECT * FROM msg").fetchall()
            check("renderer 直接读 msg 表被库拒绝", False, "竟然读到了")
        except sqlite3.DatabaseError as e:
            check("renderer 直接读 msg 表被库拒绝", True, str(e))

        # --- 改名册/权限：非管理员被拒 ---
        try:
            r.conn.execute("UPDATE role SET title='x' WHERE full_name='pipeline.renderer'")
            check("renderer 改名册被库拒绝", False, "竟然改成了")
        except sqlite3.DatabaseError as e:
            check("renderer 改名册被库拒绝", True, str(e))

        # --- 审计角色：加一条数据型权限就能看私信 ---
        admin.conn.execute("INSERT OR REPLACE INTO perm(full_name,scope,action,created_at) VALUES(?,?,?,?)",
                           ("pipeline.auditor", "msg:all", "read", talk.now_ts()))
        admin.conn.commit()
        au = talk.Talk("pipeline.auditor")
        check("加了 msg:all/read 的审计角色能看到私信", len([x for x in au.search(WORD) if x[1] == "private"]) == 1)

        # --- 经理：有管理权，但**看不到别人的私信**（用户 2026-09-22 定）---
        admin.init_owner()
        mgr = talk.Talk("owner.me")
        mgr_priv = [x for x in mgr.search(WORD) if x[1] == "private"]
        check("经理看不到别人之间的私信（0 条）", len(mgr_priv) == 0, len(mgr_priv))
        try:
            mgr.conn.execute("SELECT * FROM msg").fetchall()
            check("经理直读 msg 表也被库拒绝（只能走视图）", False, "竟然读到了")
        except sqlite3.DatabaseError as e:
            check("经理直读 msg 表也被库拒绝（只能走视图）", True, str(e)[:30])
        mgr.stage_add(WORD, 1, "经理测试步", "pipeline.author")
        mgr.gate_open(WORD, 1, "owner.me")
        check("经理的管理权还在（能排阶段、能放行）", mgr.blocked_reason("pipeline.author") is None)

        # --- inbox：等我回的（广播/私信都算）---
        ti = [x[0] for x in t.inbox("pipeline.tester")]
        ri = [x[0] for x in r.inbox("pipeline.renderer")]
        check("tester 收件箱有广播", i2 in ti, ti)
        check("tester 收件箱有私信", i3 in ti, ti)
        check("renderer 收件箱有广播（全体）", i2 in ri, ri)
        check("renderer 收件箱没有别人的私信", i3 not in ri, ri)

        # --- 文本日志：私信只落在专属文件里 ---
        priv = talk.log_path("private", "pipeline.author", "pipeline.tester")
        bcast = talk.log_path("broadcast", "pipeline.author", "全体")
        dflt = talk.log_path("default", "pipeline.author", None)
        files = [priv, talk.log_path("broadcast", "pipeline.author", "全体"), dflt]
        have = lambda p: os.path.exists(p) and WORD in open(p, encoding="utf-8").read()
        check("私信写在 private-author__tester 文件里", have(priv), os.path.basename(priv))
        check("broadcast 文件里没有私信正文", os.path.exists(bcast) and "private 消息" not in open(bcast, encoding="utf-8").read())
        _rvis = [f for f in r.visible_files("pipeline.renderer") if "-private-" in f]
        # --- 角色 ↔ session 绑定：绑了就用绑的，没绑就用默认窗口 ---
        _fn = "pipeline.tester"
        check("没绑时用默认窗口", r.tmux_session(_fn) == "roles:pipeline-tester", r.tmux_session(_fn))
        _b = admin.role_bind(_fn, "roles:home-maid")
        check("bind 后只用这个 session", _b.get("ok") and admin.tmux_session(_fn) == "roles:home-maid", _b)
        _bad = admin.role_bind(_fn, "roles:no-such-window-xyz")
        check("绑到不存在的会话要拒", (not _bad.get("ok")) and "没有这个会话" in _bad.get("why", ""), _bad.get("why"))
        admin.role_unbind(_fn)
        check("解绑后回到默认窗口", admin.tmux_session(_fn) == "roles:pipeline-tester", r.tmux_session(_fn))

        check("renderer 看不到跟自己无关的私信文件",
              not any("pipeline.renderer" not in f for f in _rvis),
              _rvis[:3])

        # --- 项目阶段（经理闸门）---
        admin.init_owner()                      # 保证管理者角色在（幂等）
        boss = talk.Talk("owner.me")
        for s, nm, rl in [(1, "功能开发", "pipeline.author"), (2, "渲染打包", "pipeline.renderer"),
                          (3, "测试", "pipeline.tester")]:
            boss.stage_add(WORD, s, nm, rl)
        check("阶段初始全部 locked（后面的人收不到活）", boss.blocked_reason("pipeline.tester") is not None)
        boss.gate_open(WORD, 1, "owner.me")
        check("放行第 1 步后：第 1 步的人能收活", boss.blocked_reason("pipeline.author") is None)
        check("放行第 1 步后：第 2 步的人仍被卡", boss.blocked_reason("pipeline.renderer") is not None)
        try:
            boss.deliver("pipeline.renderer", "不该送到的活")
            check("阶段没放行时投递被卡", False, "竟然送进去了")
        except RuntimeError as e:
            check("阶段没放行时投递被卡", True, str(e)[:40])
        try:
            talk.Talk("pipeline.author").gate_open(WORD, 2, "pipeline.author")
            check("非经理不能放行阶段", False, "竟然放行了")
        except PermissionError:
            check("非经理不能放行阶段", True)
        try:
            talk.Talk("pipeline.author").report(WORD, 1, "pipeline.author", "我做完了，就这样")
            check("报告缺字段被拒", False, "竟然收了")
        except ValueError as e:
            check("报告缺字段被拒", True, str(e)[:30])
        # 报告是"角色自己"交的活 —— 用角色自己的连接（管理者不能替别人发言，这条规矩是对的）
        talk.Talk("pipeline.author").report(WORD, 1, "pipeline.author",
                                           "做了什么：x（%s）\n证据：y\n判据：z\n依赖：w" % WORD)
        check("合格报告入库", True)
        boss.gate_done(WORD, 1, "owner.me")
        boss.gate_open(WORD, 2, "owner.me")
        check("报告合格后才允许放行下一步", boss.blocked_reason("pipeline.renderer") is None)

        # --- 回复 ---
        ts = t.reply(i3, "pipeline.tester", "收到，判据已加（" + WORD + "）")
        check("收件人能回复私信", bool(ts))
        got = t.conn.execute("SELECT COUNT(*) FROM reply WHERE msg_id=?", (i3,)).fetchone()[0]
        check("回复也入库了", got == 1, got)
    finally:
        # --- 自清（P23 的规矩：验收不许留残件）---
        for i in ids:
            admin.conn.execute("DELETE FROM reply WHERE msg_id=?", (i,))
            admin.conn.execute("DELETE FROM msg WHERE id=?", (i,))
        admin.conn.execute("DELETE FROM perm WHERE full_name='pipeline.auditor'")
        admin.conn.execute("DELETE FROM role WHERE full_name='pipeline.auditor'")
        # 阶段与阶段消息（放行/报告）一并清掉，别留残件
        admin.conn.execute("DELETE FROM stage WHERE project=?", (WORD,))
        for r in admin.conn.execute("SELECT id FROM msg WHERE feature LIKE ? OR (topic='阶段' AND body LIKE ?)",
                                    (WORD + "%", "%" + WORD + "%")).fetchall():
            admin.conn.execute("DELETE FROM reply WHERE msg_id=?", (r[0],))
            admin.conn.execute("DELETE FROM wake WHERE msg_id=?", (r[0],))
            admin.conn.execute("DELETE FROM msg WHERE id=?", (r[0],))
        # wake 是"发消息时系统自己写的"，按 WORD 直接清一遍（不靠 msg 关联）
        admin.conn.execute("DELETE FROM wake WHERE role LIKE ? OR msg_id IN"
                           " (SELECT id FROM msg WHERE topic LIKE ? OR body LIKE ?)",
                           ("%", "%" + WORD + "%", "%" + WORD + "%"))
        admin.conn.execute("DELETE FROM wake WHERE msg_id NOT IN (SELECT id FROM msg)")
        admin.conn.commit()
        left = admin.conn.execute("SELECT COUNT(*) FROM msg WHERE topic LIKE ? OR body LIKE ?",
                                  ("%" + WORD + "%", "%" + WORD + "%")).fetchone()[0]
        check("收尾：测试消息清掉了", left == 0, left)
        for p in files:
            try:
                if os.path.exists(p) and not open(p, encoding="utf-8").read().replace(WORD, "").strip():
                    os.remove(p)
            except Exception:
                pass

    ok = sum(1 for _, o, _ in RESULTS if o)
    bad = len(RESULTS) - ok
    out = os.path.join(EVID, "selftest-%s.txt" % time.strftime("%Y%m%d-%H%M%S"))
    with open(out, "w", encoding="utf-8") as f:
        f.write("== roles-chat 自检 %s ==\n" % talk.fmt(talk.now_ts()))
        for name, o, got in RESULTS:
            f.write(("OK   " if o else "FAIL ") + name + ((" | " + str(got)) if got != "" else "") + "\n")
        f.write("---- 合计：OK=%d FAIL=%d\n" % (ok, bad))
    print("---- 合计：OK=%d FAIL=%d（证据：%s）" % (ok, bad, os.path.relpath(out, ROOT)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(run())
