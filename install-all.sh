#!/usr/bin/env bash
# 一键搭建这一对：roles-chat（服务端）+ hermes-pocket（客户端）
#   bash install-all.sh            两半都搭
#   POCKET_DIR=/别的路径/... bash install-all.sh   客户端源码在别处
#   SKIP_CLIENT=1 bash install-all.sh              只搭服务端
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "① 服务端 roles-chat（建库、从 talk/*.md 重建、经验与权限自检）"
bash "$HERE/install.sh"
if [ "${SKIP_CLIENT:-0}" = "1" ]; then echo "（按 SKIP_CLIENT=1 跳过客户端）"; exit 0; fi
POCKET="${POCKET_DIR:-$HERE/../hermes-pocket}"
echo; echo "② 客户端 hermes-pocket（构建 APK）"
if [ -f "$POCKET/tools/build.sh" ]; then
  bash "$POCKET/tools/build.sh"
else
  echo "  没找到客户端源码：$POCKET（用 POCKET_DIR=... 指一下）"
fi
echo; echo "③ 装上后在客户端的「频道」里：＋ 新角色（场景/角色名/描述/标签）→ 建；角色列表、谁能接入、等你授权都在同一页"
