#!/bin/bash
# Collect git context for commit message generation

echo "=== git status ==="
git status

echo ""
echo "=== diff (staged + unstaged) ==="
git diff HEAD

echo ""
echo "=== current branch ==="
git branch --show-current

echo ""
echo "=== recent commits ==="
git log --oneline -10
