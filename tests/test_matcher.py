import pandas as pd

from matcher import Ustawienia, bez_ogonkow, dopasuj, klucz, przygotuj_indeks


def _df(wiersze):
    return pd.DataFrame(wiersze, columns=["Tytuł", "Opis", "Link bezpośredni"])


def test_ogonki():
    assert bez_ogonkow("Łódź żółć") == "Lodz zolc"


def test_klucz():
    assert klucz("dach") == "dach"
    assert klucz("szklane") == "szklan"


def test_duplikaty_na_dwoch_stronach_to_osobne_rekordy():
    tekst = "Trzy pustaki AKU, trzy różne konstrukcje. Gęstość i zużycie."
    a, b = "https://www.facebook.com/Budomisja/posts/pfbidA", "https://www.facebook.com/BudujemyDom/posts/pfbidB"
    wiersze = [(None, tekst, a), (None, tekst, b)]
    wiersze += [(None, f"Ogrodzenie fundament beton numer {i} brama", f"https://fb/x{i}")
                for i in range(20)]
    ind = przygotuj_indeks(_df(wiersze))
    art = "https://x.pl/porady/1-trzy-pustaki-aku-rozne-konstrukcje"
    wyniki, _ = dopasuj(ind, [art], Ustawienia())
    assert {w[1] for w in wyniki} == {a, b}


def test_brak_dopasowania_gdy_zero_wspolnych_slow():
    ind = przygotuj_indeks(_df([(None, "Zupełnie inny temat o kotach", "https://fb/1")]))
    wyniki, sz = dopasuj(ind, ["https://x.pl/porady/2-gonty-bitumiczne-na-dachu"], Ustawienia())
    assert wyniki == []
    assert sz["https://x.pl/porady/2-gonty-bitumiczne-na-dachu"]["powod"]
