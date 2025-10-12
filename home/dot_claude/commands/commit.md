---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git branch:*)
description: Generate a git commit message
---

# Generate a git commit message

## Context

- Current git status: !`git status`
- Current git diff (staged and unstaged changes): !`git diff HEAD`
- Current branch: !`git branch --show-current`
- Recent commits: !`git log --oneline -10`

## Your task

Based on the above changes, **draft a commit message only**.
Follow the Conventional Commits format.

**DO NOT**:

- Execute `git commit`
- Execute `git add`
- Add "Co-Authored-By: Claude" or any co-author tags
- Add links to Claude Code

**DO**:

- Show the proposed commit message
- Explain the changes briefly
- Let the user manually commit when ready
