from __future__ import annotations
import argparse
import sys
from pathlib import Path
import json
import hashlib
from typing import Dict, List, Tuple
import zlib
import time


class GitObject:
    def __init__(self, obj_type: str, content: bytes):
        self.type = obj_type
        self.content = content

    def hash(self) -> str:
        # f(<type><size>\0<content>)
        header = f"{self.type} {len(self.content)}\0".encode()
        return hashlib.sha1(header + self.content).hexdigest()

    def serialize(self) -> bytes:
        header = f"{self.type} {len(self.content)}\0".encode()
        return zlib.compress(header + self.content)

    @classmethod
    def deserialize(cls, data: bytes) -> GitObject:
        decompressed = zlib.decompress(data)
        null_idx = decompressed.find(b"\0")
        header = decompressed[:null_idx]
        content = decompressed[null_idx + 1 :]

        obj_type_bytes, _ = header.split(b" ", 1)
        obj_type = obj_type_bytes.decode()

        return cls(obj_type, content)


class Blob(GitObject):
    def __init__(self, content: bytes):
        super().__init__("blob", content)

    def get_content(self) -> bytes:
        return self.content


class Tree(GitObject):
    def __init__(
        self, entries: List[Tuple[str, str, str]] = None
    ):  # mode name hash - str str str
        self.entries = entries or []
        content = self._serialize_entries()
        super().__init__("tree", content)

    def _serialize_entries(self) -> bytes:
        # <mode> <name> \0 <hash>
        content = b""
        for mode, name, obj_hash in sorted(
            self.entries
        ):  # sorting bcz SHA1 hashing is different for hi.txt - hello.txt and hello.txt - hi.txt -> therefore could cause two diff commits
            content += f"{mode} {name} \0".encode()
            content += bytes.fromhex(
                obj_hash
            )  # bcz in serialize funcn above we are doing hexdigest() so to change it back to bytes we do this

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
            # 100644 README.md\0[20Bytes of content SHA1 hash]100645 README.md\0[20 bytes] ==> if we dont use ,i in .find() it would return first idx where it found \0 and then restart with i = 0
            if null_idx == -1:
                break

            mode_name = content[i:null_idx].decode()
            mode, name = mode_name.split(" ", 1)  # ,1 means it will only split once
            obj_hash = content[
                null_idx + 1 : null_idx + 21
            ].hex()  # 21 because SHA1 is sure to give 20 bytes of hash
            tree.entries.append((mode, name, obj_hash))

            i = null_idx + 21

        return tree


class Commit(GitObject):
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

        return "\n".join(
            lines
        ).encode()  # normally concatenating string takes more time than turning it into lists and rejoining

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
                tree_hash = line[5:]  # 5 because tree<space>  has 5 chars

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
        self.git_dir = self.path / ".pit"

        # pit/objects
        self.objects_dir = self.git_dir / "objects"

        # pit/refs
        self.refs_dir = self.git_dir / "refs"
        self.heads_dir = self.refs_dir / "heads"

        # pit/HEAD
        self.head_file = self.git_dir / "HEAD"

        # pit/index
        self.index_file = self.git_dir / "index"

    def init(self) -> bool:

        if self.git_dir.exists():
            return False

        # making folders with given vars
        self.git_dir.mkdir()
        self.objects_dir.mkdir()
        self.refs_dir.mkdir()
        self.heads_dir.mkdir()

        # other two are files and not directories
        self.head_file.write_text(
            "ref: refs/heads/master\n"
        )  # write in heads and not head

        self.save_index({})

        self.index_file.write_text(json.dumps({}, indent=2))

        print(f"Initialized empty pit repository in {self.git_dir} ")

        return True

    def store_object(self, obj: GitObject):
        obj_hash = obj.hash()
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            obj_dir.mkdir(exist_ok=True)
            obj_file.write_bytes(obj.serialize())

        return obj_hash

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

        # read file content
        content = full_path.read_bytes()

        # create BLOB object from the content
        blob = Blob(content)

        # store the blob object in local database aka file-system (.git/objects)
        blob_hash = self.store_object(blob)

        # update the index to include the file
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

        # recursively traverse directory
        # create blob objects for all files
        # store all blobs in object db (.git/objects)
        # update the index to include all the files

        for file_path in full_path.rglob("*"):
            if file_path.is_file():
                if ".pit" in file_path.parts or ".git" in file_path.parts:
                    continue

                # create & store blob object
                content = file_path.read_bytes()
                blob = Blob(content)
                blob_hash = self.store_object(blob)

                # update index
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

    def load_object(self, obj_hash: str) -> GitObject:
        obj_dir = self.objects_dir / obj_hash[:2]
        obj_file = obj_dir / obj_hash[2:]

        if not obj_file.exists():
            raise FileNotFoundError(f"Object {obj_hash} not found")

        return GitObject.deserialize(obj_file.read_bytes())

    def create_tree_from_index(self):
        index = self.load_index()
        if not index:
            tree = Tree()
            return self.store_object(tree)

        dirs = {}
        files = {}

        for file_path, blob_hash in index.items():
            parts = file_path.split("/")

            if len(parts) == 1:  # root directory
                files[parts[0]] = blob_hash
            else:
                dir_name = parts[0]
                if dir_name not in dirs:
                    dirs[dir_name] = {}
                current = dirs[dir_name]

                for part in parts[1:-1]:  # skipping the last part / element
                    if part not in current:
                        current[part] = {}

                    current = current[part]

                current[parts[-1]] = (
                    blob_hash  # assigning last element to current which is = blob_hash
                )

        # Mode ==> 100644 -> file and 40000 -> Directory
        def create_tree_recusrively(entries_dict: Dict):
            tree = Tree()  # empty tree

            for name, blob_hash in entries_dict.items():
                if isinstance(blob_hash, str):
                    tree.add_entry(
                        "100644", name, blob_hash
                    )  # populates tree with filename

                if isinstance(blob_hash, dict):
                    subtreee_hash = create_tree_recusrively(blob_hash)
                    tree.add_entry("40000", name, subtreee_hash)

            return self.store_object(tree)

        root_entries = {**files}

        for dir_name, dir_contents in dirs.items():
            root_entries[dir_name] = (
                dir_contents  # creates a single dictionary with everything, files, folders,etc.
            )

        return create_tree_recusrively(root_entries)

    def get_currrent_branch(self) -> str:
        if not self.head_file.exists():
            return "master"
        head_content = self.head_file.read_text().strip()

        if head_content.startswith("ref: refs/heads"):
            return head_content[16:]  # 16 letters already written in startwith

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

        # create a tree object from index (staging area)
        tree_hash = self.create_tree_from_index()

        current_branch = self.get_currrent_branch()

        parent_commit = self.get_branch_commit(current_branch)
        parent_hashes = [parent_commit] if parent_commit else []
        index = self.load_index()

        if not index:
            print("nothing to commit, working tree is clean")
            return None

        # if there has been no changes before commiting - we have to check tree hashes to ensure they are not same

        if parent_commit:
            parent_git_commit_object = self.load_object(parent_commit)
            parent_commit_data = Commit.from_content(parent_git_commit_object.content)
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

        pass


def main():
    parser = argparse.ArgumentParser(description="PyGit - Git Reimagined")
    subparsers = parser.add_subparsers(dest="command", help="Available Commands")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize a new repository")

    # add command
    add_parser = subparsers.add_parser(
        "add", help="Adds files and folders to the staging area."
    )
    add_parser.add_argument(
        "paths", nargs="+", help="Files and directories to add"
    )  # (?) -> 0 or 1 args and (*) -> 0 or any no of args

    # commit command
    commit_parser = subparsers.add_parser("commit", help="Creates a new commit")

    commit_parser.add_argument("-m", "--message", help="Commit message", required=True)
    commit_parser.add_argument("-a", "--author", help="Author of the commit ")

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
            if not repo.git_dir.exists():
                print("Not a pit repository - maybe try doin `pit init` first")
                return

            for path in args.paths:
                repo.add_path(path)
        elif args.command == "commit":
            if not repo.git_dir.exists():
                print("Not a git repository")
                return

            author = args.author or "pit user <user@pit.com>"
            repo.commit(args.message)

    except Exception as e:
        print(f"Error -> {e}")
        sys.exit(1)

    print(args)


main()
