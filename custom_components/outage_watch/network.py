"""Bounded public HTTP probes and conditional provider feed requests."""
import asyncio
import json
from ipaddress import ip_address
from time import monotonic

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

from .apple import FEED_URL as APPLE_FEED_URL, parse_icloud
from .google import FEED_URL as GOOGLE_FEED_URL, parse_workspace
from .polling import retry_deadline
from .statuspage import parse_feed
from .xai import FEED_URL as XAI_FEED_URL, parse_xai

SUMMARY_ONLY_FEEDS = frozenset({
    "https://status.openai.com/api/v2/summary.json",
    "https://status.perplexity.com/api/v2/summary.json",
    "https://groqstatus.com/api/v2/summary.json",
    "https://status.plex.tv/api/v2/summary.json",
    "https://status.tailscale.com/api/v2/summary.json",
})

class PublicResolver(AbstractResolver):
    def __init__(self):
        self.resolver = aiohttp.ThreadedResolver()

    async def resolve(self, host, port=0, family=0):
        addresses = await self.resolver.resolve(host, port, family)
        if any(not ip_address(item["host"]).is_global for item in addresses):
            raise OSError("Check destinations must use public IP addresses")
        return addresses

    async def close(self):
        await self.resolver.close()

def public_url(value):
    url = URL(value)
    if url.scheme not in ("http", "https") or not url.host or url.user is not None:
        raise ValueError("Enter a public HTTP or HTTPS URL without credentials")
    if url.host.lower().rstrip(".") == "localhost" or url.host.endswith(".local"):
        raise ValueError("Enter a public address")
    try:
        address = ip_address(url.host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("Enter a public address")
    _ = url.port
    return url.with_fragment(None)

async def probe(session, value):
    start = monotonic()
    try:
        url = public_url(value)
        method = "HEAD"
        async with asyncio.timeout(10):
            for _ in range(7):
                async with session.request(method, url, allow_redirects=False) as response:
                    code = response.status
                    if code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
                        url = public_url(str(url.join(URL(response.headers["Location"]))))
                        continue
                    if method == "HEAD" and code == 405:
                        method = "GET"
                        continue
                    if code in (401, 403, 429):
                        return "blocked", None, code, retry_deadline(response)
                    if 200 <= code < 300:
                        return "ok", round((monotonic() - start) * 1000), code, 0
                    return "failed", None, code, retry_deadline(response)
    except (aiohttp.ClientError, TimeoutError, ValueError, OSError):
        pass
    return "failed", None, None, 0

async def feed_update(session, url, previous):
    headers = {"If-None-Match": previous["etag"]} if previous.get("etag") else {}
    try:
        async with session.get(url, headers=headers, allow_redirects=False) as response:
            if response.status == 304 and previous.get("data"):
                return previous, 0
            if response.status != 200:
                return None, retry_deadline(response)
            body = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                body.extend(chunk)
                if len(body) > 1_000_000:
                    return None, 0
            if url == APPLE_FEED_URL:
                data = parse_icloud(body)
            elif url == XAI_FEED_URL:
                data = parse_xai(body)
            else:
                payload = json.loads(body)
                data = (parse_workspace(payload) if url == GOOGLE_FEED_URL else
                        parse_feed(payload, summary_only=url in SUMMARY_ONLY_FEEDS))
            return {"data": data, "etag": response.headers.get("ETag")}, 0
    except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, AttributeError):
        return None, 0
