# Dopasowanie postów FB do artykułów

Aplikacja Streamlit: wgrywasz CSV z Facebooka i listę linków do artykułów, a aplikacja
znajduje powiązane posty (najpierw po linku/ID w treści, potem po słownictwie).

## Uruchomienie lokalne
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # ustaw APP_PASSWORD
streamlit run app.py
```
(Bez hasła lokalnie: `ALLOW_NO_PASSWORD=1 streamlit run app.py`.)

## Wdrożenie na Streamlit Community Cloud
1. Utwórz **prywatne** repozytorium na GitHubie i wypchnij pliki.
2. share.streamlit.io -> *New app* -> wybierz repo, branch `main`, plik `app.py`.
3. *Advanced settings* -> *Secrets*:  `APP_PASSWORD = "twoje-haslo"`  (Python 3.11 lub 3.12).
4. W ustawieniach aplikacji (*Sharing*) ogranicz dostęp do wskazanych adresów e-mail.

## Dane
Pliki z Facebooka zawierają statystyki (m.in. szacowane dochody). **Nie commituj ich**
(`.gitignore` blokuje `*.csv`). Aplikacja przetwarza pliki w pamięci i ich nie zapisuje.

## Struktura
- `app.py`: interfejs, hasło, suwaki, wyniki, pobieranie
- `matcher.py`: logika dopasowania (bez Streamlita)
- `tests/`: testy (`pytest`)