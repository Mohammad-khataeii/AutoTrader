"""Seed this project's dedicated research volume without deleting prior versions."""
from __future__ import annotations

import os
from pathlib import Path

from autotrader.research.data import atomic_write, digest


def main() -> None:
    source,destination=Path('/seed'),Path('/app/research')
    for directory in (destination,Path('/app/reports')):
        directory.mkdir(parents=True,exist_ok=True)
    for path in sorted(source.rglob('*')):
        if not path.is_file() or path.suffix=='.tmp' or path.is_symlink():
            continue
        relative=path.relative_to(source)
        target=destination/relative
        if target.exists():
            if relative.parts[0] in {'datasets','runs'} and digest(target.read_bytes())!=digest(path.read_bytes()):
                raise ValueError('Immutable research version conflicts with the seed: '+str(relative))
            continue  # Preserve volume's current catalog and report pointer.
        atomic_write(target,path.read_bytes())
    for directory in (destination,Path('/app/reports')):
        for path in [directory,*directory.rglob('*')]:
            if not path.is_symlink():
                os.chown(path,10001,10001)
    print('Research seed complete; prior versions and volume pointers preserved.')


if __name__=='__main__':
    main()
