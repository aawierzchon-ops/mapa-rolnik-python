#!/usr/bin/env python3
"""
Mapa NDVI, NDWI, NDDI i temperatury powierzchni (LST) dla całej Polski
z Landsat 8/9 Collection 2 Level-2 (te same produkty USGS co w EarthExplorer,
czytane z katalogu STAC Microsoft Planetary Computer - bez konta).

Metoda (kompozyt "najnowszy bezchmurny piksel"):
  1. Szukamy scen L8/L9 z ostatnich N dni z zachmurzeniem sceny < progu (domyślnie 10%).
  2. Od najnowszej: maskę chmur QA_PIXEL czytamy w pełnej rozdzielczości (30 m) i liczymy,
     jaki ułamek każdego bloku 16x16 px (480 m) jest czysty. Pasma czytamy z wbudowanych
     podglądów COG (480 m), więc nie pobieramy całych scen.
  3. Piksel mapy (ok. 500 m) dostaje wartość z najnowszej sceny, w której był czysty.

  NDVI = (NIR - RED) / (NIR + RED)          B5, B4
  NDWI = (NIR - SWIR1) / (NIR + SWIR1)      B5, B6   (Gao, 1996)
  NDDI = (NDVI - NDWI) / (NDVI + NDWI)      (Gu i in., 2007) - tylko tam, gdzie NDVI >= 0,2
  LST  = ST_B10 * 0,00341802 + 149 - 273,15 [°C]

Wymagania: pip install -r requirements.txt
Przykład:  python skrypty/landsat_mapa.py --wyjscie _dane --chmury 10 --dni 90
"""
import argparse
import os
import sys
import time
from datetime import date, timedelta

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(__file__))
import siatka as S  # noqa: E402

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
KOLEKCJA = "landsat-c2-l2"
SATELITY = ["landsat-8", "landsat-9"]
PASMA = {"red": "red", "nir": "nir08", "swir": "swir16", "lst": "lwir11", "qa": "qa_pixel"}

SR_SKALA, SR_OFFSET = 0.0000275, -0.2
ST_SKALA, ST_OFFSET = 0.00341802, 149.0
# QA_PIXEL - odrzucamy: 0 wypełnienie, 1 chmura poszerzona, 2 cirrus, 3 chmura, 4 cień, 5 śnieg, 7 woda
QA_ODRZUC = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 7)

F = 16               # 16 x 30 m = 480 m - blok, z którego liczymy jeden piksel
MIN_CZYSTE = 0.8     # min. udział czystych pikseli 30 m w bloku
NDVI_MIN_NDDI = 0.2  # poniżej - goła gleba, NDDI nie ma sensu


def szukaj_scen(bbox, od, do, chmury, maks):
    import planetary_computer
    import pystac_client

    katalog = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    wyniki = katalog.search(collections=[KOLEKCJA], bbox=bbox, datetime=f"{od}/{do}",
                            query={"eo:cloud_cover": {"lt": chmury}, "platform": {"in": SATELITY}},
                            max_items=1000)
    sceny = []
    for it in wyniki.items():
        if all(k in it.assets for k in PASMA.values()):
            sceny.append({"id": it.id, "data": it.datetime.date().isoformat(),
                          "satelita": it.properties.get("platform", ""),
                          "chmury": it.properties.get("eo:cloud_cover"),
                          "href": {n: it.assets[k].href for n, k in PASMA.items()}})
    sceny.sort(key=lambda s: s["data"], reverse=True)
    return sceny[:maks]


def czytaj_scene(scena):
    """Zwraca (słownik tablic 480 m, transform, crs) albo None."""
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES",
               GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_HTTP_MAX_RETRY="4", GDAL_HTTP_RETRY_DELAY="3")
    with rasterio.Env(**env):
        with rasterio.open(scena["href"]["qa"]) as q:
            h, w = q.height // F, q.width // F
            okno = Window(0, 0, w * F, h * F)
            qa = q.read(1, window=okno)                   # pełna rozdzielczość - poprawne bity
            crs = q.crs
            tr = q.transform * Affine.scale(F)
        bloki = lambda a: a.reshape(h, F, w, F).mean(axis=(1, 3))  # noqa: E731
        czyste = bloki(((qa & QA_ODRZUC) == 0).astype("float32"))
        wypelnienie = bloki((qa & 1).astype("float32"))
        del qa
        dane = {}
        for nazwa in ("red", "nir", "swir", "lst"):
            with rasterio.open(scena["href"][nazwa]) as src:
                dane[nazwa] = src.read(1, window=okno, out_shape=(h, w),
                                       resampling=Resampling.average).astype("float64")

    dobre = (czyste >= MIN_CZYSTE) & (wypelnienie == 0)
    for k in ("red", "nir", "swir", "lst"):
        dobre &= dane[k] > 0
    sr = {k: dane[k] * SR_SKALA + SR_OFFSET for k in ("red", "nir", "swir")}
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = (sr["nir"] - sr["red"]) / (sr["nir"] + sr["red"])
        ndwi = (sr["nir"] - sr["swir"]) / (sr["nir"] + sr["swir"])
    lst = dane["lst"] * ST_SKALA + ST_OFFSET - 273.15
    dobre &= np.isfinite(ndvi) & np.isfinite(ndwi) & (np.abs(ndvi) <= 1) & (np.abs(ndwi) <= 1)
    wynik = {k: np.where(dobre, v, np.nan).astype("float32") for k, v in
             (("ndvi", ndvi), ("ndwi", ndwi), ("lst", lst))}
    return wynik, tr, crs


def na_siatke(arr, tr, crs, s):
    out = S.pusta(s)
    reproject(arr, out, src_transform=tr, src_crs=crs, src_nodata=np.nan,
              dst_transform=s["transform"], dst_crs=s["crs"], dst_nodata=np.nan,
              resampling=Resampling.average)
    return out


def main():
    p = argparse.ArgumentParser(description="Kompozyt Landsat 8/9 dla Polski: NDVI, NDWI, NDDI, LST.")
    p.add_argument("--wyjscie", required=True, help="katalog na warstwy PNG i meta")
    p.add_argument("--chmury", type=float, default=10, help="maks. zachmurzenie sceny w %% (domyślnie 10)")
    p.add_argument("--dni", type=int, default=90, help="ile dni wstecz (domyślnie 90)")
    p.add_argument("--maks-scen", type=int, default=250)
    a = p.parse_args()

    s = S.siatka()
    dzis = date.today()
    od = dzis - timedelta(days=a.dni)
    sceny = szukaj_scen(list(S.BBOX_WGS), od.isoformat(), dzis.isoformat(), a.chmury, a.maks_scen)
    print(f"Sceny L8/L9 z zachmurzeniem < {a.chmury}% z ostatnich {a.dni} dni: {len(sceny)}")

    kompozyt = {k: S.pusta(s) for k in ("ndvi", "ndwi", "lst")}
    wiek = S.pusta(s)  # ile dni przed dziś wykonano zdjęcie danego piksela
    t0 = time.time()
    for i, sc in enumerate(sceny, 1):
        puste = ~np.isfinite(kompozyt["ndvi"])
        if not puste.any():
            break
        try:
            dane, tr, crs = czytaj_scene(sc)
        except Exception as e:  # pojedyncza uszkodzona scena nie może zatrzymać całości
            print(f"  [{i}/{len(sceny)}] pomijam {sc['id']}: {e}")
            continue
        nowe = {k: na_siatke(v, tr, crs, s) for k, v in dane.items()}
        wstaw = puste & np.isfinite(nowe["ndvi"]) & np.isfinite(nowe["ndwi"])
        for k in kompozyt:
            kompozyt[k][wstaw] = nowe[k][wstaw]
        wiek[wstaw] = (dzis - date.fromisoformat(sc["data"])).days
        print(f"  [{i}/{len(sceny)}] {sc['data']} {sc['satelita']} chmury {sc['chmury']}%: "
              f"+{int(wstaw.sum())} px ({time.time() - t0:.0f} s)")

    ndvi, ndwi = kompozyt["ndvi"], kompozyt["ndwi"]
    with np.errstate(divide="ignore", invalid="ignore"):
        suma = ndvi + ndwi
        nddi = np.where((ndvi >= NDVI_MIN_NDDI) & (np.abs(suma) > 0.05), (ndvi - ndwi) / suma, np.nan)

    zakres = f"zdjęcia z {od.isoformat()} – {dzis.isoformat()}, zachmurzenie sceny < {a.chmury:g}%"
    W = a.wyjscie
    warstwy = [
        S.zapisz_warstwe(W, "ndvi", ndvi, nazwa="NDVI", jednostka="", vmin=-0.2, vmax=1.0,
                         paleta="ndvi", grupa="Landsat 8/9", data=zakres,
                         opis="Wskaźnik zieleni roślin. >0,6 gęsta, zdrowa roślinność; <0,2 goła gleba."),
        S.zapisz_warstwe(W, "ndwi", ndwi, nazwa="NDWI (wilgotność roślin)", jednostka="", vmin=-0.6, vmax=0.6,
                         paleta="ndwi", grupa="Landsat 8/9", data=zakres,
                         opis="Zawartość wody w roślinach i glebie (NIR–SWIR, Gao 1996). Niżej = suszej."),
        S.zapisz_warstwe(W, "nddi", nddi, nazwa="NDDI (susza)", jednostka="", vmin=-0.5, vmax=2.0,
                         paleta="nddi", grupa="Landsat 8/9", data=zakres,
                         opis="Wskaźnik suszy (Gu i in. 2007). Wyżej = większy stres wodny. Brak na gołej glebie."),
        S.zapisz_warstwe(W, "lst", kompozyt["lst"], nazwa="Temperatura powierzchni (Landsat)", jednostka="°C",
                         vmin=-20, vmax=45, paleta="temperatura", grupa="Landsat 8/9", data=zakres, miejsca=1,
                         opis="Temperatura powierzchni w chwili przelotu satelity (ok. 10:30)."),
        S.zapisz_warstwe(W, "landsat_wiek", wiek, nazwa="Wiek zdjęcia", jednostka="dni", vmin=0, vmax=254,
                         paleta="szara", grupa="Landsat 8/9", ukryta=True, miejsca=0),
    ]
    S.zapisz_meta(W, "landsat", warstwy, data_odniesienia=dzis.isoformat(), liczba_scen=len(sceny),
                  opis=zakres)


if __name__ == "__main__":
    main()
