[2026-09-23 00:43:35] owner.me → pipeline.author | 全体? 否 | 话题:【派活】修 F1：版本串每包更新 | 必读:是 | #724
    你接 hermes-pocket-测试轮 第 2 步「按测试结果修」（第 1 步已判完成，报告 #712）。
    
    要修的（测试者报的 F1，原文见 #712）：
    · 设置页「构建版本」那行要能对上**本包**：现在页面 HP.BUILD=unified-20260921c、包内 build-info.json builtAt=2026-09-22 00:35，而这个包实际 23:33 出、还含今晚才改的 talk.js → 版本串没随本轮改动更新。
    · 做法：HP.BUILD 与 build-info.json 每次打包自动写入（版本串 + 打包时间），别手写常量。
    · 证据要能对上：改完的包内 assets/ui/talk.js 与 build-info.json 的读数 + 页面读数的对照。
    
    两条硬约束：
    1) **本人已定：不接主机**（不动 NAS 的 authorized_keys）。所以测试者有 5 条（点角色→信息窗、气泡、删会话、切会话、开左栏收起会话键）本轮**没验到**，按「未验」记，**不许当通过**——你交付时也要照这个口径写。
    2) 交付用交付报告：python3 tools/talk.py report --project hermes-pocket-测试轮 --seq 2 --from pipeline.author --text "…"，四行缺一行会被拒（做了什么/证据/判据/依赖）。
    
    依赖：修完并出包后，第 3 步「复测」归测试者（还没放行，等我 gate-done 第 2 步）。
