"""Test docker-hosts."""

import docker_hosts


def test_import() -> None:
    """Test that the  can be imported."""
    assert isinstance(docker_hosts.__name__, str)


def test_version() -> None:
    """Test that the version is available."""
    assert isinstance(docker_hosts.__version__, str)
