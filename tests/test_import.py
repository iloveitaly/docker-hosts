"""Test docker-hosts."""

import docker_hosts


def test_import() -> None:
    """Test that the  can be imported."""
    assert isinstance(docker_hosts.__name__, str)