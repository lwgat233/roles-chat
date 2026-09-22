---
name: 消毒别按 token 做，会把成对的行内 HTML 拆散
must: false
tags: [渲染, 消毒, 白名单, 行内HTML]
when: 改预览的 HTML 白名单 / 消毒逻辑时
verified: 2026-09-22
---
**症状**：`<span style="color:red">字</span>` 渲染成**空 span + 文字被挤出去**，颜色也没了。

**真因**：逐 token 消毒会把成对的行内标签拆开（开标签过一个、内容过另一个、闭标签第三个）。

**做法**：**整段**在游离容器里解析 → 对整个子树做白名单过滤 → 再挂进页面；
**KaTeX 的输出要整棵放行**（按标签逐个白名单会把 `.katex` 家族吃掉）；
URL 只放行 `http/https/mailto` 与相对路径。

**判据**：`<span style>` 的行内样式保留（`getComputedStyle` 拿到 `rgb(255, 0, 0)`）、
`script/iframe/on*` 被剥掉、公式节点数量不变。
