"""
CLI tool to automatically manage Docker container hostnames in /etc/hosts file.

Monitors running containers and their networks, updating /etc/hosts with container
IPs, hostnames, and network aliases.
"""

import json
import os
import re
from pathlib import Path

import click
import docker
from structlog_config import configure_logger

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


class DockerHostsManager:
    def __init__(self, client, log):
        self.client = client
        self.log = log
        self.hosts: dict[str, list[dict]] = {}

    def build_container_hostname(self, hostname: str, domainname: str) -> str:
        if not domainname:
            return hostname

        return f"{hostname}.{domainname}"

    def extract_network_entries(self, networks: dict) -> list[dict]:
        result = []

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

    def extract_default_entry(self, container_ip: str | None) -> dict | None:
        if not container_ip:
            return None

        return {"ip": container_ip, "aliases": []}

    def get_container_data(self, info: dict) -> list[dict]:
        config = info["Config"]
        network_settings = info["NetworkSettings"]

        container_hostname = self.build_container_hostname(
            config["Hostname"], config["Domainname"]
        )
        container_name = info["Name"].strip("/")
        # in some versions of docker, IPAddress might be missing
        container_ip = network_settings.get("IPAddress")

        common_domains = [container_name, container_hostname]
        result = []

        network_entries = self.extract_network_entries(network_settings["Networks"])
        for entry in network_entries:
            result.append(
                {
                    "ip": entry["ip"],
                    "name": container_name,
                    "domains": set(entry["aliases"] + common_domains),
                }
            )

        default_entry = self.extract_default_entry(container_ip)
        if default_entry:
            result.append(
                {
                    "ip": default_entry["ip"],
                    "name": container_name,
                    "domains": set(common_domains),
                }
            )

        return result

    def read_existing_hosts(self, hosts_path: Path) -> list[str]:
        lines = hosts_path.read_text().splitlines(keepends=True)

        for i, line in enumerate(lines):
            if line == START_PATTERN:
                return lines[:i]

        return lines

    def remove_trailing_blank_lines(self, lines: list[str]) -> list[str]:
        while lines and not lines[-1].strip():
            lines.pop()

        return lines

    def generate_host_entries(self, tld: str) -> list[str]:
        if not self.hosts:
            return []

        entries = [f"\n\n{START_PATTERN}"]

        for addresses in self.hosts.values():
            for addr in addresses:
                suffixed_domains = [f"{d}.{tld}" for d in addr["domains"]]
                sorted_domains = sorted(suffixed_domains)
                entries.append(f"{addr['ip']}    {'   '.join(sorted_domains)}\n")

        entries.append(f"{END_PATTERN}\n")

        return entries

    def write_hosts_file(self, hosts_path: Path, content: str):
        aux_path = hosts_path.with_suffix(".aux")
        aux_path.write_text(content)
        aux_path.replace(hosts_path)

        self.log.info("wrote hosts file", path=str(hosts_path))

    def update_hosts_file(
        self,
        hosts_path: str,
        dry_run: bool,
        tld: str,
        print_dry_run: bool = True,
    ):
        if not self.hosts:
            self.log.info("removing all hosts before exit")
        else:
            self.log.info("updating hosts file")
            for addresses in self.hosts.values():
                for address in addresses:
                    domains = sorted(f"{domain}.{tld}" for domain in address["domains"])
                    self.log.debug(
                        "adding host entry",
                        ip=address["ip"],
                        domains=domains,
                    )

        path = Path(hosts_path)
        lines = self.read_existing_hosts(path)
        lines = self.remove_trailing_blank_lines(lines)

        host_entries = self.generate_host_entries(tld)

        if dry_run:
            if print_dry_run:
                print("".join(host_entries))

            return

        lines.extend(host_entries)
        proposed_content = "".join(lines)
        self.log.info("proposed hosts content", content=proposed_content)

        self.write_hosts_file(path, proposed_content)

    def generate_json_output(self, tld: str) -> str:
        result = {}

        for container_name in sorted(self.hosts):
            addresses = self.hosts[container_name]
            result[container_name] = {
                "addresses": sorted({address["ip"] for address in addresses}),
                "aliases": sorted(
                    {
                        f"{domain}.{tld}"
                        for address in addresses
                        for domain in address["domains"]
                    }
                ),
            }

        return json.dumps(result, indent=2, sort_keys=True)

    def remove_colliding_domains(self) -> set[str]:
        domain_containers: dict[str, set[str]] = {}

        for container_id, addresses in self.hosts.items():
            container_domains = {
                domain for address in addresses for domain in address["domains"]
            }

            for domain in container_domains:
                domain_containers.setdefault(domain, set()).add(container_id)

        colliding_domains = {
            domain
            for domain, container_ids in domain_containers.items()
            if len(container_ids) > 1
        }

        for domain in sorted(colliding_domains):
            container_names = sorted(
                {
                    address["name"]
                    for container_id in domain_containers[domain]
                    for address in self.hosts[container_id]
                }
            )
            self.log.warning(
                "omitting colliding hostname",
                hostname=domain,
                containers=container_names,
            )

        for addresses in self.hosts.values():
            for address in addresses:
                address["domains"].difference_update(colliding_domains)

        return colliding_domains

    def load_running_containers(
        self,
        include_patterns: tuple[re.Pattern[str], ...] = (),
        exclude_patterns: tuple[re.Pattern[str], ...] = (),
    ):
        for container in self.client.containers.list():
            info = container.attrs
            container_name = info["Name"].strip("/")

            if not container_name_is_included(
                container_name, include_patterns, exclude_patterns
            ):
                continue

            self.hosts[container_name] = self.get_container_data(info)

        self.remove_colliding_domains()


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
def main(file, dry_run, tld, include, exclude, json_output):
    include_patterns = compile_patterns(include, "--include")
    exclude_patterns = compile_patterns(exclude, "--exclude")

    os.environ.setdefault("PYTHON_LOG_PATH", "stderr")
    log = configure_logger()
    client = docker.from_env()
    manager = DockerHostsManager(client, log)
    manager.load_running_containers(include_patterns, exclude_patterns)
    manager.update_hosts_file(
        file,
        dry_run,
        tld,
        print_dry_run=not json_output,
    )

    if json_output:
        click.echo(manager.generate_json_output(tld))
