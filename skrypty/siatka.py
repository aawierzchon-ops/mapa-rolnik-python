"""
Wspólna siatka mapy dla całej Polski i zapis warstw.

Każda warstwa to 8-bitowy PNG w skali szarości na siatce EPSG:3857 (ten sam układ,
co podkład w Leaflet, więc warstwy idealnie się pokrywają):
  0       = brak danych
  1..255  = wartość przeskalowana liniowo z zakresu [min, max]
Do tego plik meta_<źródło>.json z opisem warstw; na końcu łączymy je w meta.json.

Uruchomienie samodzielne (łączenie opisów):
  python skrypty/siatka.py --polacz _dane
"""
import argparse
import glob
import json
import math
import os

import numpy as np
from PIL import Image
from rasterio.transform import from_origin

CRS_MAPY = "EPSG:3857"
BBOX_WGS = (14.0, 48.9, 24.3, 55.0)   # lon_min, lat_min, lon_max, lat_max (Polska z zapasem)
PIKSEL_M = 800.0                      # metry w EPSG:3857, czyli ok. 500 m w terenie na szer. 52°
R = 6378137.0


def _merc(lon, lat):
    return (math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R)


def _wgs(x, y):
    return (math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2))


def siatka():
    x0, y0 = _merc(BBOX_WGS[0], BBOX_WGS[1])
    x1, y1 = _merc(BBOX_WGS[2], BBOX_WGS[3])
    xmin = math.floor(x0 / PIKSEL_M) * PIKSEL_M
    ymin = math.floor(y0 / PIKSEL_M) * PIKSEL_M
    xmax = math.ceil(x1 / PIKSEL_M) * PIKSEL_M
    ymax = math.ceil(y1 / PIKSEL_M) * PIKSEL_M
    szer = int(round((xmax - xmin) / PIKSEL_M))
    wys = int(round((ymax - ymin) / PIKSEL_M))
    (lon_w, lat_s), (lon_e, lat_n) = _wgs(xmin, ymin), _wgs(xmax, ymax)
    return {
        "crs": CRS_MAPY,
        "szer": szer, "wys": wys,
        "transform": from_origin(xmin, ymax, PIKSEL_M, PIKSEL_M),
        "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax, "piksel_m": PIKSEL_M,
        # narożniki dla L.imageOverlay: [[płd, zach], [płn, wsch]]
        "granice_wgs": [[lat_s, lon_w], [lat_n, lon_e]],
    }


def pusta(s, wartosc=np.nan, dtype="float32"):
    return np.full((s["wys"], s["szer"]), wartosc, dtype=dtype)


def zapisz_warstwe(katalog, id_, dane, *, nazwa, jednostka, vmin, vmax, paleta, grupa,
                   opis="", data="", ukryta=False, kategorie=None, miejsca=2):
    """Zapisuje warstwę jako PNG i zwraca jej opis do meta.json.

    kategorie: lista nazw dla warstw kategorycznych (wartości 1..N w `dane`, 0/NaN = brak).
    """
    os.makedirs(katalog, exist_ok=True)
    dane = np.asarray(dane, dtype="float64")
    braki = ~np.isfinite(dane)
    if kategorie:
        q = np.where(braki, 0, np.clip(np.nan_to_num(dane), 0, 255)).astype("uint8")
    else:
        skala = (np.clip(np.nan_to_num(dane, nan=vmin), vmin, vmax) - vmin) / (vmax - vmin)
        q = (np.round(skala * 254) + 1).astype("uint8")
        q[braki] = 0
    Image.fromarray(q, mode="L").save(os.path.join(katalog, f"{id_}.png"), optimize=True)
    pokrycie = float((q > 0).mean())
    print(f"  zapisano {id_}.png ({q.shape[1]}x{q.shape[0]}, pokrycie {100 * pokrycie:.1f}%)")
    return {
        "id": id_, "plik": f"{id_}.png", "nazwa": nazwa, "jednostka": jednostka,
        "min": vmin, "max": vmax, "paleta": paleta, "grupa": grupa, "opis": opis,
        "data": data, "ukryta": ukryta, "kategorie": kategorie, "miejsca": miejsca,
        "pokrycie": round(pokrycie, 4),
    }


def zapisz_meta(katalog, zrodlo, warstwy, **dodatkowe):
    os.makedirs(katalog, exist_ok=True)
    with open(os.path.join(katalog, f"meta_{zrodlo}.json"), "w", encoding="utf-8") as f:
        json.dump({"zrodlo": zrodlo, "warstwy": warstwy, **dodatkowe}, f, ensure_ascii=False, indent=1)


def polacz_meta(katalog):
    s = siatka()
    from datetime import datetime, timezone
    wynik = {"wersja": datetime.now(timezone.utc).strftime("%Y%m%d%H%M"),
             "siatka": {k: s[k] for k in ("szer", "wys", "xmin", "ymin", "xmax", "ymax", "piksel_m", "granice_wgs")},
             "zrodla": {}, "warstwy": []}
    for plik in sorted(glob.glob(os.path.join(katalog, "meta_*.json"))):
        with open(plik, encoding="utf-8") as f:
            m = json.load(f)
        wynik["warstwy"].extend(m.pop("warstwy"))
        wynik["zrodla"][m.pop("zrodlo")] = m
    with open(os.path.join(katalog, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(wynik, f, ensure_ascii=False, indent=1)
    print(f"meta.json: {len(wynik['warstwy'])} warstw z {len(wynik['zrodla'])} źródeł")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--polacz", required=True, help="katalog z plikami meta_*.json")
    polacz_meta(p.parse_args().polacz)
