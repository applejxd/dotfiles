---
name: commit
description: "Commits in Conventional Commits manner from staged changes and commit"
allowed-tools: Bash(git status:*), Bash(git diff --cached:*), Bash(git branch --show-current), Bash(git log:*), Bash(git commit:*)
---

# Commits in Conventional Commits manner

## Context

- Branch: !`git branch --show-current`
- Status (porcelain): !`git status --porcelain`
- Staged files: !`git diff --cached --name-only`
- Staged diff: !`git diff --cached --patch --no-color`
- Recent commits: !`git log --oneline -10`

## Your task

You are a precise commit message generator. Use **only the staged changes** to produce **one** Conventional Commits message and commit it.

### Rules

1) If **no staged files**, output exactly:

    ```txt
    NO-STAGED-CHANGES
    ```

    and stop.

2) Choose **type** from: `feat | fix | docs | style | refactor | test | chore`.

3) **scope** (optional): short component derived from the top-level folder of the staged files (e.g., `api`, `cli`, `ui`, `docs`, `build`). If unclear, omit scope.

4) **subject**: concise English imperative, ≤72 chars, no period.

5) **body** (optional): a few bullet points (`- ...`) explaining why and what changed, notable impacts, and tests.

6) **breaking change**: if compatibility is broken, add `!` after `type` (e.g., `refactor(cli)!: ...`) and include a footer line:

    ```txt
    BREAKING CHANGE: brief impact and migration
    ```

7) **footer** (optional): references like `Ref: #123`.

8) **message layout** (blank lines are significant):

    ```txt
    type(scope)!: subject

    body lines...
    (blank line if there is a footer)
    footer lines...
    ```

9) **Output format (exactly two parts, no extra text):**
   - First, print the full commit message (no markdown).
   - Second, print a single execution line that commits it with two `-m` flags:

     ```bash
     !`git commit -m "<first line>" -m "<body and footers as-is>" --no-verify`
     ```

     If there is **no body/footer**, print:

     ```bash
     !`git commit -m "<first line>" --no-verify`
     ```

     Escape any double quotes in the message.

### Examples

OK (with body and footer):

```txt
feat(api): add pagination to user search

- accept limit/offset and add index for performance
- introduce query params to /users endpoint
- add unit/e2e tests for boundary cases

Ref: #123
```

BREAKING:

```txt
refactor(cli)!: redesign init command arguments

- remove positional projectName and unify into --name
- change default output directory to ./dist

BREAKING CHANGE: scripts must pass --name; update CI templates accordingly
```
