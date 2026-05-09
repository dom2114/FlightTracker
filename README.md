# RGB Matrix Flight Tracker — `dom2114` fork

This is a fork of [ColinWaddell/FlightTracker](https://github.com/ColinWaddell/FlightTracker). Colin's upstream relies on FlightRadar24, which restricted public API access in 2025 and broke that project. This fork swaps the data source so it works again, and adds a few display tweaks.

## Differences from upstream

### Data source: airplanes.live + ADSB.lol (no API key required)
- Replaced the `FlightRadarAPI` Python library with direct calls to two public, no-auth endpoints:
  - `https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}` — live aircraft within a search radius (position, altitude, ground speed, heading, registration)
  - `https://vrs-standing-data.adsb.lol/routes/{prefix}/{cs}.json` — origin/destination lookup per callsign
- Dropped Python deps that were only needed by FR24: `FlightRadarAPI`, `beautifulsoup4`, `Brotli`, `soupsieve`
- New optional `config.py` knob: `SEARCH_RADIUS_NM` (default `100`, max `250` for airplanes.live)

### Search area: radius first, then `ZONE_HOME` rectangle
- airplanes.live is queried as a circle of `SEARCH_RADIUS_NM` around `LOCATION_HOME`. Results are then narrowed to the `ZONE_HOME` rectangle (if set) before being displayed
- Set `ZONE_HOME = None` (or omit it from `config.py`) to disable the rectangle filter and use the radius only
- Upstream's `ZONE_HOME` was a no-op in earlier versions of this fork — it is now wired up

### Higher altitude ceiling
- `MAX_ALTITUDE` raised from 10,000 ft to 60,000 ft so cruising airliners and business jets are no longer filtered out

### Flight numbers shown in IATA format (e.g. `AA100`, not `AAL100`)
- airplanes.live broadcasts ADS-B callsigns in ICAO format (e.g. `AAL100` for "American 100"); IATA format (`AA100`) is what passengers actually see on tickets and boards
- On startup, [`utilities/overhead.py`](utilities/overhead.py) downloads the [vradarserver airlines dataset](https://github.com/vradarserver/standing-data) (~1,400 ICAO→IATA mappings) and caches it both in memory and to `utilities/_airlines_cache.csv` on disk
- On subsequent startups the cached copy is used immediately if the network fetch fails, so flight numbers keep working offline
- A startup warning is printed if the mapping cannot be loaded from network or cache (in that case the display falls back to the raw ICAO callsign)
- Falls back to the raw callsign when the airline genuinely isn't in the mapping (e.g. private registrations like `N12345`, charter callsigns)

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
| [`utilities/overhead.py`](utilities/overhead.py) | Data-source rewrite (FR24 → airplanes.live + ADSB.lol); ICAO→IATA airline lookup with on-disk cache fallback; `ZONE_HOME` rectangle wired up as a real post-fetch filter; new fields (`registration`, `flnum`, `speed`, `heading`) in the data dict; `MAX_ALTITUDE` raised to 60,000 ft; `SEARCH_RADIUS_NM` config option |
| [`scenes/flightdetails.py`](scenes/flightdetails.py) | Render `flnum` (IATA marketing number) instead of raw callsign; alpha-colour tweak |
| [`scenes/planedetails.py`](scenes/planedetails.py) | Add `heading_to_ordinal()`; build richer plane-details line; faster scroll |
| [`requirements.txt`](requirements.txt) | Drop FR24-specific dependencies |
| [`config.py.example`](config.py.example) | Template config pre-tuned for an Adafruit Bonnet + PWM bridge setup; copy to `config.py` and edit location values |
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
git clone https://github.com/ColinWaddell/FlightTracker
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

The values you'll most likely want to change are `LOCATION_HOME` (your latitude/longitude), `ZONE_HOME` (the bounding box of the area you care about), `WEATHER_LOCATION`, and `JOURNEY_CODE_SELECTED` (your nearest airport's IATA code).

The hardware-specific values (`HAT_PWM_ENABLED`, `GPIO_SLOWDOWN`, `BRIGHTNESS`) are pre-set for an Adafruit Bonnet with the PWM solder bridge — leave them alone unless your hardware differs.

To save and exit nano hit `Ctrl-X` followed by `Y`.

### Configuration file details 

| Variable                 | Description |
|--------------------------|-------------|
| `ZONE_HOME`              | Bounding box (lat/long rectangle) within which flights are displayed. Applied *after* the radius fetch, so the search circle must be large enough to cover the rectangle. Set to `None` to disable rectangle filtering. |
| `SEARCH_RADIUS_NM`       | Radius of the airplanes.live live-aircraft query in nautical miles. Default `100`, max `250`. *(Optional)* |
| `LOCATION_HOME`          | Latitude/longitude of your home. |
| `WEATHER_LOCATION`       | City used to display the temperature. Format: `"City"` or `"City,Province/State,Country"` (e.g., `"Paris"` or `"Paris,Ile-de-France,FR"`). |
| `OPENWEATHER_API_KEY`    | If provided, enables OpenWeather API. [Get a free key here](https://openweathermap.org/price). *(Optional)* |
| `TEMPERATURE_UNITS`      | One of `"metric"` or `"imperial"`. Defaults to `"metric"`. |
| `MIN_ALTITUDE`           | Removes planes below this altitude (in feet). Useful for filtering out planes on the tarmac. |
| `BRIGHTNESS`             | Range 0–100. Adjusts brightness of the display. |
| `GPIO_SLOWDOWN`          | Range 0–4. Higher values help reduce flickering on faster hardware (e.g., `2` for Pi Zero 2 W). |
| `JOURNEY_CODE_SELECTED`  | Three-letter airport code of a local airport to display in **bold**. *(Optional)* |
| `JOURNEY_BLANK_FILLER`   | Three-letter text used in place of an unknown airport. Defaults to `" ? "`. |
| `HAT_PWM_ENABLED`        | Enables PWM via Pi’s soundcard. Requires [solder bridge modification](https://learn.adafruit.com/assets/57727). Defaults to `True`. |


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
