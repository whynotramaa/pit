# Py-Git `pit add` — Engineering Deep-Dive

## Overview

`pit add` builds a **staging area** (index) by reading files, computing SHA1 hashes, storing them in a content-addressed object database, and recording path→hash mappings in JSON.

**Architecture:**
```
User Input → CLI Dispatch → add_path() → add_file() or add_directory()
                                              ↓
                                    store_object() → .pit/objects/
                                              ↓
                                    save_index() → .pit/index (JSON)
```

**Repository layout:**
```
.pit/
├── HEAD                    # Symref: "ref: refs/heads/master\n"
├── index                   # JSON: {"path": "blob_hash"}
├── objects/                # Content DB: xx/xxxx... (zlib blobs)
└── refs/heads/             # Branch pointers
```

## The `add` Workflow

**For a single file:**

1. Read bytes from disk
2. Create `Blob(content)` object
3. Hash: `SHA1("blob {size}\0{bytes}")` → e.g., `ab12cd34ef56...`
4. Serialize: `zlib(header + content)` → compressed bytes
5. Write to `.pit/objects/ab/12cd34ef56...`
6. Update index: `index["path/to/file"] = "ab12cd34ef56..."`
7. Save index as JSON to `.pit/index`

**For a directory:**

Recursively walk all files (skip `.pit`/`.git`), repeat steps 1–6 for each, then save once.

**GitObject structure:**
```
┌──────────────────────────────┐
│ GitObject                    │
├──────────────────────────────┤
│ type: str ("blob", "tree"...) │
│ content: bytes               │
├──────────────────────────────┤
│ hash() → SHA1 hex            │
│ serialize() → zlib(data)     │
│ deserialize(bytes) → object  │
└──────────────────────────────┘
         ↑
         │ Blob inherits, sets type="blob"
```

**Index format:**
```json
{
  "main.py": "ab12cd34ef56...",
  "src/utils.py": "ff23ee44dd55...",
  "README.md": "aabbccddee11..."
}
```

This is the **staging area**—snapshot of what's ready to commit.

## Flow Example

```
pit add main.py
    │
    ├─ Check if .pit/ exists
    ├─ Resolve path: full_path = repo_root / "main.py"
    ├─ is_file()? → YES: add_file("main.py")
    │   ├─ Read bytes
    │   ├─ Blob(bytes) → hash = "ab12cd..."
    │   ├─ Compress & write to objects/ab/12cd...
    │   ├─ Load index from .pit/index (JSON)
    │   ├─ index["main.py"] = "ab12cd..."
    │   └─ Save index back to .pit/index
    └─ Print: "Added -> main.py"

pit add .
    │
    └─ add_directory(".")
        ├─ rglob("*") → walk all files
        ├─ For each file not in .pit/ or .git/:
        │   ├─ Read, Blob, Hash, Store (steps above)
        │   └─ index[rel_path] = blob_hash
        └─ save_index() once
```

## Design Decisions

| Decision | Why | Trade-off |
|----------|-----|-----------|
| **SHA1 hashing** | Git-compatible; content-addressing | Changes affect hash |
| **zlib compression** | Smaller storage, good for text | CPU overhead |
| **JSON index** | Human-readable, easy debug | Slower than binary |
| **Relative paths** | Portability across systems | Must track root |
| **Skip .pit/.git** | Avoid recursive tracking | Manual exclusion |
| **Flat index** | Simple to merge changes | Need trees for commits |

## Object Storage

```
Content: "Hello, World!" (13 bytes)
         ↓
Header: "blob 13\0"
         ↓
Full data: "blob 13\0Hello, World!"
         ↓
SHA1: af5626b4a114d6d612c1f1a361290fa7f7eb516
         ↓
Path: .pit/objects/af/5626b4a114d6d612c1f1a361290fa7f7eb516
         ↓
Stored: zlib(header + content)
```

**Key properties:**
- **Content-addressable**: Same content always → same hash (no duplicates)
- **Immutable**: Objects never change once written
- **Self-validating**: Hash should match the path it's stored under

## Error Handling

```
add_path(path)
  ├─ Path not found? → FileNotFoundError
  ├─ is_file() → add_file()
  ├─ is_dir() → add_directory()
  └─ else → ValueError("not file or directory")

main() catches all:
  except Exception as e:
    print(f"Error -> {e}")
    sys.exit(1)

Pre-check: .pit must exist or print "Not a pit repository"
```

## Summary

`pit add` implements Git-style staging:

1. Read file → Blob → SHA1 hash
2. Compress (zlib) → store in `.pit/objects/`
3. Record `path → hash` in `.pit/index`

This creates a **content-addressable object store** + **staging index**—foundations for `commit`, which turns the flat index into a hierarchical tree snapshot.


