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
