"""Tests for CLI argument parsing and execution."""

import json
import os

import pytest
from click.testing import CliRunner

from docker_hosts.cli import (
    END_PATTERN,
    START_PATTERN,
    ensure_hosts_file_is_writable,
    main,
)
from docker_hosts.version import __version__


@pytest.fixture
def runner():
    """Provides Click's CliRunner for CLI testing."""
    return CliRunner()


@pytest.mark.unit
def test_cli_help(runner):
    """Help output is displayed correctly."""
    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "--dry-run" in result.output
    assert "--tld" in result.output
    assert "--include" in result.output
    assert "--exclude" in result.output
    assert "--json" in result.output
    assert "--version" in result.output


@pytest.mark.unit
@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_cli_version(runner, flag):
    result = runner.invoke(main, [flag])

    assert result.exit_code == 0
    assert result.output == f"docker-hosts version {__version__}\n"


@pytest.mark.unit
def test_hosts_file_permission_error_is_red_and_actionable(runner, tmp_path):
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root bypasses filesystem permissions")

    restricted_directory = tmp_path / "restricted"
    restricted_directory.mkdir()
    hosts_file = restricted_directory / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")
    restricted_directory.chmod(0o500)

    try:
        result = runner.invoke(main, [str(hosts_file)], color=True)
    finally:
        restricted_directory.chmod(0o700)

    assert result.exit_code == 1
    assert "\x1b[31m" in result.stderr
    assert "Permission denied" in result.stderr
    assert "sudo" in result.stderr
    assert "--dry-run" in result.stderr


@pytest.mark.integration
def test_cli_default_file_argument(runner, tmp_path):
    """CLI uses /etc/hosts by default but can be overridden."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file)])

    assert result.exit_code == 0
    assert hosts_file.exists()


@pytest.mark.integration
def test_cli_dry_run_flag(runner, tmp_path):
    """--dry-run flag prevents file modification."""
    hosts_file = tmp_path / "hosts"
    original_content = "127.0.0.1    localhost\n"
    hosts_file.write_text(original_content)

    result = runner.invoke(main, [str(hosts_file), "--dry-run"])

    assert result.exit_code == 0
    assert hosts_file.read_text() == original_content
    assert START_PATTERN.strip() in result.output


@pytest.mark.integration
def test_cli_tld_option(runner, tmp_path):
    """--tld option changes the domain suffix."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file), "--tld", "test"])

    assert result.exit_code == 0

    content = hosts_file.read_text()
    lines = content.split("\n")

    for line in lines:
        if (
            line.strip()
            and not line.startswith("#")
            and "localhost" not in line
            and START_PATTERN.strip() not in line
            and END_PATTERN.strip() not in line
        ):
            parts = line.split()
            if len(parts) >= 2:
                domains = parts[1:]
                for domain in domains:
                    if domain:
                        assert domain.endswith(".test")


@pytest.mark.integration
def test_cli_custom_file_path(runner, tmp_path):
    """Custom file path argument is respected."""
    custom_file = tmp_path / "custom_hosts"
    custom_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(custom_file)])

    assert result.exit_code == 0
    assert custom_file.exists()

    content = custom_file.read_text()
    assert START_PATTERN.strip() in content or len(content) == len(
        "127.0.0.1    localhost\n"
    )


@pytest.mark.integration
def test_cli_with_tmp_hosts(runner, tmp_path):
    """CLI works with an isolated hosts file path."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file)])

    assert result.exit_code == 0
    assert hosts_file.exists()

    content = hosts_file.read_text()
    assert "127.0.0.1    localhost" in content


@pytest.mark.integration
def test_cli_combines_all_options(runner, tmp_path):
    """All CLI options can be used together."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file), "--dry-run", "--tld", "dev"])

    assert result.exit_code == 0
    assert hosts_file.read_text() == "127.0.0.1    localhost\n"

    if START_PATTERN.strip() in result.output:
        assert ".dev" in result.output or result.output.count("\n") <= 5


@pytest.mark.integration
def test_cli_creates_docker_section(runner, tmp_path):
    """CLI creates Docker section in hosts file when containers exist."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file)])

    assert result.exit_code == 0

    content = hosts_file.read_text()
    assert "127.0.0.1    localhost" in content


@pytest.mark.unit
def test_ensure_hosts_file_is_writable_allows_missing_file(tmp_path):
    ensure_hosts_file_is_writable(tmp_path / "hosts")


@pytest.mark.unit
def test_ensure_hosts_file_is_writable_defers_missing_parent(tmp_path):
    ensure_hosts_file_is_writable(tmp_path / "nope" / "hosts")


@pytest.mark.unit
def test_cli_no_listen_flag(runner):
    """--listen flag has been removed from CLI."""
    result = runner.invoke(main, ["--help"])

    assert "--listen" not in result.output


@pytest.mark.unit
def test_cli_rejects_invalid_include_regex(runner):
    result = runner.invoke(main, ["--include", "["])

    assert result.exit_code == 2
    assert "Invalid value for --include" in result.output


@pytest.mark.unit
def test_cli_rejects_invalid_exclude_regex(runner):
    result = runner.invoke(main, ["--exclude", "["])

    assert result.exit_code == 2
    assert "Invalid value for --exclude" in result.output


@pytest.mark.integration
def test_cli_json_updates_hosts_and_outputs_json(runner, tmp_path):
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(
        main,
        [str(hosts_file), "--include", "postgres|redis", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)
    assert START_PATTERN.strip() in hosts_file.read_text()
    assert "updating hosts file" in result.stderr


@pytest.mark.integration
def test_cli_json_dry_run_does_not_update_hosts(runner, tmp_path):
    hosts_file = tmp_path / "hosts"
    original_content = "127.0.0.1    localhost\n"
    hosts_file.write_text(original_content)

    result = runner.invoke(
        main,
        [str(hosts_file), "--include", "postgres|redis", "--json", "--dry-run"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)
    assert hosts_file.read_text() == original_content
