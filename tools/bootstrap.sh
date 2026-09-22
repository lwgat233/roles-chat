#!/usr/bin/env bash
# 空白机器上一条命令把服务端搭起来（**从 GitHub 拉取**）
#   bash <(curl -fsSL https://raw.githubusercontent.com/lwgat233/roles-chat/master/tools/bootstrap.sh)
# 或本地：bash tools/bootstrap.sh [目标目录]
set -e
REPO="${ROLES_CHAT_REPO:-https://github.com/lwgat233/roles-chat.git}"
DEST="${1:-${ROLES_CHAT_HOME:-$HOME/roles-chat}}"
PROXY="${ROLES_CHAT_GIT_PROXY:-127.0.0.1:7890}"
echo "① 拉取 $REPO → $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --ff-only || true
else
  mkdir -p "$(dirname "$DEST")"
  git clone "$REPO" "$DEST" 2>/dev/null || {
    echo "   直连不行，走本机代理 $PROXY 再试"
    git -c http.proxy="http://$PROXY" -c https.proxy="http://$PROXY" clone "$REPO" "$DEST"
  }
fi
echo "② 装（建库 / 从 talk/*.md 重建 / 经验与权限自检）"
cd "$DEST" && bash install.sh
echo "③ 起中转站（常驻）"
bash tools/install-relay.sh || true
echo
echo "好了。服务端在：$DEST"
echo "  自检：cd $DEST && python3 tools/talk.py doctor"
