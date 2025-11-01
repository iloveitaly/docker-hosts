"""Pytest configuration and shared fixtures for docker-hosts tests."""

from pathlib import Path

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
    """Creates a temporary hosts file in tmp/ directory for testing."""
    hosts_dir = Path.cwd() / "tmp"
    hosts_dir.mkdir(exist_ok=True)

    hosts_file = hosts_dir / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    yield hosts_file

    if hosts_file.exists():
        hosts_file.unlink()


@pytest.fixture
def manager(docker_client, log):
    """Provides a fresh DockerHostsManager instance for each test."""
    return DockerHostsManager(docker_client, log)
