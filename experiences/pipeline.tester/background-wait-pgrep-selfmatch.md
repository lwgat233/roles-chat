---
name: 后台任务"在跑"不等于在跑：pgrep -f 会匹配到自己
must: true
tags: [后台, 验收, 等待, 自伤]
when: 写「等另一个任务跑完再开始」的后台链时
verified: 2026-09-22
---
**症状**：后台链里写 `while pgrep -f "verify-board.sh notes"; do sleep 5; done` 想等另一个板块收工，
结果**永远等不到**，35 分钟一条判据都没跑（`process poll` 的 `output_preview` 是空的）。

**真因**：`pgrep -f` 比的是整条命令行，而这条 `while` 所在的 bash 进程自己的命令行里
就含这串字符 —— 它在等自己。

**做法**：模式写成拆开字面量的样子（`pgrep -f "[v]erify-board.sh notes"`），或匹配真正干活的子进程
（`pgrep -f "boards/notes.sh"`）；**判进度要看有没有输出，别只看 status=running**。

**判据**：等到的下一个任务确实开始产出（日志出现第一批 OK/FAIL 行）。
