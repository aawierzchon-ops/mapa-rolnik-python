"""
Mapa dla rolnika - aplikacja Streamlit (całość w Pythonie).

  - kolorowe warstwy dla całej Polski: Landsat 8/9 (NDVI, NDWI, NDDI, temperatura powierzchni),
    ERA5-Land (temperatura i wilgotność gleby, opady), gleba (typ, porowatość),
  - kliknięcie w mapę: wartości warstw w tym punkcie + dane na żywo z Open-Meteo
    (ERA5-Land i prognoza 7 dni) + ocena gotowości do siewu.

Warstwy liczą codziennie skrypty z folderu skrypty/ (GitHub Actions) i publikują je na GitHub Pages.

Uruchomienie u siebie:  streamlit run app.py
"""
import os

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import rolnik_pogoda as P
import rolnik_warstwy as W

# ======================================================================================
# ADRES DANYCH - wpisz tu adres swojej strony GitHub Pages (Settings -> Pages),
# np. "https://jankowalska.github.io/mapa-rolnik/". Może to być też folder na dysku.
ADRES_DANYCH = os.environ.get("ROLNIK_DANE", "https://TWOJLOGIN.github.io/NAZWA-REPOZYTORIUM/")
# ======================================================================================

st.set_page_config(page_title="Mapa dla rolnika", page_icon="🌱", layout="wide")

STATUSY = {"gotowe": "🟢 można siać", "wkrotce": "🟡 wkrótce", "czekaj": "⚪ za zimno", "za_mokro": "🔵 za mokro"}
KOLEJNOSC_GRUP = ["Landsat 8/9", "ERA5-Land", "Gleba"]
IKONY_GRUP = {"Landsat 8/9": "🛰️", "ERA5-Land": "🌡️", "Gleba": "🟫"}


# ------------------------------------------------------------------ dane (z pamięcią podręczną)

@st.cache_data(ttl=1800, show_spinner="Wczytywanie opisu warstw…")
def meta():
    return W.wczytaj_meta(ADRES_DANYCH)


@st.cache_data(max_entries=20, show_spinner=False)
def warstwa(plik, wersja):          # `wersja` zmienia się po każdej aktualizacji danych
    return W.wczytaj_warstwe(ADRES_DANYCH, plik)


@st.cache_data(max_entries=20, show_spinner="Kolorowanie warstwy…")
def obraz(id_, wersja):
    w = opis(id_)
    return W.obraz_png_base64(warstwa(w["plik"], wersja), w)


@st.cache_data(ttl=600, show_spinner="Pobieranie danych na żywo z Open-Meteo…")
def na_zywo(lat, lon):
    return P.dane_na_zywo(lat, lon)


def opis(id_):
    return next(w for w in meta()["warstwy"] if w["id"] == id_)


def tekst(w, v):
    if v is None:
        return "–"
    if isinstance(v, str):
        return v
    liczba = f"{v:.{w.get('miejsca', 2)}f}".replace(".", ",")
    return f"{liczba} {w['jednostka']}".strip()


def liczba(v, miejsca=1, jednostka=""):
    return "–" if v is None else f"{v:.{miejsca}f}".replace(".", ",") + (f" {jednostka}" if jednostka else "")


def dzien_pl(d):
    dni = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]
    dt = pd.Timestamp(d)
    return f"{dni[dt.dayofweek]} {dt.day}.{dt.month:02d}"


# ------------------------------------------------------------------ start

st.title("🌱 Mapa dla rolnika")
if "TWOJLOGIN" in ADRES_DANYCH:
    st.error("Uzupełnij ADRES_DANYCH na początku pliku app.py adresem swojej strony GitHub Pages.")
    st.stop()
try:
    M = meta()
except Exception as e:
    st.error(f"Nie udało się wczytać danych z {ADRES_DANYCH} ({e}). Sprawdź, czy workflow na GitHubie "
             "zakończył się na zielono i czy adres jest poprawny.")
    st.stop()

wersja = M.get("wersja", "")
siatka = M["siatka"]
widoczne = sorted((w for w in M["warstwy"] if not w.get("ukryta")),
                  key=lambda w: KOLEJNOSC_GRUP.index(w["grupa"]) if w["grupa"] in KOLEJNOSC_GRUP else 99)

# ------------------------------------------------------------------ panel boczny

with st.sidebar:
    st.header("Warstwy")
    opcje = ["brak"] + [w["id"] for w in widoczne]
    wybor = st.radio("Pokaż na mapie", opcje,
                     format_func=lambda i: "brak warstwy" if i == "brak"
                     else f"{IKONY_GRUP.get(opis(i)['grupa'], '')} {opis(i)['nazwa']}")
    przezroczystosc = st.slider("Krycie warstwy", 0.2, 1.0, 0.75, 0.05)
    if wybor != "brak":
        w = opis(wybor)
        rys = W.legenda(w)
        st.pyplot(rys, width="stretch")
        W.plt.close(rys)
        if w.get("opis"):
            st.caption(w["opis"])
        if w.get("data"):
            st.caption(f"📅 {w['data']}")
        if w.get("pokrycie", 1) == 0:
            st.warning("Ta warstwa nie ma jeszcze danych (np. brak bezchmurnych zdjęć).")
    st.divider()
    st.caption("Dane: Landsat 8/9 – USGS · ERA5-Land – Copernicus/ECMWF przez Open-Meteo (CC BY 4.0) · "
               "gleba – SoilGrids/ISRIC. Progi temperatur do siewu są orientacyjne.")

# ------------------------------------------------------------------ mapa

lewa, prawa = st.columns([3, 2], gap="medium")

with lewa:
    mapa = folium.Map(location=[52.0, 19.3], zoom_start=6, tiles="OpenStreetMap", control_scale=True)
    # warstwy zmieniane bez przeładowania mapy (widok zostaje tam, gdzie był)
    grupa_warstwy = folium.FeatureGroup(name="warstwa")
    if wybor != "brak":
        folium.raster_layers.ImageOverlay(obraz(wybor, wersja), bounds=siatka["granice_wgs"],
                                          opacity=przezroczystosc, pixelated=True).add_to(grupa_warstwy)
    grupa_punktu = folium.FeatureGroup(name="punkt")
    klik = st.session_state.get("klik")
    if klik:
        folium.Marker([klik["lat"], klik["lng"]], tooltip="Wybrany punkt").add_to(grupa_punktu)

    wynik = st_folium(mapa, key="mapa", height=640, use_container_width=True, pixelated=True,
                      feature_group_to_add=[grupa_warstwy, grupa_punktu], returned_objects=["last_clicked"])
    nowy = (wynik or {}).get("last_clicked")
    if nowy and nowy != klik:
        st.session_state["klik"] = nowy
        st.rerun()

# ------------------------------------------------------------------ dane dla klikniętego punktu

with prawa:
    if not klik:
        st.info("👈 Kliknij w dowolne miejsce na mapie, aby zobaczyć dane dla tego punktu.")
        st.stop()

    lat, lon = klik["lat"], klik["lng"]
    st.subheader(f"📍 {lat:.4f}° N, {lon:.4f}° E")
    wart = {w["id"]: W.wartosc_w_punkcie(warstwa(w["plik"], wersja), w, siatka, lat, lon)
            for w in M["warstwy"] if w.get("pokrycie", 0) > 0}

    def wiersze(ids):
        return pd.DataFrame([(opis(i)["nazwa"], tekst(opis(i), wart.get(i))) for i in ids if i in wart],
                            columns=["", "wartość"])

    zrodla = M.get("zrodla", {})
    if "landsat" in zrodla:
        wiek = wart.get("landsat_wiek")
        data_zdj = (pd.Timestamp(zrodla["landsat"]["data_odniesienia"]) - pd.Timedelta(days=round(wiek))).date() \
            if wiek is not None else None
        st.markdown(f"**🛰️ Landsat 8/9** – {'zdjęcie z ' + str(data_zdj) if data_zdj else 'brak bezchmurnego zdjęcia'}")
        st.dataframe(wiersze(["ndvi", "ndwi", "nddi", "lst"]), hide_index=True, width="stretch")

    if "gleba" in zrodla:
        st.markdown("**🟫 Gleba** (SoilGrids, 0–30 cm)")
        df = wiersze(["gleba_klasa", "porowatosc", "gestosc"])
        if wart.get("piasek") is not None and wart.get("il") is not None:
            p, i = wart["piasek"], wart["il"]
            df.loc[len(df)] = ["Piasek / pył / ił", f"{p:.0f} / {max(0, 100 - p - i):.0f} / {i:.0f} %"]
        st.dataframe(df, hide_index=True, width="stretch")

    st.markdown("**⏱️ Na żywo** (Open-Meteo)")
    try:
        o = na_zywo(round(lat, 3), round(lon, 3))
    except Exception as e:
        st.error(f"Nie udało się pobrać danych na żywo: {e}")
        st.stop()

    k1, k2, k3 = st.columns(3)
    k1.metric("Powierzchnia", liczba(o["t_pow"], 1, "°C"), help="Temperatura powierzchni gruntu w tej godzinie (prognoza).")
    k2.metric("Gleba (ERA5)", liczba(o["t_era5"], 1, "°C"),
              help=f"Temperatura gleby 0–7 cm, ERA5-Land, średnia z 3 dni do {o['era5_do']}.")
    k3.metric("Wilgotność", liczba(o["wilg"], 2), help="Wilgotność gleby dziś [m³/m³].")
    if o["era5_blad"]:
        st.warning(f"ERA5-Land chwilowo niedostępne: {o['era5_blad']}")

    st.markdown("**🌱 Gotowość do siewu**")
    st.dataframe(pd.DataFrame([{
        "uprawa": f"{u['uprawa']} (≥{u['prog']}°C)",
        "stan": STATUSY[u["status"]] + (f" od {dzien_pl(u['siew_od'])}" if u["status"] == "wkrotce" else ""),
    } for u in o["uprawy"]]), hide_index=True, width="stretch")
    st.caption("„Można siać” = gleba ciepła w ERA5-Land i przez 3 najbliższe dni prognozy.")

    st.markdown("**📈 Prognoza 7 dni**")
    prog = pd.DataFrame(o["dni"])
    if not prog.empty:
        prog["dzień"] = prog["dzien"].map(dzien_pl)
        rys, ax = W.plt.subplots(figsize=(4.6, 1.9))
        osX = prog["dzień"].str.replace(" ", "\n")
        ax.plot(osX, prog["gleba_6cm"], marker="o", color="#2e5e2a", label="gleba 6 cm")
        ax.bar(osX, prog["opad"], color="#6baed6", alpha=0.6, label="opad [mm]")
        for prog_t, styl in ((5, ":"), (10, "--")):
            ax.axhline(prog_t, color="#999", linestyle=styl, linewidth=0.8)
        ax.set_ylabel("°C / mm", fontsize=8)
        ax.tick_params(labelsize=7.5)
        ax.legend(fontsize=7.5, frameon=False, loc="upper left")
        ax.spines[["top", "right"]].set_visible(False)
        rys.tight_layout(pad=0.4)
        st.pyplot(rys, width="stretch")
        W.plt.close(rys)
        st.caption("Linie przerywane: progi 5 °C (zboża jare, groch) i 10 °C (kukurydza, soja).")
        st.dataframe(pd.DataFrame({
            "dzień": prog["dzień"],
            "gleba 6 cm": prog["gleba_6cm"].map(lambda v: liczba(v, 1, "°C")),
            "powietrze": [f"{a:.0f}…{b:.0f} °C" for a, b in zip(prog["powietrze_min"], prog["powietrze_max"])],
            "opad": prog["opad"].map(lambda v: liczba(v, 1, "mm")),
        }), hide_index=True, width="stretch")
