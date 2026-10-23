import hmac
import os
from dataclasses import asdict

import pandas as pd
import streamlit as st

import matcher as m

st.set_page_config(page_title="Dopasowanie postów FB do artykułów",
                   page_icon="🔗", layout="wide")


# ---------- dostęp ----------

def _haslo_z_secrets():
    try:
        return st.secrets["APP_PASSWORD"]
    except Exception:
        return None


def wymagaj_hasla():
    haslo = _haslo_z_secrets()
    if not haslo:
        if os.environ.get("ALLOW_NO_PASSWORD") == "1":   # tylko do pracy lokalnej
            return
        st.error("Aplikacja zablokowana: brak `APP_PASSWORD` w Secrets.")
        st.stop()
    if st.session_state.get("auth"):
        return
    with st.form("login"):
        wpisane = st.text_input("Hasło", type="password")
        if st.form_submit_button("Zaloguj"):
            if hmac.compare_digest(wpisane.encode(), str(haslo).encode()):
                st.session_state["auth"] = True
                st.rerun()
            else:
                st.error("Nieprawidłowe hasło.")
    st.stop()


# ---------- cache ----------

@st.cache_data(show_spinner="Wczytywanie CSV…", max_entries=3)
def wczytaj_csv_cached(data: bytes):
    return m.wczytaj_csv_bytes(data)


@st.cache_data(show_spinner="Budowanie indeksu postów…", max_entries=3)
def indeks_cached(df: pd.DataFrame):
    return m.przygotuj_indeks(df)


# ---------- UI ----------

wymagaj_hasla()
st.title("🔗 Dopasowanie postów z Facebooka do artykułów")
st.caption("Pliki są przetwarzane w pamięci i nie są zapisywane na serwerze.")

with st.sidebar:
    st.header("Ustawienia dopasowania")
    min_trafien = st.slider("Minimum wspólnych słów", 1, 5, 2)
    min_wynik = st.slider("Minimalny wynik", 0.05, 1.0, 0.30, 0.05)
    min_wynik_2 = st.slider("Wynik wymagany przy 2 trafieniach", 0.05, 1.0, 0.45, 0.05)
    min_przewaga = st.slider("Minimalna przewaga nad drugim (1.0 = wyłączone)", 1.0, 2.0, 1.2, 0.05)
    potega_idf = st.slider("Waga słów rzadkich (potęga IDF)", 1.0, 3.0, 2.0, 0.5)
    unikalne = st.checkbox("Jedna treść tylko do jednego artykułu", value=True)
    ust = m.Ustawienia(min_trafien, min_wynik, min_wynik_2, min_przewaga,
                       potega_idf, unikalne, 5)

c1, c2, c3 = st.columns(3)
csv_file = c1.file_uploader("1. CSV z Facebooka", type=["csv"])
art_file = c2.file_uploader("2. Linki do artykułów (.txt/.csv)", type=["txt", "csv"])
posty_file = c3.file_uploader("3. Lista postów (opcjonalnie, zawęża wyszukiwanie)",
                              type=["txt", "csv"])

if st.button("Szukaj", type="primary", disabled=not (csv_file and art_file)):
    try:
        df = wczytaj_csv_cached(csv_file.getvalue())
        linki = m.wczytaj_linki_bytes(art_file.getvalue())
        if not linki:
            st.error("W pliku z artykułami nie znaleziono żadnych linków.")
            st.stop()
        brak_w_csv = []
        if posty_file:
            lista = m.wczytaj_linki_bytes(posty_file.getvalue())
            if not lista:
                st.error("W pliku z listą postów nie znaleziono żadnych linków.")
                st.stop()
            df, brak_w_csv = m.zawez_do_listy(df, lista)
            if df.empty:
                st.error("Żaden post z listy nie występuje w CSV.")
                st.stop()

        wyniki_std = m.szukaj_bezposrednio(df, linki)
        nieznalezione = [w[0] for w in wyniki_std if not w[2]]
        ind = indeks_cached(df)
        wyniki_dop, szczegoly = m.dopasuj(ind, nieznalezione, ust)
        raport_txt, raport_df = m.zbuduj_raport(wyniki_std, wyniki_dop)
        st.session_state["wynik"] = {
            "ust": asdict(ust), "brak_w_csv": brak_w_csv,
            "n_posty": len(ind.teksty), "n_pustych": sum(1 for t in ind.teksty.values() if len(t) < 30),
            "wyniki_std": wyniki_std, "wyniki_dop": wyniki_dop,
            "szczegoly": szczegoly, "raport_txt": raport_txt, "raport_df": raport_df,
            "debug_txt": m.debug_txt(szczegoly, ust, ind),
        }
    except ValueError as e:
        st.error(str(e))
        st.stop()

w = st.session_state.get("wynik")
if w:
    if w["ust"] != asdict(ust):
        st.warning("Ustawienia zmieniły się od ostatniego wyszukiwania. Kliknij „Szukaj\", żeby przeliczyć.")
    if w["brak_w_csv"]:
        with st.expander(f"⚠ {len(w['brak_w_csv'])} postów z listy nie ma w CSV"):
            st.write("\n".join(w["brak_w_csv"]))

    art_dop = {a for a, _, _ in w["wyniki_dop"]}
    brak = [x[0] for x in w["wyniki_std"] if not x[2] and x[0] not in art_dop]
    bezposr = sum(1 for x in w["wyniki_std"] if x[2])
    k = st.columns(5)
    k[0].metric("Artykułów", len(w["wyniki_std"]))
    k[1].metric("Bezpośrednio", bezposr)
    k[2].metric("Po słownictwie", len(art_dop))
    k[3].metric("Rekordów (z duplikatami)", len(w["wyniki_dop"]))
    k[4].metric("Bez posta", len(brak))
    st.caption(f"Postów w CSV: {w['n_posty']}, w tym bez tekstu lub krótkich: {w['n_pustych']} "
               "(nie da się ich dopasować po słowach).")

    t1, t2, t3, t4 = st.tabs(["Wyniki", "Bez posta", "Diagnostyka", "Pobierz"])
    with t1:
        st.dataframe(
            w["raport_df"], use_container_width=True, hide_index=True,
            column_config={
                "artykul": st.column_config.LinkColumn("Artykuł"),
                "post_fb": st.column_config.LinkColumn("Post FB"),
                "metoda": "Metoda",
            })
    with t2:
        if brak:
            st.write("\n".join(brak))
        else:
            st.success("Wszystkie artykuły mają przypisany post.")
    with t3:
        if not w["szczegoly"]:
            st.info("Wszystkie artykuły znaleziono bezpośrednio, brak diagnostyki.")
        else:
            wybrany = st.selectbox("Artykuł", list(w["szczegoly"].keys()))
            s = w["szczegoly"][wybrany]
            if s["powod"]:
                st.warning(s["powod"])
            if s["przydzial"]:
                st.success("Przydział: " + " | ".join(s["przydzial"]))
            if s["klucze"]:
                st.caption("Klucze ze sluga: " + ", ".join(
                    f"{kk} (idf {i}, w {d} postach)" for kk, i, d in s["klucze"]))
            if s["kandydaci"]:
                st.dataframe(pd.DataFrame(s["kandydaci"]), use_container_width=True,
                             hide_index=True)
    with t4:
        st.download_button("Raport (.txt)", w["raport_txt"], "wyniki_linkow_fb.txt", "text/plain")
        st.download_button("Wyniki (.csv)", w["raport_df"].to_csv(index=False, sep=";").encode("utf-8-sig"),
                           "wyniki_linkow_fb.csv", "text/csv")
        st.download_button("Diagnostyka (.txt)", w["debug_txt"], "wyniki_linkow_fb_debug.txt", "text/plain")