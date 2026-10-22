"""Application-local CLR configuration for portable Windows executables."""
from pathlib import Path

CLR_CONFIG = ('<?xml version="1.0" encoding="utf-8"?>\n'
              '<configuration><runtime><loadFromRemoteSources enabled="true" />'
              '</runtime></configuration>\n')


def ensure_clr_config(executable: Path) -> Path:
    target = executable.with_suffix(".exe.config")
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(CLR_CONFIG)
    except FileExistsError:
        pass
    return target
