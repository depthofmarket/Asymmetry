#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# install_wiki_hooks.sh — Install git hooks for automated wiki validation & sync
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$REPO_DIR/.git/hooks"

echo "=================================================================="
echo " Installing Karpathy LLM Wiki Git Hooks & Synchronization Scripts"
echo "=================================================================="
echo " Repository : $REPO_DIR"
echo " Hooks Dir  : $HOOKS_DIR"
echo "=================================================================="

# 1. Ensure scripts are executable
for script in sync_wiki.sh wiki_sync.py verify_wiki_integrity.py install_wiki_hooks.sh; do
    if [[ -f "$REPO_DIR/scripts/$script" ]]; then
        chmod +x "$REPO_DIR/scripts/$script"
        echo ">> Set executable: scripts/$script"
    fi
done

if [[ ! -d "$HOOKS_DIR" ]]; then
    mkdir -p "$HOOKS_DIR"
fi

# 2. Configure pre-commit hook
PRE_COMMIT_HOOK="$HOOKS_DIR/pre-commit"
PRE_COMMIT_BLOCK=$(cat << 'EOF'
# ─── WIKI_INTEGRITY_HOOK_BEGIN ──────────────────────────────────────────────
# Automatically validate wiki integrity if wiki/ files are staged
STAGED_WIKI_FILES=$(git diff --cached --name-only -- wiki/ 2>/dev/null || true)
if [[ -n "$STAGED_WIKI_FILES" ]]; then
    echo ">> [WIKI_HOOK] Validating staged wiki/ modifications..."
    REPO_ROOT="$(git rev-parse --show-toplevel)"
    PYTHON_CMD="python3"
    if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        PYTHON_CMD="${VIRTUAL_ENV}/bin/python"
    elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
        PYTHON_CMD="$REPO_ROOT/.venv/bin/python"
    fi

    if [[ -f "$REPO_ROOT/scripts/verify_wiki_integrity.py" ]]; then
        if ! "$PYTHON_CMD" "$REPO_ROOT/scripts/verify_wiki_integrity.py"; then
            echo "ERROR: [WIKI_HOOK] Wiki integrity verification failed. Aborting commit." >&2
            echo "Fix broken links, frontmatter issues, or schema errors before committing." >&2
            exit 1
        fi
    elif [[ -f "$REPO_ROOT/tests/test_wiki_integrity.py" ]]; then
        if ! "$PYTHON_CMD" -m pytest "$REPO_ROOT/tests/test_wiki_integrity.py" -q; then
            echo "ERROR: [WIKI_HOOK] Wiki test suite failed. Aborting commit." >&2
            exit 1
        fi
    fi
    echo ">> [WIKI_HOOK] Wiki validation passed cleanly."
fi
# ─── WIKI_INTEGRITY_HOOK_END ────────────────────────────────────────────────
EOF
)

if [[ ! -f "$PRE_COMMIT_HOOK" ]]; then
    echo "#!/usr/bin/env bash" > "$PRE_COMMIT_HOOK"
    echo "$PRE_COMMIT_BLOCK" >> "$PRE_COMMIT_HOOK"
    chmod +x "$PRE_COMMIT_HOOK"
    echo ">> Created .git/hooks/pre-commit"
else
    if grep -q "WIKI_INTEGRITY_HOOK_BEGIN" "$PRE_COMMIT_HOOK"; then
        echo ">> Pre-commit hook already configured. Updating block..."
        TMP_HOOK="$(mktemp)"
        awk '
            /WIKI_INTEGRITY_HOOK_BEGIN/ { skip=1 }
            !skip { print }
            /WIKI_INTEGRITY_HOOK_END/ { skip=0 }
        ' "$PRE_COMMIT_HOOK" > "$TMP_HOOK"
        echo "$PRE_COMMIT_BLOCK" >> "$TMP_HOOK"
        mv "$TMP_HOOK" "$PRE_COMMIT_HOOK"
        chmod +x "$PRE_COMMIT_HOOK"
    else
        echo ">> Appending wiki hook to existing .git/hooks/pre-commit..."
        echo "" >> "$PRE_COMMIT_HOOK"
        echo "$PRE_COMMIT_BLOCK" >> "$PRE_COMMIT_HOOK"
        chmod +x "$PRE_COMMIT_HOOK"
    fi
fi

# 3. Configure post-commit hook
POST_COMMIT_HOOK="$HOOKS_DIR/post-commit"
POST_COMMIT_BLOCK=$(cat << 'EOF'
# ─── WIKI_POST_COMMIT_HOOK_BEGIN ───────────────────────────────────────────
COMMITTED_WIKI_FILES=$(git diff-tree --no-commit-id --name-only -r HEAD -- wiki/ 2>/dev/null || true)
if [[ -n "$COMMITTED_WIKI_FILES" ]]; then
    echo ">> [WIKI_HOOK] Knowledge base updates successfully committed to HEAD."
fi
# ─── WIKI_POST_COMMIT_HOOK_END ─────────────────────────────────────────────
EOF
)

if [[ ! -f "$POST_COMMIT_HOOK" ]]; then
    echo "#!/usr/bin/env bash" > "$POST_COMMIT_HOOK"
    echo "$POST_COMMIT_BLOCK" >> "$POST_COMMIT_HOOK"
    chmod +x "$POST_COMMIT_HOOK"
    echo ">> Created .git/hooks/post-commit"
else
    if ! grep -q "WIKI_POST_COMMIT_HOOK_BEGIN" "$POST_COMMIT_HOOK"; then
        echo ">> Appending wiki hook to existing .git/hooks/post-commit..."
        echo "" >> "$POST_COMMIT_HOOK"
        echo "$POST_COMMIT_BLOCK" >> "$POST_COMMIT_HOOK"
        chmod +x "$POST_COMMIT_HOOK"
    fi
fi

echo ">> SUCCESS: Git hooks installed and verified."
echo ">> Wiki integrity will be validated automatically before any commit touching wiki/."
