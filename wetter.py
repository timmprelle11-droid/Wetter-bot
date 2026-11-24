#!/usr/bin/env python3
"""
Wetter-Bot: holt das aktuelle Wetter und die Tagesvorhersage bei Open-Meteo
(kostenlos, kein API-Key) und schickt sie per Telegram-Bot aufs Handy.

Benötigte Umgebungsvariablen (in GitHub als "Secrets" hinterlegt):
  TELEGRAM_BOT_TOKEN  – Token von @BotFather
  TELEGRAM_CHAT_ID    – deine Chat-ID

Optional:
  WETTER_ORT, WETTER_LAT, WETTER_LON  – anderer Ort (Standard: Werther (Westf.))
  NUR_UM_STUNDE       – nur senden, wenn es in Deutschland gerade diese Stunde
                        ist (z. B. "6"); leer = immer senden
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")

ORT = os.environ.get("WETTER_ORT", "Werther (Westf.)")
LAT = float(os.environ.get("WETTER_LAT", "52.0767"))
LON = float(os.environ.get("WETTER_LON", "8.4147"))

# WMO-Wettercodes → (Beschreibung, Emoji)
WETTERCODES = {
    0: ("Klar", "☀️"),
    1: ("Überwiegend klar", "🌤️"),
    2: ("Teilweise bewölkt", "⛅"),
    3: ("Bedeckt", "☁️"),
    45: ("Nebel", "🌫️"),
    48: ("Nebel mit Reif", "🌫️"),
    51: ("Leichter Nieselregen", "🌦️"),
    53: ("Nieselregen", "🌦️"),
    55: ("Starker Nieselregen", "🌧️"),
    56: ("Gefrierender Nieselregen", "🧊"),
    57: ("Starker gefrierender Nieselregen", "🧊"),
    61: ("Leichter Regen", "🌦️"),
    63: ("Regen", "🌧️"),
    65: ("Starker Regen", "🌧️"),
    66: ("Gefrierender Regen", "🧊"),
    67: ("Starker gefrierender Regen", "🧊"),
    71: ("Leichter Schneefall", "🌨️"),
    73: ("Schneefall", "🌨️"),
    75: ("Starker Schneefall", "❄️"),
    77: ("Schneegriesel", "🌨️"),
    80: ("Leichte Regenschauer", "🌦️"),
    81: ("Regenschauer", "🌧️"),
    82: ("Heftige Regenschauer", "⛈️"),
    85: ("Schneeschauer", "🌨️"),
    86: ("Starke Schneeschauer", "❄️"),
    95: ("Gewitter", "⛈️"),
    96: ("Gewitter mit Hagel", "⛈️"),
    99: ("Schweres Gewitter mit Hagel", "⛈️"),
}

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def wetter_text(code) -> str:
    beschreibung, emoji = WETTERCODES.get(int(code), ("Unbekannt", "🌡️"))
    return f"{emoji} {beschreibung}"


def hole_wetter() -> dict:
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                   "precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"
                 "sunrise,sunset,uv_index_max",
        "timezone": "Europe/Berlin",
        "forecast_days": 1,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.load(resp)


def baue_nachricht(daten: dict, jetzt: datetime) -> str:
    c = daten["current"]
    d = daten["daily"]
    h = daten["hourly"]

    def tag(feld):
        return d[feld][0]

    zeilen = [
        f"<b>Wetter für {ORT}</b>",
        f"{WOCHENTAGE[jetzt.weekday()]}, {jetzt.strftime('%d.%m.%Y')}",
        "",
        "<b>Jetzt</b>",
        f"{wetter_text(c['weather_code'])}, {round(c['temperature_2m'])} °C "
        f"(gefühlt {round(c['apparent_temperature'])} °C)",
        f"💧 Luftfeuchte {round(c['relative_humidity_2m'])} %",
        f"💨 Wind {round(c['wind_speed_10m'])} km/h, Böen {round(c['wind_gusts_10m'])} km/h",
        "",
        "<b>Heute</b>",
        f"{wetter_text(tag('weather_code'))}",
        f"🌡️ {round(tag('temperature_2m_min'))} bis {round(tag('temperature_2m_max'))} °C",
        f"☔ Regenrisiko {round(tag('precipitation_probability_max') or 0)} %, "
        f"Menge {tag('precipitation_sum'):.1f} mm".replace('.', ','),
        f"💨 Wind bis {round(tag('wind_speed_10m_max'))} km/h, Böen bis {round(tag('wind_gusts_10m_max'))} km/h",
    ]

    uv = tag("uv_index_max")
    if uv is not None and uv >= 3:
        zeilen.append(f"🕶️ UV-Index bis {uv:.0f}")

    zeilen.append(
        f"🌅 {tag('sunrise')[-5:]} Uhr   🌇 {tag('sunset')[-5:]} Uhr"
    )

    # Tagesverlauf um 9, 12, 15 und 18 Uhr
    verlauf = []
    for stunde in ("09:00", "12:00", "15:00", "18:00"):
        for i, zeit in enumerate(h["time"]):
            if zeit.endswith(stunde):
                _, emoji = WETTERCODES.get(int(h["weather_code"][i]), ("", "🌡️"))
                regen = h["precipitation_probability"][i]
                regen_text = f", ☔ {regen} %" if regen else ""
                verlauf.append(
                    f"{stunde[:2]} Uhr: {emoji} {round(h['temperature_2m'][i])} °C{regen_text}"
                )
                break
    if verlauf:
        zeilen += ["", "<b>Verlauf</b>", *verlauf]

    return "\n".join(zeilen)


def sende_telegram(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    # Mehrere Empfänger: Chat-IDs mit Komma trennen, z. B. "123456789,987654321"
    chat_ids = [c.strip() for c in os.environ["TELEGRAM_CHAT_ID"].split(",") if c.strip()]
    fehler = []
    for chat_id in chat_ids:
        body = urllib.parse.urlencode(
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        ).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=body, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                antwort = json.load(resp)
            if not antwort.get("ok"):
                fehler.append(f"Chat {chat_id}: {antwort}")
        except urllib.error.HTTPError as err:
            # Den Token nicht ausgeben – nur die Antwort von Telegram.
            fehler.append(f"Chat {chat_id}: Fehler {err.code}: {err.read().decode(errors='replace')}")
    # Erst alle Empfänger versuchen, dann Fehler melden – so bekommt einer die
    # Nachricht auch dann, wenn die Chat-ID des anderen falsch ist.
    if fehler:
        raise SystemExit("Telegram-Fehler:\n" + "\n".join(fehler))


def main() -> int:
    jetzt = datetime.now(TZ)

    # GitHub-Zeitpläne laufen in UTC. Der Workflow startet deshalb zweimal
    # (für Sommer- und Winterzeit) und dieses Skript sendet nur einmal,
    # nämlich wenn es in Deutschland gerade 6 Uhr ist.
    nur_um = os.environ.get("NUR_UM_STUNDE", "").strip()
    if nur_um and jetzt.hour != int(nur_um):
        print(f"Es ist {jetzt:%H:%M} Uhr in Deutschland – nicht {nur_um} Uhr, nichts zu tun.")
        return 0

    text = baue_nachricht(hole_wetter(), jetzt)
    sende_telegram(text)
    print("Wetter gesendet:\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
