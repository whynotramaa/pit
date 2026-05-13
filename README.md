# pit-cli

```
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║    ██████╗ ██╗████████╗                                          ║
║    ██╔══██╗██║╚══██╔══╝                                          ║
║    ██████╔╝██║   ██║                                             ║
║    ██╔═══╝ ██║   ██║                                             ║
║    ██║     ██║   ██║                                             ║
║    ╚═╝     ╚═╝   ╚═╝                                             ║
║                                                                  ║
║    A lightweight version control system built in Python.         ║
║    Stage. Commit. Branch. Repeat.                                ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```
**pit** is a minimal yet functional version control system written in pure Python. It demonstrates Git-like functionality including object storage, branching, committing, and garbage collection.


## Features

- 🚀 **Lightweight**: No external dependencies, pure Python implementation
- 📦 **Object Storage**: SHA1-based content-addressable storage system
- 🌿 **Branching**: Full branch support with easy switching
- 💾 **Commits**: Snapshot-based commit history
- 🗑️ **Garbage Collection**: Automatic cleanup of unreachable objects
- 🔍 **Status & Log**: View repository state and commit history

## Installation

### From PyPI
```bash
pip install pit-cli-ramaa
```

### From Source
```bash
git clone https://github.com/yourusername/pit-cli.git
cd pit-cli
pip install -e .
```

## Quick Start

### Initialize a repository
```bash
pit init
```

### Add files
```bash
pit add <file_or_directory>
```

### Commit changes
```bash
pit commit -m "Your commit message"
```

### Create and switch branches
```bash
pit checkout -b new-feature
```

### Switch to existing branch
```bash
pit checkout main
```

### View commit history
```bash
pit log
```

### Check status
```bash
pit status
```

### List branches
```bash
pit branch
```

### Delete a branch
```bash
pit branch -d branch-name
```

### Run garbage collection
```bash
pit gc
```

## Commands Reference

| Command | Purpose |
|---------|---------|
| `pit init` | Initialize a new repository |
| `pit add <path>` | Stage files/directories |
| `pit commit -m "msg"` | Create a commit |
| `pit checkout <branch>` | Switch to branch |
| `pit checkout -b <branch>` | Create and switch branch |
| `pit branch` | List branches |
| `pit branch -d <name>` | Delete branch |
| `pit status` | Show working tree status |
| `pit log [-n count]` | Show commit history |
| `pit gc` | Run garbage collection |

## How It Works

### Core Architecture

- **Blob**: Stores file content (uncompressed initially, then zlib-compressed)
- **Tree**: Represents directory structure, maps filenames to blob/tree hashes
- **Commit**: Captures a snapshot with tree reference, parent commits, and metadata
- **Repository**: Manages the `.pit/` directory structure and all operations

### Object Storage

Objects are stored in `.pit/objects/XX/YYYYYY...` where:
- `XX` = first 2 characters of SHA1 hash
- `YYYYYY...` = remaining hash characters

### Index & Staging

The index (`.pit/index`) tracks staged files:
```json
{
  "file1.txt": "sha1hash1",
  "dir/file2.py": "sha1hash2"
}
```

### Branches

Branches reference specific commits and are stored in `.pit/refs/heads/`:
```
.pit/refs/heads/main       → commit hash
.pit/refs/heads/feature    → commit hash
```

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Building the Package

```bash
pip install build
python -m build
```

### Installing in Development Mode

```bash
pip install -e .
```

## Project Structure

```
pit-cli/
├── pit/                    # Main package
│   └── __init__.py        # Core implementation
├── tests/                 # Unit tests
├── README.md              # This file
├── LICENSE                # MIT License
├── pyproject.toml         # Package configuration
└── main.py                # CLI entry point (legacy)
```

## Limitations

- **No remote repositories**: This is a local-only VCS
- **No merge functionality**: Switching branches replaces working tree
- **No conflict resolution**: Not applicable without merge
- **No file permissions**: Stores only content and basic metadata
- **Single committer**: No multi-user support

## Contributing

Contributions are welcome! Areas for improvement:

- [ ] Merge functionality
- [ ] Remote repository support
- [ ] Improved performance for large repositories
- [ ] Better error handling and messages
- [ ] Comprehensive test suite
- [ ] Documentation and examples

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Created as a learning project to understand version control systems.

## See Also

- [Git](https://git-scm.com/) - The inspiration
- [Gitlet](http://gitlet.io/) - Similar educational project in JavaScript

