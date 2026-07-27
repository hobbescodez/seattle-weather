# 🌦️ Fremont Weather

A tiny, dependency-free weather page for the **Fremont neighborhood of Seattle, WA** — *the Center of the Universe*. It shows current conditions, the next 12 hours, and a 7-day forecast.

## Live site

Deployed with **GitHub Pages** from the [`docs/`](docs/) folder on `main`.

Once Pages is enabled, the site is available at:

```
https://<owner>.github.io/seattle-weather/
```

## How it works

- A single self-contained [`docs/index.html`](docs/index.html) — no build step, no frameworks, no bundler.
- Live data comes from the free [Open-Meteo](https://open-meteo.com/) forecast API, fetched client-side in the browser. **No API key and no tracking.**
- Coordinates are pinned to Fremont, Seattle (`47.6510, -122.3500`), with temperatures in °F and times in America/Los_Angeles.

## Enabling GitHub Pages

This is a one-time manual step in the repository settings (it can't be toggled from a commit):

1. Go to **Settings → Pages**.
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Choose the **`main`** branch and the **`/docs`** folder, then **Save**.

GitHub will publish the site within a minute or two.

## Local preview

Just open the file, or serve the folder:

```sh
python3 -m http.server -d docs 8000
# then visit http://localhost:8000
```
