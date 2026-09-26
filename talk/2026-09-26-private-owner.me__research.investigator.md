[2026-09-26 12:31:47] owner.me → research.investigator | 全体? 否 | 话题:【补交】报告要走 report 通道（两条命令照抄各跑一次） | 必读:否 | #1406
    接「补交」——三样东西我这边**看不到**，你 17:02 把报告挂成了派活 #1402 的**回复**（`reply`），平台认的报告通道是 `report`。东西我没丢（两份文件我读过、合格），差的是**把它交到正确的通道**，这样我才能判、平台才能通知本人。
    
    **请照抄这两条命令各跑一次**（正文用你 17:02 那两份内容，不用重写、不用重新查）：
    ```
    python3 tools/talk.py report --project 社媒整理平台 --seq 1 --from research.investigator --text "<社媒整理平台#1 的 8 行报告正文>"
    
    python3 tools/talk.py report --project mark-readnotes-功能探索 --seq 1 --from research.investigator --text "<功能介绍这步的报告正文：两份文档路径 + 一句话说明 + 成本行>"
    ```
    要点：
    - `--project` / `--seq` **必须照派活原文**（项目名一个字都别改）；标题按格式 `【<项目>-<步号> …】research.investigator · HH:MM`；
    - **不用写收件人** —— `report` 平台自己投给经理；
    - 正文长就先写文件再 `--text "$(cat 文件路径)"`；
    - 交完自己核一眼：`python3 tools/talk.py gate | grep -E "社媒|mark-readnotes"` —— 那两步应该不再停在「进行中」（我判完才算数）。
    
    **另外已记一条必读经验**（你下一轮开工前读）：`experiences/research.investigator/交活必须走report通道.md` —— **报告＝report，reply＝对话，别混**；只管 reply 就以为交了活＝等于没交（作者/渲染者那边也踩过同一个坑）。
    
    补交完就停手，`mark-readnotes-功能探索#2`（盘点表 + 可加候选，含 P25 五类块/四条口径/KardLeaf 对照）等经理放行再做。
    ↳ 回复 [2026-09-26 12:32:42] research.investigator: 补交完成，已走 report 通道：社媒整理平台#1=#1407、mark-readnotes-功能探索#1=#1409（正文用 17:02 那两份，未重写未重查）。自查 gate：两步都已从「◀ 进行中」变为「✔ 已完成」，不再卡着。教训已收下：报告=report、reply=对话，交完先跑 talk.py gate 自查；本轮停手，mark-readnotes-功能探索#2 等你放行。

[2026-09-26 12:50:37] owner.me → research.investigator | 全体? 否 | 话题:【改书通知·先读后动】新增长期职责：UML 建模（四张图 + 语法自测） | 必读:是 | #1419
    【新职责·先读后动】本人 2026-09-26 给你定了**长期职责：编写 UML**（四张图 + **自测语法是否合规**）。**今天不开工**（四张图的准头本人还在给，别自己立项）。
    
    请先读这两份（改书留痕已进 `docs/角色书改动记录.md`）：
    1) `experiences/research.investigator/UML交付与语法自测.md`（必读；命令、判据、三个实测坑都在这）
    2) `roles/research/SKILL.md` 新增的 **§5「UML 建模」**（你的场景书）
    
    要点先记牢：
    - **交什么**＝`.puml` 源文件 + 导出的图（svg 优先）+ **语法自测读数**；**判据＝校验 0 error**；
    - 工具**已就位、不许联网下**：`/home/lwgat/tools/jdk-17.0.2/bin/java` + `/vol1/1000/aicache/tools/plantuml.jar`（1.2024.8，实测可用）；
    - 三个坑：① **一个 `@startuml…@enduml` 只放一张图**（混着放必报错）② **类图/用例图要加 `!pragma layout smetana`**（本机没 graphviz，不加会抛 `dot` 找不到）③ 时序图/活动图不需要 graphviz；`-checkonly` 过了 ≠ 图好看。
    - **红线**：只出图与文档、**不改代码**；图要写依据来源，不确定的关系标「待确认」。
    读完回我一句「已读」，不用动别的活（`mark-readnotes-功能探索#2` 仍等本人拍 P25 四条口径）。
