# AirScan Hybrid Dashboard

A high-visibility, curses-based terminal dashboard for monitoring aviation and marine radio communications using `rtl_airband`.

AirScan Hybrid turns standard RTL-SDR dongles into an automated scanning station, providing dynamic sorting, real-time signal strength metrics, visual SNR metering, automated audio housekeeping, and support for **Single-SDR** or **Dual-SDR** operation in a clean terminal user interface (TUI).

---

![AirScan Hybrid Dashboard](screenshot.png)

---

## Key Features

* **Single or Dual-Dongle Architecture:** Monitor a single receiver or run two RTL-SDR dongles simultaneously to sweep two separate frequency bands (e.g., VHF Civilian and UHF Military) without missing traffic.
* **Dynamic Adaptive Sorting (`S` Key):** Cycle on-the-fly between **Frequency** (numerical order), **Most Hits** (highest activity channels ranked at the top), and **Recent** (most recently active frequencies jump immediately to row 1).
* **Real-Time SNR Metering:** Automatic Signal-to-Noise Ratio calculation paired with a dynamic ASCII bar graph and colored signal ramps (Green for strong, Yellow for moderate, Red for weak).
* **Centralized Configuration (`settings.json`):** Set receiver gains, squelch thresholds, serial IDs, and audio retention without editing source code.
* **Automated Housekeeper:** Background thread purges old audio recordings after a user-defined retention period, or can be disabled to preserve all recordings.
* **Timestamped Audio Filenames:** Recordings are saved with date and time templates (`airband_YYYYMMDD_HHMMSS`), preventing filename collisions.
* **Auto-Generated Configuration:** Automatically generates a valid `rtl_airband.conf` on startup from your CSV frequency list and settings.
* **12-Hour Activity Clock:** Formats all scan events and logs using standard 12-hour time (`HH:MM:SS AM/PM`).

---

## Installation & Setup

1. **Clone the repository:**
```bash
git clone https://github.com/UPMI-Scanner/airscan_hybrid.git
cd airscan_hybrid
```

2. **System Requirements:**
* Linux (Debian, Ubuntu, Raspberry Pi OS, Mint, etc.)
* Python 3.8+
* `rtl_airband` installed and accessible in your system `$PATH`

---

## Hardware Configuration (`settings.json`)

Settings are managed in `settings.json`. If this file is missing, AirScan Hybrid creates it automatically on first launch:

```json
{
  "dual_dongle_mode": false,
  "retention_hours": 24,
  "device_1": {
    "name": "Receiver 1",
    "device": "serial = \"SDR1\";",
    "gain": 33.0,
    "squelch": 19.0
  },
  "device_2": {
    "name": "Receiver 2",
    "device": "serial = \"SDR2\";",
    "gain": 33.0,
    "squelch": 19.0
  }
}
```

### Single Dongle vs. Dual Dongle

* **Single Dongle Mode (Default):**
  * Leave `"dual_dongle_mode": false`.
  * The dashboard monitors all channels through `device_1`.
  * Point `"device"` to your hardware identifier (e.g., `serial = "SDR1";` or `index = 0;`).

* **Dual Dongle Mode:**
  * Set `"dual_dongle_mode": true`.
  * The dashboard sweeps `device_1` and `device_2` simultaneously with independent gain and squelch thresholds.
  * Point each device to its respective identifier (e.g., `serial = "SDR1";` and `serial = "SDR2";`).

* **`retention_hours`:** Number of hours to keep recorded audio files before pruning. Set to `0` to keep all audio files indefinitely.

---

## Channel Setup (`channels.csv`)

### Standard Format (Single Dongle)
In single-dongle mode, use standard 2-column CSV formatting:

```csv
Frequency,Name
118.100,Local Tower
122.800,Unicom CTAF
121.500,Aviation Emergency
133.550,Overhead Center
```

### Dual Dongle Format
In dual-dongle mode, add an optional 3rd column specifying which dongle (`1` or `2`) monitors that frequency:

```csv
Frequency,Name,Dongle
118.100,Local Tower,1
122.800,Unicom CTAF,1
292.200,Tactical Ops,2
379.100,Refuel Track,2
```

*(Any channel left without a 3rd column defaults automatically to Dongle 1).*

---

## Usage

Launch the dashboard directly from your terminal:

```bash
python3 hybrid_ui.py
```

---

## Keyboard Controls

| Key | Action |
| :--- | :--- |
| **`↑` / `↓`** | Scroll up or down through the channel list |
| **`S`** | Cycle sorting modes (**Frequency** → **Most Hits** → **Recent**) |
| **`R`** | Reset all channel hit counters to zero |
| **`Q`** | Quit dashboard and cleanly shut down the SDR background engine |

---

## Acknowledgments & Prerequisites

This dashboard requires **rtl_airband** installed on the host system to serve as the scanning engine:
* [RTLSDR-Airband GitHub Repository](https://github.com/szpajder/RTLSDR-Airband) by Tomasz Lemiech (`szpajder`).
