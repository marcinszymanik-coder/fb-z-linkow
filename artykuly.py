"""Pobieranie tytułu i leadu artykułów, z zabezpieczeniami przed SSRF."""
from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl,en;q=0.8",
}
MAX_BYTES = 3 * 1024 * 1024
MAX_PRZEKIEROWAN = 3
MAX_LINKOW = 100


def czy_bezpieczny_url(url: str) -> bool:
    """Blokuje adresy lokalne/prywatne (ochrona przed SSRF)."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast):
                return False
        return True
    except Exception:
        return False


def pobierz_html(url: str, timeout: int = 10) -> bytes:
    with requests.Session() as s:
        s.headers.update(HEADERS)
        for _ in range(MAX_PRZEKIEROWAN + 1):
            if not czy_bezpieczny_url(url):
                raise ValueError("niedozwolony lub nieosiągalny adres")
            r = s.get(url, timeout=timeout, stream=True, allow_redirects=False)
            try:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("Location")
                    if not loc:
                        raise ValueError("przekierowanie bez adresu")
                    url = urljoin(url, loc)
                    continue
                if r.status_code != 200:
                    raise ValueError(f"HTTP {r.status_code}")
                dane = r.raw.read(MAX_BYTES + 1, decode_content=True)
            finally:
                r.close()
            if len(dane) > MAX_BYTES:
                raise ValueError("strona zbyt duża")
            return dane
        raise ValueError("zbyt wiele przekierowań")


def _tekst(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


def _meta(soup, *nazwy) -> str:
    for n in nazwy:
        t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if t and t.get("content"):
            return re.sub(r"\s+", " ", t["content"]).strip()
    return ""


def _akapity_z(kontener, n: int, min_dl: int) -> list:
    wynik = []
    for p in kontener.find_all("p"):
        if p.find_parent(["nav", "footer", "aside", "form"]):
            continue
        t = _tekst(p)
        if len(t) >= min_dl:
            wynik.append(t)
            if len(wynik) >= n:
                break
    return wynik


def wyciagnij_tekst(soup, selektor: str = "", max_akapitow: int = 1,
                    min_dlugosc: int = 80) -> dict:
    """Zwraca słownik: tytul_seo, h1, opis, lead, tekst (połączony do dopasowania)."""
    tytul_seo = _tekst(soup.title) if soup.title else ""
    h1_tag = soup.find("h1")
    h1 = _tekst(h1_tag) if h1_tag else ""
    opis = _meta(soup, "og:description", "description", "twitter:description")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    akapity = []
    if selektor:
        try:
            elementy = soup.select(selektor)
        except Exception:
            elementy = []
        akapity = [t for t in (_tekst(e) for e in elementy) if t][:max_akapitow]
    if not akapity:
        for kontener in (soup.find("article"), soup.find("main"), soup.body, soup):
            if kontener is None:
                continue
            akapity = _akapity_z(kontener, max_akapitow, min_dlugosc)
            if akapity:
                break

    lead = " ".join(akapity)
    tekst = " ".join(x for x in (tytul_seo, h1, opis, lead) if x)
    return {"tytul_seo": tytul_seo, "h1": h1, "opis": opis, "lead": lead, "tekst": tekst}


def _pobierz_jeden(url: str, selektor: str, max_akapitow: int):
    try:
        dane = pobierz_html(url)
        soup = BeautifulSoup(dane, "html.parser")
        wynik = wyciagnij_tekst(soup, selektor, max_akapitow)
        wynik["blad"] = None
    except Exception as e:
        wynik = {"tytul_seo": "", "h1": "", "opis": "", "lead": "", "tekst": "",
                 "blad": str(e)[:200]}
    return url, wynik


def pobierz_artykuly(urls: list, selektor: str = "", max_akapitow: int = 1,
                     workers: int = 3) -> dict:
    """Zwraca słownik url -> dane artykułu (lub opis błędu w polu 'blad')."""
    urls = list(urls)[:MAX_LINKOW]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        wyniki = list(ex.map(lambda u: _pobierz_jeden(u, selektor, max_akapitow), urls))
    return dict(wyniki)
