"""Outbound HTTP for the onboarding agent.

The founder chooses the URL we fetch, so every request here is treated as
untrusted input:

- only http/https on the default ports;
- every hostname (including each redirect hop) must resolve to public
  addresses, so a registration can't make the server read its own network;
- bodies are capped and time-limited;
- robots.txt is honoured for the company site, and requests identify
  themselves with a descriptive User-Agent.

A resolver that changes its answer between our check and the connection
(DNS rebinding) can still slip past the address check. A production build
would pin the checked IP into the connection or route through an egress proxy.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.core.config import settings

USER_AGENT = "VentureIQ-Verifier/0.1 (+startup registration check; contact via platform)"
MAX_BYTES = 1_500_000
MAX_REDIRECTS = 4
TIMEOUT = httpx.Timeout(8.0, connect=5.0)


class FetchError(Exception):
    pass


@dataclass
class Fetched:
    url: str
    status: int
    text: str
    content_type: str


async def _assert_public(host: str) -> None:
    if not host:
        raise FetchError("missing host")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise FetchError(f"{host} resolves to a non-public address")


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise FetchError("only http and https URLs are allowed")
    if parts.port not in (None, 80, 443):
        raise FetchError("non-standard ports are not fetched")
    if parts.username or parts.password:
        raise FetchError("credentials in URLs are not allowed")
    return parts.hostname or ""


async def safe_get(url: str, *, accept: str = "text/html,application/xhtml+xml") -> Fetched:
    """GET a founder-supplied URL with the guards above; follows redirects by hand."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            await _assert_public(_check_url(url))
            async with client.stream("GET", url) as res:
                if res.is_redirect and res.headers.get("location"):
                    url = urljoin(url, res.headers["location"])
                    continue
                chunks: list[bytes] = []
                size = 0
                async for chunk in res.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                return Fetched(
                    url=str(res.url),
                    status=res.status_code,
                    text=body.decode(res.encoding or "utf-8", errors="replace"),
                    content_type=res.headers.get("content-type", ""),
                )
    raise FetchError("too many redirects")


async def robots_allows(url: str) -> bool:
    """True unless the site's robots.txt disallows our agent for this URL."""
    parts = urlsplit(url)
    try:
        res = await safe_get(f"{parts.scheme}://{parts.netloc}/robots.txt", accept="text/plain")
    except FetchError:
        return True
    except httpx.HTTPError:
        return True
    if res.status != 200:
        return True
    rp = RobotFileParser()
    rp.parse(res.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


async def api_get(url: str, *, params: dict | None = None, github: bool = False) -> httpx.Response:
    """GET a fixed, well-known public API (RDAP, DNS-over-HTTPS, GitHub)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if github:
        headers["Accept"] = "application/vnd.github+json"
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=headers, follow_redirects=True) as client:
        return await client.get(url, params=params)
