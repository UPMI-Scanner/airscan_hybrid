# AirScan Hybrid Dashboard

A curses-based terminal interface for monitoring and controlling `rtl_airband` VHF/UHF aviation scanners with native C (`librtlsdr`) hardware discovery, live signal-to-noise (SNR) telemetry, frequency-tagged audio recordings, auto-pruning retention, and Single/Dual-SDR support.

## Keyboard Shortcuts & Live Controls

| Key | Action | Description |
| :--- | :--- | :--- |
| **`↑` / `↓`** | **Select / Scroll** | Move the `>` cursor selector up and down through the channel list |
| **`L` or `Space`** | **Lockout / Skip** | Toggle lockout on the selected frequency (skips birdies/spurs and reloads `rtl_airband`) |
| **`+` or `=`** | **Squelch Up** | Increase Squelch SNR threshold by `+1.0 dB` and reload on the fly |
| **`-` or `_`** | **Squelch Down** | Decrease Squelch SNR threshold by `-1.0 dB` and reload on the fly |
| **`G`** *(Shift+g)* | **Gain Up** | Increase RF Gain by `+1.0 dB` and reload on the fly |
| **`g`** *(lowercase)* | **Gain Down** | Decrease RF Gain by `-1.0 dB` and reload on the fly |
| **`S`** | **Cycle Sort Mode** | Toggle table sorting between **Frequency**, **Most Hits**, and **Recent Activity** |
| **`R`** | **Reset Hits** | Reset all channel hit counters (`#0`) for the current session |
| **`Q`** | **Quit** | Cleanly terminate `rtl_airband`, close PTY streams, and exit |

## Features
* **Native C Hardware Probe (`dsp_engine.c` / `libengine.so`):** Queries `librtlsdr` directly via `ctypes` to verify connected RTL-SDR dongles and serial strings prior to launch.
* **Live RF Tuning & Persistent Lockouts:** All Gain, Squelch, and Channel Lockout adjustments save automatically to `settings.json` and dynamically regenerate `rtl_airband.conf`.
* **Automatic Frequency Deduplication:** Prevents `rtl_airband` from wasting tuner hops on duplicate entries in `channels.csv`.
* **Per-Frequency Audio Recording & Auto-Pruning:** Records active voice traffic with `include_freq = true` and automatically prunes recordings older than `retention_hours`.
