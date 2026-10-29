"""Nonsecret build identity for prospective decision records."""
from __future__ import annotations

import os
import re
from importlib.metadata import version


def release_identity() -> dict[str, str | None]:
    revision = os.environ.get('AUTOTRADER_RELEASE_COMMIT', '')
    return {'version': version('revolutx-autotrader'),
            'commit': revision if re.fullmatch('[a-f0-9]{40}', revision) else None,
            'scope': 'INSTALLED_BUILD_IDENTITY_NOT_MODEL_APPROVAL'}
