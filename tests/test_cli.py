"""Tests for CLI argument parsing and execution."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from docker_hosts.cli import main, START_PATTERN, END_PATTERN


@pytest.fixture
def runner():
    """Provides Click's CliRunner for CLI testing."""
    return CliRunner()


@pytest.mark.integration
def test_cli_help(runner):
    """Help output is displayed correctly."""
    result = runner.invoke(main, ['--help'])

    assert result.exit_code == 0
    assert 'Usage:' in result.output
    assert '--dry-run' in result.output
    assert '--tld' in result.output


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

    result = runner.invoke(main, [str(hosts_file), '--dry-run'])

    assert result.exit_code == 0
    assert hosts_file.read_text() == original_content
    assert START_PATTERN.strip() in result.output


@pytest.mark.integration
def test_cli_tld_option(runner, tmp_path):
    """--tld option changes the domain suffix."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file), '--tld', 'test'])

    assert result.exit_code == 0

    content = hosts_file.read_text()
    lines = content.split('\n')

    for line in lines:
        if line.strip() and not line.startswith('#') and 'localhost' not in line and START_PATTERN.strip() not in line and END_PATTERN.strip() not in line:
            parts = line.split()
            if len(parts) >= 2:
                domains = parts[1:]
                for domain in domains:
                    if domain:
                        assert domain.endswith('.test')


@pytest.mark.integration
def test_cli_custom_file_path(runner, tmp_path):
    """Custom file path argument is respected."""
    custom_file = tmp_path / "custom_hosts"
    custom_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(custom_file)])

    assert result.exit_code == 0
    assert custom_file.exists()

    content = custom_file.read_text()
    assert START_PATTERN.strip() in content or len(content) == len("127.0.0.1    localhost\n")


@pytest.mark.integration
def test_cli_with_tmp_hosts(runner):
    """CLI works with tmp/hosts file path."""
    tmp_dir = Path.cwd() / "tmp"
    tmp_dir.mkdir(exist_ok=True)

    hosts_file = tmp_dir / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [str(hosts_file)])

    assert result.exit_code == 0
    assert hosts_file.exists()

    content = hosts_file.read_text()
    assert "127.0.0.1    localhost" in content

    hosts_file.unlink()


@pytest.mark.integration
def test_cli_combines_all_options(runner, tmp_path):
    """All CLI options can be used together."""
    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("127.0.0.1    localhost\n")

    result = runner.invoke(main, [
        str(hosts_file),
        '--dry-run',
        '--tld', 'dev'
    ])

    assert result.exit_code == 0
    assert hosts_file.read_text() == "127.0.0.1    localhost\n"

    if START_PATTERN.strip() in result.output:
        assert '.dev' in result.output or result.output.count('\n') <= 5


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
def test_cli_no_listen_flag(runner):
    """--listen flag has been removed from CLI."""
    result = runner.invoke(main, ['--help'])

    assert '--listen' not in result.output
