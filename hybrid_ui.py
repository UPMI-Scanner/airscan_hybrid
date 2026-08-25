import sys, curses, subprocess, re, queue, threading, pty, os, time, csv, shutil
from datetime import datetime

# ======================================================================
#                     --- SCANNER SETTINGS ---
# Beginners: Edit these variables to match your specific SDR hardware!
# ======================================================================
SQUELCH_LEVEL = 20.0
GAIN_LEVEL = 28.0

# DEVICE SELECTION:
# If you only have one SDR dongle plugged in, use: 'index = 0;'
# If you programmed a custom serial number, use: 'serial = "YOUR_NAME";'
SDR_DEVICE = 'serial = "AIR";' 
# ======================================================================

BASE_DIR = os.path.expanduser("~/airscan_hybrid")
CSV_FILE = os.path.join(BASE_DIR, "channels.csv")
CONF_FILE = os.path.join(BASE_DIR, "rtl_airband.conf")
REC_DIR = os.path.join(BASE_DIR, "recordings")

# --- PRE-FLIGHT SAFETY CHECKS ---
if not shutil.which("rtl_airband"):
    print("CRITICAL ERROR: 'rtl_airband' is not installed or not in your system PATH.")
    print("Please install rtl_airband before running this dashboard.")
    sys.exit(1)

if not os.path.exists(CSV_FILE):
    print(f"CRITICAL ERROR: Could not find the channel list at: {CSV_FILE}")
    print("Please create a 'channels.csv' file with your frequencies and names.")
    sys.exit(1)

if not os.path.exists(REC_DIR):
    os.makedirs(REC_DIR)

def build_config_from_csv():
    mapping = {}
    freqs_hz = []
    labels_quoted = []
        
    with open(CSV_FILE, "r") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2: continue
            freq_str = row[0].strip().replace('"', '')
            name_str = row[1].strip().replace('"', '')
            
            if "freq" in freq_str.lower(): continue
            
            try:
                f_mhz = float(freq_str)
                mapping[f_mhz] = name_str
                freqs_hz.append(str(int(f_mhz * 1000000)))
                labels_quoted.append(f'"{name_str}"')
            except ValueError:
                continue
                
    if not freqs_hz:
        print("CRITICAL ERROR: 'channels.csv' is empty or formatted incorrectly.")
        sys.exit(1)

    f_list = ", ".join(freqs_hz)
    l_list = ", ".join(labels_quoted)
    
    conf = f"""devices:
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
        filename_template = "airband_activity";
      }}
    );
  }});
}});
"""
    with open(CONF_FILE, "w") as f:
        f.write(conf)
        
    return mapping

def curses_ui(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    curses.use_default_colors()
    
    curses.init_pair(1, curses.COLOR_GREEN, -1)                   
    curses.init_pair(2, curses.COLOR_CYAN, -1)                    
    curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)  
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                  
    
    config_labels = build_config_from_csv()
    q = queue.Queue()
    filter_mode = False
    
    subprocess.run(["killall", "-9", "rtl_airband"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)

    master, slave = pty.openpty()
    
    proc = subprocess.Popen(["rtl_airband", "-c", CONF_FILE, "-f"], stdout=slave, stderr=slave, close_fds=True, env=os.environ)
    os.close(slave)
    
    def reader():
        ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        while True:
            try:
                chunk = os.read(master, 4096).decode("utf-8", "ignore")
                if not chunk: break
                clean = ansi.sub("", chunk)
                q.put(clean)
            except OSError:
                break
                
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    
    freq_data = {}
    last_raw = "Initializing SDR hardware..."
    
    try:
        while True:
            try:
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    break
                elif key in (ord("f"), ord("F")):
                    filter_mode = not filter_mode
                elif key == curses.KEY_RESIZE:
                    curses.update_lines_cols()
            except curses.error:
                pass
                
            while not q.empty():
                chunk = q.get()
                if chunk.strip():
                    lines = [line for line in chunk.split('\n') if line.strip()]
                    if lines:
                        last_raw = lines[-1].strip()
                
                matches = re.findall(r"([\-\d]+)\s*/\s*([\-\d]+)\s*(\*?)\s+([\d\.]+)", chunk)
                for sig, noise, star, f in matches:
                    active = (star == "*")
                    now_str = datetime.now().strftime("%H:%M:%S")
                    
                    label = "Unknown"
                    try:
                        f_float = float(f)
                        for k, v in config_labels.items():
                            if abs(f_float - k) < 0.001:
                                label = v
                                break
                    except ValueError:
                        pass
                    
                    if f not in freq_data:
                        freq_data[f] = {"sig": sig, "noise": noise, "active": active, "last": now_str if active else "--:--:--", "label": label, "hits": 1 if active else 0, "was_active": active}
                    else:
                        if active and not freq_data[f]["was_active"]:
                            freq_data[f]["hits"] += 1
                            
                        freq_data[f]["sig"] = sig
                        freq_data[f]["noise"] = noise
                        freq_data[f]["active"] = active
                        freq_data[f]["label"] = label
                        freq_data[f]["was_active"] = active
                        if active:
                            freq_data[f]["last"] = now_str
                    
            stdscr.erase()
            max_y, max_x = stdscr.getmaxyx()
            
            if max_y < 10 or max_x < 50:
                stdscr.addstr(0, 0, "Window too small!")
                stdscr.refresh()
                curses.napms(100)
                continue
            
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            filter_text = " [FILTER ON] " if filter_mode else " "
            title = f" AIRSCAN HYBRID DASHBOARD{filter_text}// {current_time} "
            
            stdscr.addstr(0, max(0, (max_x - len(title)) // 2), title, curses.color_pair(3) | curses.A_BOLD)
            
            header = f"{'':<3}{'FREQUENCY':<11}{'NAME':<21}{'SIGNAL':>8}{'NOISE':>11}{'HITS':>9}{'LAST ACTIVE':^16}{'STATUS':<10}"
            stdscr.addstr(2, 2, header, curses.color_pair(4) | curses.A_BOLD)
            
            row = 4
            for f, data in sorted(freq_data.items(), key=lambda x: float(x[0])):
                if row >= max_y - 4: break
                
                if filter_mode and data["hits"] == 0 and not data["active"]:
                    continue 
                
                if data["active"]:
                    color = curses.color_pair(1) | curses.A_BOLD | curses.A_REVERSE
                else:
                    color = curses.color_pair(2) | curses.A_BOLD
                
                status = "REC / VOICE" if data["active"] else "SCANNING"
                prefix = "*" if data["active"] else " "
                
                hit_str = f"#{data['hits']}"
                sig_str = f"{data['sig']} dB"
                noise_str = f"{data['noise']} dB"
                safe_label = data['label'][:20] 
                
                col1 = f" {prefix} "
                col2 = f"{f:>7}    "
                col3 = f"{safe_label:<21}"
                col4 = f"{sig_str:>8}"
                col5 = f"{noise_str:>11}"
                col6 = f"{hit_str:>9}"
                col7 = f"{data['last']:^16}"
                col8 = f"{status:<10}"
                
                line_str = f"{col1}{col2}{col3}{col4}{col5}{col6}{col7}{col8}"
                padded_line = f"{line_str:<95}" 
                stdscr.addstr(row, 2, padded_line[:max_x-3], color)
                row += 1
                
            safe_raw = last_raw[:max_x - 10].replace('\r', '').replace('\n', '') if last_raw else ""
            stdscr.addstr(max_y - 2, 2, f"RAW: {safe_raw}", curses.color_pair(4) | curses.A_DIM)
            
            footer = "[F] Toggle Filter (Active/All)   [Q] Quit Dashboard & Stop Engine"
            stdscr.addstr(max_y - 1, 2, footer)
            
            stdscr.refresh()
            curses.napms(100)
            
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

if __name__ == "__main__":
    curses.wrapper(curses_ui)
