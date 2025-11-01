"""Integration tests using real Docker containers from docker-compose.yml."""

import pytest

from docker_hosts.cli import START_PATTERN, END_PATTERN


@pytest.mark.integration
def test_load_running_containers_finds_compose_services(manager):
    """Verify that postgres and redis containers from docker-compose are detected."""
    manager.load_running_containers()

    assert len(manager.hosts) >= 2

    container_names = []
    for container_data_list in manager.hosts.values():
        for container_data in container_data_list:
            container_names.append(container_data["name"])

    assert any("postgres" in name for name in container_names)
    assert any("redis" in name for name in container_names)


@pytest.mark.integration
def test_extract_postgres_container_data(manager, docker_client):
    """Verify postgres container data is correctly extracted."""
    postgres_containers = [c for c in docker_client.containers.list() if "postgres" in c.name]
    assert len(postgres_containers) > 0

    postgres = postgres_containers[0]
    container_data = manager.get_container_data(postgres.attrs)

    assert len(container_data) > 0

    for entry in container_data:
        assert "ip" in entry
        assert entry["ip"]
        assert "name" in entry
        assert "postgres" in entry["name"]
        assert "domains" in entry
        assert len(entry["domains"]) > 0


@pytest.mark.integration
def test_extract_redis_container_data(manager, docker_client):
    """Verify redis container data is correctly extracted."""
    redis_containers = [c for c in docker_client.containers.list() if "redis" in c.name]
    assert len(redis_containers) > 0

    redis = redis_containers[0]
    container_data = manager.get_container_data(redis.attrs)

    assert len(container_data) > 0

    for entry in container_data:
        assert "ip" in entry
        assert entry["ip"]
        assert "name" in entry
        assert "redis" in entry["name"]
        assert "domains" in entry
        assert len(entry["domains"]) > 0


@pytest.mark.integration
def test_full_workflow_writes_hosts_file(manager, tmp_hosts_file):
    """Test complete workflow: load containers → generate entries → write file."""
    manager.load_running_containers()
    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    content = tmp_hosts_file.read_text()

    assert "127.0.0.1    localhost" in content
    assert START_PATTERN.strip() in content
    assert END_PATTERN.strip() in content

    lines = content.split("\n")
    in_docker_section = False
    docker_entries = []

    for line in lines:
        if START_PATTERN.strip() in line:
            in_docker_section = True
            continue
        if END_PATTERN.strip() in line:
            in_docker_section = False
            continue
        if in_docker_section and line.strip():
            docker_entries.append(line)

    assert len(docker_entries) > 0

    has_postgres = any("postgres" in entry for entry in docker_entries)
    has_redis = any("redis" in entry for entry in docker_entries)

    assert has_postgres
    assert has_redis


@pytest.mark.integration
def test_hosts_file_format(manager, tmp_hosts_file):
    """Verify generated hosts file has correct format."""
    manager.load_running_containers()
    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="test")

    content = tmp_hosts_file.read_text()
    lines = content.split("\n")

    marker_count = sum(1 for line in lines if START_PATTERN.strip() in line or END_PATTERN.strip() in line)
    assert marker_count == 2

    in_docker_section = False
    for line in lines:
        if START_PATTERN.strip() in line:
            in_docker_section = True
            continue
        if END_PATTERN.strip() in line:
            break
        if in_docker_section and line.strip():
            parts = line.split()
            assert len(parts) >= 2
            ip = parts[0]
            assert "." in ip
            domains = parts[1:]
            for domain in domains:
                assert domain.endswith(".test")


@pytest.mark.integration
def test_dry_run_mode(manager, tmp_hosts_file, capsys):
    """Verify dry-run mode prints entries without writing file."""
    original_content = tmp_hosts_file.read_text()

    manager.load_running_containers()
    manager.update_hosts_file(str(tmp_hosts_file), dry_run=True, tld="localhost")

    assert tmp_hosts_file.read_text() == original_content

    captured = capsys.readouterr()
    assert START_PATTERN.strip() in captured.out
    assert END_PATTERN.strip() in captured.out


@pytest.mark.integration
def test_atomic_file_write_creates_aux_file(manager, tmp_hosts_file):
    """Verify atomic writes use .aux temporary file."""
    manager.load_running_containers()

    aux_file = tmp_hosts_file.with_suffix('.aux')
    assert not aux_file.exists()

    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    assert not aux_file.exists()
    assert tmp_hosts_file.exists()


@pytest.mark.integration
def test_preserves_existing_hosts_content(manager, tmp_hosts_file):
    """Verify pre-marker content is preserved when updating."""
    custom_content = "127.0.0.1    localhost\n192.168.1.1    custom.host\n"
    tmp_hosts_file.write_text(custom_content)

    manager.load_running_containers()
    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    content = tmp_hosts_file.read_text()

    assert "127.0.0.1    localhost" in content
    assert "192.168.1.1    custom.host" in content

    pre_marker = content.split(START_PATTERN)[0]
    assert "127.0.0.1    localhost" in pre_marker
    assert "192.168.1.1    custom.host" in pre_marker
