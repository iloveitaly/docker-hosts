"""Run file-operation checks against Docker's actual mounted /etc/hosts."""

import tarfile
from io import BytesIO
from pathlib import Path

import pytest


@pytest.mark.integration
def test_docker_mounted_hosts(docker_client):
    project_path = Path(__file__).resolve().parents[2]
    archive_buffer = BytesIO()

    with tarfile.open(fileobj=archive_buffer, mode="w") as archive:
        for relative_path in (
            "docker_hosts",
            "pyproject.toml",
            "README.md",
            "tests/conftest.py",
            "tests/integration/mounted_hosts_checks.py",
        ):
            archive.add(project_path / relative_path, arcname=relative_path)

    image = "python:3.13-slim"
    docker_client.images.pull(image)
    container = docker_client.containers.create(
        image,
        command=[
            "sh",
            "-ec",
            (
                "pip install /project pytest && "
                "pytest -o addopts= tests/integration/mounted_hosts_checks.py"
            ),
        ],
        working_dir="/project",
    )

    try:
        container.put_archive("/project", archive_buffer.getvalue())
        container.start()
        result = container.wait(timeout=300)

        assert result["StatusCode"] == 0, container.logs().decode()
    finally:
        container.remove(force=True)
