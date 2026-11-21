"""
Warstwy mapy: wczytywanie (z internetu albo z dysku), kolorowanie i odczyt wartości w punkcie.

Każda warstwa to 8-bitowy PNG w EPSG:3857 (robią je skrypty z folderu skrypty/):
  0 = brak danych, 1..255 = wartość przeskalowana liniowo z zakresu [min, max] z meta.json.
"""
import base64
import io
import json
import math
import os
import urllib.request

import matplotlib
import numpy as np
from PIL import Image

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

R = 6378137.0

PALETY = {
    "ndvi": ["#8c510a", "#d8b365", "#f6e8c3", "#c7e9a0", "#7fc97f", "#1a9641", "#00441b"],
    "ndwi": ["#8c510a", "#dfc27d", "#f6f6f6", "#9ecae1", "#3182bd", "#08306b"],
    "nddi": ["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c", "#67000d"],
    "temperatura": ["#313695", "#4575b4", "#74add1", "#e0f3f8", "#ffffbf", "#fee090", "#f46d43", "#a50026"],
    "wilgotnosc": ["#8c510a", "#dfc27d", "#c7eae5", "#5ab4ac", "#01665e", "#003c30"],
    "opady": ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
    "porowatosc": ["#fde725", "#7ad151", "#22a884", "#2a788e", "#414487", "#440154"],
    "szara": ["#000000", "#ffffff"],
    "kategorie_gleba": ["#fff7bc", "#fee391", "#fec44f", "#c2a45a", "#d9c7a0", "#e8dccb",
                        "#d6604d", "#b2654a", "#a6761d", "#e7298a", "#9e6ab8", "#6a3d9a"],
}


# ------------------------------------------------------------------ wczytywanie

def _czytaj(adres, plik):
    """Bajty pliku z adresu internetowego (GitHub Pages) albo z folderu na dysku."""
    if adres.startswith(("http://", "https://")):
        url = adres.rstrip("/") + "/" + plik
        with urllib.request.urlopen(url, timeout=60) as odp:
            return odp.read()
    with open(os.path.join(adres, plik), "rb") as f:
        return f.read()


def wczytaj_meta(adres):
    return json.loads(_czytaj(adres, "meta.json").decode("utf-8"))


def wczytaj_warstwe(adres, plik):
    """Tablica uint8 (wiersze x kolumny) z wartościami 0..255."""
    return np.array(Image.open(io.BytesIO(_czytaj(adres, plik))).convert("L"))


# ------------------------------------------------------------------ kolory

def _hex(c):
    return [int(c[i:i + 2], 16) for i in (1, 3, 5)]


def tablica_kolorow(w):
    """256 kolorów RGBA: indeks = wartość z PNG (0 = przezroczysty)."""
    lut = np.zeros((256, 4), dtype=np.uint8)
    pal = PALETY.get(w["paleta"], PALETY["szara"])
    if w.get("kategorie"):
        for i in range(1, len(w["kategorie"]) + 1):
            lut[i] = _hex(pal[(i - 1) % len(pal)]) + [255]
        return lut
    stopy = np.array([_hex(c) for c in pal], dtype=float)
    t = np.linspace(0, len(stopy) - 1, 255)          # dla wartości 1..255
    j = np.minimum(t.astype(int), len(stopy) - 2)
    f = (t - j)[:, None]
    lut[1:, :3] = np.round(stopy[j] + f * (stopy[j + 1] - stopy[j])).astype(np.uint8)
    lut[1:, 3] = 255
    return lut


def obraz_png_base64(q, w):
    """Kolorowy obraz warstwy jako adres data:image/png (do folium.ImageOverlay)."""
    rgba = tablica_kolorow(w)[q]
    bufor = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(bufor, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(bufor.getvalue()).decode("ascii")


def legenda(w):
    """Rysunek matplotlib z legendą warstwy."""
    pal = PALETY.get(w["paleta"], PALETY["szara"])
    jednostka = f" [{w['jednostka']}]" if w.get("jednostka") else ""
    if w.get("kategorie"):
        fig, ax = plt.subplots(figsize=(3.2, 0.26 * len(w["kategorie"]) + 0.2))
        ax.axis("off")
        ax.legend(handles=[Patch(facecolor=pal[i % len(pal)], edgecolor="#888", label=k)
                           for i, k in enumerate(w["kategorie"])],
                  loc="upper left", frameon=False, fontsize=8, handlelength=1.2)
        return fig
    fig, ax = plt.subplots(figsize=(3.2, 0.55))
    paleta = LinearSegmentedColormap.from_list("p", pal)
    ax.imshow(np.linspace(0, 1, 256)[None, :], aspect="auto", cmap=paleta,
              extent=[w["min"], w["max"], 0, 1])
    ax.set_yticks([])
    ax.tick_params(labelsize=8)
    ax.set_title(w["nazwa"] + jednostka, fontsize=8.5, loc="left")
    fig.tight_layout(pad=0.3)
    return fig


# ------------------------------------------------------------------ odczyt w punkcie

def do_merkatora(lat, lon):
    return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R


def wartosc_w_punkcie(q, w, siatka, lat, lon):
    """Wartość warstwy w punkcie: liczba, nazwa kategorii albo None (brak danych)."""
    x, y = do_merkatora(lat, lon)
    kol = int((x - siatka["xmin"]) // siatka["piksel_m"])
    wiersz = int((siatka["ymax"] - y) // siatka["piksel_m"])
    if not (0 <= wiersz < q.shape[0] and 0 <= kol < q.shape[1]):
        return None
    v = int(q[wiersz, kol])
    if v == 0:
        return None
    if w.get("kategorie"):
        return w["kategorie"][v - 1]
    return w["min"] + (v - 1) / 254 * (w["max"] - w["min"])
