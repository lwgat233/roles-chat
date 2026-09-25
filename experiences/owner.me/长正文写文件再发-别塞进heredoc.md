---
name: 长正文一律写文件再发 —— 别把长中文塞进 heredoc 里的 python 字符串
must: true
tags: [经理, 工具坑, heredoc, python, 派活, 报告, 省事]
when: 要发长正文（派活/判词/告知/汇总）时；要写长中文文本时
verify: 待发正文先落到 /vol1/1000/aicache/tmp/*.txt，再由脚本读取发送；不再出现 SyntaxError/反引号被吃/参数错位
---

**教训（2026-09-24/25 反复踩）**：把**长中文正文**直接塞进 `python3 - <<'PY'` 的字符串里，已经连环出过四类事故：

1. **SyntaxError: invalid character '＝' / "Perhaps you forgot a comma?"** —— 长串里混用中英文引号与全角符号，解析直接失败；
   **脚本整段没执行**（例如 R42-2 派活、R43-1 派活两次都没发出去，白等一轮）。
2. **反引号被 shell 吃掉** —— 正文里写 `` `文件名.md` `` 会被当命令替换，正文被截断（女仆那条「旧 已删除」就是这么来的）。
3. **参数错位** —— 用 `list.insert()` 往 `talk.py send` 的参数里插 `--must-reply`，把 `--to` 的值挤走，
   报 `argument --to: expected one argument`。
4. **正文里的 `&`** 会被终端当后台符，整条命令被拦。

**规矩**：
- 长正文（超过一两行、含中文标点/反引号/`&`/`（）`）**先 `write_file` 落到 `/vol1/1000/aicache/tmp/<名>.txt`**，
  再用脚本 `open(path).read()` 读出来发；脚本里**不再内联长串**。
- 拼 `talk.py` 参数用 **`args.append(...)` 追加**，别用 `insert(固定下标)`。
- 发完**读回 `delivery` 确认 `ok=1`**（本文第 1 条那两个派活就是靠读回发现的）。
- 正文里要写反引号/`&`：走文件就没事；非走 shell 不可时加引号保护。
