#!/usr/bin/env bash
# 安装常驻中转站（systemd --user）：以后不用手动跑 relay-once
#   bash tools/install-relay.sh          安装并启动
#   bash tools/install-relay.sh remove   卸载
set -e
HERE="$(cd "$(dirname "$0")/.." && pwd)"
UNIT="$HOME/.config/systemd/user/roles-relay.service"
PY="$(command -v python3)"
if [ "${1:-}" = "remove" ]; then
  systemctl --user disable --now roles-relay.service 2>/dev/null || true
  rm -f "$UNIT"; systemctl --user daemon-reload
  echo "中转站已卸载"; exit 0
fi
mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<EOF
[Unit]
Description=roles-chat 中转站（按种类把消息投给该收的角色，并收他们的终端回答）
[Service]
Type=simple
WorkingDirectory=$HERE
ExecStart=$PY $HERE/tools/talk.py relay-daemon --poll 5
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now roles-relay.service
sleep 3
systemctl --user is-active roles-relay.service && echo "中转站：在跑 ✓"
loginctl enable-linger "$USER" 2>/dev/null && echo "已开 linger（关机重启后也自动起）" || echo "（linger 没开成：只在登录状态下运行，也能用）"
