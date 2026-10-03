"""Bounded, read-only UTF-8 source loading; no shell or code execution."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import stat


DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MAX_SOURCE_BYTES = 2 * 1024 * 1024
HIDDEN_COMPONENTS = frozenset({".git", ".venv", ".aws", ".codex", "__pycache__"})
# The portable public build has no author-specific workspace exclusions.
# Hidden credential folders and paths outside the selected root stay blocked.
EXCLUDED_WORKSPACES: tuple[Path, ...] = ()


class SourceFileError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class SourceDocument:
    path: Path
    text: str
    language: str
    size_bytes: int


def _excluded(path: Path) -> bool:
    return any(path == excluded or path.is_relative_to(excluded) for excluded in EXCLUDED_WORKSPACES)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path))


class SourceFilesService:
    def __init__(self, root_path: Path | str = DEFAULT_WORKSPACE_ROOT, *, max_bytes: int = MAX_SOURCE_BYTES):
        try:
            root = _absolute(Path(root_path).expanduser())
            if _excluded(root) or any(part.casefold() in HIDDEN_COMPONENTS for part in root.parts):
                raise SourceFileError("EXCLUDED_PATH", "This folder is excluded from the source workspace.")
            if root.is_symlink():
                raise SourceFileError("ROOT_SYMLINK", "Choose the actual workspace folder, not a folder symlink.")
            root = root.resolve(strict=True)
            if _excluded(root):
                raise SourceFileError("EXCLUDED_PATH", "This folder is excluded from the source workspace.")
            if not root.is_dir():
                raise SourceFileError("NOT_DIRECTORY", "Choose an existing workspace folder.")
        except SourceFileError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise SourceFileError("ROOT_UNAVAILABLE", "The selected workspace folder is unavailable.") from error
        self.root_path = root
        self.max_bytes = max_bytes

    def resolve_path(self, value: Path | str) -> Path:
        """Resolve links inside the root without following a target outside it."""
        try:
            supplied = Path(value).expanduser()
            candidate = _absolute(supplied if supplied.is_absolute() else self.root_path / supplied)
            if not candidate.is_relative_to(self.root_path):
                raise SourceFileError("OUTSIDE_WORKSPACE", "The file is outside the selected workspace.")
            relative = candidate.relative_to(self.root_path)
            pending = deque(relative.parts)
            current = self.root_path
            links = 0
            while pending:
                part = pending.popleft()
                if part.casefold() in HIDDEN_COMPONENTS:
                    raise SourceFileError("EXCLUDED_PATH", f"{part} is excluded from the source workspace.")
                current = current / part
                if _excluded(current):
                    raise SourceFileError("EXCLUDED_PATH", "This path is excluded from the source workspace.")
                metadata = current.lstat()
                mode = metadata.st_mode
                reparse = bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
                if stat.S_ISLNK(mode) or reparse:
                    links += 1
                    if links > 40:
                        raise SourceFileError("SYMLINK_LOOP", "The source path contains a symlink loop.")
                    target_text = os.readlink(current)
                    if os.name == "nt" and target_text.startswith("\\\\?\\UNC\\"):
                        target_text = "\\\\" + target_text[8:]
                    elif os.name == "nt" and target_text.startswith("\\\\?\\"):
                        target_text = target_text[4:]
                    target = Path(target_text)
                    target = _absolute(target if target.is_absolute() else current.parent / target)
                    if not target.is_relative_to(self.root_path) or _excluded(target):
                        raise SourceFileError("OUTSIDE_WORKSPACE", "The symlink points outside the selected workspace.")
                    pending = deque((*target.relative_to(self.root_path).parts, *pending))
                    current = self.root_path
            return current
        except SourceFileError:
            raise
        except FileNotFoundError as error:
            raise SourceFileError("FILE_NOT_FOUND", f"Source file was not found: {Path(value).name}.") from error
        except (OSError, TypeError, ValueError) as error:
            raise SourceFileError("FILE_UNAVAILABLE", "The source path cannot be accessed.") from error

    def read_file(self, value: Path | str) -> SourceDocument:
        path = self.resolve_path(value)
        try:
            if not path.is_file():
                raise SourceFileError("NOT_FILE", "Select a text file; folders cannot become code tabs.")
            if path.stat().st_size > self.max_bytes:
                raise SourceFileError("FILE_TOO_LARGE", "Source preview is limited to 2 MiB per file.")
            with path.open("rb") as stream:
                raw = stream.read(self.max_bytes + 1)
            if len(raw) > self.max_bytes:
                raise SourceFileError("FILE_TOO_LARGE", "Source preview is limited to 2 MiB per file.")
            if b"\x00" in raw or any(byte < 32 and byte not in (9, 10, 12, 13) for byte in raw):
                raise SourceFileError("BINARY_FILE", "Binary files cannot be displayed as source code.")
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeError as error:
                raise SourceFileError("UNSUPPORTED_ENCODING", "Source preview supports UTF-8 text files only.") from error
            language = {".py": "python", ".pyw": "python", ".json": "json"}.get(path.suffix.lower(), "text")
            return SourceDocument(path, text, language, len(raw))
        except SourceFileError:
            raise
        except OSError as error:
            raise SourceFileError("FILE_UNAVAILABLE", f"Cannot read source file: {path.name}.") from error
