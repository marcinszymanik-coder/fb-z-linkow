"""Logika dopasowania postów z Facebooka do artykułów (bez zależności od Streamlita)."""
from __future__ import annotations

import io
import math
import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

KOLUMNY_TEKSTOWE = ["Tytuł", "Opis", "Link do strony", "Link do zasobu"]
KOLUMNA_LINKU_FB = "Link bezpośredni"

STOP = {"jak", "dla", "czy", "oraz", "przed", "przez", "tez", "sie", "nie",
        "co", "do", "od", "po", "na", "ze", "to", "jest", "ktore", "ktory",
        "ile", "lub", "ale", "tylko", "jakie", "jakich", "dlaczego", "warto",
        "poznaj", "sprawdz", "zobacz", "naprawde", "moze", "musisz", "masz",
        "twoj", "twoje", "kiedy", "dobre", "dobrze", "ktora", "wszystko"}


@dataclass
class Ustawienia:
    min_trafien: int = 2
    min_wynik: float = 0.30
    min_wynik_2_trafienia: float = 0.45
    min_przewaga: float = 1.2
    potega_idf: float = 2.0
    unikalne_posty: bool = True
    liczba_kandydatow: int = 5


@dataclass
class Indeks:
    kol: list
    teksty: dict       # url posta -> tekst
    prefiksy: dict     # url posta -> zbiór przedrostków słów
    norm_tekst: dict   # url posta -> znormalizowany tekst
    grupy: dict        # znormalizowany tekst -> lista url-i (identyczna treść)


# ---------- pomocnicze ----------

def bez_ogonkow(s: str) -> str:
    s = s.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def czysty_url(url: str) -> str:
    return url.strip().split("?")[0].split("#")[0]


def normalizuj(url: str) -> str:
    url = czysty_url(url).lower()
    return re.sub(r"^https?://(www\.)?", "", url).rstrip("/")


def normalizuj_fb(url) -> str:
    url = czysty_url(str(url)).lower().rstrip("/")
    return re.sub(r"^https?://(www\.|m\.)?", "", url)


def klucz(w: str) -> str:
    """Krótkie słowa w całości, dłuższe bez ostatniej litery (maks. 6 znaków)."""
    return w if len(w) <= 4 else w[:min(len(w) - 1, 6)]


def klucze_z_url(url: str) -> set:
    slug = czysty_url(url).rstrip("/").split("/")[-1]
    slug = re.sub(r"^\d+-", "", slug)
    slug = re.sub(r"\.\w{2,5}$", "", slug)
    return {klucz(bez_ogonkow(s.lower())) for s in slug.split("-")
            if len(s) > 2 and s.lower() not in STOP}


def kolumny_tekstu_posta(df: pd.DataFrame) -> list:
    baza = [k for k in ("Tytuł", "Opis") if k in df.columns]
    wzor = re.compile(r"tre[śs]ć|tresc|wiadomo|tekst|message|caption|text|description", re.I)
    dodatkowe = [c for c in df.columns
                 if c not in baza and c != KOLUMNA_LINKU_FB
                 and c not in KOLUMNY_TEKSTOWE
                 and wzor.search(str(c)) and df[c].dtype == object]
    return baza + dodatkowe


# ---------- wczytywanie ----------

def wczytaj_csv_bytes(data: bytes) -> pd.DataFrame:
    bledy = []
    for enc, sep in [("utf-8-sig", None), ("cp1250", None), ("utf-16", "\t")]:
        try:
            df = pd.read_csv(io.BytesIO(data), encoding=enc, sep=sep, engine="python")
            if df.shape[1] < 2 and sep is None:
                raise ValueError("podejrzanie mało kolumn")
            return df
        except Exception as e:
            bledy.append(f"{enc}: {str(e)[:100]}")
    raise ValueError("Nie udało się wczytać CSV: " + " | ".join(bledy))


def wczytaj_linki_bytes(data: bytes) -> list:
    for enc in ("utf-8-sig", "cp1250"):
        try:
            tekst = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        tekst = data.decode("utf-8", errors="ignore")
    linki = re.findall(r"https?://[^\s,;\"'<>]+", tekst)
    return list(dict.fromkeys(linki))


def zawez_do_listy(df: pd.DataFrame, linki_postow: list):
    """Zostawia w df tylko posty z listy. Zwraca (df, posty_z_listy_nieobecne_w_csv)."""
    if KOLUMNA_LINKU_FB not in df.columns:
        raise ValueError(f"Brak kolumny '{KOLUMNA_LINKU_FB}'. Dostępne: {list(df.columns)}")
    lista = {normalizuj_fb(u) for u in linki_postow}
    norm = df[KOLUMNA_LINKU_FB].map(lambda u: normalizuj_fb(u) if pd.notna(u) else None)
    brak = sorted(lista - set(norm.dropna()))
    return df[norm.isin(lista)], brak


# ---------- wyszukiwanie bezpośrednie ----------

def szukaj_bezposrednio(df: pd.DataFrame, linki: list) -> list:
    if KOLUMNA_LINKU_FB not in df.columns:
        raise ValueError(f"Brak kolumny '{KOLUMNA_LINKU_FB}'. Dostępne: {list(df.columns)}")
    kolumny = [k for k in KOLUMNY_TEKSTOWE if k in df.columns]
    kolumny += [k for k in kolumny_tekstu_posta(df) if k not in kolumny]
    if not kolumny:
        raise ValueError(f"Brak kolumn tekstowych w CSV. Dostępne: {list(df.columns)}")

    tekst = df[kolumny].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
    wyniki = []
    for url in linki:
        m = re.search(r"/(\d+)-[^/]*/?$", czysty_url(url))
        art_id = m.group(1) if m else None
        maska = pd.Series(False, index=df.index)
        if art_id:
            maska |= tekst.str.contains(rf"(?<!\d){art_id}(?!\d)", regex=True)
        maska |= tekst.str.contains(normalizuj(url), regex=False)
        posty = df.loc[maska, KOLUMNA_LINKU_FB].dropna().unique().tolist()
        wyniki.append((url, art_id, posty))
    return wyniki


# ---------- dopasowanie po słownictwie ----------

def przygotuj_indeks(df: pd.DataFrame) -> Indeks:
    if KOLUMNA_LINKU_FB not in df.columns:
        raise ValueError(f"Brak kolumny '{KOLUMNA_LINKU_FB}'. Dostępne: {list(df.columns)}")
    d = df.dropna(subset=[KOLUMNA_LINKU_FB])
    kol = kolumny_tekstu_posta(d)

    teksty = {}
    for fb_url, *wart in zip(d[KOLUMNA_LINKU_FB], *[d[c] for c in kol]):
        t = " ".join("" if pd.isna(v) else str(v) for v in wart)
        teksty[fb_url] = (teksty.get(fb_url, "") + " " + t).strip()

    prefiksy = {}
    for u, t in teksty.items():
        zb = set()
        for w in re.findall(r"\w+", bez_ogonkow(t.lower())):
            for k in range(3, min(len(w), 7) + 1):
                zb.add(w[:k])
        prefiksy[u] = zb

    norm_tekst = {u: re.sub(r"\s+", " ", t).strip().lower() for u, t in teksty.items()}
    grupy = {}
    for u, t in norm_tekst.items():
        if t:
            grupy.setdefault(t, []).append(u)
    return Indeks(kol, teksty, prefiksy, norm_tekst, grupy)


def dopasuj(ind: Indeks, artykuly_urls: list, ust: Ustawienia):
    """Zwraca (wyniki, szczegoly).
    wyniki: lista (artykuł, post, trafienia); posty o identycznej treści to osobne rekordy.
    szczegoly: słownik artykuł -> dane diagnostyczne."""
    szczegoly = {u: {"klucze": [], "powod": None, "kandydaci": [], "przydzial": []}
                 for u in artykuly_urls}
    artykuly = {}
    for u in artykuly_urls:
        k = klucze_z_url(u)
        if k:
            artykuly[u] = k
        else:
            szczegoly[u]["powod"] = "slug bez użytecznych słów"

    n = len(ind.prefiksy)
    if not artykuly or n == 0:
        for u in artykuly:
            szczegoly[u]["powod"] = "brak postów z tekstem"
        return [], szczegoly

    wszystkie = set().union(*artykuly.values())
    dfk = {k: sum(1 for s in ind.prefiksy.values() if k in s) for k in wszystkie}

    def idf(k):
        return math.log((n + 1) / (dfk.get(k, 0) + 0.5)) + 0.1

    def waga(k):
        return idf(k) ** ust.potega_idf

    pary = []
    for art_url, art_klucze in artykuly.items():
        mianownik = sum(waga(k) for k in art_klucze)
        kandydaci = []
        for fb_url, zb in ind.prefiksy.items():
            wspolne = [k for k in art_klucze if k in zb]
            if not wspolne:
                continue
            wynik = sum(waga(k) for k in wspolne) / mianownik
            tr = len(wspolne)
            ok = (tr >= ust.min_trafien and wynik >= ust.min_wynik
                  and (tr >= 3 or wynik >= ust.min_wynik_2_trafienia))
            kandydaci.append((wynik, fb_url, tr, sorted(wspolne), ok))
        kandydaci.sort(key=lambda x: x[0], reverse=True)

        niejednoznaczny = False
        if kandydaci:
            top = kandydaci[0]
            inny = next((k for k in kandydaci[1:]
                         if ind.norm_tekst[k[1]] != ind.norm_tekst[top[1]]), None)
            niejednoznaczny = bool(inny and top[0] < inny[0] * ust.min_przewaga)

        s = szczegoly[art_url]
        s["klucze"] = [(k, round(idf(k), 2), dfk.get(k, 0)) for k in sorted(art_klucze)]
        if not kandydaci:
            s["powod"] = "brak wspólnych słów z jakimkolwiek postem"
        elif not any(k[4] for k in kandydaci):
            s["powod"] = "wszyscy kandydaci poniżej progów"
        elif niejednoznaczny:
            s["powod"] = "niejednoznaczne: dwa różne posty o zbliżonym wyniku"
        else:
            for wynik, fb_url, tr, wsp, ok in kandydaci:
                if ok:
                    pary.append((round(wynik, 6), art_url, fb_url, tr))

        for wynik, fb_url, tr, wsp, ok in kandydaci[:ust.liczba_kandydatow]:
            s["kandydaci"].append({
                "ok": "✓" if ok else "✗",
                "wynik": round(wynik, 3),
                "trafień": tr,
                "duplikaty": len(ind.grupy.get(ind.norm_tekst[fb_url], [])),
                "wspólne": ", ".join(wsp),
                "post": fb_url,
                "treść": re.sub(r"\s+", " ", ind.teksty[fb_url])[:200],
            })

    pary.sort(reverse=True)
    wyniki, uzyte_art, uzyte_teksty = [], set(), set()
    for wynik, art_url, fb_url, tr in pary:
        if art_url in uzyte_art:
            continue
        t = ind.norm_tekst[fb_url]
        if ust.unikalne_posty and t in uzyte_teksty:
            continue
        for u in sorted(ind.grupy.get(t, [fb_url])):
            wyniki.append((art_url, u, tr))
            szczegoly[art_url]["przydzial"].append(u)
        uzyte_art.add(art_url)
        uzyte_teksty.add(t)

    for art_url in artykuly:
        s = szczegoly[art_url]
        if not s["przydzial"] and s["powod"] is None:
            s["powod"] = "post zajęty przez lepiej pasujący artykuł"
    return wyniki, szczegoly


# ---------- raporty ----------

def zbuduj_raport(wyniki_standardowe: list, wyniki_dopasowane: list):
    """Zwraca (tekst_raportu, DataFrame)."""
    znalezione = [w for w in wyniki_standardowe if w[2]]
    art_z_dop = {w[0] for w in wyniki_dopasowane}
    brak = [w for w in wyniki_standardowe if not w[2] and w[0] not in art_z_dop]

    rekordy_art, uzycia = {}, {}
    for a, fb, _ in wyniki_dopasowane:
        rekordy_art[a] = rekordy_art.get(a, 0) + 1
        uzycia[fb] = uzycia.get(fb, 0) + 1

    linie = ["RAPORT WYSZUKIWANIA POSTÓW NA FACEBOOKU", "=" * 50,
             f"Wszystkich artykułów:        {len(wyniki_standardowe)}",
             f"Znaleziono bezpośrednio:     {len(znalezione)}",
             f"Dopasowano po słownictwie:   {len(art_z_dop)} (rekordów: {len(wyniki_dopasowane)})",
             f"Bez posta:                   {len(brak)}",
             "=" * 50, ""]
    for url, _, posty in wyniki_standardowe:
        if posty:
            linie.append(f"ZNALEZIONO BEZPOŚREDNIO:\nArtykuł: {url}")
            linie += [f"Post FB: {p}" for p in posty]
            linie.append("-" * 50)
    if wyniki_dopasowane:
        linie += ["", "=" * 50, f"DOPASOWANIA PO SŁOWNICTWIE (artykułów: {len(art_z_dop)})",
                  "=" * 50, ""]
        for a, fb, w in sorted(wyniki_dopasowane, key=lambda x: (-x[2], x[0])):
            linie += [f"DOPASOWANO PO TREŚCI (trafione słowa kluczowe: {w}):",
                      f"Artykuł: {a}", f"Post FB: {fb}"]
            if rekordy_art[a] > 1:
                linie.append(f"UWAGA: ten sam post występuje w {rekordy_art[a]} wersjach "
                             f"(osobne rekordy, np. różne strony)")
            if uzycia[fb] > 1:
                linie.append(f"UWAGA: ten post dopasowano do {uzycia[fb]} artykułów")
            linie.append("-" * 50)
    if brak:
        linie += ["", "LINKI ARTYKUŁÓW BEZ ŻADNEGO ZNALEZIONEGO POSTA:"] + [w[0] for w in brak]

    wiersze = [{"artykul": u, "post_fb": p, "metoda": "bezposrednia"}
               for u, _, posty in wyniki_standardowe for p in posty]
    wiersze += [{"artykul": a, "post_fb": f, "metoda": f"slownictwo (trafienia: {w})"}
                for a, f, w in wyniki_dopasowane]
    wiersze += [{"artykul": w[0], "post_fb": "", "metoda": "brak"} for w in brak]
    return "\n".join(linie), pd.DataFrame(wiersze, columns=["artykul", "post_fb", "metoda"])


def debug_txt(szczegoly: dict, ust: Ustawienia, ind: Indeks) -> str:
    n_krotkich = sum(1 for t in ind.teksty.values() if len(t) < 30)
    linie = ["DIAGNOSTYKA DOPASOWANIA PO SŁOWNICTWIE", "=" * 70,
             f"Kolumny z tekstem posta: {ind.kol}",
             f"Unikalnych postów: {len(ind.teksty)} (bez tekstu/krótkie: {n_krotkich})",
             f"Ustawienia: {ust}", "=" * 70, ""]
    for art, s in szczegoly.items():
        linie.append(f"ARTYKUŁ: {art}")
        linie.append("  klucze (idf)[w ilu postach]: " +
                     ", ".join(f"{k}({i})[{d}]" for k, i, d in s["klucze"]))
        if s["powod"]:
            linie.append(f"  ⚠ {s['powod']}")
        for c in s["kandydaci"]:
            dup = f" [x{c['duplikaty']}]" if c["duplikaty"] > 1 else ""
            linie.append(f"  {c['ok']} wynik {c['wynik']}, trafień {c['trafień']}{dup}: {c['post']}")
            linie.append(f"      wspólne: {c['wspólne']}")
            linie.append(f"      treść: {c['treść']}")
        if s["przydzial"]:
            linie.append("  -> PRZYDZIAŁ: " + " | ".join(s["przydzial"]))
        linie.append("")
    return "\n".join(linie)