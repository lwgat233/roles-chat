# roles-chat 定型规范 v1（2026-09-22 定）

**一句话**：多角色协作的**公共交流平台**——角色名册 + 按角色组织的经验库 + 可检索的对话（文本为权威、SQLite 做索引与权限）+ 经理的阶段闸门。
**定型目标**：换机器/换地方时，**拷贝本目录 + 跑 `bash install.sh`** 即可用；**库丢了也能从 `talk/*.md` 重建**。

## 1. 目录（定型，别随意改）

```
roles-chat/
  install.sh            一条命令搭好（建库、建角色、必要时从日志重建、自检）
  SPEC.md               本文件：定型规范（改结构/格式/权限必须先改这里）
  README.md             怎么用（人看）
  MANIFEST.txt          文件清单
  tools/talk.py         对话核心：库 + 权限 + 投递 + 看板 + 实时跟随 + 重建
  tools/talk_selftest.py 31 条判据（权限/三类消息/阶段闸门/报告格式/收尾自清）
  tools/exp_index.py    经验库：list / must / search / check
  experiences/<场景>.<角色>/<经验>.md   目录名 = 角色全名；文件头 name/must/tags/when/verified
  talk/YYYY-MM-DD-{default|broadcast|private-<from>__<to>}.md   文本日志（**权威源**）
  talk.db               SQLite 索引 + 权限（可丢，能重建）
  evidence/             自检输出
```

**换地方只有两种做法**：① 整个目录拷过去 + `bash install.sh`；② 拷过去后设 `ROLES_CHAT_HOME=<该目录>` 再用（工具默认按自身位置推导，环境变量优先）。

## 2. 表结构（SQLite，v1）

| 表 | 字段 | 说明 |
|---|---|---|
| `role` | full_name PK, scene, name, title, created_at | 角色名册；全名 = `<场景>.<角色>`，全局唯一 |
| `perm` | full_name, scope, action, created_at（主键三者） | **权限是数据**：`msg:all∨msg:broadcast∨msg:private`+`read/write`、`room:control`+`write`、`table:role`+`write` |
| `msg` | id PK, kind(default∨broadcast∨private), from_role, to_role, topic, body, created_at, must_reply, feature, file_path | 对话索引；`feature` 用来钉项目阶段（`项目#步`） |
| `reply` | id PK, msg_id, from_role, body, created_at | 回复索引 |
| `seen` | msg_id, role, seen_at | 已读（"不回也行"的那种） |
| `room` | scope PK(`room` 或 `role:<全名>`), state(running∨paused), by_role, why, updated_at | 经理的暂停/恢复状态 |
| `stage` | project, seq, name, role, state(locked∨active∨done), updated_at（主键 project+seq） | 经理的阶段闸门 |

## 3. 权限模型（做在 SQLite 层面，绕不过去）

- 角色开连接时：**挂授权器**（`set_authorizer`）+ **按身份建 TEMP 视图 `v_msg`**；条件写死为
  `from_role=我 OR kind='default' OR kind='broadcast' OR (kind='private' AND to_role=我) OR 有 msg:all/read`。
- 直读 `msg` 表：**只有不带角色的连接（他本人的看板/命令行）或有 `msg:all/read` 的角色**才行；其余一律 `DENY`。
- 写：`role`/`perm` 要 `table:role/write`；`room`/`stage` 要 `room:control/write`；`msg`/`reply`/`seen` 人人可写（发言权）。
- **两类权限要分开**：**管流程**（经理：`room:control`+`table:role`）≠ **看内容**（`msg:all/read`）。
  经理**看不到别人之间的私信**（用户 2026-09-22 定）；他本人看得到全部。
- 私信连**文件层面**都隔离：只落 `talk/…-private-<from>__<to>.md`，别人的"可读文件"里不出现。

## 4. 三类消息（用户 2026-09-22 定）

| 类型 | 谁能看 | 用途 |
|---|---|---|
| `default` | **不看权限谁都可见** | 公告、阶段放行、交付报告 |
| `broadcast` | 全体（`to_role` 空/全体） | 公共频道喊话；默认"有待回" |
| `private` | 只收发双方 | 一对一私聊；经理也看不到 |

## 5. 文本日志格式（**权威源格式；改它必须同步改 `talk.py rebuild`**）

```
[2026-09-22 21:04:11] pipeline.author → pipeline.tester | 全体? 否 | 话题:第10轮 | 必读:是 | #12
    正文第一行
    正文第二行
    ↳ 回复 [2026-09-22 21:31:02] pipeline.tester: 收到，判据已加
```
- 同一条消息的正文缩进 4 空格；回复缩进 4 空格以 `↳ 回复` 开头、跟在所属消息下面。
- `#12` 是消息 id（重建时按它恢复，回复才对得上）。
- 文件名决定类型：`-default.md` / `-broadcast.md` / `-private-<from>__<to>.md`。

## 6. 命令清单（全部实现在 `tools/talk.py`，`--help` 里也有 choices）

| 命令 | 谁用 | 干什么 |
|---|---|---|
| `init` | 搭建 | 建库表 + 经理 + 本场景三角色（幂等） |
| `rebuild` | 搭建/恢复 | 从 `talk/*.md` 重建索引（库丢了靠它） |
| `watch [--role] [--poll] [--once]` | 他/频道面板 | **实时**跟随新消息（他本人含 🔒 私信） |
| `board [--role]` | 他/角色 | 一屏看对话（三类带标签、收发、时间、话题、必读、状态） |
| `tail --lines N` | 他 | 按权限拼日志文件看最后 N 行 |
| `send --from --to --kind --topic [--must-reply] --body` | 所有角色 | 发言（default/broadcast/private） |
| `reply --id --from --body` | 收件方 | 回话（也会写回日志） |
| `inbox --role` | 角色 | 等我回的（广播/私信/标了必读的） |
| `search --role --q` | 角色 | 在它有权看的范围内检索 |
| `files --role` | 角色 | 它有权读的日志文件 |
| `seen --id --role` | 角色 | 标已读 |
| `roles` / `role-add` / `perm-add` / `init-owner` | 经理 | 名册与权限 |
| `spawn --role [--profile]` | 经理/他 | 给角色开**固定会话**（tmux 名 `role-<场景>-<角色>`，幂等；Hermes 侧 `-c <角色> --create-if-missing`） |
| `deliver --role --text [--id]` | 经理/他 | 投递（`load-buffer`+`paste-buffer`+`Enter`）；暂停或阶段未放行时**拒绝** |
| `capture --role --lines` | 他 | 看那个角色会话最近的输出 |
| `pause/start [--role|全体] --by [--why] [--hard]` | 经理 | 停/开（角色级或房间级） |
| `status` | 经理/他 | 谁在跑、谁被停、谁欠回复、房间状态 |
| `stage-add/gate/gate-open/gate-done --project --seq [--name] [--role] --by` | 经理 | 阶段闸门：只放行当前步；判定完成必须先有合格报告 |
| `report --project --seq --from --text` | 角色 | 按固定格式交活（缺字段直接拒） |
| `roles-json` | 面板 | **角色列表（按场景分组）**：全名 / 名称 / 描述(title) / 状态(在跑·被停) / 有没有会话 / 欠多少回复 |
| `sessions-json` | 面板 | **历史记录**：他最近用过的会话（角色会话 + 单独会话），带 `alive`，点一下跳回去 |
| `solo [--name] [--launch]` | 他 | 开/续**脱离角色体系**的单独会话（只对他负责：不参与角色对话、不写 talk 日志、没有角色身份） |
| `attach [--tmux\|--role]` | 他 | 给出"怎么接进去看"的命令（`tmux attach -t …`） |
| `blocked --role` | 任何人 | 这个角色现在能不能收活 |
| `selftest` | 任何人 | 31 条判据 → `evidence/` |

## 7. 报告固定格式（角色交活必须带这四行）

```
做了什么：…
证据：<evidence/ 或仓库里的路径>
判据：<跑过什么、多少条绿>
依赖：<下一步等谁/等什么>
```

## 8. 红线（改这套东西之前先读）

1. **文本永远优先于库**：库可以整份删掉再 `rebuild`；反过来不行。改日志格式＝必须同步改 `rebuild`。
2. **新增表必须在授权器里显式放行**写权限（漏了就会 `not authorized`；`room`/`stage` 都踩过）。
3. **控制类命令要以"下令者"的身份连库**（`--by`），拿被管对象去连会被自己的权限拦死。
4. **不能替别人发言**：`send/reply/report` 的 `from` 必须是连接身份本人。
5. **管流程的权限和看内容的权限分开**：经理有前者没后者（看不到私信）。
6. 验收脚本/自检**跑完必须自清**（消息、阶段、日志文件），别留残件。

## 9. 版本与兼容

- 当前 **v1**。表结构/schema 有增改：在 §2 标注、并在 `talk.py` 的 `SCHEMA` 里用 `CREATE TABLE IF NOT EXISTS`（老库能平滑升级），必要时写迁移。
- 自检条数会随功能增长（现在是 31 条）；`install.sh` 里跑的就是它，**绿了才算这套系统可用**。


## 身份模型（2026-09-22 定，用户原话确认）

| 身份 | 是谁 | 权限 |
|---|---|---|
| `me` | **本人 = 用户** | 最高：看全部（含私信）、能直达任何角色、也能让经理去指挥 |
| `owner.me` | **经理 = 助手/代理**（"他代理我，但他不是我"） | 管流程：放行阶段、改名册/权限/接入表、暂停/恢复；**看不到私信内容** |
| `<场景>.<角色>` | 各司其职的角色 | 只能收发与自己相关的消息 |

要点：**经理不是本人**；面板/命令行以 `me` 身份说话；经理的消息另行署名 `owner.me`（可在群聊里区分"谁在说"）。


## 三种消息（2026-09-22 定）

| 种类 | 谁看得见 | 投给谁 | 标签 |
|---|---|---|---|
| `private` 私聊 | 只有收发双方 + 本人 | 收件人一个 | `【私聊】来自 <谁> #N` |
| `default` 定向（他人可见） | 面向某人，但**别人也看得见** | 收件人一个 | `【定向·他人可见】来自 <谁> #N` |
| `broadcast` 广播 | 全体 | **逐个投递**（接入表里的人，空则全体角色） | `【频道广播】来自 <谁> #N` |

投给他的每条都带标签（哪儿发的 + 谁发的 + 编号 + 「用 reply 回我」的用法）；
**他不必调函数**：在终端里直接说话，中转站会从 `╭─ ☤ Hermes ─╮` 框里抠出来记成回复。

## 中转站（relay）

- `tools/talk.py relay-once` 跑一轮；`relay-daemon` 常驻。
- 安装常驻：`bash tools/install-relay.sh`（systemd --user + linger，重启后自动起）；卸载 `bash tools/install-relay.sh remove`。
- 它盯"新出现的消息"（权威文本/库），按种类决定投给谁、以什么标志，结果记进 `delivery` 台账（`msg_id, role, ok, note`）。
- 反向：收集各角色终端里的新回答 → 记成 `reply`，面板据此画气泡。
- 游标存在 `pref` 表（`relay_cursor`），不重复投。

## 会话：一个 tmux

- 只有一个 tmux 会话 `roles`，**每个角色是里面一个窗口**（`<场景>-<角色>`）。
- 搬迁历史会话：`migrate_old_sessions()`（move-window，进程不重启、上下文不丢）。
- 投递/读屏/暂停都认窗口（`roles:<窗口>`），旧的 `role-xxx` 会话仅作兼容。
- 在线 = 该角色在 `roles` 里有窗口（或被停）。
