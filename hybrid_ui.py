#!/usr/bin/env python3
"""AirScan Hybrid Dashboard.

A curses-based terminal interface for monitoring and controlling rtl_airband
scanners with live signal metrics, auto-pruning recordings, and adaptive sorting.
"""

from __future__ import annotations

import csv
import curses
from datetime import datetime
import os
import pty
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Dict, List, Tuple

# ======================================================================
#                       --- HARDWARE SETTINGS ---
# ======================================================================
SQUELCH_LEVEL: float = 20.0
GAIN_LEVEL: float = 32.0
SDR_DEVICE: str = 'serial = "AIR";'  # Or: 'index = 0;'
RETENTION_HOURS: int = 24  # Purge audio clips older than this threshold
# ======================================================================

BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
CSV_FILE: str = os.path.join(BASE_DIR, "channels.csv")
CONF_FILE: str = os.path.join(BASE_DIR, "rtl_airband.conf")
REC_DIR: str = os.path.join(BASE_DIR, "recordings")

if not shutil.which("rtl_airband"):
    sys.exit("[CRITICAL ERROR] 'rtl_airband' binary not found in system PATH.")

if not os.path.exists(CSV_FILE):
    sys.exit(f"[CRITICAL ERROR] Channel definition file missing: {CSV_FILE}")

os.makedirs(REC_DIR, exist_ok=True)


def build_config_from_csv() -> Dict[str, str]:
    """Parse channels.csv and construct a timestamped rtl_airband configuration."""
    mapping: Dict[str, str] = {}
    freqs_hz: List[str] = []
    labels_quoted: List[str] = []

    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            freq_str = row[0].strip().replace('"', "")
            name_str = row[1].strip().replace('"', "")

            if "freq" in freq_str.lower():
                continue

            try:
                f_mhz = float(freq_str)
                norm_key = f"{f_mhz:.3f}"
                mapping[norm_key] = name_str
                freqs_hz.append(str(int(round(f_mhz * 1_000_000))))
                labels_quoted.append(f'"{name_str}"')
            except ValueError:
                continue

    if not freqs_hz:
        sys.exit("[CRITICAL ERROR] 'channels.csv' contains no valid frequency entries.")

    f_list = ", ".join(freqs_hz)
    l_list = ", ".join(labels_quoted)

    conf_content = f"""devices:
({{
  type = "rtlsdr";
  {SDR_DEVICE}
  gain = {GAIN_LEVEL};
  mode = "scan";
  channels:
  ({{
    freqs = ( {f_list} );
    labels = ( {l_list} );
    squelch_snr_threshold = {SQUELCH_LEVEL};
    outputs: (
      {{ type = "pulse"; }},
      {{
        type = "file";
        directory = "{REC_DIR}";
        filename_template = "airband_%Y%m%d_%H%M%S";
      }}
    );
  }});
}});
"""
    with open(CONF_FILE, "w", encoding="utf-8") as f:
        f.write(conf_content)

    return mapping


def start_housekeeper(directory: str, max_age_hours: int, stop_event: threading.Event) -> threading.Thread:
    """Background worker that removes audio files exceeding retention threshold."""
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
    """Primary terminal UI loop with segmented color styling."""
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.use_default_colors()

    # Color palette definition
    curses.init_pair(1, curses.COLOR_GREEN, -1)                   # Active Voice / High SNR
    curses.init_pair(2, curses.COLOR_CYAN, -1)                    # Frequencies & Headers
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)    # Main Title Bar
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                  # Moderate SNR / Hits
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)                 # Raw Diagnostics
    curses.init_pair(6, curses.COLOR_RED, -1)                     # Low / Weak SNR
    curses.init_pair(7, curses.COLOR_WHITE, -1)                   # Standard Text

    config_labels = build_config_from_csv()
    msg_queue: queue.Queue[str] = queue.Queue()
    stop_housekeeper = threading.Event()
    start_housekeeper(REC_DIR, RETENTION_HOURS, stop_housekeeper)

    sort_mode = 0  # 0: Frequency, 1: Hits, 2: Recent Activity
    sort_names = ["Frequency", "Most Hits", "Recent"]
    scroll_offset = 0

    freq_data: Dict[str, dict] = {
        f_str: {
            "sig": "--",
            "noise": "--",
            "active": False,
            "last": "--:--:-- --",
            "last_epoch": 0.0,
            "label": label,
            "hits": 0,
            "was_active": False,
        }
        for f_str, label in config_labels.items()
    }

    subprocess.run(["killall", "-9", "rtl_airband"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ["rtl_airband", "-c", CONF_FILE, "-f"],
        stdout=slave,
        stderr=slave,
        close_fds=True,
        env=os.environ,
    )
    os.close(slave)

    def output_reader() -> None:
        ansi_filter = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        while True:
            try:
                raw_chunk = os.read(master, 4096).decode("utf-8", "ignore")
                if not raw_chunk:
                    break
                clean_chunk = ansi_filter.sub("", raw_chunk)
                msg_queue.put(clean_chunk)
            except OSError:
                break

    t_reader = threading.Thread(target=output_reader, daemon=True, name="ReaderThread")
    t_reader.start()

    last_raw = "Initializing RTL-SDR hardware..."

    def safe_addstr(y: int, x: int, text: str, attr: int = 0) -> None:
        """Write strings safely within boundary bounds to prevent curses edge crashes."""
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
                elif key == curses.KEY_UP and scroll_offset > 0:
                    scroll_offset -= 1
                elif key == curses.KEY_DOWN:
                    scroll_offset += 1
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
                    # 12-hour clock format (e.g., 03:45:12 PM)
                    now_clock = datetime.now().strftime("%I:%M:%S %p")

                    try:
                        norm_f = f"{float(f):.3f}"
                    except ValueError:
                        norm_f = f

                    if norm_f not in freq_data:
                        freq_data[norm_f] = {
                            "sig": sig,
                            "noise": noise,
                            "active": is_active,
                            "last": now_clock if is_active else "--:--:-- --",
                            "last_epoch": now_epoch if is_active else 0.0,
                            "label": config_labels.get(norm_f, "Unknown"),
                            "hits": 1 if is_active else 0,
                            "was_active": is_active,
                        }
                    else:
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

            if max_y < 12 or max_x < 95:
                safe_addstr(0, 0, "Terminal window too small (Minimum: 95x12).")
                stdscr.refresh()
                curses.napms(100)
                continue

            # Header rendering with 12-hour format
            current_time = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
            title = f" AIRSCAN HYBRID DASHBOARD // {current_time} "
            safe_addstr(0, max(0, (max_x - len(title)) // 2), title, curses.color_pair(3) | curses.A_BOLD)

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
            max_rows = max_y - 6
            max_scroll = max(0, len(display_items) - max_rows)
            if scroll_offset > max_scroll:
                scroll_offset = max_scroll

            visible = display_items[scroll_offset:scroll_offset + max_rows]

            row_idx = 4
            for f_str, entry in visible:
                snr_db, snr_bar, snr_val = compute_snr_meter(entry["sig"], entry["noise"])
                sig_noise_str = f"{entry['sig']}/{entry['noise']} dB" if entry["sig"] != "--" else "--/-- dB"

                # Dynamic SNR color ramp: Green (Strong) -> Yellow (Mid) -> Red (Weak)
                if snr_val >= 15.0:
                    meter_color = curses.color_pair(1) | curses.A_BOLD
                elif snr_val >= 6.0:
                    meter_color = curses.color_pair(4) | curses.A_BOLD
                elif snr_val >= 0.0:
                    meter_color = curses.color_pair(6) | curses.A_BOLD
                else:
                    meter_color = curses.color_pair(2) | curses.A_DIM

                if entry["active"]:
                    # Whole row inverts on active audio
                    pfx = "*"
                    status = "REC / VOICE"
                    row_full = (
                        f" {pfx} {f_str:>7} MHz  {entry['label'][:19]:<20}"
                        f"{snr_db:>5}  {snr_bar:<8} {sig_noise_str:>12}  "
                        f"#{entry['hits']:<5} {entry['last']:^13}   {status:<10}"
                    )
                    safe_addstr(row_idx, 2, row_full, curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE)
                else:
                    # Segmented colorful columns during scanning
                    pfx = " "
                    status = "SCANNING"
                    safe_addstr(row_idx, 2, f" {pfx} {f_str:>7} MHz  ", curses.color_pair(2) | curses.A_BOLD)
                    safe_addstr(row_idx, 18, f"{entry['label'][:19]:<20}", curses.color_pair(7) | curses.A_BOLD)
                    safe_addstr(row_idx, 38, f"{snr_db:>5}  ", meter_color)
                    safe_addstr(row_idx, 45, f"{snr_bar:<8} ", meter_color)
                    safe_addstr(row_idx, 54, f"{sig_noise_str:>12}  ", curses.color_pair(7))
                    safe_addstr(row_idx, 68, f"#{entry['hits']:<5} ", curses.color_pair(4) | curses.A_BOLD)
                    safe_addstr(row_idx, 75, f"{entry['last']:^13}   ", curses.color_pair(1) if entry["hits"] > 0 else curses.color_pair(7) | curses.A_DIM)
                    safe_addstr(row_idx, 91, f"{status:<10}", curses.color_pair(2))

                row_idx += 1

            safe_raw = last_raw[:max_x - 10].replace("\r", "").replace("\n", "")
            safe_addstr(max_y - 2, 2, f"RAW: {safe_raw}", curses.color_pair(5) | curses.A_DIM)

            page_info = f" [Channels {scroll_offset + 1}-{min(scroll_offset + max_rows, len(display_items))} of {len(display_items)}]" if len(display_items) > max_rows else ""
            ctrls = f"[↑/↓] Scroll  [S] Sort: {sort_names[sort_mode]}  [R] Reset Hits  [Q] Quit{page_info}"
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
            os.close(master)
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
