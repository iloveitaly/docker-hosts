# Automatic Docker Hosts Management

Automatically manage Docker container hostnames in your `/etc/hosts` file. If you're running local services in Docker and want to access them via friendly names like `postgres.localhost` or `redis.localhost` instead of remembering IP addresses, this tool handles that for you.

I built this because manually editing `/etc/hosts` every time containers restart gets old fast. The tool monitors your Docker daemon, picks up container IPs and network aliases, and keeps your hosts file in sync. It's event-driven, so when you start, stop, or rename a container, your hosts file updates automatically.

## Installation

Using uv:

```bash
uv tool install docker-hosts
```

Using pip:

```bash
pip install docker-hosts
```

## Usage

Run once to update `/etc/hosts` with all running containers:

```bash
sudo docker-hosts
```

Run continuously, monitoring for container events:

```bash
sudo docker-hosts --listen
```

Preview what would be written without making changes:

```bash
docker-hosts --dry-run
```

Use a custom TLD (defaults to `.localhost`):

```bash
sudo docker-hosts --tld dev
```

Specify a custom hosts file path:

```bash
docker-hosts /tmp/hosts --dry-run
```

The tool requires sudo when writing to `/etc/hosts`, but you can test with `--dry-run` first to see what it would do.

## Features

- Event-driven updates with `--listen` - watches Docker events and updates your hosts file when containers start, stop, or get renamed. No polling, no delays.
- Network-aware - picks up all network aliases from Docker networks, not just the default bridge network. If your container is attached to multiple networks, all IPs and aliases get added.
- Safe writes - uses atomic file writes (write to temp, then rename) to avoid corrupting your hosts file. Your existing entries are preserved - the tool only manages the section between `### Start Docker Domains ###` and `### End Docker Domains ###` markers.
- Structured logging - built with structlog for clean, parseable logs. Set `LOG_LEVEL=DEBUG` to see what's happening under the hood.
- Dry-run mode - test what would be written before committing to changes. Great for understanding what the tool does or debugging issues.

# [MIT License](LICENSE.md)
