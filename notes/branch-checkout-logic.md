# Py-Git `pit branch` & `pit checkout` — Engineering Deep-Dive

## Overview

`pit branch` lists all branches, marking current with `*`. `pit checkout` switches branches by updating HEAD and restoring the working directory.

**Key directories:**
```
.pit/HEAD                      # "ref: refs/heads/{branch_name}\n"
.pit/refs/heads/{branch}       # Contains commit hash
.pit/objects/                  # Content DB
.pit/index                     # Staging area (cleared on checkout)
```

Each branch file holds the commit it points to. HEAD is a symbolic reference—it points to a branch, not directly to commits.

## Core Concepts

**Symbolic HEAD**: HEAD points to a branch ref, not directly to a commit. This allows fast switching—only the ref changes.

```
.pit/HEAD → "ref: refs/heads/master" → .pit/refs/heads/master → "abc123..."
```

**Branch refs**: Each file in `.pit/refs/heads/` is a branch. Its content is a commit hash. Reading a branch gives its current commit.

**Working directory**: Must always match the current branch's latest commit. Switching branches requires deleting old files and restoring new ones.

## Branch: List All Branches

`list_branches()` reads `.pit/refs/heads/`, gets current branch from HEAD, and marks it with `* `:

```python
current_branch = self.get_currrent_branch()  # Parse HEAD
branches = []

for branch_file in sorted(self.heads_dir.glob("*")):
    branch_name = branch_file.name
    if branch_name == current_branch:
        branches.append(f"* {branch_name}")  # Current branch
    else:
        branches.append(f"  {branch_name}")  # Two spaces for alignment

return branches
```

**Output:**
```
  develop
* master
  feature/ui
```

## Checkout: Switch Branches

Checkout performs 6 steps to transition from one commit to another:

**Phase 1: Collect files to delete** — Walk current branch's tree to inventory tracked files
```python
files_to_clear = get_files_from_tree_recurive(current_commit.tree_hash)
```

**Phase 2: Resolve target branch** — Check if branch exists
```python
branch_file = self.heads_dir / branch
if not branch_file.exists() and not create_branch:
    print(f"Branch '{branch}' not found.")
    return
```

**Phase 3: Create branch (if -b flag)** — New branch inherits source commit
```python
if create_branch and not branch_file.exists():
    self.set_branch_commit(branch, prev_commit_hash)  # Inherit commit
```

**Phase 4: Update HEAD** — Point to target branch
```python
self.head_file.write_text(f"ref: refs/heads/{branch}\n")
```

**Phase 5: Restore working directory** — Delete old files, restore new files from target commit tree
```python
# Delete old files
for rel_path in sorted(files_to_clear):
    (self.path / rel_path).unlink()

# Restore new files
self.restore_tree(target_commit.tree_hash, self.path)
```

**Phase 6: Clear index** — Prevent accidental commits from old staged files
```python
self.save_index({})
```

### Helper: `restore_tree()` — Recursive File Restoration

```python
def restore_tree(self, tree_hash: str, path: Path):
    tree = Tree.from_content(self.load_object(tree_hash).content)

    for mode, name, obj_hash in tree.entries:
        file_path = path / name

        if mode.startswith("100"):  # File
            file_path.write_bytes(self.load_object(obj_hash).content)
        elif mode.startswith("400"):  # Directory
            file_path.mkdir(exist_ok=True)
            self.restore_tree(obj_hash, file_path)
```

### Helper: `get_files_from_tree_recurive()` — Inventory All Files

```python
def get_files_from_tree_recurive(self, tree_hash: str, prefix: str = ""):
    files = set()
    tree = Tree.from_content(self.load_object(tree_hash).content)

    for mode, name, obj_hash in tree.entries:
        full_name = f"{prefix}{name}"

        if mode.startswith("100"):
            files.add(full_name)
        elif mode.startswith("400"):
            files.update(self.get_files_from_tree_recurive(obj_hash, f"{full_name}/"))

    return files
```

Returns: `{"main.py", "src/utils.py", "src/config.py", ...}`

## Flow Examples

**Example 1: List branches**
```
pit branch  →  get current from HEAD  →  list refs/heads/  →  mark current with *
Output: "  develop", "* master", "  feature/ui"
```

**Example 2: Checkout existing branch**
```
pit checkout develop
  1. files_to_clear = walk master's tree
  2. branch exists → SWITCH mode
  3. HEAD = "ref: refs/heads/develop"
  4. Delete master's files
  5. Restore develop's files from tree
  6. Clear index
  → "Switched to branch `develop`"
```

**Example 3: Create and switch new branch**
```
pit checkout -b feature/auth
  1. files_to_clear = walk master's tree
  2. branch doesn't exist + -b flag → CREATE mode
  3. Create: .pit/refs/heads/feature/auth = master's commit
  4. HEAD = "ref: refs/heads/feature/auth"
  5. Delete and restore same files (no visible change)
  6. Clear index
  → "Created new branch `feature/auth`"
     "Switched to branch `feature/auth`"
```

**Example 4: Create branch without commits (error)**
```
pit init && pit checkout -b feature/new
  → No commits yet
  → "No commits yet, cannot create a branch"
  → ABORT
```

## Design Decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| **Symbolic HEAD** | Enables fast branch switching (single ref write) | Extra indirection (HEAD → branch → commit) |
| **One ref per file** | Portable, human-readable, easy to debug | Slower enumeration for many branches |
| **File-based index cleanup** | Prevents accidental commits with old staged files | Requires re-staging after branch switch |
| **Recursive tree restoration** | Respects directory structure and permissions | Slow for large trees (N file writes) |
| **Graceful tree read failure** | Prevents crashes if tree corrupted | Inconsistent working directory (partial restore) |
| **Sorted branch listing** | Predictable output, easier to read | Minor overhead |
| **Two-space indent for branches** | Aligns with `* ` prefix (2 chars) | Conventions differ from some Git setups |

## Error Scenarios

**Checkout errors:**
1. `.pit/` doesn't exist → "Not a git repo"
2. Branch doesn't exist + no -b → "Branch '{name}' not found."
3. Branch exists + -b flag → "Branch `{name}` already exists."
4. Create branch but no commits → "No commits yet, cannot create a branch"

**Branch errors:**
1. `.pit/` doesn't exist → "Not a pit repository"
2. No branches yet → "No branches found."

## State & Performance

**State transitions:**
- `pit init` → master exists (no commits yet)
- `pit checkout -b feature` → new branch inherits source commit
- `pit checkout branch` → switch HEAD, restore files

**Performance:**
- Branch listing: O(num_branches) + directory scan
- Checkout: O(num_files) disk I/O for delete + restore
- Large repos: 10k+ files may take seconds
- Optimization opportunity: Skip restore if commits match

## Summary

**`pit branch`**: Lists all branches, marks current with `*`
- Read `.pit/refs/heads/`, check HEAD
- Output: sorted list with alignment

**`pit checkout [branch]`**: Switch branches
- Collect files from current tree
- Update HEAD to target branch
- Delete old files, restore new files from tree
- Clear index

**Key invariants:**
1. HEAD always points to a branch (symbolic ref)
2. Every branch points to a commit
3. Working directory = current branch's latest commit
4. Index is empty between commits

**Safety:**
- No commits lost (append-only)
- Branch switch is atomic (single HEAD write)
- Index cleared prevents accidental commits
- Graceful degradation on corruption
