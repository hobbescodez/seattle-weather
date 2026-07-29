"""
Build the friendly Fremont weather page (docs/index.html).

Runs the *same* estimator that powers the KSEA dashboard - trend
extrapolation, diurnal damping, the cross-station gradient network
(marine-push / offshore-flow signals) and the NWS gridpoint-forecast blend -
but pointed at the Fremont/Aurora neighborhood of Seattle: observations from
KBFI (Boeing Field), forecast and sun times at Fremont's own coordinates.

The difference from the KSEA dashboard is entirely in the *presentation*: no
markets, no betting, no trading. It borrows that dashboard's visual language
(blue-gradient sky, glass cards, uppercase section headers) as a friendlier
sibling, adds animated Meteocons weather icons chosen from the real
conditions, and translates every number into plain language with an
expandable "Why?" next to it. The real uncertainty band and the real "why the
estimate widened" reasons are kept - just written for a general audience.

Output: docs/index.html (override with DASHBOARD_OUTPUT_PATH).
    python3 build_site.py
"""

import html
import os
import re
from datetime import datetime, timedelta

import requests

from weather_estimator import (
    estimate_temp,
    estimate_daily_extremes,
    get_observation_history,
    get_sun_times,
    PEAK_HEAT_FRACTION,
    MARINE_PUSH_INDEX_THRESHOLD,
    OFFSHORE_FLOW_INDEX_THRESHOLD,
)

# --- Location config -------------------------------------------------------
# Fremont/Aurora, Seattle. Observations come from KBFI (Boeing Field), the
# nearest full ASOS station with real ground-truth readings (~5 mi south).
# The forecast and sunrise/sunset are computed at Fremont's own coordinates.
# If KBFI is unreachable we flag it - we never silently swap in KSEA/Sea-Tac.
STATION = "KBFI"
FREMONT_LAT, FREMONT_LON = 47.6510, -122.3500
LOCATION_NAME = "Fremont"
OBS_STATION_LABEL = "Boeing Field (KBFI), ~5 mi south"
HOURS_AHEAD = 3
SPARKLINE_HOURS = 6

HERE = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(HERE, "icons")


# --- small formatting helpers ---------------------------------------------

def _fmt_time(ts):
    return ts.strftime("%-I:%M %p").lower()


def _fmt_day_time(ts):
    return ts.strftime("%a %-I:%M %p").lower()


def esc(s):
    return html.escape(str(s))


# --- animated Meteocons icons ---------------------------------------------
# Inlined so the page stays a single self-contained file (animations run with
# no external requests). Each inlined SVG gets its ids/refs namespaced so the
# gradient/filter ids (they all use id="a","b",...) don't collide when several
# icons share the page.

_icon_seq = [0]


def inline_icon(name, cls):
    path = os.path.join(ICONS_DIR, name + ".svg")
    try:
        with open(path) as f:
            svg = f.read()
    except FileNotFoundError:
        print(f"icon missing: {name}")
        return ""
    _icon_seq[0] += 1
    p = f"ic{_icon_seq[0]}-"
    svg = re.sub(r'id="([^"]+)"', lambda m: f'id="{p}{m.group(1)}"', svg)
    svg = re.sub(r'url\(#([^)]+)\)', lambda m: f'url(#{p}{m.group(1)})', svg)
    svg = re.sub(r'(xlink:href|href)="#([^"]+)"',
                 lambda m: f'{m.group(1)}="#{p}{m.group(2)}"', svg)
    svg = svg.replace("<svg ", f'<svg class="{cls}" ', 1)
    return svg


# --- current-conditions text from NWS (drives icon + mood) -----------------

def get_current_forecast_period(lat, lon):
    """The NWS hourly gridpoint forecast's current period for this spot - its
    short text ("Partly Sunny", "Light Rain") and chance of rain. This is what
    lets the page respond to the actual weather. Returns a dict or None."""
    try:
        pts = requests.get(
            f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}",
            headers={"Accept": "application/geo+json"}, timeout=30,
        )
        pts.raise_for_status()
        furl = pts.json()["properties"]["forecastHourly"]
        fr = requests.get(furl, headers={"Accept": "application/geo+json"}, timeout=30)
        fr.raise_for_status()
        periods = fr.json()["properties"]["periods"]
        if not periods:
            return None
        p = periods[0]
        return {
            "short": p.get("shortForecast", ""),
            "pop": p.get("probabilityOfPrecipitation", {}).get("value"),
        }
    except Exception as e:
        print(f"NWS current-period forecast unavailable: {e}")
        return None


# --- ONE source of truth: classify the sky -> icon, backdrop, label, vibe --
# Everything the hero shows (the animated icon, the background gradient, the
# condition line and the friendly vibe) is derived here from the SAME signal,
# so they can never contradict each other (the earlier build could say
# "Mostly Sunny" while the vibe said "grey and overcast" because the two came
# from different sources). Prefer the NWS short forecast text; fall back to
# the observed cloud fraction only when the text is missing.

def _cloud_bucket_from_text(sf):
    if "partly cloudy" in sf or "partly sunny" in sf:
        return "partly"
    if "mostly cloudy" in sf or "considerable cloud" in sf:
        return "mostly"
    if "mostly sunny" in sf or "mostly clear" in sf:
        return "partly"
    if "cloudy" in sf or "overcast" in sf:
        return "cloudy"
    if "sunny" in sf or "clear" in sf or "fair" in sf:
        return "clear"
    return None


def _cloud_bucket_from_cover(c):
    if c is None:
        return "partly"
    if c <= 0.15:
        return "clear"
    if c <= 0.50:
        return "partly"
    if c <= 0.85:
        return "mostly"
    return "cloudy"


def classify_sky(short_forecast, cloud_fraction, pop, is_day):
    """Return dict(icon, sky, label, vibe) - all consistent with each other."""
    sf = (short_forecast or "").lower()

    # precipitation type (text first; obs as a weak fallback)
    if "thunder" in sf or "tstorm" in sf or "storm" in sf:
        precip = "thunder"
    elif "snow" in sf or "flurr" in sf:
        precip = "snow"
    elif "sleet" in sf or "freezing" in sf or "ice" in sf or "wintry" in sf:
        precip = "sleet"
    elif "drizzle" in sf:
        precip = "drizzle"
    elif "rain" in sf or "shower" in sf:
        precip = "rain"
    elif not sf and pop is not None and pop >= 55 and (cloud_fraction or 0) > 0.6:
        precip = "rain"
    else:
        precip = None

    foggy = ("fog" in sf or "haze" in sf or "mist" in sf) and precip is None

    bucket = _cloud_bucket_from_text(sf) if sf else None
    if bucket is None:
        bucket = _cloud_bucket_from_cover(cloud_fraction)

    daytag = "day" if is_day else "night"

    # icon (animated Meteocons filename)
    if precip == "thunder":
        icon = "thunderstorms-day-rain" if is_day else "thunderstorms-rain"
    elif precip == "snow":
        icon = "snow"
    elif precip == "sleet":
        icon = "sleet"
    elif precip == "drizzle":
        icon = "drizzle"
    elif precip == "rain":
        icon = "rain"
    elif foggy:
        icon = f"fog-{daytag}"
    elif bucket == "clear":
        icon = f"clear-{daytag}"
    elif bucket == "partly":
        icon = f"partly-cloudy-{daytag}"
    elif bucket == "mostly":
        icon = f"overcast-{daytag}"
    else:  # cloudy
        icon = "cloudy"

    # backdrop sky (4 variants, matches the main dashboard)
    clear_sky = precip is None and not foggy and bucket in ("clear", "partly")
    sky = f"{daytag}-{'clear' if clear_sky else 'cloudy'}"

    # condition label — prefer NWS's own human phrasing
    if short_forecast:
        label = short_forecast
    else:
        label = {
            "clear": "Clear" if not is_day else "Sunny",
            "partly": "Partly cloudy",
            "mostly": "Mostly cloudy",
            "cloudy": "Overcast",
        }[bucket]
        if foggy:
            label = "Fog"

    # friendly vibe — matches the classification, never the opposite
    if precip == "thunder":
        vibe = "Keep an eye on the sky — it's the unsettled, thundery kind of day."
    elif precip == "snow":
        vibe = "Bundle up — there's snow in the mix."
    elif precip == "sleet":
        vibe = "Cold and messy out there — a wintry mix."
    elif precip in ("rain", "drizzle"):
        vibe = "Classic Seattle — grab a jacket and skip the umbrella like a local."
    elif foggy:
        vibe = "Low and soft out — fog hanging around."
    elif not is_day:
        vibe = {
            "clear": "Clear and quiet overnight.",
            "partly": "A few clouds drifting by tonight.",
            "mostly": "Cloudy tonight — that tends to keep temperatures from dropping much.",
            "cloudy": "Overcast overnight — the cloud blanket holds the warmth in.",
        }[bucket]
    else:
        vibe = {
            "clear": "Bright and clear — a proper Seattle payoff day.",
            "partly": "A good mix of sun and clouds.",
            "mostly": "More cloud than sun, but staying dry.",
            "cloudy": "Grey and overcast — the usual soft Seattle light.",
        }[bucket]

    return {"icon": icon, "sky": sky, "label": label, "vibe": vibe}


# --- plain-language translations of the model's honest internals -----------

def confidence_sentence(est, now, lat, lon):
    diurnal = est["diurnal_damping"]
    sky_wind = est["sky_wind_damping"]
    trend = est["raw_trend_f_per_hr"]
    confidence = diurnal * sky_wind

    sunrise_h, sunset_h = get_sun_times(lat, lon, now.date())
    peak_h = sunrise_h + (sunset_h - sunrise_h) * PEAK_HEAT_FRACTION
    hour = now.hour + now.minute / 60
    near_peak = abs(hour - peak_h) < 1.75
    near_sunrise = abs(hour - sunrise_h) < 1.75

    if confidence >= 0.72:
        headline = "We're fairly confident about this one."
    elif confidence >= 0.5:
        headline = "We're reasonably confident here."
    elif confidence >= 0.35:
        headline = "This one's a little shaky."
    else:
        headline = "Honestly, this is a rough guess right now."

    reasons = []
    if diurnal < 0.85 and near_peak:
        reasons.append(
            "we're close to the warmest part of the day, when the temperature usually "
            "stops climbing and levels off — so exactly where it peaks is harder to pin down")
    elif diurnal < 0.85 and near_sunrise:
        reasons.append(
            "it's near dawn, when temperatures bottom out and start to turn back up — the "
            "next few hours can tip either way")
    elif diurnal < 0.9:
        reasons.append(
            "we're near a turning point in the day's natural rise-and-fall, so we're leaning "
            "less on the recent trend")
    if sky_wind < 0.7:
        reasons.append(
            "it's cloudy and/or breezy, which keeps the air mixed and stops temperatures from "
            "swinging much (so we don't expect big moves)")
    if not reasons:
        reasons.append("the temperature has been holding pretty steady lately"
                       if abs(trend) < 0.6 else "the recent trend has been clean and steady")

    return headline, "; ".join(reasons).capitalize() + "."


def band_sentence(lo, hi):
    half = (hi - lo) / 2
    if half <= 1.5:
        qual = "a fairly tight range"
    elif half <= 3.0:
        qual = "a normal amount of wiggle room"
    else:
        qual = "a wide range — there's real uncertainty right now"
    return (f"Most likely between <strong>{lo:.0f}°</strong> and <strong>{hi:.0f}°</strong> "
            f"(about ±{half:.0f}°, {qual}).")


WIDEN_TRANSLATIONS = {
    "local pressure falling": "the air pressure here is dropping, which often means a weather system is moving in",
    "marine push signal rising": "cool ocean air looks like it may be pushing inland — the classic Seattle afternoon cool-down",
    "offshore flow signal rising": "warm, dry air from east of the mountains may be sliding over the region, which can nudge temperatures up",
}


def widen_sentence(uncertainty_note):
    if not uncertainty_note:
        return ""
    parts = [p.strip() for p in uncertainty_note.split(";")]
    friendly = [WIDEN_TRANSLATIONS.get(p, p) for p in parts]
    joined = "; and ".join(friendly) if len(friendly) > 1 else friendly[0]
    return f"We widened the range because {joined}."


def signals_plain(est):
    """Gradient signals in plain language, each with an animated icon. Only the
    ones actually saying something. Returns list of (icon_name, text)."""
    out = []
    mp = est.get("marine_push_index")
    of = est.get("offshore_flow_index")
    ptrend = est.get("pressure_trend_inhg_per_hr")
    if mp is not None and mp > MARINE_PUSH_INDEX_THRESHOLD:
        out.append(("wind",
            "Cool marine air may be pushing in from the coast over the next hour or two — "
            "Seattle's typical afternoon sea-breeze cool-down. Temperatures could dip a bit "
            "faster than the trend alone suggests."))
    if of is not None and of > OFFSHORE_FLOW_INDEX_THRESHOLD:
        out.append(("extreme-day",
            "Warm, dry air from east of the Cascades looks like it may be sliding toward the "
            "coast — the pattern behind most real heat spells here. It can push temperatures "
            "higher than a normal day."))
    if ptrend is not None and ptrend < -0.015:
        out.append(("compass",
            "The air pressure is falling, which usually means a weather system is on the way "
            "and conditions are more likely to shift."))
    return out


# --- last-6-hours sparkline ------------------------------------------------

def build_sparkline_svg(times, temps, est_time, est_temp, width=640, height=170):
    pad_x, pad_top, pad_bottom = 8, 32, 30
    all_temps = temps + [est_temp]
    lo, hi = min(all_temps), max(all_temps)
    span = max(hi - lo, 1)
    lo -= span * 0.15
    hi += span * 0.15
    span = hi - lo
    t0 = times[0]
    total = (est_time - t0).total_seconds() or 1

    def xy(t, temp):
        x = pad_x + (width - 2 * pad_x) * ((t - t0).total_seconds() / total)
        y = pad_top + (height - pad_top - pad_bottom) * (1 - (temp - lo) / span)
        return x, y

    pts = [xy(t, v) for t, v in zip(times, temps)]
    est_pt = xy(est_time, est_temp)
    line_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area_path = (line_path + f" L {pts[-1][0]:.1f},{height - pad_bottom} "
                 f"L {pts[0][0]:.1f},{height - pad_bottom} Z")
    proj_path = f"M {pts[-1][0]:.1f},{pts[-1][1]:.1f} L {est_pt[0]:.1f},{est_pt[1]:.1f}"
    est_label_y = max(est_pt[1] - 14, 12)
    return f"""
<svg viewBox="0 0 {width} {height}" class="sparkline" preserveAspectRatio="none" role="img" aria-label="Temperature over the last {SPARKLINE_HOURS} hours and the estimate a few hours ahead">
  <path d="{area_path}" class="spark-area" />
  <path d="{line_path}" class="spark-line" />
  <path d="{proj_path}" class="spark-proj" />
  <line x1="{est_pt[0]:.1f}" y1="{est_pt[1]:.1f}" x2="{est_pt[0]:.1f}" y2="{height - pad_bottom:.1f}" class="spark-est-guide" />
  <circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.5" class="spark-now-dot" />
  <circle cx="{est_pt[0]:.1f}" cy="{est_pt[1]:.1f}" r="9" class="spark-est-dot-halo" />
  <circle cx="{est_pt[0]:.1f}" cy="{est_pt[1]:.1f}" r="5.5" class="spark-est-dot" />
  <text x="{est_pt[0]:.1f}" y="{est_label_y:.1f}" text-anchor="end" class="spark-est-label">{est_temp:.0f}°</text>
</svg>""".strip()


def why_block(summary_text, detail_html):
    return (f'<details class="why"><summary>{summary_text}</summary>'
            f'<div class="why-body">{detail_html}</div></details>')


def build_error_page(message):
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fremont Weather — data unavailable</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:linear-gradient(175deg,#191c24,#3d434f);color:#eaf0fb;display:grid;place-items:center;min-height:100vh;margin:0;padding:2rem;text-align:center}}
.box{{max-width:32rem}}h1{{font-size:1.4rem}}p{{color:#b9c5db;line-height:1.6}}code{{color:#f8b4b4}}</style>
</head><body><div class="box">
<h1>🌧️ Fremont weather is briefly unavailable</h1>
<p>We couldn't reach live observations from {esc(OBS_STATION_LABEL)} just now, so there's
nothing fresh to show. Rather than show another location's weather dressed up as Fremont's,
we'd rather say nothing.</p>
<p>This usually clears up on its own — check back in a few minutes.</p>
<p><code>{esc(message)}</code></p>
</div></body></html>"""


def main():
    try:
        est = estimate_temp(STATION, hours_ahead=HOURS_AHEAD,
                            lat=FREMONT_LAT, lon=FREMONT_LON, location_name=LOCATION_NAME)
        extremes = estimate_daily_extremes(STATION,
                            lat=FREMONT_LAT, lon=FREMONT_LON, location_name=LOCATION_NAME)
    except Exception as e:
        print(f"Model run failed for {STATION}: {e}")
        out_path = os.environ.get("DASHBOARD_OUTPUT_PATH", os.path.join(HERE, "docs", "index.html"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w") as f:
            f.write(build_error_page(str(e)))
        print(f"Wrote error page to {out_path}")
        return

    now = est["as_of"]
    lat, lon = FREMONT_LAT, FREMONT_LON

    sunrise_h, sunset_h = get_sun_times(lat, lon, now.date())
    now_h = now.hour + now.minute / 60
    is_day = sunrise_h <= now_h < sunset_h

    current_period = get_current_forecast_period(lat, lon)
    short_forecast = current_period["short"] if current_period else None
    pop = current_period["pop"] if current_period else None
    cloud_fraction = est["cloud_fraction"]

    sky = classify_sky(short_forecast, cloud_fraction, pop, is_day)

    # Preview-only sky override (screenshots of a given condition/time). Never
    # set in normal runs or the GitHub Action, so it has zero production
    # effect; only the backdrop/icon/vibe change, the real numbers don't.
    _pv = os.environ.get("PREVIEW_SKY")
    if _pv:
        _forcemap = {
            "night-clear": ("Clear", False), "night-cloudy": ("Mostly Cloudy", False),
            "day-clear": ("Sunny", True), "day-cloudy": ("Cloudy", True),
            "rain": ("Rain Likely", True),
        }
        _txt, _isday = _forcemap.get(_pv, (short_forecast, is_day))
        sky = classify_sky(_txt, cloud_fraction, pop, _isday)

    lo, hi = float(est["estimated_range_f"][0]), float(est["estimated_range_f"][1])
    conf_headline, conf_detail = confidence_sentence(est, now, lat, lon)
    band_html = band_sentence(lo, hi)
    widen_html = widen_sentence(est.get("uncertainty_note"))

    # honest "why?" for the estimate
    n_obs = est["n_observations"]
    trend = est["raw_trend_f_per_hr"]
    trend_dir = "rising" if trend > 0.1 else ("falling" if trend < -0.1 else "flat")
    nws_temp = est.get("nws_forecast_temp_f")
    blend_w = est.get("blend_weight_used")
    if nws_temp is not None and blend_w is not None:
        if blend_w <= 0.3:
            blend_line = (f"Our trend and the National Weather Service's hourly forecast for "
                          f"Fremont ({nws_temp:.0f}°) disagreed by more than a few degrees, so we "
                          f"leaned mostly on the forecast — it can see incoming weather our short "
                          f"local trend can't.")
        else:
            blend_line = (f"Our trend and the National Weather Service's hourly forecast for "
                          f"Fremont ({nws_temp:.0f}°) roughly agreed, so we blended them evenly.")
    else:
        blend_line = ("The National Weather Service hourly forecast wasn't available for this "
                      "exact time, so we're using our own trend estimate alone.")

    est_why = why_block("Why this number?",
        f"<p>We start from how the temperature at {esc(OBS_STATION_LABEL)} has moved over its "
        f"last {n_obs} readings — right now that's <strong>{trend_dir}</strong> "
        f"(about {trend:+.1f}° per hour).</p>"
        f"<p>{esc(conf_detail)} That's why we don't just extend the line straight out.</p>"
        f"<p>{blend_line}</p>"
        f"<p>Finally we keep the number consistent with today's expected high and low, so a "
        f"few-hours-ahead estimate can't accidentally overshoot the day's peak.</p>")

    band_why = why_block("Why a range instead of one number?",
        "<p>No honest short-term temperature estimate is a single exact number — so we show the "
        "range we actually expect. It starts around ±1° and grows the further ahead we look.</p>"
        + (f"<p>{widen_html}</p>" if widen_html else
           "<p>Right now nothing unusual is widening it beyond that baseline.</p>"))

    # today high / low
    high_status = extremes["high_status"]
    if high_status == "observed":
        high_caption = f"today's high so far, hit at {_fmt_time(extremes['observed_high_so_far_time'])}"
    else:
        high_caption = f"expected around {_fmt_time(extremes['estimated_high_time'])}"
    low_status = extremes["low_status"]
    if low_status == "today":
        low_caption = f"almost here, around {_fmt_time(extremes['estimated_low_time'])}"
    else:
        low_caption = f"expected overnight, around {_fmt_day_time(extremes['estimated_low_time'])}"

    high_why = why_block("How do we know?",
        (f"<p>The high already happened — {extremes['estimated_high_f']:.0f}° was the warmest "
         f"reading at {esc(OBS_STATION_LABEL)} so far today.</p>" if high_status == "observed" else
         "<p>Today's warmest hour hasn't arrived yet, so this is a projection: recent trend, "
         "damped as the day nears its natural peak, cross-checked against the NWS forecast. "
         "It's a floor-ish estimate — the real peak could edge higher.</p>"))
    low_source = extremes.get("low_source")
    low_src_line = {
        "nws_forecast": "Straight from the National Weather Service's hourly forecast for Fremont at that hour.",
        "trend_model": "Tonight's low is close enough that our short-term trend model handles it directly.",
        "dewpoint_fallback": "The forecast wasn't available, so we estimated it from how far the air can "
                             "radiatively cool tonight (toward the dew point, unless clouds or wind hold it up).",
    }.get(low_source, "")
    low_why = why_block("How do we know?", f"<p>{low_src_line}</p>")

    # tomorrow
    tmrw_source = extremes["tomorrow_high_source"]
    if tmrw_source == "nws_forecast":
        tmrw_note = ("From the National Weather Service's next-day forecast (a real weather model, "
                     "not our own trend guess). A day out, even the pros have real uncertainty.")
    else:
        tmrw_note = ("The forecast wasn't reachable, so this is a rough persistence guess (similar to "
                     "today, nudged by the pressure trend). Treat it as a ballpark.")

    # signals
    signal_notes = signals_plain(est)
    if signal_notes:
        signals_html = "".join(
            f'<div class="signal"><span class="wx wx-signal">{inline_icon(ic, "")}</span>'
            f'<span class="signal-text">{esc(t)}</span></div>' for ic, t in signal_notes)
        signals_html += ('<p class="signal-caveat">These are early-warning signals from weather '
            'stations around Puget Sound (the coast, the Strait, and east of the mountains). '
            'They\'re experimental — they widen our uncertainty rather than move the headline number.</p>')
    else:
        calm_icon = inline_icon("clear-day" if is_day else "clear-night", "")
        signals_html = (f'<div class="signal"><span class="wx wx-signal">{calm_icon}</span>'
            '<span class="signal-text">Nothing unusual brewing right now — the stations around '
            'Puget Sound aren\'t showing an incoming marine push or heat surge.</span></div>')

    # sparkline
    try:
        hist = get_observation_history(STATION, start=now - timedelta(hours=SPARKLINE_HOURS), end=now)
        sparkline_svg = build_sparkline_svg(list(hist["time"]), list(hist["temp_f"]),
                                            est["target_time"], est["estimated_temp_f"])
    except Exception as e:
        print(f"Sparkline history unavailable: {e}")
        sparkline_svg = '<p class="hint">Recent history unavailable right now.</p>'

    if extremes["yesterday_high_f"] is not None:
        yesterday_line = (f"Yesterday: high {extremes['yesterday_high_f']:.0f}°, "
                          f"low {extremes['yesterday_low_f']:.0f}°.")
    else:
        yesterday_line = ""

    wind_txt = f"{est['wind_mph']:.0f} mph" if est["wind_mph"] is not None else "calm"
    cloud_txt = f"{round(cloud_fraction * 100)}% cloud" if cloud_fraction is not None else "—"

    ctx = {
        "location_name": LOCATION_NAME,
        "sky_code": sky["sky"],
        "hero_icon_svg": inline_icon(sky["icon"], "wx-hero-svg"),
        "condition_text": esc(sky["label"]),
        "vibe_phrase": esc(sky["vibe"]),
        "current_temp": f"{est['current_temp_f']:.0f}",
        "as_of_time": _fmt_time(now),
        "as_of_date": now.strftime("%A, %B %-d"),
        "obs_station_label": esc(OBS_STATION_LABEL),
        "wind_txt": esc(wind_txt),
        "cloud_txt": esc(cloud_txt),
        "pop_chip": f'<span class="chip">☔ {pop}%</span>' if pop is not None else "",
        "target_time": _fmt_day_time(est["target_time"]),
        "estimated_temp": f"{est['estimated_temp_f']:.0f}",
        "conf_headline": esc(conf_headline),
        "band_html": band_html,
        "widen_html": widen_html,
        "est_why": est_why,
        "band_why": band_why,
        "sparkline_svg": sparkline_svg,
        "sparkline_hours": SPARKLINE_HOURS,
        "daily_high": f"{extremes['estimated_high_f']:.0f}",
        "high_caption": esc(high_caption),
        "high_icon_svg": inline_icon("thermometer-warmer", ""),
        "high_why": high_why,
        "daily_low": f"{extremes['estimated_low_f']:.0f}",
        "low_caption": esc(low_caption),
        "low_icon_svg": inline_icon("thermometer-colder", ""),
        "low_why": low_why,
        "tomorrow_high": f"{extremes['tomorrow_high_f']:.0f}",
        "tomorrow_low": f"{extremes['tomorrow_low_f']:.0f}",
        "tomorrow_note": esc(tmrw_note),
        "signals_html": signals_html,
        "yesterday_line": esc(yesterday_line),
        "generated_at": _fmt_time(now) + " · " + now.strftime("%b %-d"),
    }

    with open(os.path.join(HERE, "template.html")) as f:
        template = f.read()
    for key, value in ctx.items():
        template = template.replace("{{" + key + "}}", str(value))

    out_path = os.environ.get("DASHBOARD_OUTPUT_PATH", os.path.join(HERE, "docs", "index.html"))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(template)
    print(f"Wrote {out_path}  (sky={sky['sky']}, icon={sky['icon']}, condition={sky['label']})")


if __name__ == "__main__":
    main()
