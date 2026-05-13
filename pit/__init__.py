from __future__ import annotations
import argparse
import sys
from pathlib import Path
import json
import hashlib
from typing import Dict, List, Tuple, Optional
import zlib
import time


class pitObject:
    def __init__(self, obj_type: str, content: bytes):
        self.type = obj_type
        self.content = content

    def hash(self) -> str:
        header = f"{self.type} {len(self.content)}\0".encode()
        return hashlib.sha1(header + self.content).hexdigest()

    def serialize(self) -> bytes:
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header + self.content)

    @classmethod
    def deserialize(cls, data: bytes) -> pitObject:
        decompressed = zlib.decompress(data)
        null_idx = decompressed.find(b"\0")
        header = decompressed[:null_idx]
        content = decompressed[null_idx + 1 :]

        obj_type_bytes, _ = header.split(b" ", 1)
        obj_type = obj_type_bytes.decode()

        return cls(obj_type, content)


class Blob(pitObject):
    def __init__(self, content: bytes):
        super().__init__("blob", content)


class Tree(pitObject):
    def __init__(self, entries: List[Tuple[str, str, str]] = None):
        self.entries = entries or []
        content = self._serialize_entries()
        super().__init__("tree", content)

    def _serialize_entries(self) -> bytes:
        content = b""
        for mode, name, obj_hash in sorted(self.entries):
            content += f"{mode} {name} \0".encode()
            content += bytes.fromhex(obj_hash)

        return content

    def add_entry(self, mode: str, name: str, obj_hash: str):
        self.entries.append((mode, name, obj_hash))
        self.content = self._serialize_entries()

    @classmethod
    def from_content(cls, content: bytes) -> Tree:
        tree = cls()
        i = 0

        while i < len(content):
            null_idx = content.find(b"\0", i)
            if null_idx == -1:
                break

            mode_name = content[i:null_idx].decode()
            mode, name = mode_name.split(" ", 1)
            obj_hash = content[null_idx + 1 : null_idx + 21].hex()
            tree.entries.append((mode, name, obj_hash))

            i = null_idx + 21

        return tree


class Commit(pitObject):
    def __init__(
        self,
        tree_hash: str,
        parent_hashes: List[str],
        author: str,
        commiter: str,
        message: str,
        timestamp: int = None,
    ):
        self.tree_hash = tree_hash
        self.parent_hashes = parent_hashes
        self.author = author
        self.commiter = commiter
        self.message = message
        self.timestamp = timestamp or int(time.time())

        content = self._serialize_commit()
        super().__init__("commit", content)

    def _serialize_commit(self):
        lines = [f"tree {self.tree_hash}"]

        for parent in self.parent_hashes:
            lines.append(f"parent {parent}")

        lines.append(f"author {self.author} {self.timestamp} +0000")
        lines.append(f"author {self.commiter} {self.timestamp} +0000")
        lines.append("")
        lines.append(self.message)

        return "\n".join(lines).encode()

    @classmethod
    def from_content(cls, content: bytes) -> Commit:
        lines = content.decode().split("\n")
        tree_hash = None
        parent_hashes = []
        author = None
        commiter = None
        message_start = 0

        for i, line in enumerate(lines):
            if line.startswith("tree "):
                tree_hash = line[5:]

            elif line.startswith("parent "):
                parent_hashes.append(line[7:])

            elif line.startswith("author "):
                author_parts = line[7:].rsplit(" ", 2)
                author = author_parts[0]
                timestamp = int(author_parts[1])

            elif line.startswith("commiter "):
                commiter_parts = line[10:].rsplit(" ", 2)
                commiter = commiter_parts[0]

            elif line == "":
                message_start = i + 1
                break

        message = "\n".join(lines[message_start:])

        commit = cls(tree_hash, parent_hashes, author, commiter, message, timestamp)

        return commit


class Repository:
    def __init__(self, path="."):
        self.path = Path(path).resolve()
        self.pit_dir = self.path / ".pit"

        self.objects_dir = self.pit_dir / "objects"

        self.refs_dir = self.pit_dir / "refs"
        self.heads_dir = self.refs_dir / "heads"

        self.head_file = self.pit_dir / "HEAD"

        self.index_file = self.pit_dir / "index"

    def init(self) -> bool:

        if self.pit_dir.exists():
            return False

        self.pit_dir.mkdir()
        self.objects_dir.mkdir()
        self.refs_dir.mkdir()
        self.heads_dir.mkdir()

        self.head_file.write_text("ref: refs/heads/master\n")

        self.save_index({})

        self.index_file.write_text(json.dumps({}, indent=2))

        print(f"Initialized empty pit repository in {self.pit_dir} ")

        return True

    def store_object(self, obj: pitObject):
        obj_hash = obj.hash()
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            obj_dir.mkdir(exist_ok=True)
            obj_file.write_bytes(obj.serialize())

        return obj_hash

    def _is_internal_path(self, file_path: Path) -> bool:
        return ".pit" in file_path.parts or ".git" in file_path.parts

    def load_index(self) -> Dict[str, str]:
        if not self.index_file.exists():
            return {}

        try:
            return json.loads(self.index_file.read_text())
        except:
            return {}

    def save_index(self, index: Dict[str, str]):
        self.index_file.write_text(json.dumps(index, indent=2))

    def add_file(self, path: str):

        full_path = self.path / path
        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found!")

        content = full_path.read_bytes()

        blob = Blob(content)

        blob_hash = self.store_object(blob)

        index = self.load_index()
        index[path] = blob_hash
        self.save_index(index)

        print(f"Added -> {path}")

    def add_directory(self, path: str):
        full_path = self.path / path

        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found!")
        if not full_path.is_dir():
            raise ValueError(f"{path} is not a directory!")

        index = self.load_index()
        added_count = 0

        for file_path in full_path.rglob("*"):
            if file_path.is_file():
                if self._is_internal_path(file_path):
                    continue

                content = file_path.read_bytes()
                blob = Blob(content)
                blob_hash = self.store_object(blob)

                rel_path = str(file_path.relative_to(self.path))
                index[rel_path] = blob_hash
                added_count += 1

        self.save_index(index)
        if added_count > 0:
            print(f"Added {added_count} files from directory {path} !")

        else:
            print(f"Directory {path} already up to date !")

        pass

    def add_path(self, path: str) -> None:
        full_path = self.path / path

        if not full_path.exists():
            raise FileNotFoundError(f"Path {path} not found")

        if full_path.is_file():
            self.add_file(path)

        elif full_path.is_dir():
            self.add_directory(path)

        else:
            raise ValueError(f"{path} is neither a file nor directory - UNSUPPORTED")

    def load_object(self, obj_hash: str) -> pitObject:
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found")

        return pitObject.deserialize(obj_file.read_bytes())

    def create_tree_from_index(self):
        index = self.load_index()
        if not index:
            tree = Tree()
            return self.store_object(tree)

        dirs = {}
        files = {}

        for file_path, blob_hash in index.items():
            parts = file_path.split("/")

            if len(parts) == 1:
                files[parts[0]] = blob_hash
            else:
                dir_name = parts[0]
                if dir_name not in dirs:
                    dirs[dir_name] = {}
                current = dirs[dir_name]

                for part in parts[1:-1]:
                    if part not in current:
                        current[part] = {}

                    current = current[part]

                current[parts[-1]] = blob_hash

        def create_tree_recusrively(entries_dict: Dict):
            tree = Tree()

            for name, blob_hash in entries_dict.items():
                if isinstance(blob_hash, str):
                    tree.add_entry("100644", name, blob_hash)

                if isinstance(blob_hash, dict):
                    subtreee_hash = create_tree_recusrively(blob_hash)
                    tree.add_entry("40000", name, subtreee_hash)

            return self.store_object(tree)

        root_entries = {**files}

        for dir_name, dir_contents in dirs.items():
            root_entries[dir_name] = dir_contents

        return create_tree_recusrively(root_entries)

    def get_currrent_branch(self) -> str:
        if not self.head_file.exists():
            return "master"
        head_content = self.head_file.read_text().strip()

        if head_content.startswith("ref: refs/heads"):
            return head_content[16:]

        return "HEAD"

    def get_branch_commit(self, current_branch: str):
        branch_file = self.heads_dir / current_branch

        if branch_file.exists():
            return branch_file.read_text().strip()

        return None

    def set_branch_commit(self, current_branch: str, commit_hash: str):
        branch_file = self.heads_dir / current_branch
        branch_file.write_text(commit_hash + "\n")

    def commit(self, message: str, author: str = "pit user <user@pit.com>"):

        tree_hash = self.create_tree_from_index()

        current_branch = self.get_currrent_branch()

        parent_commit = self.get_branch_commit(current_branch)
        parent_hashes = [parent_commit] if parent_commit else []
        index = self.load_index()

        if not index:
            print("nothing to commit, working tree is clean")
            return None

        if parent_commit:
            parent_pit_commit_object = self.load_object(parent_commit)
            parent_commit_data = Commit.from_content(parent_pit_commit_object.content)
            if tree_hash == parent_commit_data.tree_hash:
                print("Nothing to commit, working tree clean")
                return None

        commit = Commit(
            tree_hash=tree_hash,
            parent_hashes=parent_hashes,
            author=author,
            commiter=author,
            message=message,
        )

        commit_hash = self.store_object(commit)

        self.set_branch_commit(current_branch, commit_hash)
        self.save_index({})
        print(f"Created commit {commit_hash} on branch {current_branch}")
        return commit_hash

    def get_files_from_tree_recurive(self, tree_hash: str, prefix: str = ""):
        files = set()

        try:
            tree_obj = self.load_object(tree_hash)
            tree = Tree.from_content(tree_obj.content)
            for mode, name, obj_hash in tree.entries:
                full_name = f"{prefix}{name}"
                if mode.startswith("100"):
                    files.add(full_name)
                elif mode.startswith("400"):
                    subtree_files = self.get_files_from_tree_recurive(
                        obj_hash, f"{full_name}/"
                    )
                    files.update(subtree_files)

        except Exception as e:
            print(f"Waarning: Could not read tree {tree_hash}: {e}")

        return files

    def checkout(self, branch: str, create_branch: bool):
        prev_branch = self.get_currrent_branch()
        files_to_clear = set()
        try:
            prev_commit_hash = self.get_branch_commit(prev_branch)
            if prev_commit_hash:
                prev_commit_obj = self.load_object(prev_commit_hash)
                prev_commit = Commit.from_content(prev_commit_obj.content)
                if prev_commit.tree_hash:
                    files_to_clear = self.get_files_from_tree_recurive(
                        prev_commit.tree_hash
                    )

        except Exception:
            files_to_clear = set()

        branch_file = self.heads_dir / branch

        if not branch_file.exists():
            if create_branch:
                if prev_commit_hash:
                    self.set_branch_commit(branch, prev_commit_hash)
                    print(f"Created new branch `{branch}` ")

                else:
                    print("No commits yet, cannot create a branch")
                    return

                self.head_file.write_text(f"ref: refs/heads/{branch}\n")

                print(f"Switched to branch `{branch}` ")

            else:
                print(f"Branch '{branch}' not found.")
                print("Use ___ checkout -b '{branch}' to create and switch to a branch")
                return
        else:
            if create_branch:
                print(f"Branch `{branch}` already exists.")
                return

            self.head_file.write_text(f"ref: refs/heads/{branch}\n")

            self.restore_working_dir(branch, files_to_clear)
            print(f"Switched to branch `{branch}` ")

    def restore_tree(self, tree_hash: str, path: Path):

        tree_obj = self.load_object(tree_hash)
        tree = Tree.from_content(tree_obj.content)

        for mode, name, obj_hash in tree.entries:
            file_path = path / name

            if self._is_internal_path(file_path):
                continue

            if mode.startswith("100"):
                blob_obj = self.load_object(obj_hash)
                blob = Blob(blob_obj.content)
                file_path.write_bytes(blob.content)

            elif mode.startswith("400"):
                file_path.mkdir(parents=True, exist_ok=True)
                self.restore_tree(obj_hash, file_path)

    def restore_working_dir(self, branch: str, files_to_clear: Optional[set]):
        target_commit_hash = self.get_branch_commit(branch)

        if not target_commit_hash:
            return

        for rel_path in sorted(files_to_clear):
            file_path = self.path / rel_path
            try:
                if file_path.is_file():
                    file_path.unlink()
            except Exception:
                pass

        target_commit_obj = self.load_object(target_commit_hash)
        target_commit = Commit.from_content(target_commit_obj.content)

        if target_commit.tree_hash:
            self.restore_tree(target_commit.tree_hash, self.path)

        self.save_index({})

    def list_branches(self):
        current_branch = self.get_currrent_branch()
        branches = []

        if self.heads_dir.exists():
            for branch_file in sorted(self.heads_dir.glob("*")):
                if branch_file.is_file() and not branch_file.name.startswith("."):
                    branch_name = branch_file.name
                    if branch_name == current_branch:
                        branches.append(f"* {branch_name}")
                    else:
                        branches.append(f"  {branch_name}")

        return branches

    def delete_branch(self, branch_name: str) -> bool:
        current_branch = self.get_currrent_branch()
        branch_file = self.heads_dir / branch_name

        if not branch_file.exists():
            print(f"error: branch '{branch_name}' not found.")
            return False

        if branch_name == current_branch:
            print(
                f"error: Cannot delete the branch '{branch_name}' which you are currently on."
            )
            return False

        if branch_name == "master":
            print(f"error: Cannot delete branch 'master'.")
            return False

        try:
            branch_file.unlink()
            print(f"Deleted branch '{branch_name}'")
            return True
        except Exception as e:
            print(f"error: Failed to delete branch '{branch_name}': {e}")
            return False

    def status(self):
        current_branch = self.get_currrent_branch()
        print(f"On branch {current_branch}")
        print()

        index = self.load_index()

        staged_files = list(index.keys())
        untracked_files = []
        modified_unstaged_files = []
        deleted_files = []

        for file_path in self.path.rglob("*"):
            if file_path.is_file():
                if self._is_internal_path(file_path):
                    continue

                rel_path = str(file_path.relative_to(self.path))

                if rel_path not in index:
                    untracked_files.append(rel_path)
                else:
                    try:
                        current_content = file_path.read_bytes()
                        current_blob = Blob(current_content)
                        current_hash = current_blob.hash()

                        if current_hash != index[rel_path]:
                            modified_unstaged_files.append(rel_path)
                    except Exception as e:
                        print(f"Warning: Could not read {rel_path}: {e}")

        for indexed_file in index.keys():
            full_path = self.path / indexed_file
            if not full_path.exists():
                deleted_files.append(indexed_file)

        if staged_files:
            print("Changes to be committed:")

            for file in sorted(staged_files):
                print(f"\tmodified: {file}")
            print()
        else:
            print("No changes added to commit.")
            print()

        if modified_unstaged_files:
            print("Changes not staged for commit:")
            print('  (use "pit add <file>..." to update what will be committed)')

            for file in sorted(modified_unstaged_files):
                print(f"\tmodified: {file}")
            print()

        if deleted_files:
            if not modified_unstaged_files:
                print("Changes not staged for commit:")

            for file in sorted(deleted_files):
                print(f"\tdeleted: {file}")
            print()

        if untracked_files:
            print("Untracked files:")
            print('  (use "pit add <file>..." to include in what will be committed)')
            for file in sorted(untracked_files):
                print(f"\t{file}")
            print()

        if (
            not staged_files
            and not modified_unstaged_files
            and not deleted_files
            and not untracked_files
        ):
            print("working tree clean")

    def log(self, max_count: int = 10):
        current_branch = self.get_currrent_branch()
        commit_hash = self.get_branch_commit(current_branch)

        if not commit_hash:
            print("No commits yet!")
            return

        count = 0
        while commit_hash and count < max_count:
            commit_obj = self.load_object(commit_hash)
            commit = Commit.from_content(commit_obj.content)

            print(f"Commit: {commit_hash}")
            print(f"Author: {commit.author}")
            print(f"Date: {time.ctime(commit.timestamp)}")
            print(f"\n   {commit.message}\n")

            commit_hash = commit.parent_hashes[0] if commit.parent_hashes else None
            count += 1

    def _collect_reachable_objects(self, obj_hash: str, reachable: set) -> set:
        """Recursively collect all reachable objects from a given object hash."""
        if obj_hash in reachable:
            return reachable

        reachable.add(obj_hash)

        try:
            obj = self.load_object(obj_hash)

            if obj.type == "commit":
                commit = Commit.from_content(obj.content)
                # Add tree object
                if commit.tree_hash:
                    self._collect_reachable_objects(commit.tree_hash, reachable)
                # Add parent commits
                for parent_hash in commit.parent_hashes:
                    if parent_hash:
                        self._collect_reachable_objects(parent_hash, reachable)

            elif obj.type == "tree":
                tree = Tree.from_content(obj.content)
                # Add all entries in tree
                for mode, name, entry_hash in tree.entries:
                    if entry_hash:
                        self._collect_reachable_objects(entry_hash, reachable)

        except Exception as e:
            print(f"Warning: Could not process object {obj_hash}: {e}")

        return reachable

    def _get_all_stored_objects(self) -> set:
        """Get all object hashes currently stored in the repository."""
        all_objects = set()

        if not self.objects_dir.exists():
            return all_objects

        for obj_dir in self.objects_dir.iterdir():
            if obj_dir.is_dir():
                for obj_file in obj_dir.iterdir():
                    if obj_file.is_file():
                        obj_hash = obj_dir.name + obj_file.name
                        all_objects.add(obj_hash)

        return all_objects

    def _get_reachable_objects(self) -> set:
        """Get all objects reachable from branch commits."""
        reachable = set()

        # Collect all objects reachable from all branches
        if self.heads_dir.exists():
            for branch_file in self.heads_dir.iterdir():
                if branch_file.is_file():
                    commit_hash = branch_file.read_text().strip()
                    if commit_hash:
                        self._collect_reachable_objects(commit_hash, reachable)

        return reachable

    def garbage_collect(self) -> int:
        """Remove unreachable objects from the repository.

        Returns the number of objects deleted.
        """
        all_objects = self._get_all_stored_objects()
        reachable_objects = self._get_reachable_objects()

        unreachable_objects = all_objects - reachable_objects
        deleted_count = 0

        for obj_hash in unreachable_objects:
            try:
                obj_dir = self.objects_dir / obj_hash[:2]
                obj_file = obj_dir / obj_hash[2:]

                if obj_file.exists():
                    obj_file.unlink()
                    deleted_count += 1

                # Remove empty directory if it becomes empty
                if obj_dir.exists() and not list(obj_dir.iterdir()):
                    obj_dir.rmdir()

            except Exception as e:
                print(f"Warning: Could not delete object {obj_hash}: {e}")

        if deleted_count > 0:
            print(f"Garbage collection: removed {deleted_count} unreachable object(s)")
        else:
            print("Garbage collection: no unreachable objects found")

        return deleted_count


def main():
    parser = argparse.ArgumentParser(description="Pypit - pit Reimagined")
    subparsers = parser.add_subparsers(dest="command", help="Available Commands")

    init_parser = subparsers.add_parser("init", help="Initialize a new repository")

    add_parser = subparsers.add_parser(
        "add", help="Adds files and folders to the staging area."
    )
    add_parser.add_argument("paths", nargs="+", help="Files and directories to add")

    commit_parser = subparsers.add_parser("commit", help="Creates a new commit")

    commit_parser.add_argument("-m", "--message", help="Commit message", required=True)
    commit_parser.add_argument("-a", "--author", help="Author of the commit ")

    checkout_parser = subparsers.add_parser("checkout", help="Move/Create a new branch")
    checkout_parser.add_argument("branch", help="Branch to switch to")
    checkout_parser.add_argument(
        "-b",
        "--create-branch",
        action="store_true",
        help="Create and switch a new branch",
    )

    branch_parser = subparsers.add_parser("branch", help="List and manage branches")
    branch_parser.add_argument(
        "branch_name",
        nargs="?",
        help="Branch name (required with -d flag)",
    )
    branch_parser.add_argument(
        "-d",
        "--delete",
        action="store_true",
        help="Delete a branch",
    )

    log_parser = subparsers.add_parser("log", help="prints the log of commits")
    log_parser.add_argument(
        "-n", "--max-count", type=int, default=10, help="Limit commits showm"
    )

    status_parser = subparsers.add_parser("status", help="Show working tree status")

    gc_parser = subparsers.add_parser(
        "gc", help="Garbage collection - remove unreachable objects"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    repo = Repository()

    try:
        if args.command == "init":
            if not repo.init():
                print("Repository already exists.")
                return

        elif args.command == "add":
            if not repo.pit_dir.exists():
                print("Not a pit repository - maybe try doin `pit init` first")
                return

            for path in args.paths:
                repo.add_path(path)
        elif args.command == "commit":
            if not repo.pit_dir.exists():
                print("Not a pit repository")
                return

            author = args.author or "pit user <user@pit.com>"
            repo.commit(args.message)

        elif args.command == "checkout":
            if not repo.pit_dir.exists():
                print("Not a pit repo")
                return
            repo.checkout(args.branch, args.create_branch)

        elif args.command == "branch":
            if not repo.pit_dir.exists():
                print("Not a pit repository - maybe try doin `pit init` first")
                return

            if args.delete:
                if not args.branch_name:
                    print("error: branch name required with -d flag")
                    return
                repo.delete_branch(args.branch_name)
            else:
                branches = repo.list_branches()
                if branches:
                    for branch in branches:
                        print(branch)
                else:
                    print("No branches found.")

        elif args.command == "log":
            if not repo.pit_dir.exists():
                print("Not a pit repo")
                return
            repo.log(args.max_count)

        elif args.command == "status":
            if not repo.pit_dir.exists():
                print("Not a pit repository - maybe try doin `pit init` first")
                return
            repo.status()

        elif args.command == "gc":
            if not repo.pit_dir.exists():
                print("Not a pit repository - maybe try doin `pit init` first")
                return
            repo.garbage_collect()

    except Exception as e:
        print(f"Error -> {e}")
        sys.exit(1)
