"""
CLI tool to automatically manage Docker container hostnames in /etc/hosts file.

Monitors running containers and their networks, updating /etc/hosts with container
IPs, hostnames, and network aliases. Supports continuous monitoring via --listen flag.
"""

from pathlib import Path

import click
import docker
from structlog_config import configure_logger

START_PATTERN = "### Start Docker Domains ###\n"
END_PATTERN = "### End Docker Domains ###\n"

hosts: dict[str, list[dict]] = {}


def build_container_hostname(hostname: str, domainname: str) -> str:
    if not domainname:
        return hostname

    return f"{hostname}.{domainname}"


def extract_network_entries(networks: dict) -> list[dict]:
    result = []

    for values in networks.values():
        if not values["Aliases"]:
            continue

        ip_address = values["IPAddress"]
        aliases = values["Aliases"]

        result.append({
            "ip": ip_address,
            "aliases": aliases,
        })

    return result


def extract_default_entry(container_ip: str) -> dict | None:
    if not container_ip:
        return None

    return {"ip": container_ip, "aliases": []}


def get_container_data(info: dict) -> list[dict]:
    config = info["Config"]
    network_settings = info["NetworkSettings"]

    container_hostname = build_container_hostname(
        config["Hostname"],
        config["Domainname"]
    )
    container_name = info["Name"].strip("/")
    container_ip = network_settings["IPAddress"]

    common_domains = [container_name, container_hostname]
    result = []

    network_entries = extract_network_entries(network_settings["Networks"])
    for entry in network_entries:
        result.append({
            "ip": entry["ip"],
            "name": container_name,
            "domains": set(entry["aliases"] + common_domains),
        })

    default_entry = extract_default_entry(container_ip)
    if default_entry:
        result.append({
            "ip": default_entry["ip"],
            "name": container_name,
            "domains": common_domains,
        })

    return result


def read_existing_hosts(hosts_path: Path) -> list[str]:
    lines = hosts_path.read_text().splitlines(keepends=True)

    for i, line in enumerate(lines):
        if line == START_PATTERN:
            return lines[:i]

    return lines


def remove_trailing_blank_lines(lines: list[str]) -> list[str]:
    while lines and not lines[-1].strip():
        lines.pop()

    return lines


def generate_host_entries(tld: str) -> list[str]:
    if not hosts:
        return []

    entries = [f"\n\n{START_PATTERN}"]

    for addresses in hosts.values():
        for addr in addresses:
            suffixed_domains = [f"{d}.{tld}" for d in addr["domains"]]
            sorted_domains = sorted(suffixed_domains)
            entries.append(f"{addr['ip']}    {'   '.join(sorted_domains)}\n")

    entries.append(f"{END_PATTERN}\n")

    return entries


def write_hosts_file(hosts_path: Path, content: str, log):
    aux_path = hosts_path.with_suffix('.aux')
    aux_path.write_text(content)
    aux_path.replace(hosts_path)

    log.info("wrote hosts file", path=str(hosts_path))


def update_hosts_file(hosts_path: str, log, dry_run: bool, tld: str):
    if not hosts:
        log.info("removing all hosts before exit")
    else:
        log.info("updating hosts file")
        for addresses in hosts.values():
            for addr in addresses:
                log.info("host entry", ip=addr["ip"], domains=addr["domains"])

    path = Path(hosts_path)
    lines = read_existing_hosts(path)
    lines = remove_trailing_blank_lines(lines)

    host_entries = generate_host_entries(tld)

    if dry_run:
        print(''.join(host_entries))
        return

    lines.extend(host_entries)
    proposed_content = ''.join(lines)
    log.info("proposed hosts content", content=proposed_content)

    write_hosts_file(path, proposed_content, log)


def load_running_containers(client):
    for container in client.containers.list():
        hosts[container.id] = get_container_data(container.attrs)


def handle_container_start(client, container_id: str, file: str, log, dry_run: bool, tld: str):
    info = client.api.inspect_container(container_id)
    hosts[container_id] = get_container_data(info)
    update_hosts_file(file, log, dry_run, tld)


def handle_container_stop(container_id: str, file: str, log, dry_run: bool, tld: str):
    hosts.pop(container_id, None)
    update_hosts_file(file, log, dry_run, tld)


def handle_container_rename(client, container_id: str, file: str, log, dry_run: bool, tld: str):
    info = client.api.inspect_container(container_id)
    hosts[container_id] = get_container_data(info)
    update_hosts_file(file, log, dry_run, tld)


def process_events(client, file: str, log, dry_run: bool, tld: str):
    for event in client.events(decode=True):
        if event.get("Type") != "container":
            continue

        status = event.get("status")
        container_id = event.get("id")

        if status == "start":
            handle_container_start(client, container_id, file, log, dry_run, tld)
            continue

        if status in ("stop", "die", "destroy", "kill"):
            handle_container_stop(container_id, file, log, dry_run, tld)
            continue

        if status == "rename":
            handle_container_rename(client, container_id, file, log, dry_run, tld)


@click.command()
@click.argument('file', default='/etc/hosts')
@click.option('--dry-run', is_flag=True, help='Simulate updates without writing to file')
@click.option('--tld', default='localhost', show_default=True, help='TLD to append to domains')
@click.option('--listen', is_flag=True, help='Listen for container events and update continuously')
def main(file, dry_run, tld, listen):
    log = configure_logger()
    client = docker.from_env()
    load_running_containers(client)
    update_hosts_file(file, log, dry_run, tld)

    if not listen:
        return

    process_events(client, file, log, dry_run, tld)
