# Mapa dla rolnika – wersja w Pythonie (Streamlit)

Całość napisana w Pythonie, bez własnego JavaScriptu i CSS.

| Plik / folder | Co robi |
|---|---|
| `app.py` | aplikacja Streamlit: mapa, wybór warstwy, legenda, dane po kliknięciu |
| `rolnik_warstwy.py` | wczytywanie warstw, kolorowanie, odczyt wartości w punkcie |
| `rolnik_pogoda.py` | dane na żywo z Open-Meteo (ERA5-Land + prognoza) i ocena gotowości do siewu |
| `requirements.txt` | biblioteki aplikacji (instaluje je Streamlit Cloud) |
| `skrypty/` | codzienne liczenie warstw dla całej Polski (Landsat 8/9, ERA5-Land, SoilGrids) |
| `skrypty/requirements.txt` | biblioteki skryptów (instaluje je GitHub Actions) |
| `.github/workflows/dane.yml` | codzienne uruchamianie skryptów i publikacja warstw na GitHub Pages |

## Jak to działa

1. GitHub Actions codziennie liczy warstwy (`skrypty/`) i publikuje je na GitHub Pages
   (`https://LOGIN.github.io/REPOZYTORIUM/meta.json` + pliki PNG).
2. Aplikacja `app.py` na Streamlit Community Cloud wczytuje te warstwy i pokazuje je na mapie.
3. Po kliknięciu w mapę aplikacja (Python, biblioteka `requests`) pobiera na żywo dane z Open-Meteo.

## Uruchomienie u siebie (opcjonalnie)

```
pip install -r requirements.txt
streamlit run app.py
```

Dane: Landsat 8/9 – USGS; ERA5-Land – Copernicus Climate Change Service / ECMWF; Open-Meteo (CC BY 4.0,
użycie niekomercyjne); SoilGrids – ISRIC (CC BY 4.0).
