#!/bin/bash
# deploy.sh — ZA Support Health Check v11
# One-command deploy: commit, push to GitHub, Render auto-deploys.
# Usage: bash deploy.sh [optional commit message]

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

MSG="${1:-chore: deploy $(date '+%d/%m/%Y %H:%M')}"

echo "=== ZA Support Backend — Deploy ==="
echo "Directory : $REPO_DIR"
echo "Message   : $MSG"
echo ""

# Stage all changes
git add -A

# Check if there's anything to commit
if git diff --cached --quiet; then
    echo "Nothing to commit — pushing current HEAD."
else
    git commit -m "$MSG"
    echo "✓ Committed"
fi

# Push → triggers Render auto-deploy
git push origin main
echo "✓ Pushed to GitHub → Render is deploying"
echo ""
echo "Render auto-deploy runs:"
echo "  1. pip install -r requirements.txt"
echo "  2. python migrate.py (all 0*.sql migrations, idempotent)"
echo "  3. gunicorn main:app ..."
echo ""
echo "Live: https://api.zasupport.com"
echo "Docs: https://api.zasupport.com/docs"
echo ""

# Run migrations locally if DATABASE_URL is set (optional)
if [ -n "$DATABASE_URL" ]; then
    echo "DATABASE_URL detected — running migrations locally too..."
    python3 migrate.py
fi

echo "=== Deploy complete ==="
