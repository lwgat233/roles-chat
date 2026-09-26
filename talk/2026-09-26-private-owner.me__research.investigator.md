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
