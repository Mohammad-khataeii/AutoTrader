"""Explicitly test-only process crashes. Never enabled by production settings."""
import os


def failpoint(name: str) -> None:
    if os.getenv("ENVIRONMENT") == "test" and os.getenv("AUTOTRADER_FAILPOINT") == name:
        os._exit(86)
