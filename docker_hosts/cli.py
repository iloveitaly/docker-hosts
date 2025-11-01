"""
CLI tool to automatically manage Docker container hostnames in /etc/hosts file.

Monitors running containers and their networks, updating /etc/hosts with container
IPs, hostnames, and network aliases.
"""

from pathlib import Path

import click
import docker
from structlog_config import configure_logger

START_PATTERN = "### Start Docker Domains ###\n"
END_PATTERN = "### End Docker Domains ###\n"


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

    def extract_default_entry(self, container_ip: str) -> dict | None:
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
        container_ip = network_settings["IPAddress"]

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
                    "domains": common_domains,
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

    def update_hosts_file(self, hosts_path: str, dry_run: bool, tld: str):
        if not self.hosts:
            self.log.info("removing all hosts before exit")
        else:
            self.log.info("updating hosts file")
            for addresses in self.hosts.values():
                for addr in addresses:
                    self.log.info("host entry", ip=addr["ip"], domains=addr["domains"])

        path = Path(hosts_path)
        lines = self.read_existing_hosts(path)
        lines = self.remove_trailing_blank_lines(lines)

        host_entries = self.generate_host_entries(tld)

        if dry_run:
            print("".join(host_entries))
            return

        lines.extend(host_entries)
        proposed_content = "".join(lines)
        self.log.info("proposed hosts content", content=proposed_content)

        self.write_hosts_file(path, proposed_content)

    def load_running_containers(self):
        for container in self.client.containers.list():
            self.hosts[container.id] = self.get_container_data(container.attrs)


@click.command()
@click.argument("file", default="/etc/hosts")
@click.option(
    "--dry-run", is_flag=True, help="Simulate updates without writing to file"
)
@click.option(
    "--tld", default="localhost", show_default=True, help="TLD to append to domains"
)
def main(file, dry_run, tld):
    log = configure_logger()
    client = docker.from_env()
    manager = DockerHostsManager(client, log)
    manager.load_running_containers()
    manager.update_hosts_file(file, dry_run, tld)
