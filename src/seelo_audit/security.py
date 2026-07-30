"""Validation d'URL et protection anti-SSRF. À utiliser avant tout fetch."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import tldextract

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, None}


class UnsafeUrlError(Exception):
    """Levée quand une URL est refusée pour des raisons de sécurité (SSRF)."""


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    domain: str  # domaine enregistré normalisé (sans www.), clé de cache
    host: str


def _is_unsafe_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_and_check(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Résolution DNS impossible pour {host}") from exc

    if not infos:
        raise UnsafeUrlError(f"Aucune adresse IP résolue pour {host}")

    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip_str = str(sockaddr[0])
        if _is_unsafe_ip(ip_str):
            raise UnsafeUrlError(f"{host} résout vers une IP non publique ({ip_str}) — refusé")


def normalize_domain(host: str) -> str:
    """Normalise un host en domaine enregistré (www.cabinet-zen.fr == cabinet-zen.fr)."""
    extracted = tldextract.extract(host)
    if not extracted.domain or not extracted.suffix:
        return host.lower()
    return f"{extracted.domain}.{extracted.suffix}".lower()


def _validate_single(raw: str) -> ValidatedUrl:
    candidate = raw.strip()

    # Parse tel quel d'abord : un schéma explicite mais non-http(s)
    # (javascript:, ftp:, file:, data:...) doit être rejeté immédiatement,
    # même sans "://" — urlsplit reconnaît "scheme:reste" sans "//".
    parts = urlsplit(candidate)
    if parts.scheme and parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Schéma non autorisé : {parts.scheme!r}")

    if not parts.scheme:
        candidate = f"https://{candidate}"
        parts = urlsplit(candidate)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Schéma non autorisé : {parts.scheme!r}")

    try:
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError(f"URL malformée : {raw!r}") from exc

    if port not in ALLOWED_PORTS:
        raise UnsafeUrlError(f"Port non standard refusé : {port}")

    if not parts.hostname:
        raise UnsafeUrlError("URL sans nom d'hôte")

    host = parts.hostname

    # Refuse toute IP littérale dans l'URL (contourne la résolution DNS)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeUrlError("Adresses IP littérales non autorisées")

    _resolve_and_check(host)

    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    return ValidatedUrl(url=normalized, domain=normalize_domain(host), host=host)


async def validate_url(raw: str) -> ValidatedUrl:
    """Normalise et valide une URL candidate. Lève UnsafeUrlError si refusée.

    Ne suit PAS les redirections elle-même — c'est fetcher.py qui doit
    rappeler cette fonction à chaque saut de redirection (le piège classique
    est un domaine public qui redirige vers 127.0.0.1).
    """
    return _validate_single(raw)


def robots_allows(robots_txt: str | None, url: str, user_agent: str) -> bool:
    """Retourne False seulement si robots.txt interdit explicitement l'URL.

    Un robots.txt absent ou vide autorise tout. La page d'accueil est
    auditée même si robots.txt interdit tout (c'est une consultation, pas
    une indexation) — c'est à l'appelant de poser le flag robots_restricted.
    """
    if not robots_txt:
        return True
    parser = RobotFileParser()
    parser.parse(robots_txt.splitlines())
    return parser.can_fetch(user_agent, url)
