"""Client-address resolution shared by every public, IP-rate-limited
endpoint (`dnd_ai.api.local_auth`, `dnd_ai.api.foundry_pairing`) — one
authoritative resolver (Phase 13B correction), so the self-hosted reverse-
proxy trust boundary is defined and enforced in exactly one place rather
than reimplemented per module. Both call sites previously carried their own
identically-named, identically-behaved `_client_ip` — harmless while
neither read anything but `request.client.host`, but exactly the "two
conflicting forwarded-address resolvers" shape that becomes a real risk the
moment either one starts trusting a header, so this module replaces both.

Trust model: `request.client.host` (the ASGI server's own TCP peer address)
is trusted implicitly — the server accepted a raw connection from it, so it
cannot be spoofed by the request itself. `X-Forwarded-For` is an ordinary,
entirely client-controlled HTTP header and is trusted ONLY when that
immediate peer is itself a configured trusted proxy
(`dnd_ai.config.settings.trusted_proxies`, via `dnd_ai.config.
trusted_proxy_networks_tuple` — the one authoritative configuration source)
— never for a direct or untrusted caller. With `trusted_proxies` left at
its safe empty default (no reverse proxy configured — this repository's
current `compose.yaml` topology), this resolves identically to the plain
`request.client.host` read the two modules used before this correction, so
local development and any deployment that hasn't yet placed a reverse
proxy in front of `api` are unaffected.

Exactly one hop of trust is resolved, deliberately: this application's
supported self-hosted topology (docs/adr/0012, PLAN.md §32/Phase 14) is a
single reverse proxy directly in front of `api`, not a multi-hop CDN/load-
balancer chain, so the *last* entry of `X-Forwarded-For` is trusted — the
address the trusted proxy itself observed as its own TCP peer, since every
common reverse proxy (nginx's `$proxy_add_x_forwarded_for`, Traefik, Caddy)
appends the address it directly saw rather than replacing the header
outright. That means an attacker who prepends forged entries to their own
request's `X-Forwarded-For` cannot change what this resolves to — the
trusted proxy's own append still lands last — but does mean a multi-hop
deployment (a second proxy/CDN also configured as trusted) is out of
scope; `trusted_proxies` should name only the proxy directly in front of
`api`, never a wider chain. The `Forwarded` header (RFC 7239) is
deliberately not parsed at all — an additional format this application
does not otherwise use, and one authoritative header is enough for the
supported topology.

Fails safe in every other case: an untrusted or unresolvable peer, a
missing/empty `X-Forwarded-For`, or a last entry that doesn't parse as a
literal IP address (a malformed or unexpectedly multi-valued proxy
misconfiguration) all fall back to `request.client.host` unchanged — never
raise, never trust a value this module cannot itself validate as an IP
address.
"""

import ipaddress

from fastapi import Request

from dnd_ai.config import settings, trusted_proxy_networks_tuple

__all__ = ["resolve_client_ip"]


def _peer_address(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _is_trusted_proxy_peer(peer: str) -> bool:
    networks = trusted_proxy_networks_tuple(settings)
    if not networks:
        return False
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(peer_address in network for network in networks)


def resolve_client_ip(request: Request) -> str:
    """The address this request's rate-limit/audit bookkeeping should key
    on: `request.client.host` unless that immediate peer is a configured
    trusted proxy, in which case the last `X-Forwarded-For` entry (see this
    module's docstring for why the last entry, and why only one hop) —
    provided that entry is present and a well-formed IP address. Never
    returns `None`; `"unknown"` is the same fixed placeholder the prior
    per-module `_client_ip` helpers used when the ASGI server supplied no
    peer at all (some test transports)."""
    peer = _peer_address(request)
    if not _is_trusted_proxy_peer(peer):
        return peer
    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer
    candidate = forwarded_for.rsplit(",", 1)[-1].strip()
    if not candidate:
        return peer
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return peer
    return candidate
