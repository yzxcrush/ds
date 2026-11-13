#!/usr/bin/env bash
# 把 Ds v0.1 发布到 GitHub：SSH over 443 + 仓库级 Deploy Key（写权限）。
# 用法： bash tools/publish.sh [owner/repo]     # 默认 yzxcrush/ds-v0.1
set -euo pipefail

REPO="${1:-yzxcrush/ds-v0.1}"
KEY="${DS_SSH_KEY:-$HOME/.ssh/ds_github}"
REMOTE_URL="ssh://git@ssh.github.com:443/${REPO}.git"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

say()  { printf '%s\n' "$*"; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }

[[ -f "$KEY" ]] || fail "缺少私钥：$KEY（先生成：ssh-keygen -t ed25519 -f $KEY -N ''）"
git rev-parse --git-dir >/dev/null 2>&1 || fail "$ROOT 不是 git 仓库"
[[ -z "$(git status --porcelain)" ]] || fail "工作区未提交干净，请先 git add -A && git commit"

SSH_OPTS=(-i "$KEY" -p 443 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)
export GIT_SSH_COMMAND="ssh ${SSH_OPTS[*]}"

say "→ 1/3 验证 Deploy Key …"
AUTH="$(ssh "${SSH_OPTS[@]}" -T git@ssh.github.com 2>&1 || true)"
grep -q "successfully authenticated" <<<"$AUTH" || fail \
"Deploy Key 尚未被 GitHub 认可。
  请打开 https://github.com/${REPO}/settings/keys → Add deploy key，
  粘贴 $(cat "$KEY.pub" 2>/dev/null || echo "<公钥>") 并勾选 Allow write access。
  当前返回：$AUTH"
say "  ✓ $AUTH"

say "→ 2/3 检查仓库可达（空仓库也应返回 0）…"
git ls-remote "$REMOTE_URL" >/dev/null 2>&1 || fail \
"无法访问 $REMOTE_URL
  请确认：https://github.com/new 已创建名为 ${REPO#*/} 的空仓库（不要初始化 README）。"
say "  ✓ 仓库可达"

say "→ 3/3 推送 main …"
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE_URL"
git push -u origin main
git branch -u origin/main >/dev/null 2>&1 || true

say "✓ 已发布：https://github.com/${REPO}"
say "  后续更新：git add -A && git commit -m '...' && git push"
