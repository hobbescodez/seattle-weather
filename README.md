# 🌦️ Seattle Weather

A friendly, honest weather page for **Seattle, Washington** — plus a live radar / wind / marine-layer map.

It runs the *same* temperature model that powers the KSEA dashboard — trend
extrapolation, diurnal (sunrise/sunset) damping, a cross-station gradient
network that watches for marine pushes and offshore/gap-flow heat events, and a
blend with the National Weather Service's own hourly forecast — but pointed at
Seattle, and written for someone who just wants to understand their weather
without needing to know what "diurnal damping" means.

The honesty of the underlying model is kept intact: it shows a real uncertainty
band, and when that band widens it tells you *why*, in plain language. What's
gone is the jargon — and everything else the KSEA project carried: no markets,
no betting, no trading. Just the weather.

## Live site

Deployed with **GitHub Pages** from the [`docs/`](docs/) folder on `main`:

```
https://hobbescodez.github.io/seattle-weather/
```

## How the location is wired

| Piece | Source | Why |
| --- | --- | --- |
| **Observations** (temp, wind, dew point, pressure) | **KBFI** — Boeing Field, ~5 mi south | Nearest full ASOS station to Seattle with real ground-truth readings |
| **Forecast + sunrise/sunset** | **NWS gridpoint** at `47.6510, -122.3500` | Seattle's own coordinates — `/points/{lat},{lon}` → `forecastHourly` |
| **Marine-push / offshore-flow signals** | Regional stations around Puget Sound (coast, Strait, east of the Cascades) | Physically shared across the Seattle lowland |

If KBFI observations can't be reached, the page says so plainly — it **never**
silently falls back to KSEA/Sea-Tac numbers relabeled as Seattle.

## The friendly layer

- **Plain-language confidence** — instead of "trend confidence 51%", a sentence
  that names the actual reason ("we're close to the warmest part of the day,
  when the temperature usually levels off, so exactly where it peaks is harder
  to call") — generated from the day's real situation, not hardcoded.
- **Expandable "Why?"** next to every key number — tap to reveal the honest
  detail (the trend, the damping, the NWS blend weight, the gradient signals)
  while the surface stays simple.
- **Weather-responsive** — the background, emoji, and tone shift with the actual
  conditions (sunny / cloudy / clear night / rain / an unsettled pattern), so it
  feels alive rather than static.
- **The uncertainty band and "why it widened" are always shown** — translated
  into friendly language, never stripped out for the sake of looking clean.
- **Radar / wind / marine-layer map** — a self-hosted [Leaflet](https://leafletjs.com)
  map of Puget Sound with a [RainViewer](https://www.rainviewer.com/api.html) radar
  overlay, a wind arrow, and a cloud-cover "marine layer" tint, all togglable. The map's
  live wind + cloud come from [Open-Meteo](https://open-meteo.com) (no key) — **only for
  the map**; the headline temperature estimate is still the real NWS-based model.

## Files

- [`weather_estimator.py`](weather_estimator.py) — the real model, unchanged
  except that the observing station and the forecast/sun location can be given
  separately (so it can run for a spot with no ASOS station of its own).
- [`build_site.py`](build_site.py) — runs the model for Seattle and renders the
  friendly page. No markets, no betting — just the estimator's core output,
  translated into plain language.
- [`template.html`](template.html) — the page layout and styling.
- [`docs/index.html`](docs/index.html) — the generated, GitHub-Pages-served page.

## Regenerate locally

```sh
pip install -r requirements.txt
python3 build_site.py          # writes docs/index.html from live data
python3 -m http.server -d docs 8000   # preview at http://localhost:8000
```

The page is also refreshed automatically by
[`.github/workflows/refresh.yml`](.github/workflows/refresh.yml) (hourly,
best-effort — see the note in that file).

## Enabling GitHub Pages

One-time, in repository settings (can't be toggled from a commit):

1. **Settings → Pages**
2. **Source** → *Deploy from a branch*
3. Branch **`main`**, folder **`/docs`** → **Save**
