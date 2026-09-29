"""
CLI tool to automatically manage Docker container hostnames in /etc/hosts file.

Monitors running containers and their networks, updating /etc/hosts with container
IPs, hostnames, and network aliases.
"""

import json
import os
import re
import stat
from pathlib import Path

import click
import docker
from structlog_config import LoggerWithContext, configure_logger

from docker_hosts.version import __version__

START_PATTERN = "### Start Docker Domains ###\n"
END_PATTERN = "### End Docker Domains ###\n"


def compile_patterns(
    patterns: tuple[str, ...], option_name: str
) -> tuple[re.Pattern[str], ...]:
    try:
        return tuple(re.compile(pattern) for pattern in patterns)
    except re.error as error:
        raise click.BadParameter(str(error), param_hint=option_name) from error


def container_name_is_included(
    container_name: str,
    include_patterns: tuple[re.Pattern[str], ...],
    exclude_patterns: tuple[re.Pattern[str], ...],
) -> bool:
    if include_patterns and not any(
        pattern.search(container_name) for pattern in include_patterns
    ):
        return False

    return not any(pattern.search(container_name) for pattern in exclude_patterns)


def hosts_file_permission_error(hosts_path: Path) -> click.ClickException:
    message = (
        f"Permission denied: cannot update {hosts_path}. "
        "Re-run with sudo or use --dry-run."
    )
    return click.ClickException(click.style(message, fg="red"))


def ensure_hosts_file_is_writable(hosts_path: Path) -> None:
    if not hosts_path.parent.exists():
        return

    if not os.access(hosts_path.parent, os.W_OK | os.X_OK):
        raise hosts_file_permission_error(hosts_path)

    if hosts_path.exists() and not os.access(hosts_path, os.R_OK):
        raise hosts_file_permission_error(hosts_path)


class DockerHostsManager:
    def __init__(self, client: docker.DockerClient | None, log: LoggerWithContext):
        self.client = client
        self.log = log
        self.hosts: dict[str, list[dict[str, str | set[str]]]] = {}

    def build_container_hostname(self, hostname: str, domainname: str | None) -> str:
        if not domainname:
            return hostname

        return f"{hostname}.{domainname}"

    def extract_network_entries(
        self, networks: dict
    ) -> list[dict[str, str | list[str]]]:
        result: list[dict[str, str | list[str]]] = []

        for values in networks.values():
            if not values["Aliases"]:
                continue

            ip_address = values["IPAddress"]
            aliases = values["Aliases"]

            result.append(
                {
                    "ip": ip_address,
                    "aliases": aliases,
                }
            )

        return result

    def extract_default_entry(
        self, container_ip: str | None
    ) -> dict[str, str | list[str]] | None:
        if not container_ip:
            return None

        return {"ip": container_ip, "aliases": []}

    def get_container_data(self, info: dict) -> list[dict[str, str | set[str]]]:
        config = info["Config"]
        network_settings = info["NetworkSettings"]

        container_hostname = self.build_container_hostname(
            config["Hostname"], config["Domainname"]
        )
        container_name = info["Name"].strip("/")
        # in some versions of docker, IPAddress might be missing
        container_ip = network_settings.get("IPAddress")

        common_domains = [container_name, container_hostname]
        result: list[dict[str, str | set[str]]] = []

        network_entries = self.extract_network_entries(network_settings["Networks"])
        for entry in network_entries:
            entry_ip = entry["ip"]
            assert isinstance(entry_ip, str)

            entry_aliases = entry["aliases"]
            assert isinstance(entry_aliases, list)

            result.append(
                {
                    "ip": entry_ip,
                    "name": container_name,
                    "domains": set(entry_aliases + common_domains),
                }
            )

        default_entry = self.extract_default_entry(container_ip)
        if default_entry:
            default_ip = default_entry["ip"]
            assert isinstance(default_ip, str)

            result.append(
                {
                    "ip": default_ip,
                    "name": container_name,
                    "domains": set(common_domains),
                }
            )

        return result

    def split_existing_hosts(self, hosts_path: Path) -> tuple[list[str], list[str]]:
        lines = hosts_path.read_text().splitlines(keepends=True)

        try:
            start = lines.index(START_PATTERN)
        except ValueError:
            return lines, []

        try:
            end = lines.index(END_PATTERN, start + 1)
        except ValueError:
            return lines[:start], []

        return lines[:start], lines[end + 1 :]

    def read_existing_hosts(self, hosts_path: Path) -> list[str]:
        head, _ = self.split_existing_hosts(hosts_path)

        return head

    def remove_trailing_blank_lines(self, lines: list[str]) -> list[str]:
        while lines and not lines[-1].strip():
            lines.pop()

        return lines

    def remove_leading_blank_lines(self, lines: list[str]) -> list[str]:
        while lines and not lines[0].strip():
            lines.pop(0)

        return lines

    def generate_host_entries(self, tld: str) -> list[str]:
        if not self.hosts:
            return []

        entries = [f"\n\n{START_PATTERN}"]

        for addresses in self.hosts.values():
            for addr in addresses:
                domains = addr["domains"]
                assert isinstance(domains, set)

                if not domains:
                    continue

                ip = addr["ip"]
                assert isinstance(ip, str)

                suffixed_domains = [f"{d}.{tld}" for d in domains]
                sorted_domains = sorted(suffixed_domains)
                entries.append(f"{ip}    {'   '.join(sorted_domains)}\n")

        if len(entries) == 1:
            return []

        entries.append(f"{END_PATTERN}\n")

        return entries

    def write_hosts_file(self, hosts_path: Path, content: str) -> None:
        aux_path = hosts_path.with_suffix(".aux")

        try:
            aux_path.write_text(content)

            if hosts_path.exists():
                existing = hosts_path.stat()
                os.chmod(aux_path, stat.S_IMODE(existing.st_mode))

                try:
                    os.chown(aux_path, existing.st_uid, existing.st_gid)
                except PermissionError:
                    pass

            aux_path.replace(hosts_path)
        except BaseException:
            try:
                aux_path.unlink(missing_ok=True)
            except OSError:
                pass

            raise

        self.log.info("wrote hosts file", path=str(hosts_path))

    def update_hosts_file(
        self,
        hosts_path: Path | str,
        dry_run: bool,
        tld: str,
        print_dry_run: bool = True,
    ) -> None:
        if not self.hosts:
            self.log.info("removing all hosts before exit")
        else:
            self.log.info("updating hosts file")

            for addresses in self.hosts.values():
                for address in addresses:
                    domains_value = address["domains"]
                    assert isinstance(domains_value, set)

                    if not domains_value:
                        continue

                    domains = sorted(f"{domain}.{tld}" for domain in domains_value)
                    self.log.debug(
                        "adding host entry",
                        ip=address["ip"],
                        domains=domains,
                    )

        path = Path(hosts_path)

        if path.exists():
            head, tail = self.split_existing_hosts(path)
        else:
            head, tail = [], []

        head = self.remove_trailing_blank_lines(head)
        tail = self.remove_leading_blank_lines(tail)

        host_entries = self.generate_host_entries(tld)

        if dry_run:
            if print_dry_run:
                click.echo("".join(host_entries), nl=False)

            return

        lines = head
        lines.extend(host_entries)

        if tail:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"

            lines.extend(tail)

        proposed_content = "".join(lines)
        self.log.info("proposed hosts content", content=proposed_content)

        self.write_hosts_file(path, proposed_content)

    def generate_json_output(self, tld: str) -> str:
        result: dict[str, dict[str, list[str]]] = {}

        for container_name in sorted(self.hosts):
            addresses = self.hosts[container_name]
            ips: set[str] = set()
            aliases: set[str] = set()

            for address in addresses:
                ip = address["ip"]
                assert isinstance(ip, str)
                ips.add(ip)

                domains = address["domains"]
                assert isinstance(domains, set)

                for domain in domains:
                    aliases.add(f"{domain}.{tld}")

            result[container_name] = {
                "addresses": sorted(ips),
                "aliases": sorted(aliases),
            }

        return json.dumps(result, indent=2, sort_keys=True)

    def find_colliding_domains(
        self,
    ) -> tuple[set[str], dict[str, set[str]]]:
        domain_containers: dict[str, set[str]] = {}

        for container_id, addresses in self.hosts.items():
            container_domains: set[str] = set()

            for address in addresses:
                domains = address["domains"]
                assert isinstance(domains, set)

                container_domains.update(domains)

            for domain in container_domains:
                domain_containers.setdefault(domain, set()).add(container_id)

        colliding_domains = {
            domain
            for domain, container_ids in domain_containers.items()
            if len(container_ids) > 1
        }

        return colliding_domains, domain_containers

    def warn_for_collisions(
        self,
        colliding_domains: set[str],
        domain_containers: dict[str, set[str]],
        hosts_source: dict[str, list[dict[str, str | set[str]]]] | None = None,
    ) -> None:
        source = hosts_source if hosts_source is not None else self.hosts

        for domain in sorted(colliding_domains):
            names: set[str] = set()

            for container_id in domain_containers[domain]:
                for address in source.get(container_id, []):
                    name = address["name"]
                    assert isinstance(name, str)

                    names.add(name)

            self.log.warning(
                "omitting colliding hostname",
                hostname=domain,
                containers=sorted(names),
            )

    def remove_colliding_domains(self) -> set[str]:
        colliding_domains, domain_containers = self.find_colliding_domains()

        self.warn_for_collisions(colliding_domains, domain_containers)

        for addresses in self.hosts.values():
            for address in addresses:
                domains = address["domains"]
                assert isinstance(domains, set)

                domains.difference_update(colliding_domains)

        return colliding_domains

    def prepare_hosts_for_output(
        self,
        include_patterns: tuple[re.Pattern[str], ...],
        exclude_patterns: tuple[re.Pattern[str], ...],
    ) -> None:
        colliding_domains, domain_containers = self.find_colliding_domains()
        snapshot = self.hosts

        included_keys = {
            container_name
            for container_name in snapshot
            if container_name_is_included(
                container_name, include_patterns, exclude_patterns
            )
        }

        relevant_collisions = {
            domain
            for domain in colliding_domains
            if domain_containers[domain] & included_keys
        }

        self.hosts = {
            container_name: addresses
            for container_name, addresses in snapshot.items()
            if container_name in included_keys
        }

        for addresses in self.hosts.values():
            for address in addresses:
                domains = address["domains"]
                assert isinstance(domains, set)

                domains.difference_update(colliding_domains)

        self.warn_for_collisions(
            relevant_collisions, domain_containers, hosts_source=snapshot
        )

    def load_running_containers(
        self,
        include_patterns: tuple[re.Pattern[str], ...] = (),
        exclude_patterns: tuple[re.Pattern[str], ...] = (),
    ) -> None:
        assert self.client is not None

        for container in self.client.containers.list():
            info = container.attrs
            container_name = info["Name"].strip("/")
            self.hosts[container_name] = self.get_container_data(info)

        self.prepare_hosts_for_output(include_patterns, exclude_patterns)


@click.command()
@click.argument("file", default="/etc/hosts")
@click.option(
    "--dry-run", is_flag=True, help="Simulate updates without writing to file"
)
@click.option(
    "--tld", default="localhost", show_default=True, help="TLD to append to domains"
)
@click.option(
    "--include",
    multiple=True,
    metavar="REGEX",
    help="Include containers whose names match this regex; repeatable",
)
@click.option(
    "--exclude",
    multiple=True,
    metavar="REGEX",
    help="Exclude containers whose names match this regex; repeatable",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Output the updated container aliases as JSON",
)
@click.version_option(
    __version__,
    "--version",
    "-V",
    prog_name="docker-hosts",
    message="%(prog)s version %(version)s",
)
def main(
    file: str,
    dry_run: bool,
    tld: str,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
    json_output: bool,
) -> None:
    include_patterns = compile_patterns(include, "--include")
    exclude_patterns = compile_patterns(exclude, "--exclude")

    hosts_path = Path(file)
    if not dry_run:
        ensure_hosts_file_is_writable(hosts_path)

    os.environ.setdefault("PYTHON_LOG_PATH", "stderr")
    log = configure_logger()
    client = docker.from_env()
    manager = DockerHostsManager(client, log)
    manager.load_running_containers(include_patterns, exclude_patterns)
    try:
        manager.update_hosts_file(
            hosts_path,
            dry_run,
            tld,
            print_dry_run=not json_output,
        )
    except PermissionError as error:
        raise hosts_file_permission_error(hosts_path) from error

    if json_output:
        click.echo(manager.generate_json_output(tld))
