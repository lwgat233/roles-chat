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
