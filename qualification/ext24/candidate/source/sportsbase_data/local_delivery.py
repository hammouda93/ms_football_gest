"""Safe checks for delivery files stored by the local Performance agent."""

from pathlib import Path, PurePosixPath


def resolve_existing_actions_file(storage_root, folder_key, filename):
    """Return a non-empty All Actions file contained inside storage_root."""
    folder = PurePosixPath(str(folder_key or "").replace("\\", "/"))
    raw_filename = str(filename or "").replace("\\", "/")
    safe_filename = PurePosixPath(raw_filename).name
    if (
        not folder_key
        or not safe_filename
        or folder.is_absolute()
        or ".." in folder.parts
    ):
        return None

    root = Path(storage_root).resolve()
    candidate = (root.joinpath(*folder.parts) / safe_filename).resolve()
    if root != candidate and root not in candidate.parents:
        return None
    try:
        return candidate if candidate.is_file() and candidate.stat().st_size > 0 else None
    except OSError:
        return None
