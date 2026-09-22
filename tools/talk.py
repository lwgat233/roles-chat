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
import sqlite3
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
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
        self.admin = self._is_admin()
        if role:
            self._install_guard()
        else:
            # 管理员/看板连接也要有同名视图（"看全部"就是条件恒真），
            # 否则 board 这种无 --role 的调用会撞 no such table: v_msg
            self.conn.execute("DROP VIEW IF EXISTS v_msg")
            self.conn.execute("CREATE TEMP VIEW v_msg AS SELECT * FROM msg")

    # ---------- 权限 ----------
    def _is_admin(self):
        if not self.role:
            return True
        r = self.conn.execute(
            "SELECT 1 FROM perm WHERE full_name=? AND scope='table:role' AND action='write'",
            (self.role,)).fetchone()
        return bool(r) or self.role == "system.admin"

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

        admin = self.admin

        def auth(action, arg1, arg2, dbname, source):
            if action == sqlite3.SQLITE_READ:
                if arg1 == "msg" and source != "v_msg" and not all_read and not admin:
                    return sqlite3.SQLITE_DENY        # 直接读 msg 表：不给
                return sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                if arg1 in ("role", "perm") and not admin:
                    return sqlite3.SQLITE_DENY        # 名册与权限：只有管理员能改
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

    # ---------- 投递到角色的 tmux 会话 ----------
    @staticmethod
    def tmux_session(role):
        return "role-" + role.replace(".", "-")

    def spawn(self, role, profile=None, cmd=None):
        """给角色开一个 tmux 会话（他自己另开 tmux 看）"""
        sess = self.tmux_session(role)
        run = cmd or ("hermes -p %s chat" % profile if profile else "hermes chat")
        subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-x", "120", "-y", "40", run], check=True)
        return sess

    def deliver(self, role, text):
        """把一段文本安全送进该角色的会话（多行也不怕：load-buffer + paste-buffer + Enter）"""
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

    def mark_seen(self, msg_id, role):
        self.conn.execute("INSERT OR REPLACE INTO seen(msg_id, role, seen_at) VALUES(?,?,?)",
                          (msg_id, role, now_ts()))
        self.conn.commit()

    # ---------- 读 ----------
    def inbox(self, role=None):
        role = role or self.role
        rows = self.conn.execute(
            "SELECT m.id, m.kind, m.from_role, m.to_role, m.topic, m.must_reply, m.created_at FROM v_msg m"
            " WHERE (m.to_role = ? OR m.kind='broadcast' OR m.kind='default')"
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
                                    "capture", "seen"])
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
        sess = t.spawn(a.role, a.profile)
        print("已开会话：%s（另开一个 tmux 窗口 `tmux attach -t %s` 就能看它）" % (sess, sess))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
