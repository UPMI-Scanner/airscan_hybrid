# AirScan Hybrid ✈️
A DSP-based AM aviation scanner with hit tracking and a perfectly aligned terminal UI. 

*AirScan Hybrid is a custom Python UI frontend powered by the excellent rtl_airband engine.*

## Why Hybrid?
Traditional scanner scripts use "hardware sweeping"—rapidly tuning the physical SDR chip back and forth. This causes micro-drops in audio and choppy voices. AirScan Hybrid fixes this by using Digital Signal Processing (DSP) to park the dongle in one spot, listening to a massive chunk of the aviation band simultaneously for crystal-clear, drop-free AM audio.

## Features
* **Simultaneous Monitoring:** Never miss a transmission due to hardware scanning lag.
* **Hit Tracking:** Live counters keep track of which channels are the most active.
* **Active Filter:** Press `[F]` to instantly hide dead air and only display active frequencies.
* **Bulletproof Grid:** A mathematically locked terminal interface that never breaks alignment.

## Setup & Installation

**1. Prerequisite:** You must have `rtl_airband` installed on your Linux system.

**2. Download the Code:** Open your terminal and paste this command to clone the repository and enter the folder:
```bash
git clone https://github.com/UPMI-Scanner/airscan_hybrid.git
cd airscan_hybrid
```

**3. Add Your Frequencies:** Open the `channels.csv` file and add your local frequencies.

**4. Select Your Hardware:** Open `hybrid_ui.py` and edit the **SCANNER SETTINGS** block at the very top to match your SDR dongle.

**5. Launch:** Run the dashboard:
```bash
python3 hybrid_ui.py
```
