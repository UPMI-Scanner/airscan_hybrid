# AirScan Hybrid Dashboard

A high-visibility, curses-based terminal dashboard for monitoring aviation and marine radio communications using `rtl_airband`.

AirScan Hybrid turns standard RTL-SDR dongles into an automated scanning station, providing dynamic sorting, real-time signal strength metrics, visual SNR metering, and automated audio housekeeping in a clean terminal user interface (TUI).

---

## Key Features

* **Dynamic Adaptive Sorting (`S` Key):** Cycle on-the-fly between **Frequency** (numerical order), **Most Hits** (highest activity channels ranked at the top), and **Recent** (most recently active frequencies jump immediately to row 1).
* **Real-Time SNR Metering:** Automatic Signal-to-Noise Ratio calculation paired with a dynamic ASCII bar graph and colored signal ramps (Green for strong, Yellow for moderate, Red for weak).
* **Configurable Auto-Pruning Housekeeper:** Background thread automatically purges old audio clips after a user-defined retention period, or can be disabled entirely to keep all recordings indefinitely.
* **Timestamped Audio Filenames:** Recordings are saved with exact date and time templates (`airband_YYYYMMDD_HHMMSS`), eliminating filename collisions.
* **Auto-Generated Configuration:** Automatically generates a clean, valid `rtl_airband.conf` on launch by parsing a standard `channels.csv` list.
* **Smooth Channel Scrolling:** Navigate long frequency lists with standard Up/Down arrow keys.
* **12-Hour Activity Clock:** Formats all scan events, transmission logs, and headers using standard 12-hour time (`HH:MM:SS AM/PM`).

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

## Channel Setup (`channels.csv`)

Add, edit, or remove monitoring channels using standard CSV formatting in `channels.csv`:

```csv
Frequency,Name
118.100,Local Tower
122.800,Unicom CTAF
121.500,Aviation Emergency
133.550,ZMP Center
```

* **Column 1:** Frequency in MHz
* **Column 2:** Channel label / agency description

---

## Audio Retention & Auto-Prune Configuration

You can customize how long recorded audio clips are kept before being pruned, or turn pruning off completely.

Open `hybrid_ui.py` in any text editor and adjust `RETENTION_HOURS` under the **HARDWARE & SCANNER SETTINGS** section near the top:

```python
# Keep recordings for 48 hours (default is 24)
RETENTION_HOURS = 48

# Keep recordings forever (disables auto-deletion entirely)
RETENTION_HOURS = 0
```

* **Any positive number (`1`, `24`, `72`):** Purges audio files older than that number of hours.
* **`0`:** Disables the background pruning housekeeper completely so all audio is preserved indefinitely.

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

This dashboard requires **rtl_airband** installed on the host system to serve as the radio scanning engine:
* [RTLSDR-Airband GitHub Repository](https://github.com/szpajder/RTLSDR-Airband) by Tomasz Lemiech (`szpajder`).
