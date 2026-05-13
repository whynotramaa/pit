# Py-Git `pit status` — Engineering Deep-Dive

## Overview

`pit status` provides a **working tree snapshot** by comparing the index (staging area), working directory files, and committed tree. It displays what's staged, modified, untracked, and deleted—giving the user a clear view of repository state.

**Architecture:**
```
Index (.pit/index)
    ↓
Load staging area ({path: hash})
    ↓
Walk working directory (all files)
    ↓
Compare hashes:
  ├─ In index + unchanged → staged
  ├─ In index + changed → modified (unstaged)
  ├─ Not in index → untracked
  └─ In index + missing → deleted
    ↓
Display categorized file lists
```

**Repository state model:**
```
Working Directory         Index (.pit/index)      Commit Tree
    ↓                           ↓                        ↓
main.py (v2)       →    main.py: hash1    →    main.py: hash1
config.py (v3)     →    config.py: hash2  →    config.py: hash2
new_file.py (v1)   →    (not in index)    →    (not in tree)
old_file.py (del)  →    old_file.py: hash3→    old_file.py: hash3
```

## Core Concepts

### File Status Categories

**Staged (in index)**: Files added to staging area, ready for next commit
```
├─ Currently in .pit/index
├─ Content hashed and ready
└─ Will be committed on next `pit commit`
```

**Modified unstaged (tracked but changed)**: Files in index but changed in working directory
```
├─ File exists in .pit/index
├─ Current file hash ≠ indexed hash
├─ User must `pit add` to stage changes
└─ Changes not included in next commit
```

**Untracked (new files)**: Files in working directory but never added
```
├─ Not in .pit/index
├─ Not in any commit tree
├─ User must `pit add` to start tracking
└─ Git is unaware of file
```

**Deleted (tracked but missing)**: Files in index but missing from working directory
```
├─ File path exists in .pit/index
├─ Physical file deleted from disk
├─ Hash mismatch: indexed file ≠ nothing
└─ User must `pit add` or restore to recover
```

## The Status Workflow

### Phase 1: Gather State Information

```python
# Get current branch for display
current_branch = self.get_currrent_branch()

# Load index (staging area)
index = self.load_index()

# Initialize file status lists
staged_files = list(index.keys())  # All indexed files
untracked_files = []
modified_unstaged_files = []
deleted_files = []
```

### Phase 2: Walk Working Directory

```python
for file_path in self.path.rglob("*"):
    if file_path.is_file():
        # Skip .pit repository metadata
        if ".pit" in file_path.parts or ".git" in file_path.parts:
            continue

        rel_path = str(file_path.relative_to(self.path))

        # Check if tracked
        if rel_path not in index:
            untracked_files.append(rel_path)
        else:
            # Tracked: check if modified
            current_content = file_path.read_bytes()
            current_blob = Blob(current_content)
            current_hash = current_blob.hash()

            if current_hash != index[rel_path]:
                modified_unstaged_files.append(rel_path)
```

**Key: Hash-based comparison** — Instead of timestamps or sizes, we compute SHA1 hash of current file and compare with indexed hash. If different, file is modified.

### Phase 3: Detect Deleted Files

```python
for indexed_file in index.keys():
    full_path = self.path / indexed_file
    if not full_path.exists():
        deleted_files.append(indexed_file)
```

**Invariant**: If file is in index but missing from disk, it's deleted. No hash needed—absence is detection.

### Phase 4: Display Categorized Status

Output follows Git's format with hints:

```
On branch {branch}

Changes to be committed:          ← Staged files
  modified: main.py

Changes not staged for commit:    ← Modified + deleted
  modified: utils.py
  deleted: old_file.py

Untracked files:                  ← New files
  new_file.py

working tree clean                ← If nothing to show
```

## Flow Examples

### Example 1: After Adding Files (Staged)

```
Repository state:
├─ main.py added to index, no changes since add
└─ config.py not added

Execution:
  ├─ Load index: {"main.py": "abc123"}
  ├─ Walk dir: find main.py, config.py
  │   ├─ main.py in index + hash matches → staged
  │   └─ config.py NOT in index → untracked
  ├─ No deleted files
  │
  └─ Output:
      On branch master

      Changes to be committed:
        modified: main.py

      Untracked files:
        config.py
```

### Example 2: After Modifying a Staged File

```
Repository state:
├─ main.py added to index (hash abc123)
├─ main.py edited on disk (now hash xyz789)
└─ index still has old hash

Execution:
  ├─ Load index: {"main.py": "abc123"}
  ├─ Walk dir: find main.py
  │   ├─ main.py in index
  │   ├─ Read file, compute hash → xyz789
  │   ├─ xyz789 ≠ abc123 → modified unstaged
  ├─ No deleted
  │
  └─ Output:
      On branch master

      Changes to be committed:
        modified: main.py (old version)

      Changes not staged for commit:
        modified: main.py (new version)
```

**Key insight**: Same file can appear in both "staged" and "modified unstaged"—staged is OLD version from last add, modified unstaged is CURRENT version on disk.

### Example 3: Deleted File (Tracked but Missing)

```
Repository state:
├─ old_file.py in index
├─ old_file.py deleted from disk
└─ new_file.py added to disk (untracked)

Execution:
  ├─ Load index: {"old_file.py": "def456"}
  ├─ Walk dir: find new_file.py
  │   ├─ new_file.py NOT in index → untracked
  ├─ Check indexed files:
  │   ├─ old_file.py: (self.path / "old_file.py").exists() → False
  │   └─ → deleted
  │
  └─ Output:
      On branch master

      Changes not staged for commit:
        deleted: old_file.py

      Untracked files:
        new_file.py
```

### Example 4: Clean Working Tree

```
Repository state:
├─ main.py in index + on disk (same hash)
├─ README.md in index + on disk (same hash)
└─ No new files, no deleted files

Execution:
  ├─ Load index: {"main.py": "abc123", "README.md": "def456"}
  ├─ Walk dir: all files match index hashes
  ├─ No untracked, no modified, no deleted
  │
  └─ Output:
      On branch master

      No changes added to commit.

      working tree clean
```

## Design Decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| **Hash-based comparison** | Detects content changes accurately, not timestamp-dependent | CPU cost (rehash every file) |
| **Skip .pit/.git** | Prevent metadata from showing as untracked | Manual exclusion needed |
| **Categorize by status** | Users see actionable state clearly | More output lines |
| **Try/except on file read** | Handle corrupted/permission-denied files gracefully | May hide real issues |
| **Sorted output** | Consistent, predictable display | Minor overhead |
| **Walk entire directory** | Catch all untracked files | Slow for large repos |

## Error Handling

```
Status fails gracefully:

1. .pit/ doesn't exist
   → "Not a pit repository - maybe try doin `pit init` first"

2. Index file missing
   → load_index() returns {} (empty dict)
   → All files appear untracked

3. File permission denied
   → try/except catches exception
   → Warning printed: "Could not read {file}"
   → Continues processing other files

4. Corrupted/missing object hash
   → Index contains hash, but file unreadable
   → Warning printed
   → Status continues with partial data
```

## Performance Considerations

```
Time complexity:
  O(num_files) — must walk entire working directory
  O(indexed_files) — must check deletion for each indexed file
  Per file: O(file_size) — compute SHA1 hash

Space complexity:
  O(num_files) — store file lists in memory

Scaling implications:
├─ 1k files: instant (~ms)
├─ 10k files: noticeable (~100ms)
├─ 100k files: slow (~1-5s)
└─ Optimization: incremental status (track changed dirs only)
```

## Summary

`pit status` provides operational visibility by categorizing files:

1. **Staged**: In index, ready to commit
2. **Modified unstaged**: In index but changed on disk
3. **Untracked**: On disk but not in index
4. **Deleted**: In index but missing on disk

**Key workflow:**
- Load index (staging area snapshot)
- Walk working directory and compute hashes
- Compare current hashes against indexed hashes
- Check indexed files for deletion
- Display categorized results with hints

**Implementation pattern:**
- Reuses `Blob()` for hash computation (existing class)
- Try/except for file operations (robustness)
- Early skip of `.pit` directory (avoid recursion)
- Sorted output for consistency
- Git-like messaging for familiarity

**Safety properties:**
1. **Non-destructive**: Status never modifies files or index
2. **Graceful degradation**: Corrupted files don't crash status
3. **Accurate detection**: Hash-based, not timestamp-based
4. **Complete view**: Shows all four file categories

Status is the user's primary tool for understanding repository state before add/commit operations.
