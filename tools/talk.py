#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
talk.py —— 多角色对话：文本为权威 + SQLite 索引 + 角色权限（做在 SQLite 层面）

设计见 ~/.hermes/skills/roles/设计-角色经验与多角色对话.md
三类消息：default（不看权限谁都可见）／broadcast（对全体）／private（私信，只收发双方）

权限怎么落地（不是"约定不看"）：
  1) 角色开连接时挂 SQLite 授权器（set_authorizer）：直接读 `msg` 表被拒，只能走 TEMP 视图 `v_msg`；
     写 `role`/`perm` 只有管理员角色（有 perm table:role write）才允许。
  2) `v_msg` 在连接时按该角色身份拼好条件（我发的／default／broadcast／发给我的私信／有 msg:all 读权限的）。
  3) 文本日志按类分文件：default-…md / broadcast-…md / private-<from>__<to>.md ——
     私信连"文件层面"都不会进别人的可读范围。

用法见 README.md；自检：python3 tools/talk.py selftest
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# 换地方也能用：默认按本项目自己的位置推导，可用 ROLES_CHAT_HOME 覆盖（"定型"的一部分）
ROOT = os.environ.get("ROLES_CHAT_HOME") or os.path.dirname(HERE)
TALK_DIR = os.path.join(ROOT, "talk")
DB = os.path.join(ROOT, "talk.db")
EVID = os.path.join(ROOT, "evidence")

SCHEMA = """
CREATE TABLE IF NOT EXISTS role(
  full_name TEXT PRIMARY KEY, scene TEXT, name TEXT, title TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS perm(
  full_name TEXT, scope TEXT, action TEXT, created_at INTEGER,
  PRIMARY KEY(full_name, scope, action));
CREATE TABLE IF NOT EXISTS msg(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT CHECK(kind IN ('default','broadcast','private')),
  from_role TEXT, to_role TEXT, topic TEXT, body TEXT, created_at INTEGER,
  must_reply INTEGER DEFAULT 0, feature TEXT, file_path TEXT);
CREATE TABLE IF NOT EXISTS reply(
  id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id INTEGER, from_role TEXT, body TEXT, created_at INTEGER);
CREATE TABLE IF NOT EXISTS seen(
  msg_id INTEGER, role TEXT, seen_at INTEGER, PRIMARY KEY(msg_id, role));
CREATE TABLE IF NOT EXISTS room(
  scope TEXT PRIMARY KEY, state TEXT, by_role TEXT, why TEXT, updated_at INTEGER);
-- 项目阶段（经理闸门）：项目 = 一串阶段，经理只放行当前那个，后面的阶段收不到活
CREATE TABLE IF NOT EXISTS stage(
  project TEXT, seq INTEGER, name TEXT, role TEXT, state TEXT, updated_at INTEGER,
  PRIMARY KEY(project, seq));
"""


def now_ts():
    return int(time.time())


def fmt(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def log_path(kind, from_role, to_role, day=None):
    day = day or time.strftime("%Y-%m-%d")
    if kind == "private":
        return os.path.join(TALK_DIR, "%s-private-%s__%s.md" % (day, from_role, to_role))
    return os.path.join(TALK_DIR, "%s-%s.md" % (day, kind))


class Talk:
    def __init__(self, role=None, path=DB):
        self.role = role
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.admin = (role is None) or self._has("msg:all", "read")   # 看全部内容（含私信）
        self.manage = self._can_manage()                              # 管理权（改名册/放行阶段/暂停）
        if role:
            self._install_guard()
        else:
            # 管理员/看板连接也要有同名视图（"看全部"就是条件恒真），
            # 否则 board 这种无 --role 的调用会撞 no such table: v_msg
            self.conn.execute("DROP VIEW IF EXISTS v_msg")
            self.conn.execute("CREATE TEMP VIEW v_msg AS SELECT * FROM msg")

    # ---------- 权限 ----------
    def _can_manage(self):
        """管理权：改名册 / 改权限 / 放行阶段 / 暂停恢复（代表"我"的经理角色有，普通角色没有）"""
        if self.role is None:
            return True
        return self._has("table:role", "write") or self._has("room:control", "write")

    def _is_admin(self):
        return self.admin

    def _has(self, scope, action):
        r = self.conn.execute(
            "SELECT 1 FROM perm WHERE full_name=? AND scope=? AND action=?",
            (self.role, scope, action)).fetchone()
        return bool(r)

    def _install_guard(self):
        role = self.role
        all_read = self._has("msg:all", "read")
        # 按身份建 TEMP 视图：这条 SQL 就是"谁能看见什么"的唯一出处
        cond = "from_role = %s OR kind = 'default' OR kind = 'broadcast' OR (kind = 'private' AND to_role = %s)" % (
            self._q(role), self._q(role))
        if all_read:
            cond = "1=1"
        self.conn.execute("DROP VIEW IF EXISTS v_msg")
        self.conn.execute("CREATE TEMP VIEW v_msg AS SELECT * FROM msg WHERE " + cond)

        admin = self.manage

        def auth(action, arg1, arg2, dbname, source):
            if action == sqlite3.SQLITE_READ:
                # 只有"他本人"（不带角色的连接，也就是看板/命令行）或明确拿了 msg:all/read 的角色能直读 msg；
                # **经理虽有管理权，也不该知道私信内容** —— 它同样只能走按身份过滤的视图（用户 2026-09-22 定）
                if arg1 == "msg" and source != "v_msg" and not all_read and role is not None:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                if arg1 in ("role", "perm") and not admin:
                    return sqlite3.SQLITE_DENY        # 名册与权限：只有管理员能改
                if arg1 in ("room", "stage"):
                    # 房间状态 / 项目阶段：有 room:control/write 的管理者才能改（"我"那个角色 / 经理）
                    return sqlite3.SQLITE_OK if (admin or self._has("room:control", "write")) else sqlite3.SQLITE_DENY
                if arg1 in ("msg", "reply", "seen"):
                    return sqlite3.SQLITE_OK          # 发言权：人人有
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.conn.set_authorizer(auth)

    @staticmethod
    def _q(s):
        return "'" + str(s).replace("'", "''") + "'"

    # ---------- 写 ----------
    def send(self, from_role, to_role, kind, topic, body, must_reply=False, feature=None):
        if self.role and self.role != from_role:
            raise PermissionError("我是 %s，不能替 %s 发言" % (self.role, from_role))
        ts = now_ts()
        path = log_path(kind, from_role, to_role)
        os.makedirs(TALK_DIR, exist_ok=True)
        cur = self.conn.execute(
            "INSERT INTO msg(kind,from_role,to_role,topic,body,created_at,must_reply,feature,file_path)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (kind, from_role, to_role, topic, body, ts, 1 if must_reply else 0, feature, os.path.relpath(path, ROOT)))
        mid = cur.lastrowid
        self.conn.commit()
        head = "[%s] %s → %s | 全体? %s | 话题:%s | 必读:%s | #%d\n" % (
            fmt(ts), from_role, (to_role or "全体"), "是" if kind == "broadcast" else "否",
            topic or "-", "是" if must_reply else "否", mid)
        with open(path, "a", encoding="utf-8") as f:
            if os.path.getsize(path) if os.path.exists(path) else 0:
                f.write("\n")
            f.write(head)
            f.write("".join("    " + ln + "\n" for ln in (body or "").splitlines()))
        return mid

    def reply(self, msg_id, from_role, body):
        if self.role and self.role != from_role:
            raise PermissionError("我是 %s，不能替 %s 回复" % (self.role, from_role))
        row = self.conn.execute("SELECT * FROM v_msg WHERE id=?" if self.role else "SELECT * FROM msg WHERE id=?",
                                (msg_id,)).fetchone()
        if not row:
            raise PermissionError("这条对话我看不到（库按角色把行过滤掉了）：#%d" % msg_id)
        cols = [d[0] for d in self.conn.execute(
            "SELECT * FROM v_msg LIMIT 0" if self.role else "SELECT * FROM msg LIMIT 0").description]
        m = dict(zip(cols, row))
        ts = now_ts()
        self.conn.execute("INSERT INTO reply(msg_id,from_role,body,created_at) VALUES(?,?,?,?)",
                          (msg_id, from_role, body, ts))
        self.conn.commit()
        path = os.path.join(ROOT, m.get("file_path") or log_path(m["kind"], m["from_role"], m["to_role"]))
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join("    " + ln + "\n" for ln in
                            ("↳ 回复 [%s] %s: %s" % (fmt(ts), from_role, body)).splitlines()))
        return ts

    # ---------- 看板（他自己看：全部，含私信，带标签） ----------
    def _rows(self):
        return self.conn.execute(
            "SELECT id,kind,from_role,to_role,topic,body,created_at,must_reply FROM v_msg"
            " ORDER BY created_at").fetchall()

    def board(self, limit=1000, role=None):
        """一屏看全部对话：🔒 私信 / 📢 全体 / · default，带收发、时间、话题、必读、回复数"""
        rows = self._rows()
        rep = dict(self.conn.execute("SELECT msg_id, COUNT(*) FROM reply GROUP BY msg_id").fetchall())
        out = []
        for r in rows[-limit:]:
            mid, kind, frm, to, topic, body, ts, must = r
            tag = {"private": "🔒", "broadcast": "📢", "default": "· "}[kind]
            n = rep.get(mid, 0)
            state = ("已回%d" % n) if n else ("待回" if (must or kind in ("private", "broadcast")) else "—")
            head = "%s#%-3d [%s] %-22s → %-22s 话题:%-12s 必读:%-2s %s" % (
                tag, mid, fmt(ts), frm, (to or "全体"), (topic or "-"), "是" if must else "否", state)
            out.append(head)
            first = (body or "").splitlines()[:2]
            for ln in first:
                out.append("      " + ln[:150])
        if not out:
            out.append("（空）")
        print("\n".join(out))
        print("---- 共 %d 条消息（显示最近 %d 条）" % (len(rows), min(limit, len(rows))))

    def tail(self, n=1000):
        """按权限把能读的日志文件拼起来，看最后 n 行（缓冲够用的那种看法）"""
        files = [f for f in self.visible_files() if f.endswith(".md")]
        txt = []
        for f in files:
            p = os.path.join(TALK_DIR, f)
            txt.append("===== %s =====" % f)
            txt.extend(open(p, encoding="utf-8").read().splitlines())
        print("\n".join(txt[-n:]))

    # ---------- 管理者（代表"我"的角色，如 owner.me）：开始 / 停止 / 让他们交流 ----------
    # 权限是数据：谁的 perm 里有 room:control/write，谁就能下令；下令本身也记进对话（大家看得见）。
    def _can_control(self):
        return self.admin or self._has("room:control", "write")

    def state_of(self, scope):
        r = self.conn.execute("SELECT state FROM room WHERE scope=?", (scope,)).fetchone()
        return r[0] if r else "running"

    def set_state(self, scope, state, by_role, why=""):
        if not self._can_control():
            raise PermissionError("只有管理者能控制（缺 room:control/write）：%s" % by_role)
        self.conn.execute("INSERT OR REPLACE INTO room(scope,state,by_role,why,updated_at) VALUES(?,?,?,?,?)",
                          (scope, state, by_role, why, now_ts()))
        self.conn.commit()
        self.send(by_role, None, "default", "控制", "【%s】%s%s" % (
            state, ("全体" if scope == "room" else scope), ("：" + why) if why else ""))
        return state

    def is_paused(self, role=None):
        if self.state_of("room") == "paused":
            return "room"
        if role and self.state_of("role:" + role) == "paused":
            return "role"
        return None

    def stop_role(self, role, hard=False):
        """让她停：先发 /stop 打断当前回合；hard=True 连 tmux 会话一起收"""
        sess = self.tmux_session(role)
        alive = subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0
        if alive:
            if hard:
                subprocess.run(["tmux", "kill-session", "-t", sess], capture_output=True)
            else:
                subprocess.run(["tmux", "send-keys", "-t", sess, "/stop", "Enter"], capture_output=True)
        return alive

    def status(self):
        roles = [r[0] for r in self.conn.execute("SELECT full_name FROM role ORDER BY full_name")]
        print("%-26s %-9s %-6s %s" % ("角色", "状态", "会话", "待回"))
        for r in roles:
            sess = self.tmux_session(r)
            alive = subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0
            pend = len(self.inbox(r)) if self.admin else 0
            print("%-26s %-9s %-6s %s" % (r, self.state_of("role:" + r), "活着" if alive else "-", pend))
        print("房间：%s" % self.state_of("room"))

    def init_owner(self, full="owner.me", title="我（经理：能管流程，但看不到私信内容）"):
        self.conn.execute("INSERT OR REPLACE INTO role(full_name,scene,name,title,created_at) VALUES(?,?,?,?,?)",
                          (full, full.split(".")[0], full.split(".")[1], title, now_ts()))
        # 注意：**不给 msg:all/read** —— 经理管得了流程，但看不到别人之间的私信（用户 2026-09-22 定）
        # 同时清掉历史遗留的 msg:all 授权（改规则前给过，不清就会"旧权限还在、经理照样能看"）
        self.conn.execute("DELETE FROM perm WHERE full_name=? AND scope IN ('msg:all')", (full,))
        for scope, action in [("room:control", "write"), ("table:role", "write")]:
            self.conn.execute("INSERT OR REPLACE INTO perm(full_name,scope,action,created_at) VALUES(?,?,?,?)",
                              (full, scope, action, now_ts()))
        self.conn.commit()
        return full

    # ---------- 投递到角色的 tmux 会话 ----------
    @staticmethod
    def tmux_session(role):
        return "role-" + role.replace(".", "-")

    def spawn(self, role, profile=None, launch=None):
        """给角色开一个 tmux 会话（**幂等**：已经在跑就不动它）；会话名固定 = role-<场景>-<角色>"""
        sess = self.tmux_session(role)
        if subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode == 0:
            return sess, False
        # Hermes 侧也是"同一个会话续着走"：-c <角色全名> --create-if-missing
        run = launch or ("hermes %s chat -c %s --create-if-missing" % (
            ("-p " + profile) if profile else "", role))
        subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-x", "120", "-y", "40", run], check=True)
        return sess, True

    # ---------- 项目阶段（经理闸门）：只放行当前阶段，后面的人收不到活 ----------
    REPORT_FIELDS = ["做了什么", "证据", "判据", "依赖"]

    def stage_add(self, project, seq, name, role):
        self.conn.execute("INSERT OR REPLACE INTO stage(project,seq,name,role,state,updated_at)"
                          " VALUES(?,?,?,?,COALESCE((SELECT state FROM stage WHERE project=? AND seq=?),'locked'),?)",
                          (project, seq, name, role, project, seq, now_ts()))
        self.conn.commit()

    def stages(self, project=None):
        q = "SELECT project,seq,name,role,state FROM stage"
        args = ()
        if project:
            q += " WHERE project=?"
            args = (project,)
        return self.conn.execute(q + " ORDER BY project, seq", args).fetchall()

    def gate_open(self, project, seq, by_role):
        """经理放行某个阶段：它变 active；同一项目里它后面的阶段一律 locked"""
        if not self._can_control():
            raise PermissionError("只有管理者能放行阶段：%s" % by_role)
        rows = list(self.stages(project))
        if not any(r[1] == seq for r in rows):
            raise ValueError("没有这个阶段：%s#%d" % (project, seq))
        for p, s, name, role, state in rows:
            new = "active" if s == seq else ("locked" if s > seq else state)
            self.conn.execute("UPDATE stage SET state=?, updated_at=? WHERE project=? AND seq=?",
                              (new, now_ts(), p, s))
        self.conn.commit()
        self.send(by_role, None, "default", "阶段", "【放行】%s 第 %d 步：%s" % (project, seq, self.stage_name(project, seq)))
        return "active"

    def stage_name(self, project, seq):
        r = self.conn.execute("SELECT name FROM stage WHERE project=? AND seq=?", (project, seq)).fetchone()
        return r[0] if r else "?"

    def gate_done(self, project, seq, by_role):
        """阶段收工：必须有该阶段的**格式合格的交付报告**（feature 里记着 P#N）才允许"""
        feat = "%s#%d" % (project, seq)
        # 走视图查（经理读不到 msg 表本身 —— 库拦得对，这里就不能直查表；见 P 记的那条规矩）
        n = self.conn.execute("SELECT COUNT(*) FROM v_msg WHERE feature=? AND topic LIKE '报告%'", (feat,)).fetchone()[0]
        if not n:
            raise RuntimeError("%s 第 %d 步还没有合格报告（先 run report），不放行下一步" % (project, seq))
        if not self._can_control():
            raise PermissionError("只有管理者能判定阶段完成：%s" % by_role)
        self.conn.execute("UPDATE stage SET state='done', updated_at=? WHERE project=? AND seq=?",
                          (now_ts(), project, seq))
        self.conn.commit()
        return "done"

    def blocked_reason(self, role):
        """这个角色现在能不能收到活：它所在项目里，阶段状态是 locked 就不行"""
        rows = self.stages()
        for p, s, name, r, state in rows:
            if r == role and state == "locked":
                return "%s 第 %d 步（%s）还没放行" % (p, s, name)
        return None

    def report(self, project, seq, from_role, body):
        """按固定格式交活：缺字段直接拒绝（格式 = 做了什么/证据/判据/依赖）"""
        missing = [f for f in self.REPORT_FIELDS if (f + ":") not in body and (f + "：") not in body]
        if missing:
            raise ValueError("交付格式不合格，缺：%s（格式见 README）" % "、".join(missing))
        feat = "%s#%d" % (project, seq)
        mid = self.send(from_role, None, "default", "报告 %s" % feat, body, feature=feat)
        return mid

    def deliver(self, role, text, force=False):
        """把一段文本安全送进该角色的会话（多行也不怕：load-buffer + paste-buffer + Enter）"""
        p = self.is_paused(role)
        if p and not force:
            raise RuntimeError("已暂停（%s），不投递：%s —— 管理者用 start 恢复" % (p, role))
        b = self.blocked_reason(role)
        if b and not force:
            raise RuntimeError("阶段没放行，不投递：%s（%s）—— 经理用 gate-open 放行" % (role, b))
        sess = self.tmux_session(role)
        if subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode != 0:
            raise RuntimeError("角色 %s 没有会话（先 spawn）" % role)
        buf = "rc%d" % now_ts()
        subprocess.run(["tmux", "load-buffer", "-b", buf, "-"], input=text.encode("utf-8"), check=True)
        subprocess.run(["tmux", "paste-buffer", "-b", buf, "-t", sess], check=True)
        subprocess.run(["tmux", "send-keys", "-t", sess, "Enter"], check=True)
        subprocess.run(["tmux", "delete-buffer", "-b", buf], check=True)
        return sess

    def capture(self, role, n=1000):
        """看这个角色会话最近的输出（缓冲默认 1000 行）"""
        sess = self.tmux_session(role)
        p = subprocess.run(["tmux", "capture-pane", "-p", "-S", "-%d" % n, "-t", sess],
                           capture_output=True, text=True)
        return p.stdout

    def init(self, owner="owner.me"):
        """把一套系统建起来：库表 + 经理 + 本场景的三个角色（幂等，可反复跑）"""
        self.init_owner(owner)
        for full, title in [("pipeline.author", "功能创造者"), ("pipeline.renderer", "渲染者"),
                            ("pipeline.tester", "测试者")]:
            self.conn.execute("INSERT OR REPLACE INTO role(full_name,scene,name,title,created_at) VALUES(?,?,?,?,?)",
                              (full, full.split(".")[0], full.split(".")[1], title, now_ts()))
        self.conn.commit()
        return [r[0] for r in self.conn.execute("SELECT full_name FROM role ORDER BY full_name")]

    def rebuild(self):
        """从 talk/*.md 重建库（**文本是权威源**：换机器、库丢了都靠这一步恢复）
        日志格式（每块）：[时间] 谁 → 谁 | 全体? 是/否 | 话题:x | 必读:是/否 | #id ／ 缩进正文 ／ ↳ 回复 [时间] 谁: …"""
        self.conn.execute("DELETE FROM reply")
        self.conn.execute("DELETE FROM msg")
        self.conn.commit()
        n = r = 0
        files = sorted(f for f in os.listdir(TALK_DIR)) if os.path.isdir(TALK_DIR) else []
        for fn in files:
            if not fn.endswith(".md"):
                continue
            kind, to_file, from_file = "default", None, None
            m2 = re.match(r"\d{4}-\d{2}-\d{2}-private-(.+?)__(.+?)\.md$", fn)
            if m2:
                kind, from_file, to_file = "private", m2.group(1), m2.group(2)
            elif re.match(r"\d{4}-\d{2}-\d{2}-broadcast\.md$", fn):
                kind = "broadcast"
            cur = None
            path = os.path.join(TALK_DIR, fn)
            for line in open(path, encoding="utf-8").read().splitlines():
                h = re.match(r"^\[([\d\-: ]+)\] (.+?) → (.+?) \| 全体\? (\S+) \| 话题:(\S*) \| 必读:(\S+) \| #(\d+)$", line)
                if h:
                    ts = int(time.mktime(time.strptime(h.group(1), "%Y-%m-%d %H:%M:%S")))
                    to_role = None if h.group(3) in ("全体", "") else h.group(3)
                    if to_role is None and to_file:
                        to_role = None
                    k = "broadcast" if h.group(4) == "是" else kind
                    cur = int(h.group(7))
                    self.conn.execute(
                        "INSERT OR REPLACE INTO msg(id,kind,from_role,to_role,topic,body,created_at,"
                        "must_reply,feature,file_path) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (cur, k, h.group(2), to_role, h.group(5), "", ts,
                         1 if h.group(6) == "是" else 0, None, fn))
                    n += 1
                    continue
                rp = re.match(r"^\s+↳ 回复 \[([\d\-: ]+)\] (.+?): (.*)$", line)
                if rp and cur:
                    ts = int(time.mktime(time.strptime(rp.group(1), "%Y-%m-%d %H:%M:%S")))
                    self.conn.execute("INSERT INTO reply(msg_id,from_role,body,created_at) VALUES(?,?,?,?)",
                                      (cur, rp.group(2), rp.group(3), ts))
                    r += 1
                    continue
                if line.startswith("    ") and cur is not None:
                    row = self.conn.execute("SELECT body FROM msg WHERE id=?", (cur,)).fetchone()
                    nb = ((row[0] + "\n") if (row and row[0]) else "") + line.strip()
                    self.conn.execute("UPDATE msg SET body=? WHERE id=?", (nb, cur))
        self.conn.commit()
        return n, r

    def watch(self, poll=1.0, once=False, since=None):
        """实时跟随：新消息一出现就打印（他本人＝带 🔒 的私信也看得到；带 --role 就是那个角色有权看的）
        公开频道刷新 / pocket 的频道面板就跑这一条。游标按 **id** 走（时间戳是秒级的，会重复刷同一条）。"""
        last = self.conn.execute("SELECT COALESCE(MAX(id),0) FROM v_msg").fetchone()[0]
        if since is not None:
            last = since
        while True:
            rows = self.conn.execute(
                "SELECT id,kind,from_role,to_role,topic,body,created_at,must_reply FROM v_msg"
                " WHERE id > ? ORDER BY id", (last,)).fetchall()
            for r in rows:
                tag = {"private": "🔒", "broadcast": "📢", "default": "· "}[r[1]]
                first = (r[5] or "").splitlines()[0][:90] if r[5] else ""
                print("%s#%-3d [%s] %-22s → %-22s | %-12s | %s" % (
                    tag, r[0], fmt(r[6]), r[2], r[3] or "全体", r[4] or "-", first), flush=True)
            if rows:
                last = max(r[0] for r in rows)
            if once:
                return
            time.sleep(poll)

    def mark_seen(self, msg_id, role):
        self.conn.execute("INSERT OR REPLACE INTO seen(msg_id, role, seen_at) VALUES(?,?,?)",
                          (msg_id, role, now_ts()))
        self.conn.commit()

    # ---------- 读 ----------
    def inbox(self, role=None):
        """等我回的：广播 / 私信 / 明确标了必读的；default 只是"谁都可见的记录"，不算待办"""
        role = role or self.role
        rows = self.conn.execute(
            "SELECT m.id, m.kind, m.from_role, m.to_role, m.topic, m.must_reply, m.created_at FROM v_msg m"
            " WHERE (m.kind IN ('broadcast','private') OR m.must_reply = 1)"
            "   AND (m.kind != 'private' OR m.to_role = ?)"
            "   AND NOT EXISTS (SELECT 1 FROM reply r WHERE r.msg_id = m.id AND r.from_role = ?)"
            " ORDER BY m.must_reply DESC, m.created_at", (role, role)).fetchall()
        return rows

    def search(self, q, role=None):
        like = "%" + q + "%"
        return self.conn.execute(
            "SELECT id, kind, from_role, to_role, topic, body, created_at FROM v_msg"
            " WHERE topic LIKE ? OR body LIKE ? ORDER BY created_at", (like, like)).fetchall()

    def visible_files(self, role=None):
        """这个角色有权读的文本日志文件（私信只给收发双方的专属文件）"""
        role = role or self.role
        if self.admin or self._has("msg:all", "read"):
            return sorted(os.listdir(TALK_DIR)) if os.path.isdir(TALK_DIR) else []
        out = []
        for f in sorted(os.listdir(TALK_DIR)) if os.path.isdir(TALK_DIR) else []:
            if "-private-" in f:
                pair = f.split("-private-", 1)[1][:-3]
                a, _, b = pair.partition("__")
                if role in (a, b):
                    out.append(f)
            else:
                out.append(f)
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["role-add", "perm-add", "send", "reply", "inbox", "search",
                                    "files", "selftest", "roles", "board", "tail", "spawn", "deliver",
                                    "capture", "seen", "init-owner", "pause", "start", "status",
                                    "stage-add", "gate", "gate-open", "gate-done", "report", "blocked",
                                    "watch", "init", "rebuild"])
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--by", default=None)
    ap.add_argument("--why", default="")
    ap.add_argument("--hard", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--project", default=None)
    ap.add_argument("--seq", type=int, default=0)
    ap.add_argument("--name", default=None)
    ap.add_argument("--role", default=None)
    ap.add_argument("--profile", default=None)
    ap.add_argument("--lines", type=int, default=1000)
    ap.add_argument("--text", default="")
    ap.add_argument("--full", default=None)
    ap.add_argument("--title", default="")
    ap.add_argument("--scope", default=None)
    ap.add_argument("--action", default="read")
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--to", dest="to", default=None)
    ap.add_argument("--kind", default="default")
    ap.add_argument("--topic", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--must-reply", action="store_true")
    ap.add_argument("--q", default="")
    a = ap.parse_args()

    if a.cmd == "selftest":
        sys.path.insert(0, HERE)
        import talk_selftest
        return talk_selftest.run()

    # 控制类命令要**以"下令的人"的身份连库**（--by，默认 owner.me），
    # 不能拿 --role（那是被管的对象/阶段归属）去连 —— 否则会被自己的权限检查拦下（踩过两次）
    if a.cmd in ("pause", "start", "stage-add", "gate-open", "gate-done"):
        t = Talk(a.by or "owner.me")
    elif a.cmd == "report":
        t = Talk(a.frm or a.role)          # 报告是"角色自己"交的活
    else:
        t = Talk(a.role)
    if a.cmd == "role-add":
        scene, _, name = a.full.partition(".")
        t.conn.execute("INSERT OR REPLACE INTO role(full_name,scene,name,title,created_at) VALUES(?,?,?,?,?)",
                       (a.full, scene, name, a.title, now_ts()))
        t.conn.commit()
        print("角色已登记：%s（%s）" % (a.full, a.title))
    elif a.cmd == "perm-add":
        t.conn.execute("INSERT OR REPLACE INTO perm(full_name,scope,action,created_at) VALUES(?,?,?,?)",
                       (a.role, a.scope, a.action, now_ts()))
        t.conn.commit()
        print("权限已加：%s %s/%s" % (a.role, a.scope, a.action))
    elif a.cmd == "send":
        mid = t.send(a.frm, a.to, a.kind, a.topic, a.body, a.must_reply)
        print("#%d 已记入 %s" % (mid, log_path(a.kind, a.frm, a.to)))
    elif a.cmd == "reply":
        t.reply(a.id, a.frm, a.body)
        print("#%d 已回复" % a.id)
    elif a.cmd == "inbox":
        for r in t.inbox(a.role):
            print("#%d [%s] %s→%s 话题:%s 必读:%s 发:%s" % (
                r[0], r[1], r[2], r[3] or "全体", r[4], "是" if r[5] else "否", fmt(r[6])))
    elif a.cmd == "search":
        for r in t.search(a.q, a.role):
            print("#%d [%s] %s→%s 话题:%s | %s" % (r[0], r[1], r[2], r[3] or "全体", r[4], (r[5] or "")[:40]))
    elif a.cmd == "files":
        for f in t.visible_files(a.role):
            print(f)
    elif a.cmd == "roles":
        for r in t.conn.execute("SELECT full_name,title FROM role ORDER BY full_name"):
            print("%s\t%s" % r)
    elif a.cmd == "board":
        t.board(a.lines, a.role)
    elif a.cmd == "tail":
        t.tail(a.lines)
    elif a.cmd == "spawn":
        sess, created = t.spawn(a.role, a.profile)
        print("会话 %s：%s" % (sess, "已开" if created else "本来就在跑（幂等，没动它）"))
    elif a.cmd == "stage-add":
        t.stage_add(a.project, a.seq, a.name or ("第%d步" % a.seq), a.role)
        print("阶段已登记：%s#%d %s → %s（初始 locked）" % (a.project, a.seq, a.name, a.role))
    elif a.cmd == "gate":
        rows = t.stages(a.project)
        if not rows:
            print("（还没有阶段）")
        for p, s, name, role, state in rows:
            mark = {"active": "◀ 进行中", "done": "✔ 已完成", "locked": "🔒 未放行"}.get(state, state)
            print("%-24s #%d %-14s %-24s %s" % (p, s, name, role, mark))
    elif a.cmd == "gate-open":
        t.gate_open(a.project, a.seq, a.by or "owner.me")
        print("已放行：%s 第 %d 步（后面的仍锁着）" % (a.project, a.seq))
    elif a.cmd == "gate-done":
        t.gate_done(a.project, a.seq, a.by or "owner.me")
        print("已判定完成：%s 第 %d 步" % (a.project, a.seq))
    elif a.cmd == "report":
        body = a.text or sys.stdin.read()
        mid = t.report(a.project, a.seq, a.frm or a.role, body)
        print("#%d 报告已记（%s#%d）" % (mid, a.project, a.seq))
    elif a.cmd == "blocked":
        b = t.blocked_reason(a.role)
        print("%s：%s" % (a.role, b or "可以收活（没被阶段卡住）"))
    elif a.cmd == "watch":
        t.watch(a.poll, a.once)
    elif a.cmd == "init":
        roles = t.init(a.full or "owner.me")
        print("已建好：库表 + 经理 + 角色 → %s" % "、".join(roles))
    elif a.cmd == "rebuild":
        n, r = t.rebuild()
        print("从 talk/*.md 重建完成：消息 %d 条、回复 %d 条" % (n, r))
    elif a.cmd == "deliver":
        body = a.text or sys.stdin.read()
        if a.id:
            body = "【对话 #%d】%s" % (a.id, body)
        sess = t.deliver(a.role, body)
        print("已投递到 %s" % sess)
    elif a.cmd == "capture":
        sys.stdout.write(t.capture(a.role, a.lines))
    elif a.cmd == "seen":
        t.mark_seen(a.id, a.role)
        print("#%d 已标已读（%s）" % (a.id, a.role))
    elif a.cmd == "init-owner":
        full = t.init_owner(a.full or "owner.me")
        print("经理角色已建：%s（room:control 写 + 名册管理；**不给 msg:all**——管流程但看不到私信）" % full)
    elif a.cmd == "pause":
        by = a.by or "owner.me"
        target = a.role or "全体"
        scope = "room" if (target in ("全体", "all", "room", "")) else "role:" + target
        t.set_state(scope, "paused", by, a.why)
        detail = ""
        if scope != "room":
            alive = t.stop_role(target, a.hard)
            detail = "（会话%s）" % ("已收掉" if (alive and a.hard) else ("已发 /stop" if alive else "本来就没跑"))
        print("已暂停：%s%s" % (target, detail))
    elif a.cmd == "start":
        by = a.by or "owner.me"
        target = a.role or "全体"
        scope = "room" if (target in ("全体", "all", "room", "")) else "role:" + target
        t.set_state(scope, "running", by, a.why)
        detail = ""
        if scope != "room":
            sess = t.tmux_session(target)
            if subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode != 0:
                t.spawn(target, a.profile)
                detail = "（已开会话 %s）" % sess
            else:
                detail = "（会话本来就在 %s）" % sess
        print("已恢复：%s%s" % (target, detail))
    elif a.cmd == "status":
        t.status()
    return 0


if __name__ == "__main__":
    sys.exit(main())
