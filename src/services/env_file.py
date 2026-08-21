"""
Safe read-modify-write of the dotenv file that backs runtime-editable settings.

- The target file is the highest-priority *existing* file from Settings.model_config["env_file"]
  (pydantic-settings loads them in order, later files override earlier ones). In Docker that is
  /config/.env (volume); in local dev it is ./.env. If none exists one is created.
- Only the requested keys are touched. Everything else (comments, ordering, other keys,
  multi-line values) is preserved byte-for-byte by rebuilding the file from python-dotenv's
  parser bindings, whose `original.string` spans reproduce the source exactly.
- Values are written double-quoted with dotenv escapes (\\\\, \\", \\n) so multi-line text such
  as USER_PROFILE round-trips; the file is replaced atomically (temp file + os.replace).
"""
import io
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Iterable

from dotenv.parser import parse_stream

from src.config import settings


def candidate_env_files() -> List[Path]:
    files = settings.model_config.get("env_file") or []
    if isinstance(files, (str, os.PathLike)):
        files = [files]
    return [Path(f) for f in files]


def resolve_env_file_path() -> Path:
    """
    The file UI writes go to: the last (highest-priority) existing env file; if none exists,
    /config/.env when the /config volume is present (Docker), otherwise ./.env.
    """
    existing = [p for p in candidate_env_files() if p.is_file()]
    if existing:
        return existing[-1].resolve()
    if Path("/config").is_dir():
        return Path("/config/.env")
    return Path(".env").resolve()


def encode_value(value: str) -> str:
    """Double-quoted dotenv literal. Decoded by python-dotenv back to the same string."""
    value = "" if value is None else str(value)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def read_env_values(path: Path) -> Dict[str, Optional[str]]:
    if not path.is_file():
        return {}
    from dotenv import dotenv_values
    return dict(dotenv_values(path, interpolate=False))


def render_updated(source: str, updates: Dict[str, str]) -> str:
    """
    Return `source` with each key in `updates` replaced in place (first occurrence replaced,
    later duplicates removed) or appended at the end if absent.
    """
    bindings = list(parse_stream(io.StringIO(source)))
    # Sanity: the parser must reproduce the file exactly, otherwise bail out rather than risk damage.
    if "".join(b.original.string for b in bindings) != source:
        raise ValueError("env file could not be parsed losslessly; refusing to rewrite it")

    remaining = dict(updates)
    seen = set()
    out: List[str] = []
    for b in bindings:
        if b.key in remaining:
            if b.key in seen:
                continue  # drop duplicate definitions of a key we are rewriting
            seen.add(b.key)
            out.append(f"{b.key}={encode_value(remaining[b.key])}\n")
        else:
            out.append(b.original.string)
    text = "".join(out)
    missing = [k for k in updates if k not in seen]
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        if text and not text.endswith("\n\n"):
            text += "\n"
        text += "# Written by Paper Agent Settings page\n"
        for k in missing:
            text += f"{k}={encode_value(updates[k])}\n"
    return text


def update_env_file(updates: Dict[str, str], path: Optional[Path] = None) -> Path:
    """Apply `updates` to the env file atomically. Returns the path written."""
    path = path or resolve_env_file_path()
    source = path.read_text(encoding="utf-8") if path.is_file() else ""
    new_text = render_updated(source, updates)
    if new_text == source:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
            f.flush()
            os.fsync(f.fileno())
        if path.is_file():
            try:
                os.chmod(tmp_name, path.stat().st_mode & 0o777)
            except OSError:
                pass
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def is_writable(path: Path) -> bool:
    if path.is_file():
        return os.access(path, os.W_OK)
    return os.access(path.parent if path.parent.exists() else Path("."), os.W_OK)


def env_overrides(keys: Iterable[str]) -> Dict[str, str]:
    """
    Keys that are set as *process* environment variables (which outrank the env file),
    mapped to the actual variable name found. pydantic-settings is case-insensitive by default.
    """
    found = {}
    upper_env = {k.upper(): k for k in os.environ}
    for key in keys:
        if key.upper() in upper_env:
            found[key] = upper_env[key.upper()]
    return found
