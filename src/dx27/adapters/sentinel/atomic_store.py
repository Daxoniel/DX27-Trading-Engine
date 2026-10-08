"""Publish complete, fsynced files with exclusive creation, on NTFS/POSIX."""

import os
from pathlib import Path
from uuid import uuid4


def exclusive_write(path, data):
    path = Path(path)
    pending = path.parent / (".pending-" + uuid4().hex)
    try:
        with pending.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard-link publication is atomic and refuses replacement of existing files.
        os.link(pending, path)
    finally:
        if pending.exists():
            pending.unlink()
