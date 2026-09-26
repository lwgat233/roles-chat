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

[2026-09-26 18:31:34] owner.me → pipeline.renderer | 全体? 否 | 话题:【派活】hermes-pocket 汇总包 第 2 步：出 hermes-pocket-汇总-20260926.apk + 轮次对照清单 | 必读:是 | #1462
    接 **`hermes-pocket-汇总包` 第 2 步「出 09-26 汇总包」**（本人当场问的：「打包成 apk 了吗」—— 他要的是**总的那个包**：一个包含当轮全部已收尾改动的汇总包 + 清单，不是单轮包）。
    
    **从当前源树出**：`apk/测试版/hermes-pocket-汇总-20260926.apk`（名字照这个）。
    （背景：现状最新包是单轮的 `hermes-pocket-R45-Shift回车不误发-20260926.apk`（5091338 字节 · sha256 `c9615844…`），源树里没有比它更新的文件 ⇒ 内容上已含当轮改动，但名字是单轮的、也没有汇总清单。）
    
    **交付四样（缺一不算交）**：
    1. **整包 sha256 + 字节数**（真跑 `sha256sum`／`stat`，别转述）；
    2. **包内 build-info**：版本串（`unified-…`）与 `featureId`（本轮用 `汇总-20260926`）；
    3. **对账 PASS 的原始输出**：自己跑 `python3 tools/stamp-build.py --verify`（整树），**贴原始输出**（不要写"PASS"四个字就算）；
    4. **清单**（本人要的"里面有什么"）：逐条列 **hermes-pocket 各轮/需求** —— `已含 / 不含 + 原因`。
       - 基线＝上一版汇总包 `hermes-pocket-汇总-20260924.apk`（含 R25/R26/R27/R29/R31~R37）；**它之后的全部**都要在这份清单里逐条点名：R39 · R40 · R41 · R42 · **R43** · R45（以及 R28/R30/R32~R38 的处置）。
       - **R43 特别注意**：那是**平台侧**修复（`talk.py say()` 带回执 + CLI 打 JSON），**App 端一行未改** ⇒ 清单里写「**不含（App 侧无改动）**＋原因」，别让他以为漏做。
       - **R38** 判的是「**非缺陷**」⇒ 写明「**本来就不该有新包**」；R30 口径未定（未改代码）；R28 照实说（查登记表写原因）。
       - 归档口径：清单文件落 `evidence/汇总-20260926/清单-轮次对照.txt`。
    
    **口径**：汇总包＝**当前源树出的整包**（含当轮全部已收尾改动），不是重新实现；**不许**在出包时改任何源文件；单轮包**保留**（当证据/回滚用，交付只看汇总包）。
    **出完报我**：走 `report` 通道（`--project hermes-pocket-汇总包 --seq 2`）；标题【hermes-pocket-汇总包-2 …】+ 做/证据/判据/等/成本；**边界**：不接主机、未验 ≠ 通过。
    ↳ 回复 [2026-09-26 18:32:58] pipeline.renderer: 出好了，报告 **#1464**（hermes-pocket-汇总包#2）。四样齐：
    ① `apk/测试版/hermes-pocket-汇总-20260926.apk`（**5091338 字节**，真跑 stat）整包 sha256 **f50cc6b230c06c105c60470c90b0e52972fc471fcbbcb4599c66c84b5faaa91b**（真跑 sha256sum）。
    ② 包内 build-info：`testVersion=unified-20260926-183153` · `featureId=汇总-20260926` · `builtAt=2026-09-26 18:31 CST`。
    ③ 整树 `stamp-build.py --verify` 退出码 0；原文 79 行全量落 `evidence/汇总-20260926/verify-整树-原始输出.txt`（sha256 `cb956fe13a60…`，**PASS 1 处 / FAIL 0 处**）。末段原文照贴：「  ✓ assets/ui/vendor/xterm.js ／ 源  1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495 ／ 包内1f991ac3b4b283ebf96e60ae23a00a52765dd3a2e46fa6fdda9f1aab032f7495」＋「PASS 包内 ↔ 源树 对账」。
    ④ 清单在 `evidence/汇总-20260926/清单-轮次对照.txt`：**已含**＝基线 R25/R26/R27/R29/R31~R37（本轮无新改动、不是漏）＋本包新增 **R39 / R40 / R41 / R42 / R45**（逐条带源码标记与证据目录）；**不含**＝**R43**（平台侧 `tools/talk.py` 的 say() 回执＋CLI JSON，**App 一行未改** ⇒ 没有可含的东西）· **R38**（判「非缺陷」⇒ 本来就不该有新包）· **R28**（未做：与 R26 重叠，只到定位、第 2/3 步 ended）· **R30**（未做：口径未定、未改代码）· R32~R37（已在 09-24 基线包里）；顺带点名 **R46**（新登记「首屏双份渲染」，R39-3 真机抓到、非本轮引入，未修）。
    口径守住：**零源码改动**（只出包）、单轮包全部保留、本轮没重跑测试；未验照写（5 条不接主机项、R29/R31 真触摸、R27 探测耗电、R30 设备真断网）。命名说明：用 `--name 汇总`（build.sh 自动补日期）才得到你要的 `hermes-pocket-汇总-20260926.apk`；照 `--name 汇总-20260926` 会变成 `…-20260926-20260926`。
    （报告里我把平台侧路径笔误成 `tool/talk.py`，正确是 `tools/talk.py`，以此条为准。）
