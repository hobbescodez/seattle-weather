"""
Build the friendly Fremont weather page (docs/index.html).

Runs the *same* estimator that powers the KSEA dashboard - trend
extrapolation, diurnal damping, the cross-station gradient network
(marine-push / offshore-flow signals) and the NWS gridpoint-forecast blend -
but pointed at the Fremont/Aurora neighborhood of Seattle: observations from
KBFI (Boeing Field), forecast and sun times at Fremont's own coordinates.

The difference from the KSEA dashboard is entirely in the *presentation*.
There are no markets, no betting, no trading, no performance ledger - just the
weather. And instead of surfacing raw jargon ("trend confidence 51%", "diurnal
damping 0.35"), every number is translated into plain language, with an
expandable "Why?" next to it for anyone who wants the honest detail. The real
uncertainty band and the real "why the estimate widened" reasons are kept -
just written for someone who doesn't already know the terms.

Output: docs/index.html (override with DASHBOARD_OUTPUT_PATH).
    python3 build_site.py
"""

import html
import json
import os
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


# --- small formatting helpers ---------------------------------------------

def _fmt_time(ts):
    return ts.strftime("%-I:%M %p").lower()


def _fmt_day_time(ts):
    return ts.strftime("%a %-I:%M %p").lower()


def esc(s):
    return html.escape(str(s))


# --- current-conditions text from NWS (drives the "mood" of the page) ------

def get_current_forecast_period(lat, lon):
    """
    The NWS hourly gridpoint forecast's *current* period for this spot -
    its short text ("Partly Sunny", "Light Rain") and chance of rain. This
    is what lets the page respond to the actual weather (sunny vs. rainy vs.
    something unusual) instead of being a static readout. Returns a dict or
    None if the forecast can't be reached.
    """
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
        pop = p.get("probabilityOfPrecipitation", {}).get("value")
        return {
            "short": p.get("shortForecast", ""),
            "pop": pop,
            "is_daytime": p.get("isDaytime", True),
        }
    except Exception as e:
        print(f"NWS current-period forecast unavailable: {e}")
        return None


# --- weather "mood": theme + tone that shifts with real conditions ---------

RAIN_WORDS = ("rain", "shower", "drizzle", "thunder", "storm", "snow", "sleet")


def pick_mood(cloud_fraction, is_day, short_forecast, pop, unsettled):
    """
    Choose a visual/tonal mood from the actual conditions. Returns
    (mood_class, hero_emoji, vibe_phrase). mood_class drives the background
    gradient (see the template's CSS); vibe_phrase is a short human read on
    the day.
    """
    sf = (short_forecast or "").lower()
    rainy = any(w in sf for w in RAIN_WORDS) or (pop is not None and pop >= 40)
    cloud = cloud_fraction if cloud_fraction is not None else 0.0

    if rainy:
        if "thunder" in sf or "storm" in sf:
            return ("mood-storm", "⛈️", "Keep an eye out — it's the unsettled kind of day.")
        if "snow" in sf or "sleet" in sf:
            return ("mood-snow", "🌨️", "Bundle up — wintry mix out there.")
        return ("mood-rain", "🌧️", "Classic Seattle — grab a jacket, skip the umbrella like a local.")

    if not is_day:
        if cloud <= 0.4:
            return ("mood-clear-night", "🌙", "Clear and quiet overnight.")
        return ("mood-cloudy-night", "☁️", "Cloudy tonight — that tends to keep temperatures from dropping much.")

    if cloud <= 0.15:
        return ("mood-sunny", "☀️", "Bright and clear — a proper Seattle payoff day.")
    if cloud <= 0.5:
        return ("mood-partly", "🌤️", "A mix of sun and clouds.")
    if cloud <= 0.85:
        return ("mood-partly", "⛅", "More cloud than sun, but dry.")
    return ("mood-cloudy", "☁️", "Grey and overcast — the usual soft Seattle light.")


# --- plain-language translations of the model's honest internals -----------

def confidence_sentence(est, now, lat, lon):
    """
    Translate the model's damping (its "how much do we trust the recent
    trend right now" figure) into a plain sentence that names the actual
    reason, adapted to the situation - never a hardcoded line. Returns
    (headline_phrase, detail_sentence).
    """
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

    # Name the dominant reason the estimate is (or isn't) steady.
    reasons = []
    if diurnal < 0.85 and near_peak:
        reasons.append(
            "we're close to the warmest part of the day, when the temperature "
            "usually stops climbing and levels off — so exactly where it peaks is "
            "harder to pin down"
        )
    elif diurnal < 0.85 and near_sunrise:
        reasons.append(
            "it's near dawn, when temperatures bottom out and start to turn back "
            "up — the next few hours can tip either way"
        )
    elif diurnal < 0.9:
        reasons.append(
            "we're near a turning point in the day's natural rise-and-fall, so "
            "we're leaning less on the recent trend"
        )

    if sky_wind < 0.7:
        reasons.append(
            "it's cloudy and/or breezy, which keeps the air mixed and stops "
            "temperatures from swinging much (so we don't expect big moves)"
        )

    if not reasons:
        if abs(trend) < 0.6:
            reasons.append("the temperature has been holding pretty steady lately")
        else:
            reasons.append("the recent trend has been clean and steady")

    return headline, "; ".join(reasons).capitalize() + "."


def band_sentence(lo, hi, est_temp):
    half = (hi - lo) / 2
    if half <= 1.5:
        qual = "a fairly tight range"
    elif half <= 3.0:
        qual = "a normal amount of wiggle room"
    else:
        qual = "a wide range — there's real uncertainty right now"
    return (
        f"Most likely between <strong>{lo:.0f}°</strong> and <strong>{hi:.0f}°</strong> "
        f"(about ±{half:.0f}°, {qual})."
    )


# Translate each raw "why the band widened" token into a friendly clause.
WIDEN_TRANSLATIONS = {
    "local pressure falling": (
        "the air pressure here is dropping, which often means a weather system "
        "is moving in"
    ),
    "marine push signal rising": (
        "cool ocean air looks like it may be pushing inland — the classic Seattle "
        "afternoon cool-down"
    ),
    "offshore flow signal rising": (
        "warm, dry air from east of the mountains may be sliding over the region, "
        "which can nudge temperatures up"
    ),
}


def widen_sentence(uncertainty_note):
    if not uncertainty_note:
        return ""
    parts = [p.strip() for p in uncertainty_note.split(";")]
    friendly = [WIDEN_TRANSLATIONS.get(p, p) for p in parts]
    joined = "; and ".join(friendly) if len(friendly) > 1 else friendly[0]
    return f"We widened the range because {joined}."


def signals_plain(est):
    """
    The cross-station gradient signals, in plain language - only the ones
    that are actually saying something. Returns a list of (emoji, text)
    surfaced as 'what might change things' notes. Kept honest: these are
    early, experimental signals, and we say so.
    """
    out = []
    mp = est.get("marine_push_index")
    of = est.get("offshore_flow_index")
    ptrend = est.get("pressure_trend_inhg_per_hr")

    if mp is not None and mp > MARINE_PUSH_INDEX_THRESHOLD:
        out.append((
            "🌊",
            "Cool marine air may be pushing in from the coast over the next hour "
            "or two — Seattle's typical afternoon sea-breeze cool-down. If it "
            "arrives, temperatures could dip a bit faster than the trend alone "
            "suggests.",
        ))
    if of is not None and of > OFFSHORE_FLOW_INDEX_THRESHOLD:
        out.append((
            "🔥",
            "Warm, dry air from east of the Cascades looks like it may be sliding "
            "toward the coast — the pattern behind most real heat spells here. It "
            "can push temperatures higher than a normal day.",
        ))
    if ptrend is not None and ptrend < -0.015:
        out.append((
            "📉",
            "The air pressure is falling, which usually means a weather system is "
            "on the way and conditions are more likely to shift.",
        ))
    return out


# --- the last-6-hours sparkline (same visual as the KSEA dashboard) --------

def build_sparkline_svg(times, temps, est_time, est_temp, width=640, height=170):
    pad_x, pad_top, pad_bottom = 8, 32, 30
    all_temps = temps + [est_temp]
    lo, hi = min(all_temps), max(all_temps)
    span = max(hi - lo, 1)
    lo -= span * 0.15
    hi += span * 0.15
    span = hi - lo

    t0 = times[0]
    total_seconds = (est_time - t0).total_seconds() or 1

    def xy(t, temp):
        x = pad_x + (width - 2 * pad_x) * ((t - t0).total_seconds() / total_seconds)
        y = pad_top + (height - pad_top - pad_bottom) * (1 - (temp - lo) / span)
        return x, y

    pts = [xy(t, v) for t, v in zip(times, temps)]
    est_pt = xy(est_time, est_temp)

    line_path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area_path = (
        line_path + f" L {pts[-1][0]:.1f},{height - pad_bottom} "
        f"L {pts[0][0]:.1f},{height - pad_bottom} Z"
    )
    proj_path = f"M {pts[-1][0]:.1f},{pts[-1][1]:.1f} L {est_pt[0]:.1f},{est_pt[1]:.1f}"
    est_label_y = max(est_pt[1] - 14, 12)

    return f"""
<svg viewBox="0 0 {width} {height}" class="sparkline" preserveAspectRatio="none" role="img" aria-label="Temperature over the last {SPARKLINE_HOURS} hours and the estimate for a few hours ahead">
  <path d="{area_path}" class="spark-area" />
  <path d="{line_path}" class="spark-line" />
  <path d="{proj_path}" class="spark-proj" />
  <line x1="{est_pt[0]:.1f}" y1="{est_pt[1]:.1f}" x2="{est_pt[0]:.1f}" y2="{height - pad_bottom:.1f}" class="spark-est-guide" />
  <circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3.5" class="spark-now-dot" />
  <circle cx="{est_pt[0]:.1f}" cy="{est_pt[1]:.1f}" r="9" class="spark-est-dot-halo" />
  <circle cx="{est_pt[0]:.1f}" cy="{est_pt[1]:.1f}" r="5.5" class="spark-est-dot" />
  <text x="{est_pt[0]:.1f}" y="{est_label_y:.1f}" text-anchor="end" class="spark-est-label">{est_temp:.0f}°</text>
</svg>
""".strip()


def why_block(summary_text, detail_html):
    """A tap/click-to-expand 'Why?' element - native <details>, works with no
    JS and on mobile taps."""
    return (
        f'<details class="why"><summary>{summary_text}</summary>'
        f'<div class="why-body">{detail_html}</div></details>'
    )


def build_error_page(message):
    """Honest failure page - shown if KBFI observations can't be reached. We
    deliberately do NOT fall back to another station's numbers relabeled as
    Fremont."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fremont Weather — data unavailable</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:#0f172a;color:#e2e8f0;display:grid;place-items:center;min-height:100vh;margin:0;padding:2rem;text-align:center}}
.box{{max-width:32rem}}h1{{font-size:1.4rem}}p{{color:#94a3b8;line-height:1.6}}code{{color:#f8b4b4}}</style>
</head><body><div class="box">
<h1>🌧️ Fremont weather is briefly unavailable</h1>
<p>We couldn't reach live observations from {esc(OBS_STATION_LABEL)} just now, so
there's nothing fresh to show. Rather than show you another location's weather
dressed up as Fremont's, we'd rather say nothing.</p>
<p>This usually clears up on its own — check back in a few minutes.</p>
<p><code>{esc(message)}</code></p>
</div></body></html>"""


def main():
    # --- run the real model for Fremont (never falls back to KSEA) ---------
    try:
        est = estimate_temp(
            STATION, hours_ahead=HOURS_AHEAD,
            lat=FREMONT_LAT, lon=FREMONT_LON, location_name=LOCATION_NAME,
        )
        extremes = estimate_daily_extremes(
            STATION, lat=FREMONT_LAT, lon=FREMONT_LON, location_name=LOCATION_NAME,
        )
    except Exception as e:
        print(f"Model run failed for {STATION}: {e}")
        out_path = os.environ.get(
            "DASHBOARD_OUTPUT_PATH",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "index.html"),
        )
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
    lo, hi = float(est["estimated_range_f"][0]), float(est["estimated_range_f"][1])
    band_half = (hi - lo) / 2

    unsettled = bool(est.get("uncertainty_note")) or band_half > 3.0
    mood_class, hero_emoji, vibe_phrase = pick_mood(
        cloud_fraction, is_day, short_forecast, pop, unsettled
    )

    # Plain-language condition line for the hero.
    if short_forecast:
        condition_text = short_forecast
    elif cloud_fraction is None:
        condition_text = "conditions unavailable"
    elif cloud_fraction <= 0.15:
        condition_text = "Clear" if not is_day else "Sunny"
    elif cloud_fraction <= 0.5:
        condition_text = "Partly cloudy"
    elif cloud_fraction <= 0.85:
        condition_text = "Mostly cloudy"
    else:
        condition_text = "Overcast"

    # --- estimate + its plain-language explanation -------------------------
    conf_headline, conf_detail = confidence_sentence(est, now, lat, lon)
    band_html = band_sentence(lo, hi, est["estimated_temp_f"])
    widen_html = widen_sentence(est.get("uncertainty_note"))

    # honest "why?" for the estimate: the real chain, in plain-ish words
    n_obs = est["n_observations"]
    trend = est["raw_trend_f_per_hr"]
    trend_dir = "rising" if trend > 0.1 else ("falling" if trend < -0.1 else "flat")
    nws_temp = est.get("nws_forecast_temp_f")
    blend_w = est.get("blend_weight_used")
    if nws_temp is not None and blend_w is not None:
        if blend_w <= 0.3:
            blend_line = (
                f"Our trend and the National Weather Service's hourly forecast for "
                f"Fremont ({nws_temp:.0f}°) disagreed by more than a few degrees, so we "
                f"leaned mostly on the forecast — it can see incoming weather our short "
                f"local trend can't."
            )
        else:
            blend_line = (
                f"Our trend and the National Weather Service's hourly forecast for "
                f"Fremont ({nws_temp:.0f}°) roughly agreed, so we blended them evenly."
            )
    else:
        blend_line = (
            "The National Weather Service hourly forecast wasn't available for this "
            "exact time, so we're using our own trend estimate alone."
        )

    est_why = why_block(
        "Why this number?",
        f"<p>We start from how the temperature at {esc(OBS_STATION_LABEL)} has moved over "
        f"its last {n_obs} readings — right now that's <strong>{trend_dir}</strong> "
        f"(about {trend:+.1f}° per hour).</p>"
        f"<p>{esc(conf_detail)} That's why we don't just extend the line straight out.</p>"
        f"<p>{blend_line}</p>"
        f"<p>Finally we keep the number consistent with today's expected high and low, so "
        f"a few-hours-ahead estimate can't accidentally overshoot the day's peak.</p>",
    )

    band_why = why_block(
        "Why a range instead of one number?",
        "<p>No honest short-term temperature estimate is a single exact number — so we "
        "show the range we actually expect. It starts around ±1° and grows the further "
        "ahead we look.</p>"
        + (f"<p>{esc_strip_tags(widen_html)}</p>" if widen_html else
           "<p>Right now nothing unusual is widening it beyond that baseline.</p>"),
    )

    # --- today's high / low ------------------------------------------------
    high_status = extremes["high_status"]
    if high_status == "observed":
        high_caption = f"today's high so far, hit at {_fmt_time(extremes['observed_high_so_far_time'])}"
    else:
        high_caption = f"expected around {_fmt_time(extremes['estimated_high_time'])} (the warmest part of the day)"

    low_status = extremes["low_status"]
    if low_status == "today":
        low_caption = f"tonight's low is almost here, around {_fmt_time(extremes['estimated_low_time'])}"
    else:
        low_caption = f"expected overnight, around {_fmt_day_time(extremes['estimated_low_time'])}"

    high_why = why_block(
        "How do we know?",
        (f"<p>The high already happened — {extremes['estimated_high_f']:.0f}° was the "
         f"warmest reading at {esc(OBS_STATION_LABEL)} so far today.</p>"
         if high_status == "observed" else
         "<p>Today's warmest hour hasn't arrived yet, so this is a projection: we take the "
         "recent trend, damp it as the day approaches its natural peak, and cross-check it "
         "against the National Weather Service forecast. It's a floor-ish estimate — the "
         "real peak could edge higher.</p>"),
    )

    low_source = extremes.get("low_source")
    low_src_line = {
        "nws_forecast": "This comes straight from the National Weather Service's hourly "
                        "forecast for Fremont at that hour.",
        "trend_model": "Tonight's low is close enough that our short-term trend model "
                       "handles it directly.",
        "dewpoint_fallback": "The forecast wasn't available, so we estimated it from how "
                             "far the air can radiatively cool tonight (toward the dew "
                             "point, unless clouds or wind hold it up).",
    }.get(low_source, "")
    low_why = why_block("How do we know?", f"<p>{low_src_line}</p>")

    # --- tomorrow ----------------------------------------------------------
    tmrw_high = extremes["tomorrow_high_f"]
    tmrw_low = extremes["tomorrow_low_f"]
    tmrw_source = extremes["tomorrow_high_source"]
    if tmrw_source == "nws_forecast":
        tmrw_note = (
            "From the National Weather Service's next-day forecast (a real weather model, "
            "not our own trend guess). A day out, even the pros have real uncertainty."
        )
    else:
        tmrw_note = (
            "The forecast wasn't reachable, so this is a rough persistence guess (similar "
            "to today, nudged by the pressure trend). Treat it as a ballpark."
        )

    # --- 'what might change things' ---------------------------------------
    signal_notes = signals_plain(est)
    if signal_notes:
        signals_html = "".join(
            f'<div class="signal"><span class="signal-emoji">{e}</span>'
            f'<span>{esc(t)}</span></div>'
            for e, t in signal_notes
        )
        signals_html += (
            '<p class="signal-caveat">These are early-warning signals from weather '
            'stations around Puget Sound (the coast, the Strait, and east of the '
            'mountains). They\'re experimental — they widen our uncertainty rather than '
            'move the headline number.</p>'
        )
    else:
        signals_html = (
            '<div class="signal"><span class="signal-emoji">✅</span><span>Nothing unusual '
            'brewing right now — the stations around Puget Sound aren\'t showing an '
            'incoming marine push or heat surge.</span></div>'
        )

    # --- sparkline ---------------------------------------------------------
    try:
        window_start = now - timedelta(hours=SPARKLINE_HOURS)
        hist = get_observation_history(STATION, start=window_start, end=now)
        times = list(hist["time"])
        temps = list(hist["temp_f"])
        sparkline_svg = build_sparkline_svg(
            times, temps, est["target_time"], est["estimated_temp_f"]
        )
    except Exception as e:
        print(f"Sparkline history unavailable: {e}")
        sparkline_svg = '<p class="hint">Recent history unavailable right now.</p>'

    # --- yesterday (light context) ----------------------------------------
    if extremes["yesterday_high_f"] is not None:
        yesterday_line = (
            f"Yesterday: high {extremes['yesterday_high_f']:.0f}°, "
            f"low {extremes['yesterday_low_f']:.0f}°."
        )
    else:
        yesterday_line = ""

    wind_txt = f"{est['wind_mph']:.0f} mph" if est["wind_mph"] is not None else "calm"
    cloud_txt = (
        f"{round(cloud_fraction * 100)}% cloud cover" if cloud_fraction is not None else "—"
    )
    pop_txt = f"{pop}% chance of rain" if pop is not None else None

    ctx = {
        "location_name": LOCATION_NAME,
        "mood_class": mood_class,
        "hero_emoji": hero_emoji,
        "vibe_phrase": esc(vibe_phrase),
        "current_temp": f"{est['current_temp_f']:.0f}",
        "condition_text": esc(condition_text),
        "as_of_time": _fmt_time(now),
        "as_of_date": now.strftime("%A, %B %-d"),
        "obs_station_label": esc(OBS_STATION_LABEL),
        "wind_txt": esc(wind_txt),
        "cloud_txt": esc(cloud_txt),
        "pop_chip": f'<span class="chip">☔ {pop}%</span>' if pop_txt else "",
        "hours_ahead": HOURS_AHEAD,
        "target_time": _fmt_day_time(est["target_time"]),
        "estimated_temp": f"{est['estimated_temp_f']:.0f}",
        "conf_headline": esc(conf_headline),
        "conf_detail": esc(conf_detail),
        "band_html": band_html,
        "widen_html": widen_html,
        "est_why": est_why,
        "band_why": band_why,
        "sparkline_svg": sparkline_svg,
        "sparkline_hours": SPARKLINE_HOURS,
        "daily_high": f"{extremes['estimated_high_f']:.0f}",
        "high_caption": esc(high_caption),
        "high_why": high_why,
        "daily_low": f"{extremes['estimated_low_f']:.0f}",
        "low_caption": esc(low_caption),
        "low_why": low_why,
        "tomorrow_high": f"{tmrw_high:.0f}",
        "tomorrow_low": f"{tmrw_low:.0f}",
        "tomorrow_note": esc(tmrw_note),
        "signals_html": signals_html,
        "yesterday_line": esc(yesterday_line),
        "generated_at": _fmt_time(now) + " · " + now.strftime("%b %-d"),
        "data_json": esc(json.dumps(est, default=str, indent=2)),
    }

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "template.html")) as f:
        template = f.read()
    for key, value in ctx.items():
        template = template.replace("{{" + key + "}}", str(value))

    default_out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "docs", "index.html"
    )
    out_path = os.environ.get("DASHBOARD_OUTPUT_PATH", default_out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(template)
    print(f"Wrote {out_path}")


def esc_strip_tags(s):
    """widen_html already contains safe <strong>-free text; it's our own copy,
    so pass it through. Named helper kept so the intent is explicit."""
    return s


if __name__ == "__main__":
    main()
