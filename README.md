# roles-chat —— 多角色：角色名册 / 经验库 / 可检索的对话（含 SQLite 权限）

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
