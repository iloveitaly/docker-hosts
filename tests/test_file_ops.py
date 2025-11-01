"""Unit tests for file operations."""

from pathlib import Path

import pytest

from docker_hosts.cli import START_PATTERN, END_PATTERN


@pytest.mark.unit
def test_read_existing_hosts_without_marker(manager, tmp_hosts_file):
    """Reading a hosts file without markers returns all lines."""
    content = "127.0.0.1    localhost\n192.168.1.1    example.com\n"
    tmp_hosts_file.write_text(content)

    lines = manager.read_existing_hosts(tmp_hosts_file)

    assert ''.join(lines) == content


@pytest.mark.unit
def test_read_existing_hosts_with_marker(manager, tmp_hosts_file):
    """Reading a hosts file with markers returns only pre-marker content."""
    content = f"127.0.0.1    localhost\n{START_PATTERN}172.17.0.2    container.localhost\n{END_PATTERN}"
    tmp_hosts_file.write_text(content)

    lines = manager.read_existing_hosts(tmp_hosts_file)

    assert ''.join(lines) == "127.0.0.1    localhost\n"


@pytest.mark.unit
def test_read_existing_hosts_empty_file(manager, tmp_hosts_file):
    """Reading an empty hosts file returns empty list."""
    tmp_hosts_file.write_text("")

    lines = manager.read_existing_hosts(tmp_hosts_file)

    assert lines == []


@pytest.mark.unit
def test_remove_trailing_blank_lines(manager):
    """Trailing blank lines are removed from line list."""
    lines = ["line1\n", "line2\n", "\n", "\n", ""]

    result = manager.remove_trailing_blank_lines(lines)

    assert result == ["line1\n", "line2\n"]


@pytest.mark.unit
def test_remove_trailing_blank_lines_no_blanks(manager):
    """Line list without trailing blanks is unchanged."""
    lines = ["line1\n", "line2\n"]

    result = manager.remove_trailing_blank_lines(lines)

    assert result == ["line1\n", "line2\n"]


@pytest.mark.unit
def test_remove_trailing_blank_lines_all_blank(manager):
    """All blank lines results in empty list."""
    lines = ["\n", "\n", ""]

    result = manager.remove_trailing_blank_lines(lines)

    assert result == []


@pytest.mark.unit
def test_generate_host_entries_empty_hosts(manager):
    """Empty hosts dict generates no entries."""
    manager.hosts = {}

    entries = manager.generate_host_entries("localhost")

    assert entries == []


@pytest.mark.unit
def test_generate_host_entries_single_container(manager):
    """Single container generates properly formatted entry."""
    manager.hosts = {
        "container1": [
            {
                "ip": "172.17.0.2",
                "name": "postgres",
                "domains": {"postgres", "db"}
            }
        ]
    }

    entries = manager.generate_host_entries("test")

    assert len(entries) == 3
    assert entries[0] == f"\n\n{START_PATTERN}"
    assert "172.17.0.2" in entries[1]
    assert "db.test" in entries[1]
    assert "postgres.test" in entries[1]
    assert entries[-1] == f"{END_PATTERN}\n"


@pytest.mark.unit
def test_generate_host_entries_domains_sorted(manager):
    """Domains are sorted alphabetically in output."""
    manager.hosts = {
        "container1": [
            {
                "ip": "172.17.0.2",
                "name": "app",
                "domains": {"zebra", "alpha", "middle"}
            }
        ]
    }

    entries = manager.generate_host_entries("localhost")

    entry_line = entries[1]
    domains = entry_line.split()[1:]
    assert domains == ["alpha.localhost", "middle.localhost", "zebra.localhost"]


@pytest.mark.unit
def test_write_hosts_file_creates_aux(manager, tmp_hosts_file, log):
    """Writing hosts file uses .aux temporary file."""
    content = "127.0.0.1    localhost\n"

    manager.write_hosts_file(tmp_hosts_file, content)

    assert tmp_hosts_file.read_text() == content

    aux_file = tmp_hosts_file.with_suffix('.aux')
    assert not aux_file.exists()


@pytest.mark.unit
def test_update_hosts_file_dry_run(manager, tmp_hosts_file, capsys):
    """Dry-run mode prints to stdout without modifying file."""
    original_content = tmp_hosts_file.read_text()
    manager.hosts = {
        "container1": [
            {
                "ip": "172.17.0.2",
                "name": "postgres",
                "domains": {"postgres"}
            }
        ]
    }

    manager.update_hosts_file(str(tmp_hosts_file), dry_run=True, tld="localhost")

    assert tmp_hosts_file.read_text() == original_content

    captured = capsys.readouterr()
    assert START_PATTERN.strip() in captured.out
    assert "postgres.localhost" in captured.out


@pytest.mark.unit
def test_update_hosts_file_consistent_formatting(manager, tmp_hosts_file):
    """Updating hosts file ensures consistent spacing before Docker section."""
    tmp_hosts_file.write_text("127.0.0.1    localhost\n\n\n")

    manager.hosts = {
        "container1": [
            {
                "ip": "172.17.0.2",
                "name": "app",
                "domains": {"app"}
            }
        ]
    }

    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    content = tmp_hosts_file.read_text()

    assert "127.0.0.1    localhost\n\n\n### Start Docker Domains ###" in content


@pytest.mark.unit
def test_update_hosts_file_with_existing_docker_section(manager, tmp_hosts_file):
    """Updating replaces existing Docker section."""
    existing = f"127.0.0.1    localhost\n{START_PATTERN}172.17.0.2    old.localhost\n{END_PATTERN}\n"
    tmp_hosts_file.write_text(existing)

    manager.hosts = {
        "container1": [
            {
                "ip": "172.17.0.3",
                "name": "new",
                "domains": {"new"}
            }
        ]
    }

    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    content = tmp_hosts_file.read_text()

    assert "old.localhost" not in content
    assert "new.localhost" in content
    assert "172.17.0.3" in content


@pytest.mark.unit
def test_update_hosts_file_empty_hosts(manager, tmp_hosts_file):
    """Empty hosts dict creates section with only markers."""
    tmp_hosts_file.write_text("127.0.0.1    localhost\n")

    manager.hosts = {}

    manager.update_hosts_file(str(tmp_hosts_file), dry_run=False, tld="localhost")

    content = tmp_hosts_file.read_text()

    assert "127.0.0.1    localhost" in content
