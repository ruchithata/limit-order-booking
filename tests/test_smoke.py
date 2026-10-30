"""Smoke tests for the initial project setup."""

import engine


def test_package_version_is_available() -> None:
    """The engine package should import and expose its version."""
    assert engine.__version__ == "0.1.0"


def test_package_is_importable() -> None:
    """The initial package should be importable without runtime dependencies."""
    assert engine.__name__ == "engine"
