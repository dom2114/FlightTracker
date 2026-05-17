# RGB Matrix Flight Tracker — `dom2114` fork

This is a fork of [ColinWaddell/FlightTracker](https://github.com/ColinWaddell/FlightTracker). Colin's upstream relies on FlightRadar24, which restricted public API access in 2025 and broke that project. This fork swaps the data source so it works again, and adds a few display tweaks.

## Differences from upstream

### Data source: airplanes.live + ADSB.lol (no API key required)
- Replaced the `FlightRadarAPI` Python library with direct calls to two public, no-auth endpoints:
  - `https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}` — live aircraft within a search radius (position, altitude, ground speed, heading, registration)
  - `https://vrs-standing-data.adsb.lol/routes/{prefix}/{cs}.json` — origin/destination lookup per callsign
- Dropped Python deps that were only needed by FR24: `FlightRadarAPI`, `beautifulsoup4`, `Brotli`, `soupsieve`
- New optional `config.py` knob: `SEARCH_RADIUS_NM` (template default `10`, max `250` for airplanes.live)

### Search area: radius with defensive client-side filter
- airplanes.live is queried as a circle of `SEARCH_RADIUS_NM` around `LOCATION_HOME`
- Returned aircraft are re-checked locally with a haversine distance calculation and any that fall outside `SEARCH_RADIUS_NM` are dropped — the upstream API occasionally returns craft slightly outside the requested circle, this guarantees the display honours the configured radius
- The radius check is horizontal ground distance in nautical miles; altitude is only used later when choosing which in-radius aircraft are closest to home
- Upstream's `ZONE_HOME` rectangle filter has been removed in this fork; the radius alone defines the search area

### Higher altitude ceiling
- `MAX_ALTITUDE` raised from 10,000 ft to 60,000 ft so cruising airliners and business jets are no longer filtered out

### Flight numbers shown in IATA format (e.g. `AA100`, not `AAL100`)
- airplanes.live broadcasts ADS-B callsigns in ICAO format (e.g. `AAL100` for "American 100"); IATA format (`AA100`) is what passengers actually see on tickets and boards
- On startup, [`utilities/overhead.py`](utilities/overhead.py) downloads the [vradarserver airlines dataset](https://github.com/vradarserver/standing-data) (~1,400 ICAO→IATA mappings) and caches it both in memory and to `utilities/_airlines_cache.csv` on disk
- On subsequent startups the cached copy is used immediately if the network fetch fails, so flight numbers keep working offline
- A startup warning is printed if the mapping cannot be loaded from network or cache (in that case the display falls back to the raw ICAO callsign)
- Falls back to the raw callsign when the airline genuinely isn't in the mapping (e.g. private registrations like `N12345`, charter callsigns)

### Optional: real marketing flight numbers for compressed callsigns (airlabs.co)
- The cheap ICAO→IATA prefix swap above is correct for legacy carriers (BA, LH, AA, AF, KL, etc.) where the callsign suffix matches the marketing flight number. For low-cost carriers (Ryanair, easyJet, Wizz) the operational callsign is *compressed* — e.g. `EZY76HE` is the radio callsign for marketing flight `U28706`, with no deterministic relationship between `76HE` and `8706`. The mapping only exists in airline ops systems and licensed schedule data.
- Set `AIRLABS_API_KEY` in `config.py` to enable on-demand lookups via [airlabs.co](https://airlabs.co/) for compressed callsigns. Free tier is 1000 requests/month; sign-up at https://airlabs.co/signup gives an instant key.
- Lookup is by ADS-B hex code (since airlabs indexes by canonical callsigns rather than the operational compressed form). Pure-numeric callsigns are skipped — they cost zero API calls because the cheap conversion is already correct.
- Results are cached by `(callsign, UTC date)` so repeated sightings of the same flight cost nothing.
- `AIRLABS_MAX_CALLS_PER_DAY` (default 30) caps daily usage. On 401/429/HTTP errors the enricher backs off cleanly and falls back to the cheap conversion.
- Coverage caveat: airlabs covers all major carriers but a few smaller operators (e.g. Jet2 / EXS) aren't in their dataset. For compressed callsigns the display falls back to the raw ICAO callsign (e.g. `EXS17TU`) rather than fabricating a synthetic IATA-prefixed value (`LS17TU`) that doesn't appear on any ticket.

### Richer scrolling plane-details line
- The bottom scrolling line now shows: aircraft type, registration, altitude (with thousands separator), heading in degrees, ordinal compass direction, and ground speed in knots. For example:
  > `A320 - N123AA - Alt 35,000' - Hdg 270° (W) - GS 450 kts`
- New `heading_to_ordinal()` helper converts a heading in degrees to a compass ordinal (`N`, `NE`, `E`, …)
- Scroll speed increased from 1 px/frame to 3.3 px/frame so the longer text loops in a comparable on-screen time

### Flight-number colour tweak
- Alpha portion of the flight number recoloured (`colours.BLUE` → `colours.BLUE_LIGHT`) so it matches the numeric portion for a uniform look

## Files changed vs upstream

| File | Change |
|---|---|
| [`utilities/overhead.py`](utilities/overhead.py) | Data-source rewrite (FR24 → airplanes.live + ADSB.lol); ICAO→IATA airline lookup with on-disk cache fallback; client-side haversine radius filter so flights outside `SEARCH_RADIUS_NM` are never displayed; `ZONE_HOME` rectangle filter removed (radius alone defines the search area); optional airlabs.co marketing-flight-number enrichment for compressed callsigns; new fields (`registration`, `flnum`, `speed`, `heading`) in the data dict; `MAX_ALTITUDE` raised to 60,000 ft; `SEARCH_RADIUS_NM` config option |
| [`utilities/flightnumber_enricher.py`](utilities/flightnumber_enricher.py) | NEW — airlabs.co client with per-callsign caching, daily quota cap, and error backoff |
| [`scenes/flightdetails.py`](scenes/flightdetails.py) | Render `flnum` (IATA marketing number) instead of raw callsign; alpha-colour tweak |
| [`scenes/planedetails.py`](scenes/planedetails.py) | Add `heading_to_ordinal()`; build richer plane-details line; faster scroll |
| [`requirements.txt`](requirements.txt) | Drop FR24-specific dependencies |
| [`config.py.example`](config.py.example) | Template config pre-tuned for an Adafruit Bonnet + PWM bridge setup; copy to `config.py` and edit location values |
| [`tests/`](tests/) | Focused unit coverage for radius filtering, distance ordering, coordinate parsing, and airlabs cache reuse |
| [`.gitignore`](.gitignore) | Ignore local scratch folders + the on-disk airline-mapping cache |

---

# RGB Matrix Flight Tracker

- 📖 [Blog post about this project](https://blog.colinwaddell.com/flight-tracker/)
- ☢️ [Why you should **avoid** buying this pre-built from Flight Tracker LED](https://colinwaddell.com/articles/flight-tracker-led-ripoff-part-2-its-so-much-worse)
  - They are being sold with a hidden backdoor allowing remote access to your home network

[![Finished flight tracker showing a flight](https://blog.colinwaddell.com/user/pages/01.articles/02.flight-tracker/screen-flight-thumb.jpg)](https://blog.colinwaddell.com/user/pages/01.articles/02.flight-tracker/screen-flight-thumb.jpg)

# Setup

## Installation

The previous instructions were written against Debian Buster and can be found [at this commit](https://github.com/ColinWaddell/FlightTracker/blob/44aa282bdc54a897ab72cbd0dc49017f6a11c11a/README.md). People were starting to find the instructions didn't line up with the latest version of Debian Bookworm. These new instructions are less battle-tested than the previous version so if you run into any problems please raise it as an issue.

### Installation Guide

These instructions will assume that running the Flight Tracker on your Raspberry Pi is the only thing you're going to be doing with the device. The other assumptions are going to be:

- You've got your Raspberry Pi set up with Raspbian based on Debian Bookworm 
- The username of the device is `pi`
- If you're not using a screen/keyboard attached to the Pi then you've figured out how to remote edit over SSH

### Installation Locations

For future reference, in this installation process we're going to use the following locations:

| Location                                | Purpose                                                             |
| --------------------------------------- | ------------------------------------------------------------------- |
| `/home/pi/rpi-rgb-led-matrix`           | RGB Matrix Driver                                                   |
| `/home/pi/FlightTracker`           | The Flight Tracking software (this repo)                            |
| `/home/pi/FlightTracker/env`       | The virtual environment we'll install the necessary Python packages  |
| `/home/pi/FlightTracker/config.py` | Config file for this flight tracking software                       |

### First steps

Before installing anything let's ensure our system is up-to-date:

```
sudo apt-get update
sudo apt-get dist-upgrade
```

This will take a while on a fresh device as it picks up all its updates.

### Install the RGB Screen

1. Assemble the RGB matrix, Pi, and Bonnet as described in [this Adafruit guide](https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/overview).
2. It is recommended that the [solder bridge is added to the HAT](https://learn.adafruit.com/assets/57727) in order to use the Pi's soundcard to drive the device's PWM.
3. Please [read the official installation instructions](https://learn.adafruit.com/adafruit-rgb-matrix-bonnet-for-raspberry-pi/driving-matrices) for further details before proceeding **but don't run any commands or install anything yet**.
4. Use the following commands to install the `rgb-matrix` library. Please note the paths used in these instructions are used later in this guide and must be adhered to for everything to make sense.

```
cd /home/pi
curl https://raw.githubusercontent.com/adafruit/Raspberry-Pi-Installer-Scripts/main/rgb-matrix.sh > /tmp/rgb-matrix.sh
sudo bash /tmp/rgb-matrix.sh
```

5. If the installation has worked successfully then there should be some demo applications available to run. **For the Adafruit Bonnet you must pass `--led-gpio-mapping`** — without it the demo runs but produces a blank panel because the default `regular` mapping drives the wrong GPIO pins:

```
cd /home/pi/rpi-rgb-led-matrix/examples-api-use

# If you soldered the PWM bridge on the Bonnet (recommended):
sudo ./demo --led-rows=32 --led-cols=64 --led-gpio-mapping=adafruit-hat-pwm -D0

# If you did NOT solder the PWM bridge:
sudo ./demo --led-rows=32 --led-cols=64 --led-gpio-mapping=adafruit-hat -D0
```

You should see a clean rotating square. If it flickers or tears, add `--led-slowdown-gpio=2` (or `3`/`4`).

### Install this Flight Tracking software

1. Clone this repository:

```
cd /home/pi/
git clone https://github.com/dom2114/FlightTracker
```

2. Head into this repository and create a virtual environment, activate it and install all the dependencies

```
cd /home/pi/FlightTracker
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

3. Head into the rgb-matrix library and install the Python library into our virtual environment. These commands assume you are still using the same environment that we activated in the above steps. If not, rerun the `source` command in the `FlightTracker` directory.

```
cd /home/pi/rpi-rgb-led-matrix/bindings/python
pip install .
```

### Configure the Flight Tracking software for your location

The repo ships a [`config.py.example`](config.py.example) with sane defaults for an Adafruit Bonnet + PWM-bridge setup. Copy it and edit the location values:

```
cd /home/pi/FlightTracker
cp config.py.example config.py
nano config.py
```

The values you'll most likely want to change are `LOCATION_HOME` (your latitude, longitude, and altitude), `SEARCH_RADIUS_NM` (how wide a circle around home to display), `WEATHER_LOCATION`, and `JOURNEY_CODE_SELECTED` (your nearest airport's IATA code).

The hardware-specific values (`HAT_PWM_ENABLED`, `GPIO_SLOWDOWN`, `BRIGHTNESS`) are pre-set for an Adafruit Bonnet with the PWM solder bridge — leave them alone unless your hardware differs.

To save and exit nano hit `Ctrl-X` followed by `Y`.

### Configuration file details 

| Variable                 | Description |
|--------------------------|-------------|
| `SEARCH_RADIUS_NM`       | Radius (nautical miles) of the live-aircraft search around `LOCATION_HOME`. Applied both as the airplanes.live query parameter and as a client-side haversine cutoff. Template default `10`, max `250`. *(Optional)* |
| `LOCATION_HOME`          | Latitude, longitude, and altitude in kilometres for your home/search centre. |
| `WEATHER_LOCATION`       | City used to display the temperature. Format: `"City"` or `"City,Province/State,Country"` (e.g., `"Paris"` or `"Paris,Ile-de-France,FR"`). |
| `OPENWEATHER_API_KEY`    | If provided, enables OpenWeather API. [Get a free key here](https://openweathermap.org/price). *(Optional)* |
| `TEMPERATURE_UNITS`      | One of `"metric"` or `"imperial"`. Defaults to `"metric"`. |
| `MIN_ALTITUDE`           | Removes planes below this altitude (in feet). Useful for filtering out planes on the tarmac. |
| `BRIGHTNESS`             | Range 0–100. Adjusts brightness of the display. |
| `GPIO_SLOWDOWN`          | Range 0–4. Higher values help reduce flickering on faster hardware (e.g., `2` for Pi Zero 2 W). |
| `JOURNEY_CODE_SELECTED`  | Three-letter airport code of a local airport to display in **bold**. *(Optional)* |
| `JOURNEY_BLANK_FILLER`   | Three-letter text used in place of an unknown airport. Defaults to `" ? "`. |
| `HAT_PWM_ENABLED`        | Enables PWM via Pi’s soundcard. Requires [solder bridge modification](https://learn.adafruit.com/assets/57727). Defaults to `True`. |
| `AIRLABS_API_KEY`        | Optional airlabs.co API key for real marketing flight numbers on compressed callsigns. Leave blank to disable. |
| `AIRLABS_MAX_CALLS_PER_DAY` | Daily cap for airlabs.co enrichment calls. Defaults to `30`. |


### Configuring permissions to avoid running as root

Previous versions of the instructions always pointed out to run everything as root for performance reasons but for security I think this is best avoided. Plus the latest version of the GPIO driver and rgb-matrix have strong opinions about who is in charge when running as root.

To avoid running as root and to grant Python permission to set real-time scheduling priorities, grant the capability to the venv's Python interpreter (this survives OS Python upgrades and only affects this venv):

```
sudo setcap 'cap_sys_nice=eip' /home/pi/FlightTracker/env/bin/python3
```

### Running the software manually

The software can now be tested by running it from the command line

```
cd /home/pi/FlightTracker 
env/bin/python3 flight-tracker.py
```

To quit tap `Ctrl-C`.

### Running the software on start-up

This repo contains an example `.service` file to allow this software to be easily run on boot. Provided that the same paths have been used in your own installation as these instructions then you shouldn't need to edit this file.

```
sudo cp /home/pi/FlightTracker/assets/FlightTracker.service /etc/systemd/system/FlightTracker.service
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable FlightTracker.service
sudo systemctl start FlightTracker.service
```

Any problems, check the status and logs:

```
sudo systemctl status FlightTracker.service
journalctl -u FlightTracker.service -f
```

## Optional

### Loading LED
An LED can be wired to a GPIO on the Raspberry Pi which can then blink when data is being loaded.

To enable this add the following to your `config.py`. Adjust `LOADING_LED_GPIO_PIN` to suit your setup.

```
LOADING_LED_ENABLED = True
LOADING_LED_GPIO_PIN = 25
```

### Rainfall chart
If weather data is being pulled from my server (as opposed to using `OPENWEATHER_API_KEY`) then you can
display a chart of rainfall by adding the following to your `config.py`:

```
RAINFALL_ENABLED = True
```

[![Example Weather Chart](https://raw.githubusercontent.com/ColinWaddell/FlightTracker/refs/heads/master/assets/weather.jpg)](https://raw.githubusercontent.com/ColinWaddell/FlightTracker/refs/heads/master/assets/weather.jpg)

# License Update:
As of April 2025, Flight Tracker is released under the GNU General Public License v3.0

You’re welcome to use, modify, and share the code—just keep it under the same license and include
proper attribution (retain my copyright and license notice). See LICENSE for details.

[I had to add this license as folks have started selling these online as their own with zero attribution](https://colinwaddell.com/articles/flight-radar-ripoff). Open-source projects like this are our CVs: they show peers and potential employers what we can do. Passing off someone else’s work as your own robs us of our chance to promote ourselves.
