#!/usr/bin/env python3
"""
Mapa gleb Polski z SoilGrids 2.0 (ISRIC, 250 m), warstwa 0-30 cm:
klasa uziarnienia wg USDA (polskie nazwy), porowatość ogólna, udział piasku i iłu,
gęstość objętościowa.

  porowatość = 1 - gęstość objętościowa / 2,65 g/cm³ (gęstość fazy stałej)

Gleba się nie zmienia - w workflow wynik trzymany jest w pamięci podręcznej
i liczony tylko raz.

Przykład:  python skrypty/gleba_mapa.py --wyjscie _dane
"""
import argparse
import os
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import reproject, transform_bounds
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S  # noqa: E402

URL = "/vsicurl/https://files.isric.org/soilgrids/latest/data/{zm}/{zm}_{gl}_mean.vrt"
GLEBOKOSCI = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}      # waga = miąższość warstwy
ZMIENNE = {"sand": 0.1, "silt": 0.1, "clay": 0.1, "bdod": 0.01}  # g/kg -> %, cg/cm³ -> g/cm³
GESTOSC_FAZY_STALEJ = 2.65

KLASY = ["piasek", "piasek gliniasty", "glina piaszczysta", "glina", "pył gliniasty", "pył",
         "glina piaszczysto-ilasta", "glina ilasta", "glina pylasto-ilasta", "ił piaszczysty",
         "ił pylasty", "ił"]


def klasy_usda(piasek, pyl, il):
    """Wektorowo: numer klasy 1..12 (kolejność jak KLASY) wg trójkąta USDA."""
    warunki = [
        pyl + 1.5 * il < 15,
        pyl + 2 * il < 30,
        ((il >= 7) & (il < 20) & (piasek > 52)) | ((il < 7) & (pyl < 50)),
        (il >= 7) & (il < 27) & (pyl >= 28) & (pyl < 50) & (piasek <= 52),
        ((pyl >= 50) & (il >= 12) & (il < 27)) | ((pyl >= 50) & (pyl < 80) & (il < 12)),
        (pyl >= 80) & (il < 12),
        (il >= 20) & (il < 35) & (pyl < 28) & (piasek > 45),
        (il >= 27) & (il < 40) & (piasek > 20) & (piasek <= 45),
        (il >= 27) & (il < 40) & (piasek <= 20),
        (il >= 35) & (piasek > 45),
        (il >= 40) & (pyl >= 40),
    ]
    return np.select(warunki, list(range(1, 12)), default=12)


def czytaj_na_siatke(url, s):
    with rasterio.open(url) as src:
        b = transform_bounds(s["crs"], src.crs, s["xmin"], s["ymin"], s["xmax"], s["ymax"], densify_pts=50)
        okno = from_bounds(*b, transform=src.transform).round_offsets(op="floor").round_lengths(op="ceil")
        dane = src.read(1, window=okno, boundless=True, fill_value=src.nodata if src.nodata is not None else 0)
        dane = dane.astype("float32")
        if src.nodata is not None:
            dane[dane == src.nodata] = np.nan
        out = S.pusta(s)
        reproject(dane, out, src_transform=src.window_transform(okno), src_crs=src.crs, src_nodata=np.nan,
                  dst_transform=s["transform"], dst_crs=s["crs"], dst_nodata=np.nan,
                  resampling=Resampling.average)
    return out


def main():
    p = argparse.ArgumentParser(description="Mapa gleb Polski z SoilGrids.")
    p.add_argument("--wyjscie", required=True)
    a = p.parse_args()
    s = S.siatka()

    wart = {}
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="5"):
        for zm, mnoznik in ZMIENNE.items():
            suma, wagi = S.pusta(s, 0.0), S.pusta(s, 0.0)
            for gl, waga in GLEBOKOSCI.items():
                print(f"SoilGrids {zm} {gl} ...")
                v = czytaj_na_siatke(URL.format(zm=zm, gl=gl), s) * mnoznik
                ok = np.isfinite(v)
                suma[ok] += v[ok] * waga
                wagi[ok] += waga
            wart[zm] = np.where(wagi > 0, suma / np.where(wagi > 0, wagi, 1), np.nan)

    razem = wart["sand"] + wart["silt"] + wart["clay"]
    ok = np.isfinite(razem) & (razem > 0) & np.isfinite(wart["bdod"])
    with np.errstate(invalid="ignore", divide="ignore"):
        piasek, pyl, il = (np.where(ok, 100 * wart[k] / razem, np.nan) for k in ("sand", "silt", "clay"))
    klasa = np.where(ok, klasy_usda(np.nan_to_num(piasek), np.nan_to_num(pyl), np.nan_to_num(il)), np.nan)
    bd = np.where(ok, wart["bdod"], np.nan)
    porowatosc = 100 * (1 - bd / GESTOSC_FAZY_STALEJ)

    W, opis = a.wyjscie, "SoilGrids 2.0 (ISRIC), średnia 0–30 cm"
    warstwy = [
        S.zapisz_warstwe(W, "gleba_klasa", klasa, nazwa="Typ gleby (uziarnienie USDA)", jednostka="",
                         vmin=1, vmax=12, paleta="kategorie_gleba", grupa="Gleba", kategorie=KLASY, data=opis,
                         opis="Klasa uziarnienia wg trójkąta USDA, z udziału piasku, pyłu i iłu."),
        S.zapisz_warstwe(W, "porowatosc", porowatosc, nazwa="Porowatość gleby", jednostka="%", vmin=25, vmax=65,
                         paleta="porowatosc", grupa="Gleba", data=opis, miejsca=1,
                         opis="Porowatość ogólna = 1 − gęstość objętościowa / 2,65 g/cm³."),
        S.zapisz_warstwe(W, "piasek", piasek, nazwa="Piasek", jednostka="%", vmin=0, vmax=100, paleta="szara",
                         grupa="Gleba", ukryta=True, miejsca=0),
        S.zapisz_warstwe(W, "il", il, nazwa="Ił", jednostka="%", vmin=0, vmax=100, paleta="szara",
                         grupa="Gleba", ukryta=True, miejsca=0),
        S.zapisz_warstwe(W, "gestosc", bd, nazwa="Gęstość objętościowa", jednostka="g/cm³", vmin=0.5, vmax=2.0,
                         paleta="szara", grupa="Gleba", ukryta=True, miejsca=2),
    ]
    S.zapisz_meta(W, "gleba", warstwy, opis=opis)


if __name__ == "__main__":
    main()
