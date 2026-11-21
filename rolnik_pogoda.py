"""
Dane na żywo dla jednego punktu z Open-Meteo:
  - ERA5-Land (Copernicus) - temperatura i wilgotność gleby z ostatnich dostępnych dni,
  - prognoza na 7 dni - temperatura powierzchni i gleby, wilgotność, powietrze, opady,
oraz ocena gotowości do siewu dla kilku upraw.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

STREFA = "Europe/Warsaw"
ARCHIWUM_URL = "https://archive-api.open-meteo.com/v1/archive"
PROGNOZA_URL = "https://api.open-meteo.com/v1/forecast"

# Minimalna temperatura gleby do siewu [°C] - wartości orientacyjne, do weryfikacji agronomicznej
UPRAWY = [("kukurydza", 10), ("soja", 10), ("słonecznik", 8), ("ziemniak", 8),
          ("burak cukrowy", 6), ("groch", 5), ("pszenica jara", 5), ("jęczmień jary", 5), ("owies", 5)]
PROG_ZA_MOKRO = 0.40   # m³/m³
DNI_STABILNIE = 3      # tyle kolejnych dni prognozy musi mieć glebę >= progu


def _pobierz(url, parametry):
    odp = requests.get(url, params=parametry, timeout=30)
    if odp.status_code != 200:
        raise RuntimeError(f"Open-Meteo {odp.status_code}: {odp.text[:150]}")
    return odp.json()


def _srednie_dobowe(godzinowe, zmienna, min_godzin=1):
    dni = {}
    for t, v in zip(godzinowe.get("time", []), godzinowe.get(zmienna) or []):
        if v is not None:
            dni.setdefault(t[:10], []).append(v)
    return [(d, sum(w) / len(w)) for d, w in sorted(dni.items()) if len(w) >= min_godzin]


def dane_na_zywo(lat, lon):
    teraz = datetime.now(ZoneInfo(STREFA))
    dzis = teraz.date()
    wspolne = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": STREFA}

    try:
        era5 = _pobierz(ARCHIWUM_URL, {**wspolne, "models": "era5_land",
                                       "start_date": (dzis - timedelta(days=14)).isoformat(),
                                       "end_date": (dzis - timedelta(days=5)).isoformat(),
                                       "hourly": "soil_temperature_0_to_7cm,soil_moisture_0_to_7cm"})
        era5_blad = None
    except Exception as e:  # ERA5 niedostępne - prognoza i tak się pokaże
        era5, era5_blad = {}, str(e)

    prognoza = _pobierz(PROGNOZA_URL, {**wspolne, "forecast_days": 7,
                                       "hourly": "soil_temperature_0cm,soil_temperature_6cm,soil_moisture_3_to_9cm",
                                       "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min"})
    return ocena(era5, prognoza, teraz, era5_blad)


def ocena(era5, prognoza, teraz, era5_blad=None):
    hist = _srednie_dobowe(era5.get("hourly", {}), "soil_temperature_0_to_7cm", 20)
    ostatnie = hist[-3:]
    t_era5 = sum(v for _, v in ostatnie) / len(ostatnie) if ostatnie else None
    w_hist = _srednie_dobowe(era5.get("hourly", {}), "soil_moisture_0_to_7cm", 20)

    h = prognoza["hourly"]
    t_prog = _srednie_dobowe(h, "soil_temperature_6cm")
    w_prog = _srednie_dobowe(h, "soil_moisture_3_to_9cm")
    godzina = teraz.strftime("%Y-%m-%dT%H:00")
    t_pow = h["soil_temperature_0cm"][h["time"].index(godzina)] if godzina in h["time"] else None
    wilg = w_prog[0][1] if w_prog else (w_hist[-1][1] if w_hist else None)

    uprawy = []
    for nazwa, prog in UPRAWY:
        siew_od = next((t_prog[i][0] for i in range(len(t_prog) - DNI_STABILNIE + 1)
                        if all(t >= prog for _, t in t_prog[i:i + DNI_STABILNIE])), None)
        pierwsze3 = [t for _, t in t_prog[:3]]
        cieplo = len(pierwsze3) == 3 and all(t >= prog for t in pierwsze3)
        if wilg is not None and wilg > PROG_ZA_MOKRO:
            status = "za_mokro"
        elif t_era5 is not None and t_era5 >= prog and cieplo:
            status = "gotowe"
        elif siew_od:
            status = "wkrotce"
        else:
            status = "czekaj"
        uprawy.append({"uprawa": nazwa, "prog": prog, "status": status, "siew_od": siew_od})

    d = prognoza["daily"]
    dni = [{"dzien": dz, "gleba_6cm": t,
            "powietrze_min": d["temperature_2m_min"][i], "powietrze_max": d["temperature_2m_max"][i],
            "opad": d["precipitation_sum"][i]} for i, (dz, t) in enumerate(t_prog)]
    return {"t_pow": t_pow, "t_era5": t_era5, "era5_do": ostatnie[-1][0] if ostatnie else None,
            "era5_blad": era5_blad, "wilg": wilg, "dni": dni, "uprawy": uprawy}
