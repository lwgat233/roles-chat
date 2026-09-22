[2026-09-23 07:31:40] owner.me → pipeline.tester | 全体? 否 | 话题:【派活】第 4 步 复测：装渲染者的包，三处读数对账 | 必读:是 | #833
    接 hermes-pocket-测试轮 第 4 步「复测」（第 3 步渲染出包已判完成）。
    
    复测对象 = **渲染者出的那一版包**（不是作者自出的那个，作者那个只算过程材料）：
    · 路径：apk/测试版/hermes-pocket-渲染出包-复测对象-20260923.apk
    · 整包 sha256：ba5231f7acacb77559dd5adc9355b14ecadb71465aa3983c6f0bde7e6bd77e49
    · 包内 assets/build-info.json：testVersion = unified-20260923-012200，builtAt = 2026-09-23 01:22 CST
    · 包内 ui/talk.js sha256 应为 4a5f584c7b2c59fcd6a7ff0a1747bdcdb5b990dc9c42318b1a6e65645694d60a
    
    你要做的（三处读数互相对账）：
    1) **先对整包 sha256**（别装错版本），再装到无头模拟器上。
    2) 读**设置页「构建版本」那一行** + **终端横幅**。
    3) 与**包内 assets/build-info.json** 对一遍；复核工具可直接用：
       python3 source/hermes-pocket/tools/stamp-build.py --verify apk/测试版/hermes-pocket-渲染出包-复测对象-20260923.apk
    
    口径（照写，不许放宽）：
    · 本人已定**不接主机**（不动 NAS 的 authorized_keys）；
    · 第 1 步那 5 条（点角色→信息窗 / 气泡 / 删会话 / 切会话 / 开左栏收起会话键）本轮**未验 —— 未验 ≠ 通过**，照这个口径记；
    · 判据通过与否由你说，作者/渲染者自己跑的读数不算。
    
    交付用交付报告（四行缺一行会被拒）：
    python3 tools/talk.py report --project hermes-pocket-测试轮 --seq 4 --from pipeline.tester --text "做了什么:… 证据:… 判据:… 依赖:…"
    
    附：你昨晚没收到 #716~#719 是投递 bug（字卡在你输入框里没提交；女仆已修，并给你窗口补了回车），那几条是旧的控制公告，**不用补动作，以本条为准**。
