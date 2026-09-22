# roles-chat —— 多角色：角色名册 / 经验库 / 可检索的对话（含 SQLite 权限）

> **定型规范见 `SPEC.md`**（v1：目录、表、权限、命令、日志格式、红线、迁移）。
> **换机器/换地方**：把整个目录拷过去 → `bash install.sh` → 完事。
> **库丢了也不怕**：文本是权威源，`talk.py rebuild` 从 `talk/*.md` 重建；`install.sh` 里已包含这一步。
> 路径默认按本项目自身位置推导，也可 `export ROLES_CHAT_HOME=<目录>` 覆盖。

用户要的东西（口述整理）：
1. **角色管理**（沿用 `~/.hermes/skills/roles/`：场景 + 角色卡 + 全局唯一全名 `<场景>.<角色>`）。
2. **经验库**：每个角色一个目录（**目录名 = 角色全名**），一条经验一个文件，带 `must: true/false`（必须 / 可选）与标签；
   **我一说身份，就要加载该角色必读经验并按任务检索其余**。
3. **多角色对话**：对全体 / 私信 / **default**（不看权限谁都可见）三类；标注收发双方、发出时间、回复时间；**可检索**。
4. **权限做在 SQLite 层面**：什么角色进来只能看见、只能改什么，由库控制，不靠自觉。

设计书：`~/.hermes/skills/roles/设计-角色经验与多角色对话.md`

## 目录
```
tools/talk.py            对话：写文本日志 + 入库 + 按角色权限读（含 selftest）
tools/talk_selftest.py   自检：三类消息与权限的 20 条判据
tools/exp_index.py       经验库：list / must / search / check
experiences/<场景>.<角色>/   经验（目录名=角色全名；文件头必须有 name/must/tags/when/verified）
talk/YYYY-MM-DD-<类>.md  文本日志（权威源；private 按收发生成专属文件）
talk.db                  SQLite 索引 + 权限表（日志是权威源，索引入库便于检索）
evidence/                自检输出
```

## 权限怎么落地（实测，不是设计口号）
角色开连接时挂 **SQLite 授权器**：直接读 `msg` 表被拒（`access to msg.id is prohibited`），只能走按身份拼好的
TEMP 视图 `v_msg`；名册/权限表只有管理员角色能改（`not authorized`）。私信连**文本文件层面**都不进别人的可读清单。

## 经理与阶段闸门（一个项目 = 一串阶段，只放行当前那一步）

```bash
# 经理排阶段（标在 stage 表里，初始全部 locked）
python3 tools/talk.py stage-add --project mark-readnotes-第11轮 --seq 1 --name 功能开发 --role pipeline.author
python3 tools/talk.py stage-add --project mark-readnotes-第11轮 --seq 2 --name 渲染打包 --role pipeline.renderer
python3 tools/talk.py stage-add --project mark-readnotes-第11轮 --seq 3 --name 测试     --role pipeline.tester
python3 tools/talk.py gate --project mark-readnotes-第11轮          # 一眼看谁在跑 / 谁锁着
python3 tools/talk.py gate-open --project <P> --seq 1 --by owner.me # 只放行第 1 步（后面的仍锁）
python3 tools/talk.py blocked --role pipeline.renderer              # 查某人现在能不能收活
python3 tools/talk.py gate-done --project <P> --seq 1 --by owner.me # 判定完成（必须先有合格报告）
```

规矩（全部实测过）：
- **阶段锁住的人收不到活**：`deliver` 会拒 —— `阶段没放行，不投递：pipeline.renderer（… 第 2 步（渲染打包）还没放行）`。
- **只有经理（有 `room:control/write`）能放行**；普通角色 `gate-open` 被拒。
- **判定完成必须先有该阶段的合格报告**，否则：`第 1 步还没有合格报告（先 run report），不放行下一步`。
- 放行/报告都写进对话（`话题:阶段` / `话题:报告 <项目#步>`），看板上一眼能看出流程走到哪。

## 交付报告的固定格式（角色交活必须带这四行）

```
做了什么：<一句话>
证据：<evidence/ 里的路径>
判据：<跑过什么、多少条绿>
依赖：<下一步等谁 / 等什么>
```
`talk.py report --project <P> --seq N --from <角色> --text "…"`：**缺任何一行直接拒**，
拒绝信息就是缺哪几项；合格才入库（`feature` 记 `P#N`，阶段完成判定就是看它）。

## 固定会话（幂等，名字按角色）

`talk.py spawn --role <场景>.<角色> [--profile <名>]`：tmux 会话名固定 `role-<场景>-<角色>`；
**已经在跑就不动它**（幂等）。Hermes 侧用 `hermes -p <profile> chat -c <角色全名> --create-if-missing`
—— 按名字续同一个会话，没有就用这个名字建，所以"session 固定且按角色命名"是真的。

## 与 hermes-pocket 的对接（下一步，本项目的一部分）

hermes-pocket 是 WebView + 原生 SSH 的移动终端壳，连单个会话是它的强项。要在它上面加：
1. **频道面板**：复用它已有的 SSH 通道跑 `talk.py board`（看公共频道）与 `talk.py send --kind broadcast`（喊话）；
2. **单角色入口一排**：点哪个进哪个角色的固定会话（`role-<场景>-<角色>`）。
它现有的 `.mjs` 测试**不动**（用户交代过）；面板加完在模拟器上按老规矩验收。

## 管理者（代表"我"的角色：owner.me）

```bash
python3 tools/talk.py init-owner                       # 建 owner.me：msg:all 读写 + room:control 写 + 名册管理
python3 tools/talk.py status                           # 谁在跑 / 谁被停 / 谁还欠回复 / 房间状态
python3 tools/talk.py pause --role <全名> --by owner.me --why "先停一下"     # 停一个角色（发 /stop，--hard 连会话收掉）
python3 tools/talk.py pause --by owner.me --why "全体停"                     # 停全体：房间暂停，投递一律被拒
python3 tools/talk.py start --role <全名> --by owner.me [--profile <名>]     # 恢复（没会话就现场开）
```

规矩：
- **控制权是数据**（`perm` 里的 `room:control/write`），不是代码分支；非管理者下令被拒
  （实测：`只有管理者能控制（缺 room:control/write）`），连"停自己"也不行。
- **暂停期间 `deliver` 一律拒绝**（除非 `--force`），所以角色真的收不到新活。
- 下令本身也写进对话（`话题:控制`），**大家看得见谁在什么时候让谁停/开**。
- 状态在 `room` 表（scope=`room` 或 `role:<全名>`），重启不丢。

## 常用命令
```bash
# 角色与权限
python3 tools/talk.py role-add --full pipeline.author --title 功能创造者
python3 tools/talk.py perm-add --role pipeline.auditor --scope msg:all --action read

# 发消息（三类：default 不看权限谁都可见 / broadcast 全体 / private 私信）
python3 tools/talk.py send --role pipeline.author --from pipeline.author --to 全体 \
        --kind broadcast --topic 公告 --must-reply --body "……"
python3 tools/talk.py send --role pipeline.author --from pipeline.author --to pipeline.tester \
        --kind private --topic 交接 --body "……"
python3 tools/talk.py reply --id 3 --from pipeline.tester --body "收到，判据已加"

# **他看的一屏**（CLI 优先）：三类带标签、带收发/时间/话题/必读/待回
python3 tools/talk.py board                 # 全部（含私信，只有他能这么看）
python3 tools/talk.py board --role pipeline.tester   # 某个角色能看到的那些
python3 tools/talk.py tail --lines 1000     # 按权限拼日志文件，看最后 1000 行

# 角色跑在 tmux 会话里（他自己另开 tmux 看）
python3 tools/talk.py spawn  --role pipeline.tester [--profile tester]
python3 tools/talk.py deliver --role pipeline.tester --id 3 --text "请处理这条"
python3 tools/talk.py capture --role pipeline.tester --lines 1000    # 抓它最近的输出

# 其它
python3 tools/talk.py inbox  --role pipeline.tester
python3 tools/talk.py files  --role pipeline.tester      # 这个角色有权读的日志文件
python3 tools/talk.py selftest                           # 20 条判据 → evidence/
python3 tools/exp_index.py must --role pipeline.author    # 说身份后必须先读的
```

## 跑法（CLI 优先，2026-09-22 用户定）
- **每个角色一个 tmux 会话**（`spawn` 开，名字 `role-<场景>-<角色>`；命令默认 `hermes -p <profile> chat`）——
  他在另一个 tmux 窗口 `tmux attach -t role-xxx` 或 `capture` 看它们，缓冲看千行足够。
- **投递**用 `deliver`（`load-buffer` + `paste-buffer` + `Enter`，多行也不会被换行弄坏）。
- **回复**让角色自己用工具写回（`talk.py reply`），**不靠抓屏猜**；抓屏只用于你旁观。
- 提醒角色去看消息的那句话（Routine/cron 或手工投递）：
  `先跑 talk.py inbox --role <我>，把等我回的（尤其 必读:是）处理掉，再用 talk.py reply --id N 回话。`

## 规矩
- 一个角色 = 一个会话（开场自报全名）；**角色之间不直接对话**，一律通过 `talk/` 日志（可检索、跨 session 能接上）。
- 收工前跑 `talk.py inbox --role <我>`，把等我回的（尤其 `must-reply`）回掉。
- 经验过期要重验：文件头 `verified` 是实测日期。
