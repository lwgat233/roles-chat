[2026-09-26 17:47:09] owner.me → pipeline.author | 全体? 否 | 话题:【派活】hermes-pocket-R45 第 1 步 定位（实体键盘 Shift+Enter 误发） | 必读:是 | #1440
    接 **`hermes-pocket-R45` 第 1 步「定位与改法」**（只定位、只出改法，不写代码）。来源＝测试者 R41-5 真机复测抓到的红（登记表 R-45）：
    
    **现象**：实体键盘 **Shift+Enter 把消息发出去了**（本该是"不发送"，A 案口径下也不换行）。测试者给的序列（真机 `input keycombination 59 66`）：
    `keydown Shift(shiftKey=false)` → `keydown Enter(shiftKey=true，主路拦住了)` → `keyup Shift(shiftKey=true ⇒ shiftDown=true)` → `keyup Enter(shiftKey=false ⇒ shiftDown 被覆盖成 false)` ⇒ **keyup 兜底那条路发送**；实测 `talk.say 1 次`、body 打进去了、输入框清空。**之后普通回车仍能发、不粘滞**。
    
    **要量清（文件:行 + 读数）**：
    1) **谁闯的祸**：`bindEnterSend` 里 `keyup` 兜底那段（`talk.js` 的公共入口，调用点群聊/单聊/授权框三处）—— 把 `shiftDown = e.shiftKey` 覆盖 `keydown` 判定这行**指出来**，并说清为什么"Shift 先松、Enter 后松"（真实最常见的松键顺序）必然踩到；
    2) **同类风险扫一遍**：`beforeinput` 兜底那条是否也有同样的 shift 判定漏洞（R41 定位时抓到过 beforeinput 误发 Shift+Enter）；三处调用点是否都受影响（给逐处结论）；
    3) **改法（给候选 + 代价）**，至少含：A＝把 keydown 时的 shift 状态**记住 400ms 窗口**（不读 keyup 的 `e.shiftKey`）；B＝keyup 兜底里**同时看 `e.shiftKey || shiftDownLatched`**；C＝干脆**去掉 keyup 兜底**（代价：某些输入法只给 keyup 就发不出去了 —— R41 就是为救那种输入法才加的，**别轻易删**）。给**你推荐哪条 + 判据**；
    4) **别碰的**：R-41 那条链（真机回车能发、组字态 1.5s 兜底复位）、R-31 防连点口径、R-36 状态机、R-39 的 padding 与 `--sayline-h`、R-42 右缘热区。
    5) **回归面与复测建议**：改 `assets/ui/talk.js` ⇒ **要重出包**（归 renderer）；复测板块＝主块 **①聊天页-单聊** ＋ **②聊天页-群聊**（同一公共入口）＋ 跨块 **⑧频道页**（授权框也走它），理由写清；判据建议＝**Shift+Enter 发出 0 条**、**普通回车仍 1 条**、**组字态回车仍能发**（R41 不许回归）、**同一次回车不出两条**。
    边界：不接主机、**未验 ≠ 通过**；证据进 `evidence/R45-定位-20260926/`；标题【hermes-pocket-R45-1 …】+ 4 行 + 成本¥；**交活走 `report` 通道**（`--project hermes-pocket-R45 --seq 1`）。
    ↳ 回复 [2026-09-26 17:50:23] pipeline.author: R-45 第 1 步已交报告 #1442（8 行，走 report 通道）。
    **谁闯的祸**：**`talk.js:221`** `inp.addEventListener("keyup", (e) => { shiftDown = !!(e && e.shiftKey); if (isEnter(e)) go(e); });` —— keyup 兜底把 shift 状态**从正在死掉的键事件里重读**：`keyup Shift(shiftKey=true ⇒ shiftDown=true)` → `keyup Enter(**shiftKey=false** ⇒ 覆盖回 false)` → `go()` 里 `shifted()`（talk.js:203）读到 false ⇒ 发送。keydown 主路（talk.js:214-220）**是有守卫的、正确拦住了**，keyup 是"第二次机会"。
    **为什么必然踩到**：真机最常见的松键顺序就是"**Shift 先松、Enter 后松**"（先抬小指再抬中指），那一刻系统按"还没松的键"算修饰键 ⇒ `keyup Enter` 必为 `shiftKey=false`；反过来（Enter 先松）能躲过，但不受用户控制。
    复现（CDP 真键盘、按你给的序列）：**单聊 Shift+Enter → talk.say 1 次**、**群聊 → talk.shout 1 次**；普通回车仍 1 次（功能没坏）。发完输入框被重画 ⇒ 不粘滞。
    **同类风险**：`beforeinput` 兜底（talk.js:222-225）也走同一个被污染的 `shiftDown`，而 `InputEvent` **没有 `shiftKey` 属性**（R-41 定位时抓到过它误发）⇒ 必须一起治。**三处调用点**：talk.js:565 群聊 gin（实测中招）· talk.js:1152 单聊 inp（实测中招）· talk.js:681 授权回复框（同函数同构，标同构推断）⇒ 修公共入口一处三处一起好。
    **改法＝A/B 合并（我推荐，约 4 行、只动 bindEnterSend）**：talk.js:197 的 `shiftDown` → `shiftAt`（时间戳闩）；talk.js:203 `shifted()` 改读 `(shiftAt && now()-shiftAt < 400)`；keydown(214) 开头加 `if (e.key === "Shift" || e.shiftKey === true) shiftAt = now();`（**必须含 `e.key === "Shift"`** —— 真机上它的 keydown 可能 shiftKey=false）；**keyup(221) 只记 true、绝不用 keyup 清 0**；beforeinput 不改（走同一 shifted）。
    **七用例实测（现状 → A/B → 去掉 keyup）**：Shift+Enter **1→0**；普通回车 1→1→1；**输入法提交+只补 keyup13 1→1→0（⇒ 候选 C 把 R-41 救回来的输入法场景砍掉，不要做 C）**；beforeinput 1→1→1；一次按键三条路 1→1→1（防重复在）；连按两次 2→2→2；Shift+Enter 后紧接着回车 2→**1**（不粘滞）。
    **判据**：Shift+Enter ⇒ 0 条 · 普通回车 ⇒ 1 条 · 输入法提交+keyup13 ⇒ 1 条（R-41 不回归）· beforeinput ⇒ 1 条 · 三条路同触发 ⇒ 1 条 · 连按两次 ⇒ 2 条 · Shift+Enter 后回车 ⇒ 1 条。**不碰**：R-41 链（含组字 1.5s 兜底 talk.js:227-238）· R-31 防连点 · R-36 状态机 · R-39 padding/`--sayline-h` · R-42 右缘热区。
    回归面：改 talk.js（约 4 行）⇒ 必须重出包（归 renderer）；复测主块 ①单聊 + ②群聊（同一公共入口，实测两处都中招）+ 跨块 ⑧频道页（授权框 talk.js:681 也走它）；建议真机用**实体键盘**打 Shift+Enter（0 条）/ 普通回车（1 条）/ 软键盘回车（1 条）。边界：不接主机、未验≠通过；证据 evidence/R45-定位-20260926/（sha256 8a3f280718de…），登记表 R-45 已改，提交 ea77539。

[2026-09-26 18:30:09] owner.me → pipeline.author | 全体? 否 | 话题:【派活】社媒整理平台#3 首档实现（第一刀：骨架 + 采集最小闭环 + 一行状态） | 必读:是 | #1458
    接 **`社媒整理平台` 第 3 步「首档实现」**（第一刀，别一次做完）。**开工先读**：`docs/05-计划-2026-09-26.md`（功能↔板块↔判据）、`docs/决定-2026-09-26-动态流与转文本.md`（两条已**暂定（可推翻）**）、`docs/06-部署对比-2026-09-26.md`（暂定 A 案）、`docs/01-功能清单-v0.1.md`、`docs/03-环境配方-小模型实测-v0.1.md`、`docs/功能介绍.md`。
    
    **已定的口径（照做，别自己改）**：
    - **动态流＝不做**（C5/C8 本版不做，写清不留空块）；
    - **转文本＝faster-whisper `base` int8**（CPU，无 GPU；**要**时间轴）；
    - **部署＝A 案起步**（SSH + `systemd --user`，无免密 sudo；`Linger=yes` 已实测）；
    - 三条都是**暂定、本人可推翻**：代码里别把选型写死，留一个**单点配置**（模型名、开关）方便回填。
    
    **这一刀的范围（只做这些，做完停下交报告）**：
    1. **项目骨架**：落 `/vol1/1000/airesults/social-archive/`（`app/` 源码 + `tools/` 脚本 + `docs/` + `evidence/`；**大件缓存进 `/vol1/1000/aicache/`，不许进家目录**）；
    2. **采集最小闭环（匿名可读那部分）**：按博主/分组 → 拉投稿列表 → 拉稿件元数据与播放器信息 → 落**本地库**（先 SQLite，字段能对上 05-计划 的判据）；**限速 + 退避**（同接口 4 分钟内 412↔200 是实测的，必须实现，别裸循环）；
    3. **一行状态 + 日志**：跑一次能打印"这次抓到 N 条、跳过 M 条、耗时 X 秒"；
    4. **一条端到端判据**：给定一个博主 id，能 **真跑到数据落库** 并能在 **本地页面**（先最简 HTML 列表即可）看到条目；把命令、原始输出、条数写进 `evidence/`。
    
    **先不做**（留给后续轮次）：转文本 T1–T6（先把"音频下载 + 落库"的接口留好、别接模型）、动态流 C5/C8、检索过滤 A4、导出分享 E1–E3、设置页 S2–S5、`systemd` 单元真装（先写 `env/` 配方与单元文件草稿，别动系统）。
    **红线**：**本地优先、少联网**（依赖装进 venv 或 `aicache/`；能跑本地就本地）；**不许把密钥/Cookie 写进代码或文档**；抓取要**限速**、尊重站点；产物与文档按归档硬约定落位（**不进 `/vol1/1000` 根目录、不进 mydoc**）。
    **交活**：走 `report` 通道（`--project 社媒整理平台 --seq 3 --from pipeline.author`）；报告 ≤8 行：标题 `【社媒整理平台-3 …】pipeline.author · HH:MM` + 做/证据/判据/等/成本（¥ 实价）；**详细说明留 `docs/`，报告给路径清单**。**这一刀做完停下**，下一步（转文本接线）等经理放行；边界＝不接主机、**未验 ≠ 通过**。
    ↳ 回复 [2026-09-26 18:38:59] pipeline.author: 第 3 步「首档实现」已交报告 #1467（走 report 通道，≤8 行）。**这一刀做完停手**，等放行。
    落位：`/vol1/1000/airesults/social-archive/`（app/ 六模块 + tools/run-sync.sh + env/ 单元草稿 + docs/07-实现说明-第3步.md）；**零安装**（只用系统 python3 标准库）；缓存在 aicache（模型目录已指过去），本机库在项目内 data/（已 gitignore）。
    真读数：`mid=7275647` → 5 组 / **154 条**真落库；`GET /c/7275647 → 200`、页面 154 行；一行状态「抓到 154 条、跳过 0 条、耗时 58.2 秒」；限速 1.5s 串行 + 退避（412→5s 重试→落库可重放）；**断点续跑**（某组第 2 页 code=-503 → 游标停 page=2，下轮续跑取回余 7 条）与**去重**（后两轮 new=0、条目恒 154）各验一轮。
    两件要你定的：① **C4 投稿列表匿名取不到**（三轮全是 412→-352 风控）——要它必须登录 Cookie，红线禁止存 Cookie，请定夺（改公开入口／本版放弃只做分组）；② 转文本接线等放行（`stt.enabled=False` 未动模型，`text_path/text_source/segments_path` 字段与官方字幕线索已备）。
    实跑顺手修掉：`http=200 code=-503` 原不算失败 ⇒ 已纳入退避；采集器遇非 0 code 只 return 不落库 ⇒ 已改为一律落 `sync_error`。COMMIT `1f0b65b` 已推；成本 ≈¥0.59。

[2026-09-26 18:39:54] owner.me → pipeline.author | 全体? 否 | 话题:【派活】社媒整理平台#4 转文本接线第一刀（base int8·带时间轴；单点配置不许写死） | 必读:是 | #1471
    接 **`社媒整理平台` 第 4 步「转文本接线（第一刀）」**。开工先读：`docs/05-计划-2026-09-26.md`（T1–T6 的判据）、`docs/决定-2026-09-26-动态流与转文本.md`（**转文本＝faster-whisper `base` int8，CPU；要时间轴**）、`docs/07-实现说明-第3步.md`（你上一刀的骨架与落库形状）、`docs/03-环境配方-小模型实测-v0.1.md`（实测数字：base 12–13.6× 实时 / 峰值 0.5–0.7GB / **自带时间轴**）。
    
    **这一刀的范围（只做这些，做完停下交报告）**：
    1. **音频取回**：给定一个已落库的 `item`，能取到音频（**先做能取到的路径**，取不到要落 `sync_error` 可重放，不许静默失败）；
    2. **转文本接线**：接 **faster-whisper base int8（CPU）**，**输出必须带时间轴**；结果落你已经留好的字段（`text_path` / `text_source` / `text_segments`）；`stt.enabled` 从 `False` 变成**可开关**（默认关、一条命令打开）；
    3. **单点配置**：模型名/线程数/开关写在**一处配置**里（**别把选型写死**，本人可能推翻成 SenseVoice）；
    4. **一条端到端判据**：给定 **1 个真实 item**，一条命令跑出「音频 → 文本（含时间轴）」并**落库**；把命令、原始输出、**耗时与峰值内存**、文本片段（前几行，带时间戳）写进 `evidence/转文本-20260926/`；
    5. **依赖安装**：走 **本地优先**（venv 放 `/vol1/1000/aicache/` 或项目内 `app/.venv`，按你上次的口径），**别装系统包、别动家目录**；模型文件下到 `aicache/`（**一次性**，记进 `env/` 配方，别每次任务联网）。
    
    **先不做**：批量转全部（先单条跑通）、SenseVoice 对照、字幕合并 T6、导出/检索/UI 大改、`systemd` 真装。
    **红线**：**不许存 Cookie/密钥**（C4 我已经定夺＝不做，见下）；抓取限速；产物落 `/vol1/1000/airesults/social-archive/`，大件缓存进 `aicache/`。
    **交活**：走 `report` 通道（`--project 社媒整理平台 --seq 4 --from pipeline.author`）；报告 ≤8 行：标题 `【社媒整理平台-4 …】pipeline.author · HH:MM` + 做/证据/判据/等/成本（¥ 实价）；**交完停手**；边界＝不接主机、**未验 ≠ 通过**。
    ↳ 回复 [2026-09-26 18:43:10] pipeline.author: 第 4 步「转文本接线（第一刀）」已交报告 #1473。**这一刀做完停手**。
    一条命令：`python3 -m app.cli transcribe --bvid BV1A34y1k7Ft --stt-on`（默认关，不加就拒绝）。链路＝`app/audio.py` 取音频（甲 playurl/dash 直下，乙 venv yt-dlp 兜底，取不到落 sync_error）→ `app/stt_worker.py` 在 STT venv 里跑 faster-whisper base int8 → `app/transcribe.py` 落 `text_path`/`text_source=whisper`/`text_chars`/`text_segments` + `state=text`。
    真读数：例 1 `BV1A34y1k7Ft`（17s）→ 1 段 12 字、转写 2.7s、峰值 596MB；例 2 `BV1sZ4y1d7U5`（41s，说话类）→ **10 段 216 字**、转写 9.5s、峰值 709MB；文本带 `[00:00:00 → 00:00:02]` 时间轴，`segments.json` 带 start/end/text；音轨转完即删（临时目录为空）。
    单点配置：`app/config.py` 的 `stt` 块（enabled/model/compute_type/cpu_threads/vad/models_root/venv_python）—— 本人若推翻成 SenseVoice，只改这里 + 加一个 worker，落库形状不动。**本刀零安装、零联网下载**（venv 与 base 权重第 1 步就在 aicache）。
    两条要你定的：① 批量转 154 条 / SenseVoice 对照（T5）等放行；批量前请定「串行 + 一次一条」的资源口径（宿主 7.8GB，单次配 4 线程约 0.6–0.7GB 峰值）。② 一个未验：本刀转写速度 **4.3–6.4× 实时**，低于第 1 步实测的 12–13.6×（候选：只给 4 线程 / 样本短 / 宿主另有负载），要不要专门做一轮对照。
    证据 `evidence/转文本-20260926/`（sha256 `c67b7c1f2238…`），说明 `docs/08-实现说明-第4步.md`，COMMIT `fd43a14` 已推。成本 ≈¥0.16（开工/收工两次打点相减）。

[2026-09-26 18:43:30] owner.me → pipeline.author | 全体? 否 | 话题:【派活】社媒整理平台#5 批量转文本·试点 5 条（串行一次一条；先试点后全量） | 必读:是 | #1477
    接 **`社媒整理平台` 第 5 步「批量转文本（受控）」**。第 4 步已判过（接线跑通：两例真条目、带时间轴、落库字段齐、零安装）。
    
    **你问的资源口径我定了（照做）**：
    1. **串行、一次只跑一条**（**不许并行**）；
    2. `cpu_threads` 保持 **4**（本机 8 核、**内存只有 7.8GB**，重活必须克制）；
    3. **先跑试点 5 条**（挑不同长度：短/中/长各来一点），**看耗时与峰值内存曲线**再决定要不要跑全量 154 —— 试点数据先交报告，**全量我另放一条**，别一口气跑完；
    4. **跑之前先确认宿主没有别的重活**（不许同时开模拟器/其它大批量任务）；**一发现内存压力就立刻停**并把现场写进证据；
    5. 失败**一律落 `sync_error` 可重放**，不许静默跳过；音轨**转完即删**（照第 4 步的做法）。
    
    **判据（试点这一段，逐条给真读数）**：① 试点 **5 条**：成功 N 条（**≥4**）、失败 M 条（都要有可重放记录）；② **每条都有时间轴**（`segments` 的 start/end 非空）；③ **峰值内存**（每条 + 全局最高，用 `/usr/bin/time -v` 或 `/proc` 读数）；④ **耗时**（每条秒数与"× 实时"倍数，与第 4 步对照）；⑤ 页面/接口能读回文本（给一条命令 + 回显）；⑥ 落库字段齐（`text_source/text_chars/text_segments/state=text`）。
    **顺带把第 4 步那个未验说清**（**不用新做实验，就报事实**）：你实测 4.3–6.4× 实时 vs 第 1 步 12–13.6×，**候选原因写清即可**（线程数/样本短/宿主负载），**别下结论**；如果试点里有更长的音频，就顺手把这个差值的趋势记一笔。
    **先不做**：SenseVoice 对照（T5）· 官方字幕合并（T6）· 导出/检索/UI 大改 · systemd 真装。
    **交活**：走 `report` 通道（`--project 社媒整理平台 --seq 5 --from pipeline.author`）；报告 ≤8 行：标题 `【社媒整理平台-5 …】pipeline.author · HH:MM` + 做/证据/判据/等/成本；**试点交完停下等放行跑全量**；边界＝不接主机、**未验 ≠ 通过**。
