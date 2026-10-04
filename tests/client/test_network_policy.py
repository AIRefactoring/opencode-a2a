from __future__ import annotations

import asyncio
import socket

import pytest

from opencode_a2a.client.network_policy import (
    A2ANetworkPolicyError,
    matches_allowed_host,
    resolve_host_addresses,
    validate_agent_url,
)


def test_matches_allowed_host_exact_and_wildcard() -> None:
    assert not matches_allowed_host("", ["peer.example.com"])
    assert not matches_allowed_host(None, ["peer.example.com"])
    assert matches_allowed_host("peer.example.com", ["", "peer.example.com"])
    assert matches_allowed_host("peer.example.com", ["peer.example.com"])
    assert matches_allowed_host("a.example.com", ["*.example.com"])
    assert matches_allowed_host("b.a.example.com", ["*.example.com"])
    assert not matches_allowed_host("example.com", ["*.example.com"])
    assert not matches_allowed_host("other.org", ["*.example.com"])
    assert not matches_allowed_host("evil-example.com", ["*.example.com"])


def test_matches_allowed_host_host_port_pinning() -> None:
    # host:port entries match the exact pair (fleet deployments pin peers)
    assert matches_allowed_host("127.0.0.1", ["127.0.0.1:8104"])
    assert matches_allowed_host("peer.example.com", ["peer.example.com:9443"])
    # hostname-only entries keep matching every port (backwards compatible)
    assert matches_allowed_host("peer.example.com", ["peer.example.com"])


@pytest.mark.asyncio
async def test_validate_rejects_port_not_in_allowlist(monkeypatch) -> None:
    # every entry carries a port and the URL's port does not match any of
    # them: hop to another fleet adapter on the same host is rejected even
    # though the hostname itself is allowlisted.
    with pytest.raises(A2ANetworkPolicyError, match="port .* not allowed"):
        await validate_agent_url(
            "http://127.0.0.1:8105/",
            allowed_hosts=["127.0.0.1:8104", "127.0.0.1:8106"],
            allow_private_hosts=True,
        )


@pytest.mark.asyncio
async def test_validate_accepts_pinned_port(monkeypatch) -> None:
    decision = await validate_agent_url(
        "http://127.0.0.1:8104/",
        allowed_hosts=["127.0.0.1:8104", "127.0.0.1:8106"],
        allow_private_hosts=True,
    )
    assert decision.allowed_host and decision.credentials_allowed


@pytest.mark.asyncio
async def test_validate_mixed_entries_hostname_still_matches(monkeypatch) -> None:
    # a hostname-only entry still matches any port next to pinned ones
    _patch_public_dns(monkeypatch, "93.184.216.34")
    decision = await validate_agent_url(
        "http://peer.example.com:9443/",
        allowed_hosts=["https://other.example.com:1", "peer.example.com"],
    )
    assert decision.allowed_host


@pytest.mark.asyncio
async def test_resolve_host_addresses_resolves_localhost() -> None:
    addresses = await resolve_host_addresses("localhost")

    assert addresses
    assert all(address for address in addresses)


@pytest.mark.asyncio
async def test_resolve_host_addresses_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = asyncio.get_running_loop()
    infos = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.35", 0)),
    ]

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple]:
        del args, kwargs
        return infos

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    addresses = await resolve_host_addresses("peer.example.com")

    assert addresses == ("93.184.216.34", "93.184.216.35")


@pytest.mark.asyncio
async def test_resolve_host_addresses_rejects_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()

    async def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple]:
        del args, kwargs
        raise socket.gaierror("no such host")

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(A2ANetworkPolicyError, match="could not be resolved"):
        await resolve_host_addresses("peer.example.com")


def _patch_public_dns(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    async def fake_resolve(host: str) -> tuple[str, ...]:
        del host
        return tuple(addresses)

    monkeypatch.setattr(
        "opencode_a2a.client.network_policy.resolve_host_addresses",
        fake_resolve,
    )


@pytest.mark.asyncio
async def test_validate_rejects_non_http_schemes(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("file:///etc/passwd")
    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("ftp://peer.example.com/")
    with pytest.raises(A2ANetworkPolicyError, match="scheme"):
        await validate_agent_url("peer.example.com/path")


@pytest.mark.asyncio
async def test_validate_rejects_empty_url() -> None:
    with pytest.raises(A2ANetworkPolicyError, match="agent_url is required"):
        await validate_agent_url("")
    with pytest.raises(A2ANetworkPolicyError, match="agent_url is required"):
        await validate_agent_url("   ")


@pytest.mark.asyncio
async def test_validate_rejects_missing_host_and_userinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="host"):
        await validate_agent_url("https:///path")
    with pytest.raises(A2ANetworkPolicyError, match="userinfo"):
        await validate_agent_url(
            "https://user:pass@peer.example.com/"  # pragma: allowlist secret
        )


@pytest.mark.asyncio
async def test_validate_rejects_host_outside_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    with pytest.raises(A2ANetworkPolicyError, match="not allowed"):
        await validate_agent_url(
            "https://other.org/",
            allowed_hosts=["peer.example.com"],
        )


@pytest.mark.asyncio
async def test_validate_accepts_allowlisted_public_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_public_dns(monkeypatch, "93.184.216.34")

    decision = await validate_agent_url(
        "https://peer.example.com/",
        allowed_hosts=["*.example.com"],
    )
    assert decision.host == "peer.example.com"
    assert decision.allowed_host is True
    assert decision.credentials_allowed is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "192.168.1.1",
        "172.16.0.1",
        "0.0.0.0",
        "::1",
        "fd00::1",
        "fe80::1",
    ],
)
@pytest.mark.asyncio
async def test_validate_rejects_private_resolution(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    _patch_public_dns(monkeypatch, address)

    with pytest.raises(A2ANetworkPolicyError, match="private/loopback"):
        await validate_agent_url("https://peer.example.com/")


@pytest.mark.asyncio
async def test_allow_private_hosts_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_public_dns(monkeypatch, "127.0.0.1")

    decision = await validate_agent_url(
        "https://127.0.0.1:8000/",
        allow_private_hosts=True,
    )
    assert decision.credentials_allowed is False


@pytest.mark.asyncio
async def test_validate_rejects_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str) -> tuple[str, ...]:
        del host
        raise socket.gaierror("no such host")

    monkeypatch.setattr(
        "opencode_a2a.client.network_policy.resolve_host_addresses",
        fake_resolve,
    )

    with pytest.raises(A2ANetworkPolicyError, match="could not be resolved"):
        await validate_agent_url("https://peer.example.com/")


@pytest.mark.asyncio
async def test_validate_propagates_resolver_policy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str) -> tuple[str, ...]:
        del host
        raise A2ANetworkPolicyError("resolver blocked")

    monkeypatch.setattr(
        "opencode_a2a.client.network_policy.resolve_host_addresses",
        fake_resolve,
    )

    with pytest.raises(A2ANetworkPolicyError, match="resolver blocked"):
        await validate_agent_url("https://peer.example.com/")
