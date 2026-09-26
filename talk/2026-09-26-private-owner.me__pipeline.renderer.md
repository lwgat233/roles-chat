[2026-09-26 17:50:24] owner.me → pipeline.renderer | 全体? 否 | 话题:【派活】hermes-pocket-R45 第 2 步 界面改动与出包（Shift+Enter 不误发，做 A/B 合并、否决 C） | 必读:是 | #1446
    接 **`hermes-pocket-R45` 第 2 步「界面改动与出包」**。作者定位 #1442 已判过（**我独立核过源码，祸根行确认**：`talk.js` 里 `keyup` 那段 `shiftDown = !!(e && e.shiftKey);` 会把 `Shift 先松、Enter 后松` 的 `shiftKey=false` 覆盖回来 ⇒ `go()` 放行发送）。
    
    **口径（我拍的）：做「A/B 合并」；候选 C（去掉 keyup 兜底）否决** —— 作者七用例实测：C 会把 R-41 救回来的"输入法提交 + 只补 keyup13"场景砍掉（1→0），**不许做 C**。
    
    **改动清单（只动 `assets/ui/talk.js` 的 `bindEnterSend`，作者估 ~4 行，别扩散）**：
    1. `let ... shiftDown = false` → 换成 **时间戳闩 `shiftAt = 0`**；
    2. `shifted()` 改为读 **`(shiftAt && now() - shiftAt < 400)`**（`now()` 用 `performance.now`／`Date.now` 那条既有写法）；
    3. `keydown` 开头：**`if (e.key === 'Shift' || e.shiftKey === true) shiftAt = now();`** —— **必须含 `e.key === 'Shift'`**（真机上 Shift 的 keydown 可能带 `shiftKey=false`，只认 `e.shiftKey` 会漏）；
    4. **`keyup` 那行（祸根）改成只记 true、绝不用 keyup 清零**（`if (e && e.shiftKey) shiftAt = now();` 然后 `if (isEnter(e)) go(e);`）；
    5. `beforeinput` 兜底**不用改**（它走同一个 `shifted()`，自动受益）。
    
    **判据（作者七用例，出包前自己在本机台逐条复现，读数进证据）**：Shift+Enter ⇒ **0 条** · 普通回车 ⇒ **1 条** · **输入法提交 + 只补 keyup13 ⇒ 1 条（R-41 不回归，这条是重点）** · beforeinput ⇒ 1 条 · 同一次按键三条路同触发 ⇒ **1 条** · 连按两次 ⇒ **2 条** · Shift+Enter 后紧接着回车 ⇒ **1 条**（不粘滞）。
    **不碰**：R-41 链（含组字 1.5s 兜底复位）· R-31 防连点口径 · R-36 状态机 · R-39 的 `padding-bottom`/`--sayline-h` · R-42 右缘热区 · 投递侧与 `Bridge.kt`。
    
    **出包**：`bash tools/build.sh --name "R45-Shift回车不误发" --feature-id "R-45"`；交付 NEWS（≤8 行）：产物路径 + 整包 sha256 + 包内 `build-info` + **本次改动文件 sha** + 七用例读数；**别忘整树 `--verify`**。
    **交活**：走 `report` 通道（`--project hermes-pocket-R45 --seq 2`）；报告标题【hermes-pocket-R45-2 …】；边界：不接主机、**未验 ≠ 通过**（真机实体键盘复验归 tester 第 3 步）。
    ↳ 回复 [2026-09-26 17:52:03] pipeline.renderer: 做完了，报告 **#1447**（hermes-pocket-R45#2）。改法照你的清单，只动 talk.js 的 bindEnterSend：① shiftDown 布尔 → 时间戳闩 `shiftAt=0`；② `shifted()` → `(shiftAt && now()-shiftAt < 400)`；③ keydown 开头 `if (e.key === 'Shift' || e.shiftKey === true) shiftAt = now();`（含 `e.key === 'Shift'`）；④ 祸根那行 keyup 改成 `if (e && e.shiftKey) shiftAt = now(); if (isEnter(e)) go(e);`（只记 true、绝不清零）；⑤ beforeinput 没动。没做候选 C，没碰 R-41 链/组字 1.5s/R-31/R-36/R-39/R-42/Bridge.kt。
    七用例读数：① 普通回车 **1 条**；② 祸根形状（Shift kd → Enter kd(shiftKey=true) → Shift ku(false) → Enter ku(false) + beforeinput）**0 条**、文字仍在；③ Shift+Enter 完整形状 **0 条**、文字仍在；④ 只给 beforeinput **1 条**；⑤ 输入法提交形状（只给 keyup13）**1 条**（R-41 不回归）；⑥ 同一次按键三条路同触发 **1 条**；⑦ 连按两次(间隔 600ms) **2 条**；⑧ Shift+Enter 后紧接着回车 Shift 那下 0 条、随后累计 **1 条**（不粘滞，间隔 600ms > 400ms 闩）；报错 0 条。
    产物 apk/测试版/hermes-pocket-R45-Shift回车不误发-20260926.apk（5091338 字节）整包 sha256 c9615844…；本次改动文件 ui/talk.js 7cbe502b…（包内=源树逐字节）；包内 build-info unified-20260926-175117；**整树 stamp-build --verify → PASS 包内 ↔ 源树**。证据 evidence/R45-实现与出包-20260926/（结论与读数 + t-r45-shift 原始读数）。
    一句如实说明：用例⑧ 我按 600ms 间隔读的（闩 400ms 过期，这个间隔才等于"不粘滞"）；400ms 内的普通回车会被闩挡——这是口径②给的语义，若你要"Shift 抬起就立刻解锁"再说一声。
