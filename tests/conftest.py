"""Pytest configuration and shared fixtures for docker-hosts tests."""

import docker
import pytest
from structlog_config import configure_logger

from docker_hosts.cli import DockerHostsManager


@pytest.fixture
def docker_client():
    """Provides a real Docker client for integration tests."""
    return docker.from_env()


@pytest.fixture
def log():
    """Provides a configured structlog logger for tests."""
    return configure_logger()


@pytest.fixture
def tmp_hosts_file(tmp_path):
    """Creates an isolated temporary hosts file for testing."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    return hosts_file


@pytest.fixture
def manager(log):
    """Provides a manager without a Docker client for unit tests."""
    return DockerHostsManager(None, log)


@pytest.fixture
def docker_manager(docker_client, log):
    """Provides a manager with a real Docker client for integration tests."""
    return DockerHostsManager(docker_client, log)
