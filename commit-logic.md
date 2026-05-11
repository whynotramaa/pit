# Py-Git `pit commit` — Engineering Deep-Dive

## Overview

`pit commit` creates an immutable snapshot by converting the flat staging index into a hierarchical tree, linking to parent commits, and storing the result as a commit object in the content-addressed database. It then advances the branch pointer and clears the staging area.

**Architecture:**
```
Staging Index (.pit/index)
         ↓
  create_tree_from_index()  (flat → hierarchical)
         ↓
   Commit object (tree_hash + parent_hash + metadata)
         ↓
  store_object()  (in .pit/objects/)
         ↓
  set_branch_commit()  (.pit/refs/heads/master → hash)
         ↓
  save_index({})  (clear staging)
```

## Why Trees Matter

The index is **flat**: `{"main.py": "hash1", "src/utils.py": "hash2"}`. But Git needs **hierarchical** snapshots to represent directory structure. `create_tree_from_index()` transforms the flat index into nested Tree objects:

**Example:**
```
Index:
{
  "main.py": "abc123",
  "README.md": "def456",
  "src/utils.py": "ghi789"
}

→ Tree structure:
Root Tree (hash: xyz789)
├─ main.py (mode 100644, blob: abc123)
├─ README.md (mode 100644, blob: def456)
└─ src/ (mode 40000, subtree: qrs012)
   └─ utils.py (mode 100644, blob: ghi789)

Mode: 100644 = file, 40000 = directory
```

Each tree is serialized, hashed, and stored in objects DB. The root tree hash becomes the commit's snapshot.

## The Commit Workflow

**Phase 1: Build Tree**
- Load index from `.pit/index`
- Recursively organize into nested Tree objects
- Store each tree, get root tree hash

**Phase 2: Link Parent**
- Read `.pit/refs/heads/master` (if exists)
- If branch file exists → extract parent commit hash
- If not → first commit (no parent)

**Phase 3: Detect Changes (Crucial!)**
```
if parent_commit exists:
  ├─ Load parent commit object from objects DB
  ├─ Extract parent's tree_hash
  ├─ If parent_tree_hash == current_tree_hash:
  │   └─ Print "Nothing to commit, working tree clean"
  │      ABORT (avoid duplicate commits)
  └─ Else: Continue
```

**Why?** Commits are snapshots. If the tree hasn't changed, creating a new commit is redundant. Git does this too.

**Phase 4: Create & Store Commit**
```
Commit object:
  tree: "abc123def456..."
  parent: "prev_hash..." (only if not first)
  author: "pit user <user@pit.com> 1234567890 +0000"
  committer: "pit user <user@pit.com> 1234567890 +0000"

  initial commit (message)

Serialized → SHA1 hash → zlib compress → store in .pit/objects/
```

**Phase 5: Advance Branch**
- Write commit hash to `.pit/refs/heads/master`
- Branch now points to latest commit

**Phase 6: Clear Staging**
- Write `{}` to `.pit/index`
- Ready for next `pit add` cycle

## Flow Example

```
pit commit -m "initial commit"
    │
    ├─ Check .pit/ exists
    ├─ Load index: {"main.py": "ab12...", ...}
    │
    ├─ create_tree_from_index()
    │   ├─ Organize nested dirs
    │   ├─ Create/store Tree objects recursively
    │   └─ Return root_tree_hash = "xyz789..."
    │
    ├─ get_currrent_branch() → "master"
    ├─ get_branch_commit("master") → None (first commit)
    │
    ├─ parent_hashes = []
    │
    ├─ Create Commit(tree_hash="xyz789...", parent_hashes=[])
    │
    ├─ store_object(commit) → commit_hash = "ff99ee..."
    │
    ├─ set_branch_commit("master", "ff99ee...")
    │
    ├─ save_index({})
    │
    └─ Print: "Created commit ff99ee... on branch master"

pit add file.txt && pit commit -m "second commit"
    │
    ├─ create_tree_from_index() → tree_hash = "abc999..."
    ├─ get_branch_commit("master") → "ff99ee..." (parent)
    │
    ├─ Load parent commit, extract parent tree_hash = "xyz789..."
    ├─ Compare: "abc999..." != "xyz789..." → Changes! Continue
    │
    ├─ Create Commit(tree="abc999...", parent=["ff99ee..."])
    ├─ store_object() → "ee88dd..."
    ├─ set_branch_commit("master", "ee88dd...")
    ├─ save_index({})
    │
    └─ Print: "Created commit ee88dd... on branch master"
```

## Commit Object Format

```
Stored in .pit/objects/ like blobs/trees, but type="commit"

Serialized (text → bytes):
┌────────────────────────────────┐
│ tree 7a8f9c1e2b3c4d5e...       │
│ parent 3b2d4f5e8a9b1c2d...     │  (only if not first)
│ author pit user... 1234567890  │
│ author pit user... 1234567890  │
│                                │
│ This is my commit message      │
│ Can be multiline               │
└────────────────────────────────┘

Hashed, compressed, stored.
SHA1 identifies commit uniquely.
```

## Key Design Decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| **Tree comparison** | Prevent empty commits (same content) | Extra load/deserialize per commit |
| **Index clearing** | Explicit staging cycle | Requires re-add for next commit |
| **Immutable snapshots** | Content-addressed dedup | Can't modify history |
| **Branch pointers** | Track commit history | Manual ref management |
| **Timestamp in commit** | Record when committed | Affects hash (no reproducibility) |

## Index Lifecycle

```
Empty {}  →[add]→  Dirty {...}  →[add]→  Dirty {...}
   ↑                                           │
   │                                      [commit]
   │                                           ↓
   └─────────────────────────────  Empty {}
```

Index starts empty. `pit add` populates it. `pit commit` clears it. Cycle repeats.

Before commit: Index must have entries or abort ("nothing to commit").
After commit: Index wiped, ready for next cycle.

## Error Scenarios

```
Commit fails in these cases:

1. .pit/ doesn't exist
   → "Not a git repository"

2. Index empty ({})
   → "nothing to commit, working tree is clean"

3. Tree unchanged from parent
   → "Nothing to commit, working tree clean"

4. Corrupted object (deserialize fails)
   → "Error -> {exception}"
```

## Summary

`pit commit` implements Git's snapshot model:

1. **Flatten → Hierarchical**: Convert flat index to tree objects
2. **Link History**: Reference parent commit (if exists)
3. **Detect Changes**: Compare tree hashes; abort if identical
4. **Store**: Serialize commit with metadata (author, timestamp, message)
5. **Advance Branch**: Update ref to point to new commit
6. **Reset Stage**: Clear index for next cycle

Every commit is immutable and uniquely identified by its SHA1. Same content always produces same hash—the foundation of Git's reproducible, verifiable history.
