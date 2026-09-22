#!/usr/bin/env bash
# roles-chat 一条命令搭建 —— 换机器 / 换地方：把整个目录拷过去，跑这个就行。
# （"定型"的一部分：不依赖原路径，库丢了也能从 talk/*.md 重建）
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export ROLES_CHAT_HOME="${ROLES_CHAT_HOME:-$HERE}"

command -v python3 >/dev/null || { echo "缺 python3，先装上"; exit 1; }
command -v tmux    >/dev/null || echo "提示：没装 tmux —— 角色会话（spawn/deliver/capture）用不了，其它命令照常"

mkdir -p "$HERE/talk" "$HERE/evidence" "$HERE/experiences"

echo "① 建库与角色"
python3 "$HERE/tools/talk.py" init

echo "② 有日志就从日志重建索引（文本是权威源）"
if [ -n "$(ls -A "$HERE/talk" 2>/dev/null)" ]; then
  python3 "$HERE/tools/talk.py" rebuild
else
  echo "   （talk/ 里还没有日志，跳过）"
fi

echo "③ 经验库自检"
python3 "$HERE/tools/exp_index.py" check

echo "④ 跑一遍权限自检（31 条判据）"
python3 "$HERE/tools/talk.py" selftest | tail -2

cat <<EOF

搭好了。ROLES_CHAT_HOME=$ROLES_CHAT_HOME

常用（把 \$R 换成 $HERE）：
  \$R/tools/talk.py watch                     # 实时看公共频道（私信只有你本人看得到，带 🔒）
  \$R/tools/talk.py board                     # 一屏看全部对话
  \$R/tools/talk.py spawn --role pipeline.tester --profile tester   # 给角色开固定会话（幂等）
  \$R/tools/talk.py deliver --role pipeline.tester --text "做这个"  # 投递
  \$R/tools/talk.py inbox  --role pipeline.tester                   # 角色看自己该回的
  \$R/tools/exp_index.py must --role pipeline.tester                # 说身份后必读的经验
  \$R/tools/talk.py gate --project <项目>                            # 经理看阶段走到哪
EOF
