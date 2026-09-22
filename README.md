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

## 常用命令
```bash
python3 tools/talk.py role-add --full pipeline.author --title 功能创造者
python3 tools/talk.py perm-add --role pipeline.auditor --scope msg:all --action read
python3 tools/talk.py send  --role pipeline.author --from pipeline.author --to 全体 \
        --kind broadcast --topic 公告 --must-reply --body "……"
python3 tools/talk.py send  --role pipeline.author --from pipeline.author --to pipeline.tester \
        --kind private --topic 交接 --body "……"
python3 tools/talk.py inbox  --role pipeline.tester
python3 tools/talk.py search --role pipeline.tester --q 判据
python3 tools/talk.py files  --role pipeline.tester      # 这个角色有权读的日志文件
python3 tools/talk.py selftest                           # 20 条判据 → evidence/
python3 tools/exp_index.py must --role pipeline.author    # 说身份后必须先读的
```

## 规矩
- 一个角色 = 一个会话（开场自报全名）；**角色之间不直接对话**，一律通过 `talk/` 日志（可检索、跨 session 能接上）。
- 收工前跑 `talk.py inbox --role <我>`，把等我回的（尤其 `must-reply`）回掉。
- 经验过期要重验：文件头 `verified` 是实测日期。
