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
- **接活先登记阶段（经理的固定动作）**：拿到本人派的活，**先** `stage-add` 把步骤排出来（再 `gate-open` 放行第 1 步），**然后**才往角色投递。
  没登记阶段的活，切角色通知和逾期追问里都看不到进度（`progress_line()` 会显示"还没有登记项目阶段"）。

## 切角色/放行/完成 → 自动告知本人

经理不用手写汇报，这三处会自己推给本人（QQ，经女仆）：
- `switch --role X`：角色切换（切到谁 + 为什么 + 项目进度）
- `gate-open`：放行某步（= 下一个角色接手）
- `gate-done`：某步判定完成

## 逾期追问（派了活没回音就催）

```bash
python3 tools/talk.py nudge --minutes 45 --max 2        # 手动跑一次（加 --dry 只看会做什么）
```

- **判据**：`delivery.ok=1`（投出去了）且那个角色**没有** `reply`，且已过 `--minutes`（默认 45）。
- 不追：发给经理自己的、纯告知类（`【告知/【已解决/【收工/【进度`）。
- **不连环催**：`pref['nudge:<msg>:<role>'] = 时间|次数`，阈值内只问一次；最多问 `--max` 次（默认 2）。
- **升级**：问够次数，**或对方会话不在** → 走女仆报本人「卡住」。
- **常驻**：由 `roles-relay.service` 每分钟扫一次（`ExecStart` 里带 `--poll 5 --minutes 45 --max 2`）。
  **改了 `talk.py` 必须重启服务才生效**：`systemctl --user restart roles-relay.service`。
  unit 必须指向真项目 `/vol1/1000/airesults/roles-chat`（曾经指到过一份 `aicache/tmp/rc-gh` 的副本，导致中转站对着另一个库干活）。

## 女仆转达的节奏：5 分钟一批（2026-09-23 定）

经理/角色标了「要通知他」的东西，**不是一条一条推**，而是攒成一批推给本人：

- 节流键：`setting.relay_min_interval`（秒，默认 **300**＝5 分钟）；`pref.relay_last_push` 记上一批的推送时刻。
- `relay()` 在这个窗口内**直接返回 0 条**（条目仍挂在 `notify.pushed_at IS NULL`），到点后一次推出；`force=True` 可立即推。
- 中转站每轮都会调一次 `relay()`（以前只在有人主动调时才推 → 「标了通知却一直没到我手上」就是那个漏洞），所以队列到点会自动清。
- 验证配方：沙箱里把 `HERMES_BIN` 换成 `/bin/true`，攒 3 条 → 第一次推 3、紧接着推 0、把 `relay_last_push` 拨回 400 秒前再推 1。

## 女仆＝本人的 QQ 通道（唯一，2026-09-23 定）

- 名册里的 `home.maid` **不是一个需要 tmux 窗口的角色**，而是那条 QQ 通道的署名
  （用户原话：「你就是女仆啊」「你的 session 本来就是唯一的」）。
- 所以：**不许 `spawn --role home.maid`**（会被拒）；`deliver('home.maid', …)` 直接返回 QQ 目标、不往 tmux 投；
  `role_online('home.maid')` 恒 True；`session` 表里她那行指向**本人的 QQ 会话**（`hermes=<QQ 会话 id>`，`tmux` 写 qq 目标）。
- **事故教训（2026-09-23）**：`stop_role(hard=True)` 原先是 `tmux kill-session -t <target>`，
  而 target 形如 `roles:home-maid` → **tmux 忽略窗口部分、把整个 roles 会话杀掉**，5 个角色全被 SIGHUP，
  只能按名字重新 `spawn` 恢复（上下文没丢）。已修：目标含 `:` 时用 `kill-window`，只有裸会话名才用 `kill-session`。

## 女仆身份注册（2026-09-23 定：她＝本人 QQ 通道，不是一个 tmux 会话）

要"被系统认出来"，四处都要登记，缺一处面板里她就还是空壳：

| 位置 | 值 |
|---|---|
| `role` 行 | `home.maid` / scene `home` / name `maid` / title `可爱女仆（个人助手：管生活，中转要紧的话）` |
| `session` 行 | `hermes=<这条 QQ 会话的 id>`、`tmux=qqbot:<chat_id>`、`bind` 留空 |
| Hermes 侧标题 | 这条会话 `title='home.maid'`（`title_source=manual`）；旧的死会话要改名/归档，**否则唯一标题占着、认不出来** |
| `member` 接入表 | `qqbot` ← `home.maid`（不加这条，`roles-json` 里 `channels` 是空的） |
| 状态 | `room` 里 `role:home.maid` = `running`（她的"活着"= 这条通道在，不是 tmux 窗口在） |

判据：`talk.py roles-json` 里她必须是 `session=true · online=true · channels=["qqbot"]`。
改状态/接入表要 `--by owner.me`（女仆自己没控制权，这是对的）。

## 收工纪律：各角色保留"中断场景"，女仆除外（2026-09-23 本人定）

- **收工 = 停手，不停会话。** 每个角色收工时必须让下一个人能接着干：
  1. 手上的活写进报告/台账（做到哪一步、判据绿了几条、哪些未验）；
  2. **写一句"中断场景"**：当前步骤 / 下一步该谁 / 未提交的改动在哪个文件 / 关键命令与路径；
  3. **会话保持活着**（`tmux` 窗口与 Hermes 会话都不许杀）：不许 `kill-window`、`kill-session`、`stop_role --hard`。
- 真要省内存时才可以暂停，但**暂停前必须先留下上面那句"中断场景"**；恢复用 `hermes chat -c <角色全名>`（按名字续，上下文不丢）。
- **女仆除外**：她不是 tmux 会话，她就是本人的 QQ 通道；她不需要（也不许）有窗口，收工只把该报的报完。
- 判据：`tmux list-windows -t roles` 里四个角色窗口都在；每个角色最后一条报告里有"中断场景"那一句。

## 术语约定（2026-09-23 本人定，别再搞错）

- **"打包" = 生成 APK**（用当前源树走 `tools/build.sh`：盖章 → 核对 → gradle → **包内对账** → 归档 `apk/测试版/`），
  出完报 **APK 路径 + 整包 sha256**。
- **不做 tar.gz 交付压缩包** —— 除非本人明说"**打包给我 / 打包发我**"，那时才打交付包（MANIFEST + 整包哈希）。
  没人要就别生成、更别往 QQ 里发。
- 报告/通知里出现"打包"二字时，指的是上面第一条。

## 转达规范（女仆转发 · 要注释 · 2026-09-23 本人定）

- **是谁在转要说清**：转达抬头固定 `【女仆转发 · 正文未改】`；**正文一个字都不改**，原样贴。
- **每条都要带女仆注释**：`〔女仆注〕…` —— 说明这条对本人意味着什么（告知类不用回／在等你回话／
  阶段报告判定中／卡住需要处理）。注释由 `relay()` 的 `_relay_note()` 生成，写在正文之后。
- **自己另加的话**一律用 `〔女仆注〕` 起头，跟转发正文分得清。
- 代本人发的话署名 `home.maid` 并在正文标「代本人发」；本人明说"以我的名义"才署 `me`。

## 隐形对接信息（2026-09-23 定：能看出"收没收到"，但本人看不到）

- **一条消息的对接状态**：`talk.py ack --id N` → `#N 对接：投递 2/2 · 已读 1 · 已回 1`
  （投递数取自 `delivery`、已读取自 `seen`、已回取自 `reply`；没投到的角色会点名）。
  **这是给角色/系统看的，不推送、不进面板、不进文本日志**，所以本人看不到。
- **要记一条对接**：`talk.py ack --id N --state read|delivered|replied|failed --note "…"`
  → 写一条**隐形消息**（`msg.hidden=1`）：只入库，不写 `talk/*.md`、不建 wake、不进面板/气泡/推送。
- 过滤点（本人侧全部视图）：`board` / `watch` / `since_json` / `thread`(气泡) / `relay`(推 QQ)。
  文本日志是"给本人 grep 的"，所以隐形消息**一律不写进去**。
- 用途：女仆/经理之间的"收到没""转达没"这类握手，以后走隐形通道，不再往对话里塞【已转】那种会占屏的条。

## 交付报告格式（标题 + 五行 · 2026-09-23 二次收紧：标题明确、≤8 行）

```
【<项目>-<步号> <步名>】<角色全名> · <HH:MM>
做：<一句话，≤40 字>
证据：<evidence/ 里的路径>
判据：<关键数字 + 绿/红>
等：<下一步等谁 / 等什么；没有写"无"；未验写"未验≠通过">
成本：调用 N 次 · 输入 X · 输出 Y · 缓存读 Z · ≈¥W
```
`talk.py report …`：**缺行直接拒**；`feature` 记 `P#N`，阶段完成判定就看它。

**简洁（本人定，两次收紧后的口径）**：**含标题 ≤8 行**；标题必须含"项目-步骤 + 角色 + 时间"；
每行一件事；判据只留"数字 + 结论"；**原始输出一律进证据文件**，对话里不贴；超 8 行 = 不合格。

**成本用人民币**：`¥ = 美元估算 × cny_per_usd`（默认 **7.2**，存在 `talk.db` 的 `setting.cny_per_usd`）。
取数照 ⑦ 的差值法：任务开始前、结束后各读一次 `session_model_usage`，相减即"本次任务"。

**进度通知**：`progress_line()` 一行一个项目（`R29：1/3 · 当前 2 实现与出包(renderer)`）；
发通知**只报刚动的那个项目**（传 `project=`），没变的不列。

## 固定会话（幂等，名字按角色）

`talk.py spawn --role <场景>.<角色> [--profile <名>]`：tmux 会话名固定 `role-<场景>-<角色>`；
**已经在跑就不动它**（幂等）。Hermes 侧用 `hermes -p <profile> chat -c <角色全名> --create-if-missing`
—— 按名字续同一个会话，没有就用这个名字建，所以"session 固定且按角色命名"是真的。

## 面板 UI 规范（pocket 侧；用户 2026-09-22 定：**全按键，不输指令**）

**铁规（用户原话）**：「我不需要输入那么多东西，到底哪个指令对应哪个指令……你有个按键，点一下我就知道要对谁说话了。尽量简洁、方便。」
所以面板**不许出现需要用户敲命令/敲角色名/选消息类型的地方**；用户只敲"要说的话"，其余靠按键带出上下文。

```
【频道页】（默认）
  顶部： [实时 ✓]  [含私信 🔒 ✓]        ← 两个开关，默认都开
  中部： 实时消息流（📢/🔒/· + 谁→谁 + 时间 + 话题）
  角色按钮（按场景分组，一个角色一个按钮，直接点，不用选"对谁"）：
        owner    [me 经理]
        pipeline [author 功能创造者] [renderer 渲染者] [tester 测试者]
        每个按钮上带：状态点（在跑/被停）+ 欠回复数角标
  底部： [ 🗣 全体喊话 ]   [ ＋ 新对话 ]     ← 就这两个；新对话 = solo（只对我负责）
  历史： 上次单独聊过的会话（谁 + 时间），点一下跳回去
【点某个角色之后 → 跟"他"说话】（上下文就是"对这个人"）
  顶部： ← 频道   |   author（功能创造者）· 在跑 · 欠2
  中部： 这个角色的会话内容（终端）
  底部： [ 输入框：说点什么 ]  [ 发送 ]      ← 发送 = 私信给他 + 投进他的会话
        [ 看他要回什么 ]                    ← inbox（只显示"他欠我的"）
  说明：**没有"选择对象"、没有"选择私信/广播"**，全由"你从哪个按钮进来"决定
【全体喊话】（点 🗣 之后）
  输入框 + [ 喊话 ]    ← 就是 broadcast
【＋ 新对话】（solo）
  直接开一个只对我负责的会话，进去就是终端 + 输入框（不参与角色对话、不写 talk 日志）
```

后端一栏对应的命令（面板**只调这些，不拼命令行给用户看**）：
`roles-json`（按钮列表与角标）、`watch`（消息流）、`send --kind private --to <角色>` + `deliver`（对某个角色说话）、
`send --kind broadcast`（全体）、`inbox --role <角色>`（看他要回什么）、`sessions-json`（历史）、`solo`（新对话）。

## 可爱女仆 与 QQ 专属对话（用户 2026-09-22 定）

- **角色**：`home.maid` —— **可爱女仆**（个人助手）。管他的生活；与经理（`owner.me`）对接；
  **把要紧的话中转给他**。面板上她在 `home` 场景里（和其他角色一样一个按钮）。
- **谁想对他说话**：不用直接推给他 —— 角色把话发给女仆（`send --to home.maid --kind private`），
  或在自己那条消息上标一句"要她知道"：
  `talk.py notify --id <消息号>`
- **中转格式**（女仆推给他时固定这样）：
  ```
  【角色频道 · 女仆转达】
  · #103 pipeline.author（2026-09-22 20:13:56）
    话题：要你拍板
    要你决定：现在拍还是等下周
    什么时候要：今天
  ```
- **推到哪里**：**钉死一条 QQ 专属对话**（现在用他的 QQ 一对一 dm）：
  ```bash
  talk.py setting --name qq_target --text "qqbot:3FDE0CB3E30CD63FC5C635B4C657C844"
  talk.py relay            # 真的推（调 hermes send -t <qq_target>）
  talk.py relay --dry      # 只打印不发，先看格式
  ```
- **不会重复推**：`notify(msg_id, marked_at, pushed_at, channel)` 记着推没推过 —— 推过就不再出现。
- 想换频道（比如专门开一个 QQ 群当女仆频道）：`setting --name qq_target --text "qqbot:<群 id>"`，
  `hermes send -l` 会列出当前可用的目标。

## 与 hermes-pocket 的对接（下一步，本项目的一部分）

hermes-pocket 是 WebView + 原生 SSH 的移动终端壳，连单个会话是它的强项。要在它上面加：
1. **频道面板**：复用它已有的 SSH 通道跑 `talk.py watch`（实时刷公共频道，你本人带 🔒 私信也看得到）与
   `talk.py send --kind broadcast|private`（喊话/私信）；
2. **角色入口（按场景分组）**：跑 `talk.py roles-json`，每个角色一行——**名称 + 描述 + 状态（在跑/被停）+ 欠回复数**，
   点进去 = 它的固定会话 `role-<场景>-<角色>`；
3. **一个"抛离角色体系"的入口**：`talk.py solo` —— 新建/续一个**只对我负责**的单独会话（不参与角色对话、不写 talk 日志）；
4. **历史记录**：`talk.py sessions-json` —— 我上次单独跟谁聊、什么时候，点一下跳回去；
5. **私信态键位变化**：进了单聊（私信/某个会话）后，频道页的"喊话/广播"键收起，换成该会话自己的键（接进去看 / 返回）。
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
