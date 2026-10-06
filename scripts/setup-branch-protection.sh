#!/usr/bin/env bash
# 配置 GitHub 分支保护：把 CI 门禁设为 required status check。
#
# 用途（P0 / RR-3）：让 `.github/workflows/ci.yml` 中的 layer-gate 成为
# "未通过不可合并" 的强制检查。
#
# 前置条件：
#   1) 仓库已配置 git remote（origin 指向 GitHub）
#   2) `gh auth status` 显示已登录且具备 repo 管理权限（admin）
#
# 用法：
#   ./scripts/setup-branch-protection.sh [branch] [check-name]
#   默认 branch=main，check-name="Layer Matrix Gate (L0-L5)"
set -euo pipefail

BRANCH="${1:-main}"
CHECK="${2:-Layer Matrix Gate (L0-L5)}"

if ! command -v gh >/dev/null 2>&1; then
  echo "✗ 未安装 gh CLI：https://cli.github.com/" >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "✗ gh 未登录或 token 失效，请先执行: gh auth login" >&2
  exit 1
fi

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || true)"
if [ -z "$REPO" ]; then
  echo "✗ 未能解析仓库（缺少 git remote？请先 git remote add origin <url>）" >&2
  exit 1
fi

echo "→ 为 $REPO@$BRANCH 配置分支保护，required check = '$CHECK'"

# 保留既有规则的基础上，写入 required_status_checks / 禁强制推送 / 禁删除分支
gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" \
  -H "Accept: application/vnd.github+json" \
  -f "required_status_checks[strict]=true" \
  -f "required_status_checks[contexts][]=$CHECK" \
  -f "enforce_admins=true" \
  -f "required_pull_request_reviews[required_approving_review_count]=0" \
  -f "restrictions=" \
  -F "allow_force_pushes=false" \
  -F "allow_deletions=false" >/dev/null

echo "✓ 已配置。验证："
gh api "repos/$REPO/branches/$BRANCH/protection" --jq '.required_status_checks.contexts'
