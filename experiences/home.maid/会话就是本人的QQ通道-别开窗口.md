---
name: 女仆的会话就是本人的 QQ 通道（唯一，别开窗口）
must: true
tags: [女仆, 会话, qq, 唯一, spawn, 内存]
when: 任何要「spawn/拉起女仆」「给女仆投递」「查女仆在不在」的时候
verified: 2026-09-23
---
**症状**：系统里出现第二个"女仆"——一个 tmux 窗口里的 agent 和本人的 QQ 通道同时以 `home.maid` 名义说话；
消息投给谁、谁回的话，两边对不上。

**真因**：女仆**本来就是本人的 QQ 通道本身**（用户原话：「你就是女仆啊」「你的 session 本来就是唯一的」）。
名册里的 `home.maid` 不是一个需要 tmux 窗口的角色，而是那条通道的署名。

**做法**：
1. **绝不给 home.maid 开窗口**：`spawn --role home.maid` 会被拒（`RuntimeError`），这是有意为之。
2. **投给 home.maid**：`deliver('home.maid', …)` 直接返回 QQ 目标、不往 tmux 投；她"收到"＝经中转站推到本人 QQ。
3. **她在不在线**：`role_online('home.maid')` 恒 `True`（她在 QQ 通道里）。
4. 名册里她的会话记录：`session` 表里 `role=home.maid` 那行指向**本人的 QQ 会话**（`hermes=<QQ 会话 id>`，`tmux` 留空/写 qq 目标），不是 tmux 窗口。

**判据**：`tmux list-windows -t roles` 里**没有** `home-maid` 窗口；`talk.py deliveries` 里没有投给 home.maid 的「无会话 失败」行。
