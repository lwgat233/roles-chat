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
import json
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
-- 会话台账：角色会话 + "只对我负责"的单独会话（面板的"历史记录"就查它）
CREATE TABLE IF NOT EXISTS session(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, name TEXT, role TEXT, tmux TEXT, hermes TEXT,
  created_at INTEGER, last_used INTEGER, note TEXT);
-- 键值设置（qq 目标、女仆频道等）
CREATE TABLE IF NOT EXISTS setting(k TEXT PRIMARY KEY, v TEXT, updated_at INTEGER);
-- 该不该通知他（角色标注）+ 推没推过（女仆中转用）
CREATE TABLE IF NOT EXISTS notify(msg_id INTEGER PRIMARY KEY, marked_at INTEGER, pushed_at INTEGER, channel TEXT);
-- 唤醒：一条消息该动谁（私信/@点名=直接 approved；广播=候选 pending，等经理放行/跳过）
-- 中转站的投递台账：哪条消息投给了谁、什么时候、成没成
CREATE TABLE IF NOT EXISTS pref(k TEXT PRIMARY KEY, v TEXT);   -- 中转站小状态（游标等）
CREATE TABLE IF NOT EXISTS delivery(
  msg_id INTEGER, role TEXT, at INTEGER, ok INTEGER, note TEXT, PRIMARY KEY(msg_id, role));
CREATE TABLE IF NOT EXISTS wake(
  msg_id INTEGER, role TEXT, state TEXT, by_role TEXT, why TEXT, at INTEGER, delivered_at INTEGER,
  PRIMARY KEY(msg_id, role));
-- 接入表（**由经理维护**）：哪个频道（=场景）里谁可以收到消息；不在表里就不打扰他
CREATE TABLE IF NOT EXISTS member(
  channel TEXT, role TEXT, added_by TEXT, at INTEGER, PRIMARY KEY(channel, role));
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


TMUX_SESSION = "roles"          # 只用一个 tmux 会话；每个角色是里面的一个窗口（省后台、切换不用敲命令）


def hermes_bin():
    """找到 hermes 可执行文件：非交互环境下 PATH 里没有它，得自己找"""
    import shutil
    for c in (shutil.which("hermes"),
              os.path.expanduser("~/.local/bin/hermes"),
              os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes"),
              "/usr/local/bin/hermes"):
        if c and os.path.exists(c):
            return c
    return "hermes"


HERMES_BIN = hermes_bin()


def win_name(role):
    """角色 → 窗口名：home.maid → home-maid"""
    return str(role or "").replace(".", "-")


def ensure_tmux_session():
    if subprocess.run(["tmux", "has-session", "-t", TMUX_SESSION], capture_output=True).returncode != 0:
        subprocess.run(["tmux", "new-session", "-d", "-s", TMUX_SESSION], check=True)


def tmux_windows():
    r = subprocess.run(["tmux", "list-windows", "-t", TMUX_SESSION, "-F", "#{window_name}"],
                       capture_output=True, text=True)
    return [x.strip() for x in r.stdout.split("\n") if x.strip()] if r.returncode == 0 else []


def migrate_old_sessions():
    """把"一个角色一个 tmux 会话"的窗口搬进 roles（进程不重启、上下文不丢），旧会话随之消失"""
    r = subprocess.run(["tmux", "ls", "-F", "#{session_name}"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    moved = []
    for sess in [x.strip() for x in r.stdout.split("\n") if x.strip()]:
        if not sess.startswith("role-"):
            continue
        ensure_tmux_session()
        win = sess[len("role-"):]
        if subprocess.run(["tmux", "move-window", "-s", sess + ":0", "-t", TMUX_SESSION + ":"],
                          capture_output=True).returncode != 0:
            continue
        subprocess.run(["tmux", "rename-window", "-t", TMUX_SESSION + ":", win], capture_output=True)
        moved.append("%s → %s:%s" % (sess, TMUX_SESSION, win))
    return moved


class Talk:
    def __init__(self, role=None, path=DB):
        self.role = role
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        # 老库补列（CREATE TABLE IF NOT EXISTS 不会加列）：角色标签、消息的广播范围
        for sql in ("CREATE TABLE IF NOT EXISTS pref(k TEXT PRIMARY KEY, v TEXT)",
                   "ALTER TABLE notify ADD COLUMN answered_at INTEGER",
                   "ALTER TABLE role ADD COLUMN tags TEXT",
                    "ALTER TABLE msg ADD COLUMN scope TEXT"):
            try:
                self.conn.execute(sql)
            except sqlite3.Error:
                pass
        self.conn.commit()
        # 身份（用户 2026-09-22 定）：
        #   me        = 本人（用户）：最高权限，看全部含私信，能直达任何角色
        #   owner.me  = 经理（助手，代他指挥角色）：管流程，但**看不到私信内容**
        self.admin = (role is None) or (role == "me") or self._has("msg:all", "read")   # 看全部内容（含私信）
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
        all_read = (role == "me") or self._has("msg:all", "read")   # 本人(me)看全部含私信
        # 按身份建 TEMP 视图：这条 SQL 就是"谁能看见什么"的唯一出处
        cond = "from_role = %s OR kind = 'default' OR kind = 'broadcast' OR (kind = 'private' AND to_role = %s)" % (
            self._q(role), self._q(role))
        if all_read:
            cond = "1=1"
        self.conn.execute("DROP VIEW IF EXISTS v_msg")
        self.conn.execute("CREATE TEMP VIEW v_msg AS SELECT * FROM msg WHERE " + cond)

        admin = self.manage
        # 写权限：**治理表**只有经理能改；其余表（发言/标注/台账这类）放行。
        # 这么分是为了不再"每加一张新表就报 not authorized"（member/wake 都踩过），
        # 而真正要紧的内容隔离在**读**那一侧（msg 只能走视图）。
        GOVERN = ("role", "perm", "room", "stage", "member")

        def auth(action, arg1, arg2, dbname, source):
            if action == sqlite3.SQLITE_READ:
                # 只有"他本人"（不带角色的连接，也就是看板/命令行）或明确拿了 msg:all/read 的角色能直读 msg；
                # **经理虽有管理权，也不该知道私信内容** —— 它同样只能走按身份过滤的视图（用户 2026-09-22 定）
                if arg1 == "msg" and source != "v_msg" and not all_read and role is not None:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                if arg1 in GOVERN and not admin:
                    return sqlite3.SQLITE_DENY        # 治理表：只有经理（= 有管理权的角色）
                return sqlite3.SQLITE_OK              # 其余表放行（发言、标注、台账…）
            return sqlite3.SQLITE_OK

        self.conn.set_authorizer(auth)

    @staticmethod
    def _q(s):
        return "'" + str(s).replace("'", "''") + "'"

    # ---------- 写 ----------
    def send(self, from_role, to_role, kind, topic, body, must_reply=False, feature=None, scope=None):
        if self.role and self.role != from_role:
            raise PermissionError("我是 %s，不能替 %s 发言" % (self.role, from_role))
        ts = now_ts()
        path = log_path(kind, from_role, to_role)
        os.makedirs(TALK_DIR, exist_ok=True)
        cur = self.conn.execute(
            "INSERT INTO msg(kind,from_role,to_role,topic,body,created_at,must_reply,feature,file_path,scope)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (kind, from_role, to_role, topic, body, ts, 1 if must_reply else 0, feature,
             os.path.relpath(path, ROOT), scope))
        mid = cur.lastrowid
        self.conn.commit()
        # 发完就把"谁该动"摊开：私信/@点名 → 直接唤醒；广播 → 候选，等经理放行（见 wake_seed）
        # 注意：**不要静默吞异常** —— 吞了就会出现"消息发了但没有唤醒记录"这种查不出的怪事
        self.wake_seed(mid)
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
        sess = self.target(role)
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

    # ---------- 面板要的料：角色（按场景分组）+ 会话历史 + "只对我负责"的单独会话 ----------

    def _remember(self, kind, name, role, tmux, hermes, note=""):
        r = self.conn.execute("SELECT id FROM session WHERE tmux=?", (tmux,)).fetchone()
        if r:
            self.conn.execute("UPDATE session SET last_used=? WHERE id=?", (now_ts(), r[0]))
        else:
            self.conn.execute(
                "INSERT INTO session(kind,name,role,tmux,hermes,created_at,last_used,note)"
                " VALUES(?,?,?,?,?,?,?,?)", (kind, name, role, tmux, hermes, now_ts(), now_ts(), note))
        self.conn.commit()

    @staticmethod
    def _alive(tmux):
        return subprocess.run(["tmux", "has-session", "-t", tmux], capture_output=True).returncode == 0

    def roles_json(self):
        """面板的角色列表：**按场景分组**，每个角色带 名称/描述(title)/状态/**谁在线**/**能接入哪些频道**/欠多少回复"""
        ch = {}
        for channel, role, *_ in self.member_list():
            ch.setdefault(channel, []).append(role)
        ch_by_role = {}
        for channel, roles in ch.items():
            for r in roles:
                ch_by_role.setdefault(r, []).append(channel)
        scenes = {}
        for full, scene, name, title, tags in self.conn.execute(
                "SELECT full_name,scene,name,title,COALESCE(tags,'') FROM role ORDER BY scene, full_name"):
            alive = self.role_online(full)
            scenes.setdefault(scene, []).append({
                "full_name": full, "name": name, "title": title or "", "tags": (tags or ""),
                "state": self.state_of("role:" + full),
                "session": alive,
                "online": alive and self.state_of("role:" + full) != "paused",
                "channels": sorted(ch_by_role.get(full, [])),
                "pending": len(self.inbox(full)) if self.role is None else 0,
            })
        return {"scenes": [{"scene": s, "roles": v} for s, v in sorted(scenes.items())],
                "channels": {c: sorted(v) for c, v in sorted(ch.items())}}

    def sessions_json(self, limit=20):
        """历史记录：他最近用过的会话（角色会话 + 单独会话），点一下就能跳回去"""
        out = []
        for r in self.conn.execute(
                "SELECT id,kind,name,role,tmux,hermes,created_at,last_used,note FROM session"
                " ORDER BY last_used DESC LIMIT ?", (limit,)).fetchall():
            out.append({"id": r[0], "kind": r[1], "name": r[2], "role": r[3], "tmux": r[4],
                        "hermes": r[5], "created_at": r[6], "last_used": r[7], "note": r[8] or "",
                        "alive": self._alive(r[4]) if r[4] else False})
        return {"sessions": out}

    def solo(self, name=None, launch=None):
        """**抛离角色体系**的单独会话：只对"我"负责，不参与角色对话、不写 talk 日志、没有角色身份。
        （面板上那个"开一个新对话"的入口就是它）"""
        name = name or ("solo%d" % now_ts())
        tmux = "solo-" + name
        hermes = "solo-" + name
        created = False
        if not self._alive(tmux):
            run = launch or ("hermes chat -c %s --create-if-missing" % hermes)
            subprocess.run(["tmux", "new-session", "-d", "-s", tmux, "-x", "120", "-y", "40", run], check=True)
            created = True
        self._remember("solo", name, None, tmux, hermes, "只对我负责（不属于任何角色）")
        return tmux, created

    def spawn(self, role, profile=None, launch=None):
        """给角色在 roles 会话里开一个**窗口**（幂等）；一个 tmux 装所有角色，不再一个角色一个会话"""
        self._ensure_ready()          # 还没搭就先搭：没有搭建也可以拉起来时搭
        win = win_name(role)
        ensure_tmux_session()
        sess = "%s:%s" % (TMUX_SESSION, win)
        if win in tmux_windows():
            return sess, False
        # Hermes 侧同一个会话续着走：-c <角色全名> --create-if-missing
        run = launch or ("hermes %s chat -c %s --create-if-missing" % (
            ("-p " + profile) if profile else "", role))
        subprocess.run(["tmux", "new-window", "-t", TMUX_SESSION + ":", "-n", win, run], check=True)
        self._remember("role", role, role, sess, role, "角色窗口（roles 会话内，幂等）")
        return sess, True

    # ---------- 项目阶段（经理闸门）----------
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

    def doctor(self):
        """自检：库就绪吗 / 每个角色是不是真有窗口 / 中转站活着吗（客户端每次启动都问一次）"""
        out = {"db": os.path.exists(DB), "tmux": subprocess.run(
            ["tmux", "has-session", "-t", TMUX_SESSION], capture_output=True).returncode == 0,
            "roles": [], "missing": []}
        try:
            rows = [r[0] for r in self.conn.execute("SELECT full_name FROM role ORDER BY full_name")]
        except Exception:
            rows = []
        out["roles_total"] = len([r for r in rows if r not in ("owner.me", "me")])
        for full in rows:
            if full in ("owner.me", "me"):
                continue
            ok = self.role_online(full)
            out["roles"].append({"role": full, "session": ok})
            if not ok:
                out["missing"].append(full)
        r = subprocess.run(["systemctl", "--user", "is-active", "roles-relay.service"],
                           capture_output=True, text=True)
        out["relay"] = (r.stdout or "").strip() or "unknown"
        return out

    def _ensure_ready(self):
        """服务端还没搭？就地搭起来 —— 客户端『拉起他』时也会走到这儿"""
        try:
            if os.path.exists(DB) and self.conn.execute("SELECT COUNT(*) FROM role").fetchone()[0] > 0:
                return False
        except Exception:
            pass
        # 本机什么都没有？从 GitHub 拉一份再装（换机器就用这条路）
        dest = os.environ.get("ROLES_CHAT_HOME") or os.path.join(os.path.expanduser("~"), "roles-chat")
        repo = os.environ.get("ROLES_CHAT_REPO", "https://github.com/lwgat233/roles-chat.git")
        bs = os.path.join(ROOT, "tools", "bootstrap.sh")
        if os.path.exists(bs):
            subprocess.run(["bash", bs, ROOT], capture_output=True)
            return True
        if not os.path.exists(os.path.join(ROOT, "install.sh")):
            subprocess.run(["git", "clone", repo, dest], capture_output=True)
            sh2 = os.path.join(dest, "install.sh")
            if os.path.exists(sh2):
                subprocess.run(["bash", sh2], cwd=dest, capture_output=True)
                return True
        sh = os.path.join(ROOT, "install.sh")
        if os.path.exists(sh):
            subprocess.run(["bash", sh], cwd=ROOT, capture_output=True)
            return True
        return False

    def target(self, role):
        """这个角色该投到哪：优先 roles:<窗口名>（新），退而用旧的 role-xxx 会话"""
        win = win_name(role)
        if win in tmux_windows():
            return "%s:%s" % (TMUX_SESSION, win)
        old = self.tmux_session(role)
        if subprocess.run(["tmux", "has-session", "-t", old], capture_output=True).returncode == 0:
            return old
        return "%s:%s" % (TMUX_SESSION, win)

    def role_online(self, role):
        """在线 = 他在 roles 里有窗口（或旧的独立会话还活着）"""
        return (win_name(role) in tmux_windows()) or self._alive(self.tmux_session(role))

    def say(self, role, body, topic="私信", kind="private", frm="me"):
        """我(本人)说一句：**记进对话 + 主动投给他**，每条都带来源标签（哪儿发的 + 谁发的 + 编号），
        末尾告诉他用 reply 函数回我（这样回话走正式通道，面板能画成气泡）。
        role 传 全体/ all 时 = 广播：**对每个相关的人各投一份、各存记录**（不靠"文件被改了你自己看"）。
        """
        if str(role) in ("全体", "all", "*"):
            kind = "broadcast"
            mid = self.send(frm, "全体", kind, topic, body)
            rows = [r[0] for r in self.conn.execute(
                "SELECT DISTINCT role FROM member WHERE role NOT IN ('owner.me','me') ORDER BY role").fetchall()]
            if not rows:      # 接入表空 → 退回"全部角色"
                rows = [r[0] for r in self.conn.execute(
                    "SELECT full_name FROM role WHERE full_name NOT IN ('owner.me','me') ORDER BY full_name").fetchall()]
            label = "【频道广播】来自 %s #%d" % (frm, mid)
            out = []
            for who in rows:
                text = "%s\n%s\n\n（回我用：python3 tools/talk.py reply --id %d --from %s --body \"你的话\"）" % (
                    label, body, mid, who)
                try:
                    self.deliver(who, text)
                    self.conn.execute("INSERT OR REPLACE INTO seen(msg_id,role,seen_at) VALUES(?,?,?)",
                                      (mid, who, now_ts())) if False else None
                    out.append({"role": who, "delivered": True})
                except Exception as e:
                    out.append({"role": who, "delivered": False, "error": str(e)})
            self.conn.commit()
            return {"id": mid, "broadcast": True, "count": len(out), "results": out}

        mid = self.send(frm, role, kind, topic, body)
        label = ("【频道广播】" if kind == "broadcast" else "【私聊】") + "来自 %s #%d" % (frm, mid)
        text = "%s\n%s\n\n（回我用：python3 tools/talk.py reply --id %d --from %s --body \"你的话\"）" % (
            label, body, mid, role)
        try:
            self.deliver(role, text)
            return {"id": mid, "delivered": True, "to": role}
        except Exception as e:
            return {"id": mid, "delivered": False, "error": str(e), "to": role}

    def deliver(self, role, text, force=False):
        """把一段文本安全送进该角色的会话（多行也不怕：load-buffer + paste-buffer + Enter）"""
        p = self.is_paused(role)
        if p and not force:
            raise RuntimeError("已暂停（%s），不投递：%s —— 管理者用 start 恢复" % (p, role))
        b = self.blocked_reason(role)
        if b and not force:
            raise RuntimeError("阶段没放行，不投递：%s（%s）—— 经理用 gate-open 放行" % (role, b))
        sess = self.target(role)
        if subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode != 0:
            raise RuntimeError("角色 %s 没有会话（先 spawn）" % role)
        buf = "rc%d" % now_ts()
        if "\n" in text:
            # 多行：粘贴后隔一下再回车（有的 TUI 会把紧跟粘贴的回车吞掉 → 用户报过"没发送换行符"）
            subprocess.run(["tmux", "load-buffer", "-b", buf, "-"], input=text.encode("utf-8"), check=True)
            subprocess.run(["tmux", "paste-buffer", "-b", buf, "-t", sess], check=True)
            time.sleep(0.25)
            subprocess.run(["tmux", "send-keys", "-t", sess, "Enter"], check=True)
        else:
            # 单行：直接打字再回车，最稳（不经过粘贴缓冲，TUI 一定能收）
            subprocess.run(["tmux", "send-keys", "-t", sess, "-l", text], check=True)
            time.sleep(0.12)
            subprocess.run(["tmux", "send-keys", "-t", sess, "Enter"], check=True)
        subprocess.run(["tmux", "delete-buffer", "-b", buf], check=False)   # 单行分支没建过缓冲区，删失败不算错
        return sess

    def capture(self, role, n=1000):
        """看这个角色会话最近的输出（缓冲默认 1000 行）"""
        sess = self.target(role)
        p = subprocess.run(["tmux", "capture-pane", "-p", "-S", "-%d" % n, "-t", sess],
                           capture_output=True, text=True)
        return p.stdout

    def init(self, owner="owner.me"):
        """把一套系统建起来：库表 + 经理 + 本场景的三个角色（幂等，可反复跑）"""
        self.init_owner(owner)
        for full, title in [("pipeline.author", "功能创造者"), ("pipeline.renderer", "渲染者"),
                            ("pipeline.tester", "测试者"),
                            ("home.maid", "可爱女仆（个人助手：管生活，把要紧的话中转给我）")]:
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

    def since_json(self, after_id=0, limit=200):
        """给面板轮询用：id 大于 after_id 的新消息（面板每隔一两秒问一次，不用长连接）"""
        rows = self.conn.execute(
            "SELECT id,kind,from_role,to_role,topic,body,created_at,must_reply FROM v_msg"
            " WHERE id > ? ORDER BY id LIMIT ?", (after_id, limit)).fetchall()
        return {"last": (rows[-1][0] if rows else after_id), "messages": [
            {"id": r[0], "kind": r[1], "from": r[2], "to": r[3], "topic": r[4],
             "body": r[5], "at": r[6], "must_reply": bool(r[7])} for r in rows]}

    # ---------- 中转站：盯文本/库，按种类把话投给该收的人；并收角色的终端回答 ----------
    KINDS = {"private": "私聊", "default": "定向（他人可见）", "broadcast": "广播"}

    def relay_targets(self, kind, to_role, scope=None):
        """这条该投给谁：私聊/定向 = 那个人；广播 = 接入表里的人（空则全体角色）"""
        if kind in ("private", "default") and to_role and to_role not in ("全体", "all", "*"):
            return [to_role]
        rows = [r[0] for r in self.conn.execute(
            "SELECT DISTINCT role FROM member WHERE role NOT IN ('owner.me','me') ORDER BY role").fetchall()]
        if not rows:
            rows = [r[0] for r in self.conn.execute(
                "SELECT full_name FROM role WHERE full_name NOT IN ('owner.me','me') ORDER BY full_name").fetchall()]
        if scope:
            want = [x.strip() for x in str(scope).split(",") if x.strip()]
            rows = [r for r in rows if r.split(".")[0] in want] or rows
        return rows

    def relay_label(self, kind, frm, mid):
        tag = {"private": "【私聊】", "default": "【定向·他人可见】", "broadcast": "【频道广播】"}.get(kind, "【消息】")
        return "%s来自 %s #%d" % (tag, frm, mid)

    def extract_answer(self, screen):
        """从角色的终端屏幕里抠出他最近一次回答（Hermes 的回答画在 ╭─ ☤ Hermes ─╮ 框里）"""
        lines = str(screen or "").split("\n")
        start = -1
        for i in range(len(lines) - 1, -1, -1):
            if "☤" in lines[i] and "╭" in lines[i]:
                start = i
                break
        if start < 0:
            return ""
        out = []
        for l in lines[start + 1:]:
            if "╰" in l or re.match(r"^[─═]{5,}", l):
                break
            out.append(l.strip("│| "))
        return "\n".join([x for x in out if x]).strip()

    def relay_once(self, cursor=None, deliver=True, collect=True):
        """跑一轮：① 把新消息投给该收的人（带种类标签）② 把角色的终端回答收成记录"""
        cur = cursor if cursor is not None else int(self.state_get("relay_cursor", "0") or 0)
        sent = []
        rows = self.conn.execute(
            "SELECT id,kind,from_role,to_role,scope,body FROM v_msg WHERE id>? AND from_role IN ('me','owner.me')"
            " ORDER BY id", (cur,)).fetchall()
        for mid, kind, frm, to_role, scope, body in rows:
            if not deliver:
                sent.append({"id": mid, "skipped": True})
                continue
            label = self.relay_label(kind, frm, mid)
            for who in self.relay_targets(kind, to_role, scope):
                text = "%s\n%s\n\n（回我用：python3 tools/talk.py reply --id %d --from %s --body \"你的话\"；直接在这里说也行）" % (
                    label, body, mid, who)
                ok = True
                try:
                    self.deliver(who, text)
                except Exception as e:
                    ok = False
                    text = str(e)
                self.conn.execute("INSERT OR REPLACE INTO delivery(msg_id,role,at,ok,note) VALUES(?,?,?,?,?)",
                                  (mid, who, now_ts(), 1 if ok else 0, text[:120] if not ok else ""))
                sent.append({"id": mid, "to": who, "ok": ok})
            cur = max(cur, mid)
        # 收角色的终端回答 → 记成 reply（他不必自己调函数）
        collected = []
        if collect:
            for (full,) in self.conn.execute("SELECT full_name FROM role WHERE full_name NOT IN ('owner.me','me')"):
                if not self.role_online(full):
                    continue
                try:
                    screen = tmux_out = subprocess.run(["tmux", "capture-pane", "-p", "-t", self.target(full)],
                                                       capture_output=True, text=True).stdout
                except Exception:
                    continue
                ans = self.extract_answer(screen)
                if not ans:
                    continue
                key = "said_" + full
                if ans == (self.state_get(key, "") or ""):
                    continue
                self.state_set(key, ans)
                last = self.conn.execute(
                    "SELECT id FROM v_msg WHERE (to_role=? OR from_role=?) AND from_role IN ('me','owner.me')"
                    " ORDER BY id DESC LIMIT 1", (full, full)).fetchone()
                mid = last[0] if last else 0
                try:
                    self.conn.execute("INSERT INTO reply(msg_id,from_role,body,created_at) VALUES(?,?,?,?)",
                                      (mid, full, ans, now_ts()))
                    collected.append({"role": full, "reply_to": mid})
                except Exception:
                    pass
        self.conn.commit()
        self.state_set("relay_cursor", str(cur))
        return {"cursor": cur, "delivered": sent, "collected": collected}

    # ---------- 上达：要本人拍板/知道的事，一律由女仆带话到 QQ ----------
    TELL_KINDS = ("授权", "选择", "收工", "卡住", "告知")

    def tell_user(self, kind, what, options="", frm="owner.me", topic=None, push=True):
        """**由女仆把话带给本人**（QQ）：授权 / 选择 / 收工 / 卡住 都走这条。
        女仆不授权、不替他决定 —— 她只负责"带到"（他答了再由女仆转回去）。
        """
        kind = kind if kind in self.TELL_KINDS else "告知"
        body = str(what or "")
        if options:
            body += "\n可选项：" + str(options)
        top = topic or kind
        mid = self.send(frm, "home.maid", "private", "【%s】%s" % (kind, top), body)
        self.mark_notify(mid)
        pushed = None
        if push:
            try:
                pushed = self.relay(dry=False)
            except Exception as e:
                pushed = "推失败：%s" % e
        return {"id": mid, "kind": kind, "pushed": pushed}

    def ask(self, from_role, what, options="", topic="要你授权", target="home.maid"):
        """角色要授权/拍板：先落一条给他的对话（默认发给可爱女仆），标上"要向他知道"，然后中转。
        —— 授权/审批这条路也归女仆：她收、她整理、她推给他，他答完她再转回去（用户 2026-09-22 定）。"""
        sc = self.conn.execute("SELECT scene FROM role WHERE full_name=?", (from_role,)).fetchone()
        who = "%s（场景 %s / 会话 %s）" % (from_role, sc[0] if sc else "-", self.tmux_session(from_role))
        body = "【要授权/拍板】来自 " + who + "\n" + what + ("" if not options else "\n可选项：" + options)
        mid = self.send(from_role, target, "private", topic, body)
        self.mark_notify(mid)
        return mid

    def answer(self, ask_id, text, by_role="owner.me"):
        """他答了（从 QQ 或命令行）：记成他发的消息回给提问的人，并把这问标成已答"""
        r = self.conn.execute("SELECT from_role,topic FROM msg WHERE id=?", (ask_id,)).fetchone()
        if not r:
            raise ValueError("没有这条提问：%s" % ask_id)
        to_role, topic = r[0], r[1]
        mid = self.send(by_role, to_role, "private", "答复:" + (topic or ""), text)
        self.conn.execute("UPDATE notify SET answered_at=? WHERE msg_id=?", (now_ts(), ask_id))
        self.conn.commit()
        return mid

    def role_del(self, full, by_role="owner.me", force=False):
        """删角色（经理）：role + 权限 + 接入表一起清。owner.me 不许删；会话还在跑要先停或 --force。"""
        if not self._can_control():
            raise PermissionError("只有经理能删角色：%s" % by_role)
        if full == "owner.me":
            raise PermissionError("owner.me 是经理本人，不能删")
        if not self.conn.execute("SELECT 1 FROM role WHERE full_name=?", (full,)).fetchone():
            raise ValueError("没有这个角色：%s" % full)
        if self.role_online(full) and not force:
            raise PermissionError("他的会话还在跑（tmux %s）：先停了他，或加 --force" % self.tmux_session(full))
        perms = self.conn.execute("SELECT COUNT(*) FROM perm WHERE full_name=?", (full,)).fetchone()[0]
        mems = self.conn.execute("SELECT COUNT(*) FROM member WHERE role=?", (full,)).fetchone()[0]
        self.conn.execute("DELETE FROM role WHERE full_name=?", (full,))
        self.conn.execute("DELETE FROM perm WHERE full_name=?", (full,))
        self.conn.execute("DELETE FROM member WHERE role=?", (full,))
        self.conn.commit()
        return {"deleted": full, "perms_removed": perms, "members_removed": mems}

    def role_edit(self, full, title=None, tags=None, scene=None, name=None, by_role="owner.me"):
        """改角色信息（经理）。改场景/角色名 = 改"身份证"：role 表与 perm 一起搬。"""
        if not self._can_control():
            raise PermissionError("只有经理能改角色信息：%s" % by_role)
        row = self.conn.execute("SELECT scene,name,title,tags FROM role WHERE full_name=?", (full,)).fetchone()
        if not row:
            raise ValueError("没有这个角色：%s" % full)
        sc, nm, ti, tg = row
        nsc = (scene if scene not in (None, "") else sc)
        nnm = (name if name not in (None, "") else nm)
        nfull = nsc + "." + nnm
        nti = ti if title is None else title
        ntg = tg if tags is None else tags
        self.conn.execute("UPDATE role SET scene=?,name=?,full_name=?,title=?,tags=? WHERE full_name=?",
                          (nsc, nnm, nfull, nti, ntg, full))
        if nfull != full:
            self.conn.execute("UPDATE perm SET full_name=? WHERE full_name=?", (nfull, full))
        self.conn.commit()
        return {"full": nfull, "was": full, "scene": nsc, "name": nnm, "title": nti or "", "tags": ntg or ""}

    def thread(self, role, limit=100):
        """一对一聊天记录（面板画气泡用）：who=me 我说的 / him 他说的"""
        out = []
        for kind, fr, to, body, ts, mid in self.conn.execute(
                "SELECT kind,from_role,to_role,body,created_at,id FROM v_msg WHERE"
                " (from_role='owner.me' AND to_role=?) OR from_role=? ORDER BY id LIMIT ?",
                (role, role, limit)).fetchall():
            out.append({"id": mid, "who": "me" if fr == "owner.me" else "him", "body": body, "at": ts or 0})
        try:
            for mid, by, body, ts in self.conn.execute(
                    "SELECT msg_id,from_role,body,created_at FROM reply WHERE from_role=? ORDER BY created_at", (role,)).fetchall():
                out.append({"id": mid, "who": "him", "body": body, "at": ts or 0})
        except Exception:
            pass
        out.sort(key=lambda x: x["at"])
        return {"role": role, "count": len(out), "items": out}

    def deliveries_json(self, limit=20):
        """投递台账（面板显示"谁收了、谁没收、为什么"）"""
        rows = self.conn.execute(
            "SELECT d.msg_id,d.role,d.ok,d.note,d.at,m.topic,m.body FROM delivery d"
            " LEFT JOIN v_msg m ON m.id=d.msg_id ORDER BY d.msg_id DESC, d.role LIMIT ?", (limit,)).fetchall()
        return {"count": len(rows), "items": [
            {"msg": r[0], "role": r[1], "ok": bool(r[2]), "note": r[3] or "", "at": r[4],
             "topic": r[5] or "", "body": (r[6] or "")[:40]} for r in rows]}

    def asks_json(self):
        """还没答的授权/拍板请求 —— 面板上"谁在等你"就靠它"""
        rows = self.conn.execute(
            "SELECT n.msg_id,m.from_role,m.topic,m.body,m.created_at FROM notify n"
            " JOIN v_msg m ON m.id=n.msg_id WHERE n.answered_at IS NULL ORDER BY n.msg_id").fetchall()
        return {"count": len(rows), "asks": [
            {"id": r[0], "from": r[1], "topic": r[2], "body": r[3], "at": r[4]} for r in rows]}

    def state_get(self, k, default=None):
        """中转站自己的小状态（游标等）—— 不被业务用到，存在 pref 表"""
        try:
            r = self.conn.execute("SELECT v FROM pref WHERE k=?", (k,)).fetchone()
            return r[0] if r else default
        except Exception:
            return default

    def state_set(self, k, v):
        try:
            self.conn.execute("INSERT OR REPLACE INTO pref(k,v) VALUES(?,?)", (k, str(v)))
            self.conn.commit()
        except Exception:
            pass

    def setting_get(self, k, default=None):
        r = self.conn.execute("SELECT v FROM setting WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def setting_set(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO setting(k,v,updated_at) VALUES(?,?,?)", (k, v, now_ts()))
        self.conn.commit()

    def mark_notify(self, msg_id):
        """角色标一句"这句要让他知道" —— 女仆会把它中转给他（QQ 那条专属对话）"""
        self.conn.execute("INSERT OR REPLACE INTO notify(msg_id,marked_at,pushed_at,channel)"
                          " VALUES(?,?,NULL,NULL)", (msg_id, now_ts()))
        self.conn.commit()

    def relay(self, target=None, dry=False, limit=20):
        """女仆的活：把"标了要通知他、还没推过"的话整理成固定格式推给他（默认 QQ 专属对话）。
        格式：谁 → 什么事 → 要你决定什么 → 什么时候要。dry=True 只打印不发。"""
        tgt = target or self.setting_get("qq_target") or ""
        rows = self.conn.execute(
            "SELECT m.id,m.from_role,m.to_role,m.topic,m.body,m.created_at FROM v_msg m"
            " JOIN notify n ON n.msg_id=m.id WHERE n.pushed_at IS NULL ORDER BY m.id LIMIT ?",
            (limit,)).fetchall()
        if not rows:
            return 0, tgt, ""
        parts = ["【角色频道 · 女仆转达】"]
        for mid, frm, to, topic, body, ts in rows:
            head = "· #%d %s（%s）" % (mid, frm, fmt(ts))
            parts.append(head)
            if topic:
                parts.append("  话题：%s" % topic)
            for ln in (body or "").splitlines():
                parts.append("  " + ln)
        text = "\n".join(parts)
        if not dry:
            if not tgt:
                raise RuntimeError("还没设 qq 目标：talk.py setting set qq_target qqbot:<id>")
            subprocess.run([HERMES_BIN, "send", "-t", tgt, text], check=True)
            for mid, *_ in rows:
                self.conn.execute("UPDATE notify SET pushed_at=?, channel=? WHERE msg_id=?",
                                  (now_ts(), tgt, mid))
            self.conn.commit()
        return len(rows), tgt, text

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

    # ---------- 接入表：经理决定"这个频道里谁能收到消息" ----------

    def member_add(self, channel, role, by_role):
        if not self._can_control():
            raise PermissionError("只有经理能改接入表：%s" % by_role)
        self.conn.execute("INSERT OR REPLACE INTO member(channel,role,added_by,at) VALUES(?,?,?,?)",
                          (channel, role, by_role, now_ts()))
        self.conn.commit()
        return "%s 接入 %s" % (role, channel)

    def member_del(self, channel, role, by_role):
        if not self._can_control():
            raise PermissionError("只有经理能改接入表：%s" % by_role)
        self.conn.execute("DELETE FROM member WHERE channel=? AND role=?", (channel, role))
        self.conn.commit()
        return "%s 移出 %s" % (role, channel)

    def member_list(self, channel=None):
        q = ("SELECT m.channel,m.role,m.added_by,m.at,r.title FROM member m"
             " LEFT JOIN role r ON r.full_name=m.role")
        args = ()
        if channel:
            q += " WHERE m.channel=?"
            args = (channel,)
        return self.conn.execute(q + " ORDER BY m.channel, m.role", args).fetchall()

    def _members_of(self, channels):
        """这个频道里能收到消息的人；接入表空着就退回"该场景全部角色"（免得新场景一上来没人理）"""
        out = set()
        rows = self.member_list()
        by_ch = {}
        for ch, role, *_ in rows:
            by_ch.setdefault(ch, set()).add(role)
        for ch in channels:
            out |= by_ch.get(ch, set())
        if not out:
            for full, scene in self.conn.execute("SELECT full_name,scene FROM role").fetchall():
                if scene in channels:
                    out.add(full)
        return out

    # ---------- 注册（TUI）：场景 → 角色名 → 描述 → 标签 → 组 ----------

    def reg_role(self, scene, name, title, tags=""):
        """登记一个角色：**全名 = <场景>.<角色>**；tags 是它身上的标签（逗号分隔）；
        场景就是"组"。面板/roles-json 会按场景分组显示。"""
        scene = (scene or "").strip()
        name = (name or "").strip()
        require_ok = scene.replace("-", "").isalnum() and name.replace("-", "").isalnum()
        if not (scene and name and require_ok):
            raise ValueError("场景和角色名只能用字母数字与短横线：<场景>.<角色>")
        full = "%s.%s" % (scene, name)
        self.conn.execute("INSERT OR REPLACE INTO role(full_name,scene,name,title,tags,created_at)"
                          " VALUES(?,?,?,?,?,?)", (full, scene, name, title or "", tags or "", now_ts()))
        self.conn.commit()
        return full

    def reg_line(self, full):
        r = self.conn.execute("SELECT full_name,scene,name,title,tags FROM role WHERE full_name=?",
                              (full,)).fetchone()
        return "%-24s 场景=%-12s 角色=%-12s 标签=%-20s 描述=%s" % (r[0], r[1], r[2], r[3] or "-", r[4] or "-")

    # ---------- 唤醒：只有 @了他 / 私信他 / （经理放行的）广播，他才会动 ----------

    def _mentions(self, body, topic):
        text = (body or "") + " " + (topic or "")
        return set(re.findall(r"@([a-z0-9-]+\.[a-z0-9-]+)", text))

    def wake_seed(self, msg_id):
        """发完消息就摊开"谁该动"：私信/@点名 → 直接 approved；广播 → 候选 pending（等经理放行）。"""
        m = self.conn.execute("SELECT kind,to_role,topic,body,scope FROM v_msg WHERE id=?", (msg_id,)).fetchone()
        if not m:
            return 0
        kind, to_role, topic, body, scope = m
        n = 0
        if kind == "private" and to_role:
            self._wake_set(msg_id, to_role, "approved", "system", "私信")
            n = 1
        for who in self._mentions(body, topic):
            self._wake_set(msg_id, who, "approved", "system", "@点名")
            n += 1
        if kind == "broadcast":
            groups = [g.strip() for g in (scope or "").split(",") if g.strip()]
            if groups:
                cand = self._members_of(groups)      # 经理维护的接入表说了算
                for full in sorted(cand):
                    if full == "owner.me":
                        continue
                    cur = self.conn.execute("SELECT state FROM wake WHERE msg_id=? AND role=?",
                                            (msg_id, full)).fetchone()
                    if cur and cur[0] == "approved":
                        continue          # @点名/私信已经让它动了，别再改回候选
                    self._wake_set(msg_id, full, "pending", None, None)
                    n += 1
            else:
                for full, scene in self.conn.execute("SELECT full_name,scene FROM role").fetchall():
                    if full == "owner.me":
                        continue
                    self._wake_set(msg_id, full, "pending", None, None)
                    n += 1

    def _wake_set(self, msg_id, role, state, by_role, why):
        self.conn.execute("INSERT OR REPLACE INTO wake(msg_id,role,state,by_role,why,at,delivered_at)"
                          " VALUES(?,?,?,?,?,?,COALESCE((SELECT delivered_at FROM wake"
                          " WHERE msg_id=? AND role=?),NULL))",
                          (msg_id, role, state, by_role, why, now_ts(), msg_id, role))
        self.conn.commit()

    def wake_list(self, msg_id=None):
        q = ("SELECT w.msg_id,w.role,w.state,w.by_role,w.why,m.topic,m.kind FROM wake w"
             " LEFT JOIN v_msg m ON m.id=w.msg_id")
        args = ()
        if msg_id:
            q += " WHERE w.msg_id=?"
            args = (msg_id,)
        return self.conn.execute(q + " ORDER BY w.msg_id DESC, w.role", args).fetchall()

    def wake_ok(self, msg_id, role, by_role):
        """经理放行：让他动（后面 wake-run 会真的投递给他）"""
        if not self._can_control():
            raise PermissionError("只有经理能决定谁动：%s" % by_role)
        self._wake_set(msg_id, role, "approved", by_role, "放行")
        return "approved"

    def wake_skip(self, msg_id, role, by_role, why=""):
        """经理跳过：这件事不适合他，不打扰他"""
        if not self._can_control():
            raise PermissionError("只有经理能决定谁不动：%s" % by_role)
        self._wake_set(msg_id, role, "skipped", by_role, why or "跳过")
        return "skipped"

    def wake_run(self, msg_id, dry=False):
        """把这条消息里**approved 且还没投递过**的角色叫起来（投递到他的固定会话）"""
        rows = self.conn.execute(
            "SELECT w.role FROM wake w WHERE w.msg_id=? AND w.state='approved' AND w.delivered_at IS NULL",
            (msg_id,)).fetchall()
        m = self.conn.execute("SELECT kind,from_role,topic,body FROM v_msg WHERE id=?", (msg_id,)).fetchone()
        out = []
        for (role,) in rows:
            text = "【%s #%d】%s: %s%s" % ("私信" if m[0] == "private" else "广播", msg_id, m[1],
                                          (m[2] + " — ") if m[2] else "", m[3])
            if dry:
                out.append((role, "dry"))
                continue
            try:
                self.deliver(role, text)
                self.conn.execute("UPDATE wake SET delivered_at=? WHERE msg_id=? AND role=?",
                                  (now_ts(), msg_id, role))
                self.conn.commit()
                out.append((role, "ok"))
            except Exception as e:
                out.append((role, str(e)[:60]))
        return out

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
                                    "watch", "init", "rebuild", "roles-json", "sessions-json", "solo",
                                    "attach", "since-json", "setting", "notify", "relay",
                                    "reg", "wake", "wake-ok", "wake-skip", "wake-run",
                                    "member", "member-add", "member-del", "ask", "answer", "asks", "role-edit", "role-del", "thread", "say", "relay-once", "relay-daemon", "deliveries", "tell", "doctor", "setup"])
    ap.add_argument("--launch", default=None)
    ap.add_argument("--tmux", default=None)
    ap.add_argument("--dry", action="store_true")
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
    ap.add_argument("--tags", default=None)
    ap.add_argument("--scene", default=None)
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
    if a.cmd in ("pause", "start", "stage-add", "gate-open", "gate-done",
                 "member-add", "member-del", "wake-ok", "wake-skip",
                 # 治理类（改名册/权限/角色）也必须以下令者身份连库 ——
                 # 否则会拿"无角色的连接"连（= 管理员），权限检查形同虚设（踩过：非经理删掉了角色）
                 "role-add", "perm-add", "role-edit", "role-del",
                 "say"):
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
        try:
            r = t.tell_user("收工", "%s 交了「%s」第 %s 阶段的报告" % (a.role, a.project, a.seq), frm=a.role)
            print("已由女仆带话给本人：#%d（收工）" % r["id"])
        except Exception as e:
            print("带话失败：%s" % e)
    elif a.cmd == "perm-add":
        t.conn.execute("INSERT OR REPLACE INTO perm(full_name,scope,action,created_at) VALUES(?,?,?,?)",
                       (a.role, a.scope, a.action, now_ts()))
        t.conn.commit()
        print("权限已加：%s %s/%s" % (a.role, a.scope, a.action))
    elif a.cmd == "send":
        mid = t.send(a.frm, a.to, a.kind, a.topic, a.body, a.must_reply, scope=a.scope)
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
        if a.why:
            try:
                r = t.tell_user("卡住", "%s 卡住了：%s" % (a.role, a.why), frm=a.role)
                print("已由女仆带话给本人：#%d" % r["id"])
            except Exception as e:
                print("带话失败：%s" % e)
    elif a.cmd == "since-json":
        print(json.dumps(t.since_json(a.id or 0), ensure_ascii=False))
    elif a.cmd == "reg":
        # 有参数＝直接注册；没参数＝TUI 逐项问（换场景时用这个）
        if a.full:
            scene, _, name = a.full.partition(".")
        else:
            print("注册一个角色（回车用默认）")
            scene = input("  场景（组，比如 home / pipeline）：").strip()
            name = input("  角色名（字母数字短横线，比如 maid）：").strip()
            a.title = input("  描述（它是干什么的）：").strip() or a.title
            a.scope = input("  标签（逗号分隔，比如 生活,助理）：").strip() or a.scope
        full = t.reg_role(scene, name, a.title or "", a.scope or "")
        print("已注册：" + t.reg_line(full))
        print("（面板/roles-json 会按场景分组显示它；要它参与对话就 talk.py spawn --role %s）" % full)
    elif a.cmd == "ask":
        mid = t.ask(a.frm or a.role, a.text or a.body, "", a.topic or "要你授权")
        print("#%d 已登记提问 → 女仆会带着「哪个角色 / 哪个会话」转达给他" % mid)
    elif a.cmd == "role-edit":
        r = t.role_edit(a.full, a.title, a.tags, a.scene, a.name, a.by or "owner.me")
        print("已改：%s → %s  描述=%s 标签=%s" % (r["was"], r["full"], r["title"] or "-", r["tags"] or "-"))
    elif a.cmd == "role-del":
        r = t.role_del(a.full, a.by or "owner.me", a.force)
        print("已删 %s（连带清掉 %d 条权限、%d 条接入）" % (r["deleted"], r["perms_removed"], r["members_removed"]))
    elif a.cmd == "thread":
        print(json.dumps(t.thread(a.role, a.lines or 100), ensure_ascii=False))
    elif a.cmd == "setup":
        built = t._ensure_ready()
        d = t.doctor()
        print(json.dumps({"built": built, "doctor": d}, ensure_ascii=False))
    elif a.cmd == "doctor":
        print(json.dumps(t.doctor(), ensure_ascii=False))
    elif a.cmd == "deliveries":
        print(json.dumps(t.deliveries_json(a.lines or 20), ensure_ascii=False))
    elif a.cmd == "asks":
        print(json.dumps(t.asks_json(), ensure_ascii=False))
    elif a.cmd == "answer":
        mid = t.answer(a.id, a.text or a.body, a.by or "owner.me")
        print("#%d 已记入你的答复并回给提问的人" % mid)
    elif a.cmd == "member-add":
        print(t.member_add(a.scope or "", a.role, a.by or "owner.me"))
    elif a.cmd == "member-del":
        print(t.member_del(a.scope or "", a.role, a.by or "owner.me"))
    elif a.cmd == "member":
        rows = t.member_list(a.scope or None)
        if not rows:
            print("（接入表还空着 —— 广播时会退回「该场景全部角色」）")
        for ch, role, by, at, title in rows:
            print("%-14s %-24s %-12s %s" % (ch, role, title or "", by or ""))
    elif a.cmd == "wake":
        rows = t.wake_list(a.id or None)
        if not rows:
            print("（还没有唤醒记录）")
        for mid, role, state, by, why, topic, kind in rows:
            print("#%-4d %-24s %-9s %-10s %s" % (mid, role, state, by or "-", why or (topic or "")))
    elif a.cmd == "wake-ok":
        print(t.wake_ok(a.id, a.role, a.by or "owner.me"), "→", a.role)
    elif a.cmd == "wake-skip":
        print(t.wake_skip(a.id, a.role, a.by or "owner.me", a.why), "→", a.role)
    elif a.cmd == "wake-run":
        for role, res in t.wake_run(a.id, a.dry):
            print("%-24s %s" % (role, res))
    elif a.cmd == "setting":
        if a.text:
            t.setting_set(a.name, a.text)
            print("已设 %s = %s" % (a.name, a.text))
        else:
            print("%s = %s" % (a.name, t.setting_get(a.name) or "(没设)"))
    elif a.cmd == "notify":
        t.mark_notify(a.id)
        print("#%d 已标：要她知道（女仆中转时会带上）" % a.id)
    elif a.cmd == "relay-once":
        r = t.relay_once(a.id if a.id else None)
        print("中转一轮：游标=%d 投递=%s 收回答=%s" % (r["cursor"], r["delivered"] or "无", r["collected"] or "无"))
    elif a.cmd == "relay-daemon":
        import time as _t
        print("中转站起来了（每 %d 秒一轮，Ctrl-C 停）" % (a.poll or 5))
        while True:
            try:
                r = t.relay_once()
                if r["delivered"] or r["collected"]:
                    print("  投递=%s 收回答=%s" % (r["delivered"], r["collected"]))
            except Exception as e:
                print("  一轮出错：%s" % e)
            _t.sleep(a.poll or 5)
    elif a.cmd == "relay":
        n, tgt, text = t.relay(a.text or None, a.dry)
        print("中转 %d 条 → %s%s" % (n, tgt or "(没设目标)", "（dry-run 只打印不发）" if a.dry else ""))
        if text:
            print(text)
    elif a.cmd == "watch":
        t.watch(a.poll, a.once)
    elif a.cmd == "init":
        roles = t.init(a.full or "owner.me")
        print("已建好：库表 + 经理 + 角色 → %s" % "、".join(roles))
    elif a.cmd == "rebuild":
        n, r = t.rebuild()
        print("从 talk/*.md 重建完成：消息 %d 条、回复 %d 条" % (n, r))
    elif a.cmd == "roles-json":
        print(json.dumps(t.roles_json(), ensure_ascii=False))
    elif a.cmd == "sessions-json":
        print(json.dumps(t.sessions_json(), ensure_ascii=False))
    elif a.cmd == "solo":
        tmux, created = t.solo(a.name, a.launch)
        print(json.dumps({"tmux": tmux, "created": created, "role": None,
                          "hint": "tmux attach -t %s" % tmux}, ensure_ascii=False))
    elif a.cmd == "attach":
        target = a.tmux or (a.role and t.tmux_session(a.role)) or None
        if not target:
            print("要 --tmux <名字> 或 --role <全名>"); return 2
        if not t._alive(target):
            print("会话不在：%s（先 spawn/solo）" % target); return 3
        print("tmux attach -t %s" % target)
    elif a.cmd == "tell":
        r = t.tell_user(a.kind or "告知", a.body or a.text or "", a.topic and "" or "", a.by or "owner.me",
                        a.topic, push=(a.dry is not True))
        print("已由女仆带话给本人：#%d（%s）推送=%s" % (r["id"], r["kind"], r["pushed"]))
    elif a.cmd == "say":
        r = t.say(a.role, a.body or a.text or "", a.topic or "私信", a.kind or "private",
                  frm=(a.by or "me"))   # 署名：本人(me) 或 经理(owner.me)
        if r.get("broadcast"):
            print("#%d 广播：逐个投递 %d 人 → %s" % (r["id"], r["count"],
                  ", ".join((x["role"] + ("✓" if x["delivered"] else "✗")) for x in r["results"])))
        else:
            print("#%d 已记入并投给 %s（投递%s）" % (r["id"], r.get("to", a.role),
                  "成功" if r.get("delivered") else "失败：" + str(r.get("error"))))
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
