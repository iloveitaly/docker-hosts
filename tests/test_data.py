"""Unit tests for data extraction functions."""

import pytest


@pytest.mark.unit
def test_build_container_hostname_with_domainname(manager):
    """Hostname and domainname are combined with dot separator."""
    result = manager.build_container_hostname("myhost", "example.com")

    assert result == "myhost.example.com"


@pytest.mark.unit
def test_build_container_hostname_without_domainname(manager):
    """Empty domainname returns just hostname."""
    result = manager.build_container_hostname("myhost", "")

    assert result == "myhost"


@pytest.mark.unit
def test_build_container_hostname_none_domainname(manager):
    """None domainname returns just hostname."""
    result = manager.build_container_hostname("myhost", None)

    assert result == "myhost"


@pytest.mark.unit
def test_extract_network_entries_single_network(manager):
    """Single network with aliases is extracted correctly."""
    networks = {"bridge": {"IPAddress": "172.17.0.2", "Aliases": ["web", "app"]}}

    result = manager.extract_network_entries(networks)

    assert len(result) == 1
    assert result[0]["ip"] == "172.17.0.2"
    assert result[0]["aliases"] == ["web", "app"]


@pytest.mark.unit
def test_extract_network_entries_multiple_networks(manager):
    """Multiple networks are all extracted."""
    networks = {
        "bridge": {"IPAddress": "172.17.0.2", "Aliases": ["web"]},
        "custom": {"IPAddress": "172.18.0.3", "Aliases": ["api"]},
    }

    result = manager.extract_network_entries(networks)

    assert len(result) == 2
    ips = [entry["ip"] for entry in result]
    assert "172.17.0.2" in ips
    assert "172.18.0.3" in ips


@pytest.mark.unit
def test_extract_network_entries_no_aliases(manager):
    """Networks without aliases are skipped."""
    networks = {"bridge": {"IPAddress": "172.17.0.2", "Aliases": None}}

    result = manager.extract_network_entries(networks)

    assert result == []


@pytest.mark.unit
def test_extract_network_entries_empty_aliases(manager):
    """Networks with empty alias list are skipped."""
    networks = {"bridge": {"IPAddress": "172.17.0.2", "Aliases": []}}

    result = manager.extract_network_entries(networks)

    assert result == []


@pytest.mark.unit
def test_extract_network_entries_mixed_aliases(manager):
    """Only networks with aliases are included."""
    networks = {
        "bridge": {"IPAddress": "172.17.0.2", "Aliases": ["web"]},
        "host": {"IPAddress": "172.17.0.3", "Aliases": None},
    }

    result = manager.extract_network_entries(networks)

    assert len(result) == 1
    assert result[0]["ip"] == "172.17.0.2"


@pytest.mark.unit
def test_extract_default_entry_with_ip(manager):
    """Valid IP creates default entry."""
    result = manager.extract_default_entry("172.17.0.2")

    assert result == {"ip": "172.17.0.2", "aliases": []}


@pytest.mark.unit
def test_extract_default_entry_empty_ip(manager):
    """Empty IP returns None."""
    result = manager.extract_default_entry("")

    assert result is None


@pytest.mark.unit
def test_extract_default_entry_none_ip(manager):
    """None IP returns None."""
    result = manager.extract_default_entry(None)

    assert result is None


@pytest.mark.unit
def test_get_container_data_basic(manager):
    """Basic container data is extracted correctly."""
    info = {
        "Name": "/mycontainer",
        "Config": {"Hostname": "myhost", "Domainname": ""},
        "NetworkSettings": {"IPAddress": "172.17.0.2", "Networks": {}},
    }

    result = manager.get_container_data(info)

    assert len(result) == 1
    assert result[0]["ip"] == "172.17.0.2"
    assert result[0]["name"] == "mycontainer"
    assert "mycontainer" in result[0]["domains"]
    assert "myhost" in result[0]["domains"]


@pytest.mark.unit
def test_get_container_data_with_domainname(manager):
    """Container with domainname includes combined hostname."""
    info = {
        "Name": "/app",
        "Config": {"Hostname": "web", "Domainname": "example.com"},
        "NetworkSettings": {"IPAddress": "172.17.0.2", "Networks": {}},
    }

    result = manager.get_container_data(info)

    assert len(result) == 1
    assert "app" in result[0]["domains"]
    assert "web.example.com" in result[0]["domains"]


@pytest.mark.unit
def test_get_container_data_with_network_aliases(manager):
    """Network aliases are included in domains."""
    info = {
        "Name": "/postgres",
        "Config": {"Hostname": "db", "Domainname": ""},
        "NetworkSettings": {
            "IPAddress": "172.17.0.2",
            "Networks": {
                "mynetwork": {"IPAddress": "172.18.0.3", "Aliases": ["database", "pg"]}
            },
        },
    }

    result = manager.get_container_data(info)

    assert len(result) == 2

    network_entry = next(e for e in result if e["ip"] == "172.18.0.3")
    assert "database" in network_entry["domains"]
    assert "pg" in network_entry["domains"]
    assert "postgres" in network_entry["domains"]
    assert "db" in network_entry["domains"]


@pytest.mark.unit
def test_get_container_data_no_default_ip(manager):
    """Container without default IP only has network entries."""
    info = {
        "Name": "/app",
        "Config": {"Hostname": "web", "Domainname": ""},
        "NetworkSettings": {
            "IPAddress": "",
            "Networks": {"custom": {"IPAddress": "172.18.0.3", "Aliases": ["webapp"]}},
        },
    }

    result = manager.get_container_data(info)

    assert len(result) == 1
    assert result[0]["ip"] == "172.18.0.3"


@pytest.mark.unit
def test_get_container_data_multiple_networks(manager):
    """Container on multiple networks has entry for each."""
    info = {
        "Name": "/multi",
        "Config": {"Hostname": "host", "Domainname": ""},
        "NetworkSettings": {
            "IPAddress": "172.17.0.2",
            "Networks": {
                "net1": {"IPAddress": "172.18.0.3", "Aliases": ["alias1"]},
                "net2": {"IPAddress": "172.19.0.4", "Aliases": ["alias2"]},
            },
        },
    }

    result = manager.get_container_data(info)

    assert len(result) == 3

    ips = [entry["ip"] for entry in result]
    assert "172.17.0.2" in ips
    assert "172.18.0.3" in ips
    assert "172.19.0.4" in ips


@pytest.mark.unit
def test_get_container_data_name_stripping(manager):
    """Container name has leading slash stripped."""
    info = {
        "Name": "/my-container-name",
        "Config": {"Hostname": "host", "Domainname": ""},
        "NetworkSettings": {"IPAddress": "172.17.0.2", "Networks": {}},
    }

    result = manager.get_container_data(info)

    assert result[0]["name"] == "my-container-name"
    assert "my-container-name" in result[0]["domains"]
