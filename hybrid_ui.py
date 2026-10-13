#!/usr/bin/env python3
"""AirScan Hybrid Dashboard.

A curses-based terminal interface for monitoring and controlling rtl_airband
scanners with live signal metrics, auto-pruning recordings, adaptive sorting,
and seamless Single-SDR or Dual-SDR support.
"""

from __future__ import annotations

import copy
import csv
import ctypes
import curses
from datetime import datetime
import json
import os
import pty
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
CSV_FILE: str = os.path.join(BASE_DIR, "channels.csv")
CONF_FILE: str = os.path.join(BASE_DIR, "rtl_airband.conf")
SETTINGS_FILE: str = os.path.join(BASE_DIR, "settings.json")
REC_DIR: str = os.path.join(BASE_DIR, "recordings")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "dual_dongle_mode": False,
    "retention_hours": 24,
    "locked_out": [],
    "device_1": {
        "name": "Receiver 1",
        "device": 'serial = "AIR";',
        "gain": 33.0,
        "squelch": 19.0,
    },
    "device_2": {
        "name": "Receiver 2",
        "device": 'serial = "SDR2";',
        "gain": 33.0,
        "squelch": 19.0,
    },
}

if not shutil.which("rtl_airband"):
    sys.exit("[CRITICAL ERROR] 'rtl_airband' binary not found in system PATH.")

if not os.path.exists(CSV_FILE):
    sys.exit(f"[CRITICAL ERROR] Channel definition file missing: {CSV_FILE}")

os.makedirs(REC_DIR, exist_ok=True)


def probe_sdr_hardware() -> str:
    for lib_name in ("libengine.so", "dsp_engine.so"):
        lib_path = os.path.join(BASE_DIR, lib_name)
        if os.path.exists(lib_path):
            try:
                lib = ctypes.CDLL(lib_path)
                lib.check_radio_count.restype = ctypes.c_int
                lib.get_radio_name.argtypes = [ctypes.c_int]
                lib.get_radio_name.restype = ctypes.c_char_p
                cnt = lib.check_radio_count()
                if cnt <= 0:
                    return "No RTL-SDR Detected"
                names = []
                for i in range(cnt):
                    n = lib.get_radio_name(i)
                    names.append(n.decode("utf-8", "ignore") if n else f"SDR#{i}")
                return f"{cnt}x SDR ({', '.join(names)})"
            except Exception:
                pass
    return "RTL-SDR Ready"


def load_settings() -> Dict[str, Any]:
    """Load settings from settings.json, creating defaults if missing."""
    if not os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SETTINGS, f, indent=2)
        except OSError:
            pass
        return copy.deepcopy(DEFAULT_SETTINGS)

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            settings = copy.deepcopy(DEFAULT_SETTINGS)
            if isinstance(data, dict):
                # Backwards compatibility for single-device configs
                if "sdr_device" in data and "device_1" not in data:
                    settings["device_1"] = {
                        "name": "Receiver 1",
                        "device": data.get("sdr_device", 'serial = "SDR1";'),
                        "gain": float(data.get("gain_level", 33.0)),
                        "squelch": float(data.get("squelch_level", 19.0)),
                    }
                settings.update(data)
            return settings
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(DEFAULT_SETTINGS)


def save_settings(settings: Dict[str, Any]) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


def build_config_from_csv(settings: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """Parse channels.csv and construct a single or multi-device rtl_airband configuration."""
    mapping: Dict[str, Dict[str, str]] = {}
    d1_freqs: List[str] = []
    d1_labels: List[str] = []
    d2_freqs: List[str] = []
    d2_labels: List[str] = []

    is_dual = bool(settings.get("dual_dongle_mode", False))

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            freq_str = row[0].strip().replace('"', "")
            name_str = row[1].strip().replace('"', "")

            target_dongle = "1"
            if is_dual and len(row) >= 3 and row[2].strip() in ("1", "2"):
                target_dongle = row[2].strip()

            if "freq" in freq_str.lower():
                continue

            try:
                f_mhz = float(freq_str)
                norm_key = f"{f_mhz:.3f}"
                if norm_key in mapping:
                    continue
                mapping[norm_key] = {"name": name_str, "dongle": target_dongle}
                locked_set = set(settings.get("locked_out", []))
                if norm_key in locked_set:
                    continue
                f_hz = str(int(round(f_mhz * 1_000_000)))

                if is_dual and target_dongle == "2":
                    d2_freqs.append(f_hz)
                    d2_labels.append(f'"{name_str}"')
                else:
                    d1_freqs.append(f_hz)
                    d1_labels.append(f'"{name_str}"')
            except ValueError:
                continue

    if not d1_freqs and not d2_freqs:
        sys.exit("[CRITICAL ERROR] 'channels.csv' contains no valid frequency entries.")

    d1_cfg = settings.get("device_1", DEFAULT_SETTINGS["device_1"])
    d2_cfg = settings.get("device_2", DEFAULT_SETTINGS["device_2"])

    device_blocks: List[str] = []

    if d1_freqs:
        dev1_target = d1_cfg.get("device", 'serial = "SDR1";')
        if not dev1_target.endswith(";"):
            dev1_target += ";"
        device_blocks.append(f"""  {{
    type = "rtlsdr";
    {dev1_target}
    gain = {d1_cfg.get('gain', 33.0)};
    mode = "scan";
    channels:
    ({{
      freqs = ( {', '.join(d1_freqs)} );
      labels = ( {', '.join(d1_labels)} );
      squelch_snr_threshold = {d1_cfg.get('squelch', 19.0)};
      outputs: (
        {{ type = "pulse"; }},
        {{
          type = "file";
          directory = "{REC_DIR}";
          filename_template = "airband_d1";
          include_freq = true;
        }}
      );
    }});
  }}""")

    if is_dual and d2_freqs:
        dev2_target = d2_cfg.get("device", 'serial = "SDR2";')
        if not dev2_target.endswith(";"):
            dev2_target += ";"
        device_blocks.append(f"""  {{
    type = "rtlsdr";
    {dev2_target}
    gain = {d2_cfg.get('gain', 33.0)};
    mode = "scan";
    channels:
    ({{
      freqs = ( {', '.join(d2_freqs)} );
      labels = ( {', '.join(d2_labels)} );
      squelch_snr_threshold = {d2_cfg.get('squelch', 19.0)};
      outputs: (
        {{ type = "pulse"; }},
        {{
          type = "file";
          directory = "{REC_DIR}";
          filename_template = "airband_d2";
          include_freq = true;
        }}
      );
    }});
  }}""")

    conf_content = "devices:\n(\n" + ",\n".join(device_blocks) + "\n);\n"
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        f.write(conf_content)

    return mapping


def start_housekeeper(directory: str, max_age_hours: int, stop_event: threading.Event) -> Optional[threading.Thread]:
    """Background worker that removes audio files exceeding the retention threshold."""
    if max_age_hours <= 0:
        return None

    def worker() -> None:
        while not stop_event.is_set():
            try:
                now = time.time()
                cutoff = now - (max_age_hours * 3600)
                if os.path.exists(directory):
                    for entry in os.scandir(directory):
                        if entry.is_file() and entry.stat().st_mtime < cutoff:
                            try:
                                os.remove(entry.path)
                            except OSError:
                                pass
            except Exception:
                pass
            for _ in range(600):
                if stop_event.is_set():
                    break
                time.sleep(1)

    t = threading.Thread(target=worker, daemon=True, name="HousekeeperThread")
    t.start()
    return t


def compute_snr_meter(sig_raw: str, noise_raw: str) -> Tuple[str, str, float]:
    """Calculate SNR, render ASCII bar, and return raw numerical SNR."""
    try:
        sig = float(sig_raw)
        noise = float(noise_raw)
        snr = max(0.0, sig - noise)
        filled = int(min(snr, 30.0) / 5.0)
        bar = "█" * filled + "·" * (6 - filled)
        return f"{int(snr):>2} dB", f"[{bar}]", snr
    except (ValueError, TypeError):
        return "-- dB", "[······]", -1.0


def curses_ui(stdscr: curses.window) -> None:
    """Primary terminal UI loop supporting single or dual SDR layouts."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.use_default_colors()

    # Color palette
    curses.init_pair(1, curses.COLOR_GREEN, -1)                   # Active Voice / High SNR
    curses.init_pair(2, curses.COLOR_CYAN, -1)                    # Frequencies / Headers
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)    # Main Title Bar
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                  # Moderate SNR / Hits
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)                 # Diagnostics / Raw Log
    curses.init_pair(6, curses.COLOR_RED, -1)                     # Weak SNR
    curses.init_pair(7, curses.COLOR_WHITE, -1)                   # Standard Text
    curses.init_pair(8, curses.COLOR_YELLOW, -1)                  # Dongle 2 Highlight

    settings = load_settings()
    is_dual = bool(settings.get("dual_dongle_mode", False))
    config_labels = build_config_from_csv(settings)

    msg_queue: queue.Queue[str] = queue.Queue()
    stop_housekeeper = threading.Event()
    start_housekeeper(REC_DIR, int(settings.get("retention_hours", 24)), stop_housekeeper)

    sort_mode = 0  # 0: Frequency, 1: Hits, 2: Recent Activity
    sort_names = ["Frequency", "Most Hits", "Recent"]
    scroll_offset = 0
    cursor_idx = 0
    locked_freqs = set(settings.get("locked_out", []))

    freq_data: Dict[str, dict] = {
        f_str: {
            "sig": "--",
            "noise": "--",
            "active": False,
            "last": "--:--:-- --",
            "last_epoch": 0.0,
            "label": meta["name"],
            "dongle": meta["dongle"],
            "hits": 0,
            "was_active": False,
        }
        for f_str, meta in config_labels.items()
    }

    subprocess.run(["killall", "-9", "rtl_airband"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.4)

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["rtl_airband", "-c", CONF_FILE, "-f"],
        stdout=slave,
        stderr=slave,
        close_fds=True,
        env=os.environ,
    )
    os.close(slave)
    master_ref = [master]

    def reload_airband() -> None:
        nonlocal proc
        old_fd = master_ref[0]
        master_ref[0] = -1
        try:
            os.close(old_fd)
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
        subprocess.run(["killall", "-9", "rtl_airband"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)
        save_settings(settings)
        build_config_from_csv(settings)
        new_m, new_s = pty.openpty()
        proc = subprocess.Popen(
            ["rtl_airband", "-c", CONF_FILE, "-f"],
            stdout=new_s,
            stderr=new_s,
            close_fds=True,
            env=os.environ,
        )
        os.close(new_s)
        master_ref[0] = new_m

    def output_reader() -> None:
        ansi_filter = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        while not stop_housekeeper.is_set():
            fd = master_ref[0]
            if fd < 0:
                time.sleep(0.05)
                continue
            try:
                raw_chunk = os.read(fd, 4096).decode("utf-8", "ignore")
                if not raw_chunk:
                    time.sleep(0.05)
                    continue
                clean_chunk = ansi_filter.sub(" ", raw_chunk)
                msg_queue.put(clean_chunk)
            except OSError:
                time.sleep(0.05)

    t_reader = threading.Thread(target=output_reader, daemon=True, name="ReaderThread")
    t_reader.start()

    last_raw = f"Hardware Probe: {probe_sdr_hardware()}"

    def safe_addstr(y: int, x: int, text: str, attr: int = 0) -> None:
        max_y, max_x = stdscr.getmaxyx()
        if 0 <= y < max_y and 0 <= x < max_x:
            stdscr.addstr(y, x, text[:max(0, max_x - x - 1)], attr)

    try:
        while True:
            try:
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    break
                elif key in (ord("s"), ord("S")):
                    sort_mode = (sort_mode + 1) % 3
                    scroll_offset = 0
                elif key in (ord("r"), ord("R")):
                    for item in freq_data.values():
                        item["hits"] = 0
                elif key in (ord("+"), ord("=")):
                    sq = min(50.0, float(settings["device_1"].get("squelch", 19.0)) + 1.0)
                    settings["device_1"]["squelch"] = sq
                    if is_dual and "device_2" in settings:
                        settings["device_2"]["squelch"] = sq
                    last_raw = f"Squelch increased to {sq:.1f} dB — reloading rtl_airband..."
                    reload_airband()
                elif key in (ord("-"), ord("_")):
                    sq = max(1.0, float(settings["device_1"].get("squelch", 19.0)) - 1.0)
                    settings["device_1"]["squelch"] = sq
                    if is_dual and "device_2" in settings:
                        settings["device_2"]["squelch"] = sq
                    last_raw = f"Squelch decreased to {sq:.1f} dB — reloading rtl_airband..."
                    reload_airband()
                elif key == ord("G"):
                    gn = min(49.6, float(settings["device_1"].get("gain", 33.0)) + 1.0)
                    settings["device_1"]["gain"] = gn
                    if is_dual and "device_2" in settings:
                        settings["device_2"]["gain"] = gn
                    last_raw = f"RF Gain increased to {gn:.1f} dB — reloading rtl_airband..."
                    reload_airband()
                elif key == ord("g"):
                    gn = max(0.0, float(settings["device_1"].get("gain", 33.0)) - 1.0)
                    settings["device_1"]["gain"] = gn
                    if is_dual and "device_2" in settings:
                        settings["device_2"]["gain"] = gn
                    last_raw = f"RF Gain decreased to {gn:.1f} dB — reloading rtl_airband..."
                    reload_airband()
                elif key == curses.KEY_UP:
                    cursor_idx = max(0, cursor_idx - 1)
                elif key == curses.KEY_DOWN:
                    cursor_idx = min(max(0, len(freq_data) - 1), cursor_idx + 1)
                elif key in (ord("l"), ord("L"), ord(" ")):
                    items_now = list(freq_data.items())
                    if sort_mode == 0:
                        items_now.sort(key=lambda x: float(x[0]))
                    elif sort_mode == 1:
                        items_now.sort(key=lambda x: (-x[1]["hits"], float(x[0])))
                    elif sort_mode == 2:
                        items_now.sort(key=lambda x: (-x[1]["last_epoch"], float(x[0])))
                    if 0 <= cursor_idx < len(items_now):
                        sel_f = items_now[cursor_idx][0]
                        if sel_f in locked_freqs:
                            locked_freqs.remove(sel_f)
                            action_str = "UNLOCKED"
                        else:
                            if len(locked_freqs) >= len(freq_data) - 1:
                                last_raw = "Cannot lock out the last remaining active frequency!"
                                continue
                            locked_freqs.add(sel_f)
                            freq_data[sel_f]["active"] = False
                            freq_data[sel_f]["sig"] = "--"
                            freq_data[sel_f]["noise"] = "--"
                            action_str = "LOCKED OUT"
                        settings["locked_out"] = sorted(locked_freqs)
                        last_raw = f"Frequency {sel_f} MHz ({freq_data[sel_f]['label']}) {action_str} — reloading..."
                        reload_airband()
                elif key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
            except curses.error:
                pass

            while not msg_queue.empty():
                chunk = msg_queue.get()
                clean_lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
                if clean_lines:
                    last_raw = clean_lines[-1]

                matches = re.findall(r"([\-\d]+)\s*/\s*([\-\d]+)\s*(\*?)\s+([\d\.]+)", chunk)
                for sig, noise, star, f in matches:
                    is_active = (star == "*")
                    now_epoch = time.time()
                    now_clock = datetime.now().strftime("%I:%M:%S %p")

                    try:
                        norm_f = f"{float(f):.3f}"
                    except ValueError:
                        norm_f = f

                    if norm_f in freq_data:
                        target = freq_data[norm_f]
                        if is_active and not target["was_active"]:
                            target["hits"] += 1
                        target["sig"] = sig
                        target["noise"] = noise
                        target["active"] = is_active
                        target["was_active"] = is_active
                        if is_active:
                            target["last"] = now_clock
                            target["last_epoch"] = now_epoch

            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()
            min_width = 100 if is_dual else 95

            if max_y < 12 or max_x < min_width:
                safe_addstr(0, 0, f"Terminal window too small (Minimum: {min_width}x12).")
                stdscr.refresh()
                curses.napms(100)
                continue

            current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            mode_tag = "DUAL-SDR" if is_dual else "SDR"
            cur_gn = float(settings["device_1"].get("gain", 33.0))
            cur_sq = float(settings["device_1"].get("squelch", 19.0))
            title = f" AIRSCAN HYBRID ({mode_tag} | GAIN: {cur_gn:.1f} dB | SQL: {cur_sq:.1f} dB) // {current_time} "
            safe_addstr(0, max(0, (max_x - len(title)) // 2), title, curses.color_pair(3) | curses.A_BOLD)

            if is_dual:
                col_header = (
                    f"{'':<3}{'DEV':<5}{'FREQUENCY':<13}{'NAME':<20}{'SNR':>5}  {'LEVEL':<8} "
                    f"{'SIG / NOISE':>12}  {'HITS':<6} {'LAST ACTIVE':^13}   {'STATUS':<10}"
                )
            else:
                col_header = (
                    f"{'':<3}{'FREQUENCY':<13}{'NAME':<20}{'SNR':>5}  {'LEVEL':<8} "
                    f"{'SIG / NOISE':>12}  {'HITS':<6} {'LAST ACTIVE':^13}   {'STATUS':<10}"
                )
            safe_addstr(2, 2, col_header, curses.color_pair(2) | curses.A_BOLD)

            items = list(freq_data.items())
            if sort_mode == 0:
                items.sort(key=lambda x: float(x[0]))
            elif sort_mode == 1:
                items.sort(key=lambda x: (-x[1]["hits"], float(x[0])))
            elif sort_mode == 2:
                items.sort(key=lambda x: (-x[1]["last_epoch"], float(x[0])))

            display_items = items
            max_rows = max(1, max_y - 6)
            if cursor_idx >= len(display_items):
                cursor_idx = max(0, len(display_items) - 1)
            if cursor_idx < scroll_offset:
                scroll_offset = cursor_idx
            elif cursor_idx >= scroll_offset + max_rows:
                scroll_offset = cursor_idx - max_rows + 1
            max_scroll = max(0, len(display_items) - max_rows)
            if scroll_offset > max_scroll:
                scroll_offset = max_scroll

            visible = display_items[scroll_offset:scroll_offset + max_rows]

            row_idx = 4
            for vis_i, (f_str, entry) in enumerate(visible):
                is_selected = (scroll_offset + vis_i == cursor_idx)
                is_locked = (f_str in locked_freqs)
                snr_db, snr_bar, snr_val = compute_snr_meter(entry["sig"], entry["noise"])
                sig_noise_str = f"{entry['sig']}/{entry['noise']} dB" if entry["sig"] != "--" else "--/-- dB"

                if snr_val >= 15.0:
                    meter_color = curses.color_pair(1) | curses.A_BOLD
                elif snr_val >= 6.0:
                    meter_color = curses.color_pair(4) | curses.A_BOLD
                elif snr_val >= 0.0:
                    meter_color = curses.color_pair(6) | curses.A_BOLD
                else:
                    meter_color = curses.color_pair(2) | curses.A_DIM

                dev_tag = f"[D{entry['dongle']}]"
                dev_color = curses.color_pair(2) if entry["dongle"] == "1" else curses.color_pair(8) | curses.A_BOLD

                if entry["active"]:
                    pfx = "*"
                    status = "REC / VOICE"
                    if is_dual:
                        row_full = (
                            f" {pfx} {dev_tag:<4} {f_str:>7} MHz  {entry['label'][:19]:<20}"
                            f"{snr_db:>5}  {snr_bar:<8} {sig_noise_str:>12}  "
                            f"#{entry['hits']:<5} {entry['last']:^13}   {status:<10}"
                        )
                    else:
                        row_full = (
                            f" {pfx} {f_str:>7} MHz  {entry['label'][:19]:<20}"
                            f"{snr_db:>5}  {snr_bar:<8} {sig_noise_str:>12}  "
                            f"#{entry['hits']:<5} {entry['last']:^13}   {status:<10}"
                        )
                    safe_addstr(row_idx, 2, row_full, curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
                else:
                    pfx = ">" if is_selected else " "
                    status = "LOCKED OUT" if is_locked else "SCANNING"
                    row_hl = curses.A_UNDERLINE if is_selected else 0
                    status_col = (curses.color_pair(6) | curses.A_BOLD) if is_locked else curses.color_pair(2)
                    freq_col = (curses.color_pair(6) | curses.A_DIM) if is_locked else (curses.color_pair(2) | curses.A_BOLD)
                    name_col = (curses.color_pair(6) | curses.A_DIM) if is_locked else (curses.color_pair(7) | curses.A_BOLD)
                    pfx_col = (curses.color_pair(4) | curses.A_BOLD) if is_selected else curses.color_pair(7)
                    if is_dual:
                        safe_addstr(row_idx, 2, f" {pfx} ", pfx_col | row_hl)
                        safe_addstr(row_idx, 5, f"{dev_tag:<5}", dev_color | row_hl)
                        safe_addstr(row_idx, 10, f"{f_str:>7} MHz  ", freq_col | row_hl)
                        safe_addstr(row_idx, 23, f"{entry['label'][:19]:<20}", name_col | row_hl)
                        safe_addstr(row_idx, 43, f"{snr_db:>5}  ", meter_color | row_hl)
                        safe_addstr(row_idx, 50, f"{snr_bar:<8} ", meter_color | row_hl)
                        safe_addstr(row_idx, 59, f"{sig_noise_str:>12}  ", curses.color_pair(7) | row_hl)
                        safe_addstr(row_idx, 73, f"#{entry['hits']:<5} ", curses.color_pair(4) | curses.A_BOLD | row_hl)
                        safe_addstr(row_idx, 80, f"{entry['last']:^13}   ", (curses.color_pair(1) if entry["hits"] > 0 else curses.color_pair(7) | curses.A_DIM) | row_hl)
                        safe_addstr(row_idx, 96, f"{status:<10}", status_col | row_hl)
                    else:
                        safe_addstr(row_idx, 2, f" {pfx} ", pfx_col | row_hl)
                        safe_addstr(row_idx, 5, f"{f_str:>7} MHz  ", freq_col | row_hl)
                        safe_addstr(row_idx, 18, f"{entry['label'][:19]:<20}", name_col | row_hl)
                        safe_addstr(row_idx, 38, f"{snr_db:>5}  ", meter_color | row_hl)
                        safe_addstr(row_idx, 45, f"{snr_bar:<8} ", meter_color | row_hl)
                        safe_addstr(row_idx, 54, f"{sig_noise_str:>12}  ", curses.color_pair(7) | row_hl)
                        safe_addstr(row_idx, 68, f"#{entry['hits']:<5} ", curses.color_pair(4) | curses.A_BOLD | row_hl)
                        safe_addstr(row_idx, 75, f"{entry['last']:^13}   ", (curses.color_pair(1) if entry["hits"] > 0 else curses.color_pair(7) | curses.A_DIM) | row_hl)
                        safe_addstr(row_idx, 91, f"{status:<10}", status_col | row_hl)

                row_idx += 1

            safe_raw = last_raw[:max_x - 10].replace("\r", "").replace("\n", "")
            safe_addstr(max_y - 2, 2, f"RAW: {safe_raw}", curses.color_pair(5) | curses.A_DIM)

            page_info = f" [Channels {scroll_offset + 1}-{min(scroll_offset + max_rows, len(display_items))} of {len(display_items)}]" if len(display_items) > max_rows else ""
            ctrls = f"[↑/↓] Select  [L] Lockout  [S] Sort:{sort_names[sort_mode]}  [+/-] Squelch  [G/g] Gain  [R] Reset  [Q] Quit{page_info}"
            safe_addstr(max_y - 1, 2, ctrls)

            stdscr.refresh()
            curses.napms(100)

    finally:
        stop_housekeeper.set()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.close(master_ref[0])
        except OSError:
            pass


if __name__ == "__main__":
    sys.stdout.write("\x1b[8;30;110t")
    sys.stdout.flush()
    time.sleep(0.1)

    try:
        curses.wrapper(curses_ui)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        import traceback
        with open("crash.log", "w", encoding="utf-8") as err_log:
            err_log.write(traceback.format_exc())
        print(f"\n[!] AirScan Hybrid encountered an unhandled exception: {exc}")
        print("[!] Diagnostic trace captured in 'crash.log'.\n")
