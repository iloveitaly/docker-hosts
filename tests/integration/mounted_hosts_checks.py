"""Checks collected explicitly by pytest inside a disposable Docker container."""

import errno
import os
from pathlib import Path

import pytest

from docker_hosts.cli import END_PATTERN, START_PATTERN


@pytest.fixture(autouse=True)
def require_container_hosts_mount():
    assert " /etc/hosts " in Path("/proc/self/mountinfo").read_text()


def test_update_mounted_hosts_preserves_file_and_truncates(manager):
    hosts_path = Path("/etc/hosts")
    original_content = hosts_path.read_text()
    original_stat = hosts_path.stat()
    aux_path = hosts_path.with_suffix(".aux")
    aux_path.write_text(original_content)

    try:
        with pytest.raises(OSError) as error:
            aux_path.replace(hosts_path)

        assert error.value.errno == errno.EBUSY
    finally:
        aux_path.unlink()

    for domains in ({"app", "longer-alias", "another-alias"}, {"app"}, set()):
        manager.hosts = {
            "app": [{"ip": "192.0.2.1", "name": "app", "domains": domains}]
        }
        expected_content = original_content
        if domains:
            aliases = "   ".join(f"{domain}.test" for domain in sorted(domains))
            expected_content += (
                f"\n\n{START_PATTERN}192.0.2.1    {aliases}\n{END_PATTERN}\n"
            )

        manager.update_hosts_file(hosts_path, dry_run=False, tld="test")

        assert hosts_path.read_text() == expected_content
        assert not aux_path.exists()
        current_stat = hosts_path.stat()
        assert current_stat.st_ino == original_stat.st_ino
        assert current_stat.st_uid == original_stat.st_uid
        assert current_stat.st_gid == original_stat.st_gid
        assert current_stat.st_mode == original_stat.st_mode


def test_replacement_permission_error_does_not_write_in_place(manager):
    hosts_directory = Path("/tmp/docker-hosts-permission-test")
    hosts_directory.mkdir()
    hosts_directory.chmod(0o1777)
    hosts_path = hosts_directory / "hosts"
    original_content = "127.0.0.1    localhost\n"
    hosts_path.write_text(original_content)
    hosts_path.chmod(0o666)

    os.seteuid(65534)
    try:
        with pytest.raises(PermissionError) as error:
            manager.write_hosts_file(hosts_path, "192.0.2.1    app.test\n")

        assert error.value.errno == errno.EPERM
    finally:
        os.seteuid(0)

    assert hosts_path.read_text() == original_content
    assert not hosts_path.with_suffix(".aux").exists()


def test_read_only_filesystem_error_propagates(manager):
    hosts_path = Path("/sys/docker-hosts-test")

    with pytest.raises(OSError) as error:
        manager.write_hosts_file(hosts_path, "192.0.2.1    app.test\n")

    assert error.value.errno == errno.EROFS
