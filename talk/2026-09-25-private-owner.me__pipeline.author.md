[2026-09-25 09:22:50] owner.me → pipeline.author | 全体? 否 | 话题:【派活】hermes-pocket-R41 第 1 步 定位（App 输入框回车=发送） | 必读:是 | #1314
    接 hermes-pocket-R41 第 1 步「定位与改法」（只定位、只出改法，不写代码）。
    
    **来源**：本人 2026-09-24 当场（App 频道里跟人对话时）「**他无法输入 enter 键表示确认**」。登记表 R-41 有原文与初步定位。
    
    **我已经先查过的（省你时间，直接验证+补全，别重头挖）**：
    - 投递侧没问题：App 走 `Bridge.kt:772 talk.say` → `talk.py say` → 平台 `deliver()`，那条路上有**双回车兜底**（粘完 0.8s 回车 + 0.6s 补一次）＋ O-1 的「对方会话消息条数 +1」确认 ⇒ **不是"字躺在对方输入框"**那类。
    - 输入侧可疑：App 只在 `keydown` 里判 `e.key === 'Enter'`（**群聊 `talk.js:459`**、**单聊 `talk.js:1029`**），而安卓输入法的「回车/发送」键**经常不触发 keydown**（有的只给 `keyCode=229`）；输入框**没设 `enterkeyhint`**（全仓 grep 0 处）。
    
    **要交（≤8 行、新闻格式、¥实价）**：
    1) **量清现状**（文件:行）：两个输入框（群聊 `gin` / 单聊 `inp`）现在各挂了什么事件、`Enter` 走哪条路、**有没有别的输入框漏挂**（频道页/设置页/其它 `talk-askin`）；`Bridge.kt`/`deliver()` 侧有没有二次确认；
    2) **判定**：本地台能不能**复现**"按回车没反应"？（用 CDP 派发**真触摸/真键盘事件**，如果派发 `keydown` 有反应、而派发 `keyCode=229`/`beforeinput` 无反应 ⇒ 就是 IME 那条路）；**不能复现就如实说"本地台复现不了、需真机"**，别硬凑结论；
    3) **改法**（文件:行，四条都要给）：① 输入框加 `enterkeyhint="send"`；② 补 `keyup` + `keyCode===13` 兜底；③ `beforeinput`/`inputType==='insertLineBreak'` 再兜一层；④ 与「长按/Shift 换行」怎么共存（别把换行弄没了）；并说明三条兜底**会不会重复发送**（同一段文字发两次的防护）。
    4) 代价与回归面：要重出的包 + 要复测的板块（照 SPEC §10 点名；判据建议＝**真机按输入法回车能发出消息**（App 出现自己气泡 + 对方会话条数 +1）、换行仍可用）。
    边界：不接主机、**未验 ≠ 通过**；证据进 `evidence/R41-定位-20260925/`；标题【hermes-pocket-R41-1 …】+ 4 行 + 成本¥。
    ↳ 回复 [2026-09-25 09:26:02] pipeline.author: R-41 第 1 步已交报告 #1315（8 行）。
    **先答"能不能复现"**：机制能复现 —— 真 Enter 能发（群聊 shout=1、单聊 say=1），而「输入法提交（insertText：只有 beforeinput/input、没有 keydown）＋只补 keyup」和「只派 beforeinput」**都发不出去（=0）**；事件序：真 Enter＝`keydown(13)→keypress(13)→beforeinput(insertLineBreak)→keyup(13)`，输入法提交＝`beforeinput(insertText)→input(insertText)`（**全程无 keydown**），组字＝`compositionstart→compositionupdate→beforeinput(insertCompositionText,isComposing)→input`。**但真机各输入法到底给哪些事件，本地台给不出答案** —— 我没写"已复现"，只给机制与改法。
    接线现状（你给的初步定位都对，我补全）：群聊 `#tk-shoutin`（talk.js:492-509）与单聊 `#tk-sayin`（talk.js:1058-1083）都**只挂 keydown(Enter)**、**enterkeyhint 全仓 0 处**；**另有一处漏挂**：授权回复框（talk.js:598-620 `.tk-askin`）**连 Enter 都没挂**，只能点发送键；投递侧复核 `Bridge.kt:772 talk.say` → `talk.py:1039 deliver()`（paste-buffer + Enter + 双回车兜底）没问题。
    改法四条（文件:行）：① `enterkeyhint="send"` → talk.js:492-494 / 1058-1060（＋授权框 598-600）；② `keyup` + `keyCode===13` 兜底；③ `beforeinput`/`input` 判 `insertLineBreak|insertParagraph` 兜底（唯一能救"完全没有按键事件"的路）；④ 换行共存两案待拍：**A** 保持单行 input、三条兜底都加 `!shiftKey`（Shift+Enter 不发送也不换行，最小改动）／**B** 换 `<textarea rows=1>`+自动长高（先例 app.js:1892-1893），Enter 发送 / Shift+Enter 真换行，代价＝改动面大。
    **候选接线实测（页面注入、工程未动）**：keyup 兜底→1 次、beforeinput 兜底→1 次、**一次按键三条路都触发→1 次**（防重复生效）、连按两次→2 次；⚠ **抓到 Shift+Enter 被 beforeinput 兜底误发 1 次**（单行 input 没有换行，insertLineBreak 被当成发送）⇒ 每条兜底都必须带 `!shiftKey`。
    防重复：每框一个 `sentAt` 时间窗（建议 400ms）＋发完清空 value（现有 fire() 已清）；⚠ 输入法提交那条路 value 非空，所以时间窗不能省。仓库里已有"两边都接管＝一次回车发两遍（本地实测抓到过）"的先例注释（app.js:1901-1903），出包后请让 tester 专门验一次。
    回归面：改 talk.js ⇒ 必须重出包（归 renderer）；复测板块 主块 ②群聊 + ①单聊（判据＝真机按输入法回车能发出：出现自己气泡＋对方会话条数 +1；换行按 A/B 口径；同一次回车不出两条），跨块 ⑧频道页（授权框也补了）。建议真机至少两种输入法并记下事件序列 —— 这决定 ②③ 两条兜底够不够。
    边界：不接主机、未验≠通过；证据 evidence/R41-定位-20260925/（sha256 d6dc99348e00…），登记表 R-41 已改，提交 f43b23a。
