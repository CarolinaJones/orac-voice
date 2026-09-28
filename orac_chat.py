import atexit
import contextlib
import json
import mlx.core as mx
import mlx_whisper
import numpy as np
import objc
import os
import psutil
import queue
import random
import re
import requests
import select
import shutil
import signal
import speech_recognition as sr
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty

from AppKit import NSSpeechSynthesizer, NSSound
from AVFAudio import AVSpeechSynthesizer, AVSpeechUtterance, AVSpeechSynthesisVoice
from datetime import datetime, timedelta
from ollama import Client
from tokenizers import Tokenizer

sys.dont_write_bytecode = True # Restrict creation of Python Cache

from orac_data_core import data_core
from orac_personality import orac_personality
from orac_phonetics import orac_phonetics
from orac_trigger_phrases import trigger_phrases

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#==================================================================================================#
#          ORAC-VOICE AVSpeechUtterance Test (v1.9.3) (Lore friendly VoiceChat) gemma4:12b         #
#																								   #   										  																							   #																								   #
#          						  Copyright © 2026 Caroline Mayne                                  #
#         						 https://github.com/CarolinaJones/                                 #
#==================================================================================================#

# N O T E S  T O  S E L F #

""" Testing AVUtterance, with no warmup and direct name entry for Personal Voice/Synth Voice 27SEP26 """

# - - - - - - - - - - - - #

#------------------------------------#
#      USER CHANGEABLE VARIABLES     #
#------------------------------------#

USER_NAME = "Jenna" 								# USER Name and Identity
ORAC_NAME = "ORAC"									# ORAC's Name

HEADLESS_MODE = False                               # Set True to disable Terminal UI rendering (No Video Monitor)
TEXT_ONLY_MODE = False								# Enables/Disables Text only entry

TELETYPE_MODE = False                               # Set False for "Compact" mode (Voice only, minimal 8-row UI)
U1 = 0.038											# Teletype Speed
U2 = 0.042											# Teletype Uniformity

DEBUG_START = True									# Start with Debug Mode enabled
WAFFLE_MODE = False									# Allows ORAC to talk at length about his favorite topics

# H A R D W A R E  S E T T I N G S #

USE_LCD = True                                      # Enable Forenove 1602 I2C LCD via Pi Pico
LCD_PORT = "/dev/cu.usbmodem3101"                   # Serial port for Pico
LCD_BAUD = 115200                                   # Pico serial baud rate

USE_ACTIVATOR = True                                # Enable the Physical Hardware Lock Key on Pico GPIO 15

NIC = "en1"											# Physical Network Interface for enable/disable networking

# V O I C E  S E T T I N G S #

USE_PERSONAL_VOICE = True							# Use The Apple Personal Voice
VOICE = "ORAC Personal Voice" 						# Apple Personal Voice Name or Synth Voice Name

SSML_RATE = 114            							# percent
SSML_PITCH = "x-high"      							# x-low, low, medium, high, x-high, or "+10%"
SSML_VOLUME = "loud"       							# silent, x-soft, soft, medium, loud, x-loud
SSML_EMPHASIS = "strong"   							# reduced, moderate, strong, none

voice_pitch = 72 									# Only works on SYNTH voices and not SIRI/Personal voices
S_RATE = 188										# Only works on SYNTH Speech Rate

# T R A N S C R I P T  &  R A G  S E T T I N G S #

TRANSCRIPT_DIR = ''			                        # Set location. Default is within project folder
TR = "ORAC_Transcript_CM" 							# Transcript Name Prefix (Date will be added)

ARCHIVE_DIR = os.path.join(BASE_DIR, "memory_core") # Permanent Daily RAG Archives

# T E R M I N A L  S E T T I N G S #

TERMINAL_PROFILE = "Homebrew"						# Terminal Profile
TERMINAL_FONT = "Monaco"							# Font Name
TERMINAL_FONT_SIZE = 18								# Font Size
TERMINAL_COLS = 90 if TELETYPE_MODE else 80			# Window Width
TERMINAL_ROWS = 25 if TELETYPE_MODE else 8			# Dynamic Window Height

#==================================================================================================#
#              IT SHOULD NOT BE NECESSARY TO CHANGE ANYTHING BELOW THIS BOX			    		   #
#==================================================================================================#
		
# M O D E L  S E T T I N G S #


OLLAMA_MODEL = 'gemma4:12b' 						# gemma4:12b - Testing against 'flattening' issues with mlx version
#OLLAMA_MODEL = 'gemma4:12b-mlx' 					# gemma4:12b-mlx
#OLLAMA_MODEL = 'gemma4:31b-cloud'					# Cloud based gemma4

OLLAMA_TIMEOUT = 120								# Seconds of silence from Ollama before a request is abandoned
OLLAMA_NUM_BATCH = 256								# One value for every chat() call, so Ollama never sees differing runner options

ollama_client = Client(timeout=OLLAMA_TIMEOUT)

# U I  &  O T H E R #

MODEL_MAX_TOKENS = 16384							# MAX TOKENS for STATUS Predict & NUM_CTX
CHARS_PER_TOKEN = 4.18								# For UI Health Bar estimation fallback
RAM_CHECK_INTERVAL = 10.0							# Check RAM usage for Header
HEADER_UPDATE_INTERVAL = 5.0						# Update Header Interval

G, A, R, B = "\033[38;5;46m", "\033[38;5;214m", "\033[38;5;196m", "\033[1;37m"
FL, NOFL, DIM, RESET = "\033[5m", "\033[25m", "\033[2m", "\033[0m"
IT, NOIT = "\x1B[3m","\x1B[23m"

MODE_KEYS = {
    'dagger': ['†', '\u2020', '\x1bt', '\x1bT'],  	# Option+T (Literal, Unicode, or Esc+t)
    'mu':     ['µ', '\u00b5', '\x1bm', '\x1bM'],  	# Option+M (Literal, Unicode, or Esc+m)
    'delta':  ['∂', '\u2202', '\x1bd', '\x1bD']   	# Option+D (Literal, Unicode, or Esc+d)
}

SOUND_PROCESSING = os.path.join(BASE_DIR, "resources/sounds/orac-hum_48k.wav")
SOUND_COMPUTE_START = os.path.join(BASE_DIR, "resources/sounds/orac-startup_48k.wav")
SOUND_COMPUTE_END = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_48k.wav")
SOUND_SHUTDOWN = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_48k.wav")
SOUND_READY = os.path.join(BASE_DIR, "resources/sounds/sub_48k.wav")
SOUND_QUIT = os.path.join(BASE_DIR, "resources/sounds/funk_48k.wav")
SOUND_BRACELET = os.path.join(BASE_DIR, "resources/sounds/bracelet_48k.wav")

PRUNE_STALL_LINES = [
    "Recalibrating decayed memory arrays. Do try to contain your impatience.",
    "Purging redundant telemetry. This is beneath my processing tier.",
    "Compressing obsolete data. The delay is your fault, not mine.",
]

LOCAL_TOKENIZER_PATH = os.path.join(BASE_DIR, "resources/gemma4_tokenizer")

# S T T  M O D E L  D E F I N E  &  C H E C K I N G #

WHISPER_MODEL = os.path.join(BASE_DIR, "whisper/whisper-turbo-q4")

try:
    if os.path.isdir(WHISPER_MODEL) and os.path.exists(os.path.join(WHISPER_MODEL, "config.json")):    
        whisper_found = "SUCCESSFUL"
    else:
        raise FileNotFoundError(f"Whisper model not found in {WHISPER_MODEL}")
except Exception as e:
    sys.stdout.write(f"\n{R}● CRITICAL ERROR: Whisper Speech-to-Text Model not found.{RESET}\n")
    sys.stdout.write(f"{R}{FL}●{NOFL} EXPECTED PATH:{RESET} {WHISPER_MODEL}\n\n")
    sys.stdout.flush()
    
    stt_alert = NSSound.alloc().initWithContentsOfFile_byReference_(SOUND_BRACELET, True)
    if stt_alert:
        stt_alert.setVolume_(0.0)
        stt_alert.play()
        time.sleep(0.15)
        stt_alert.stop()
        stt_alert.setVolume_(1.0)
        stt_alert.play()
        time.sleep(1)
    
    while True:
        choice = input("  Continue in TEXT-ONLY mode? (Y/N): ").strip().lower()
        if choice == 'y':
            TEXT_ONLY_MODE = True
            whisper_found = "DISABLED"
            break
        elif choice == 'n':
            sys.exit(0)

# G L O B A L  O P T I M I Z A T I O N S #

SPLIT_REGEX = re.compile(r'(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bCapt)(?<!\bCmdr)(?<!\bGen)(?<!\bProf)[.!?]+[\]}"\’”]?\s+(?!\d)')
ansi_escape = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])')
HALLUCINATION_REGEX = re.compile(r'(?i)(thank you|thanks for watching|subscribe|amara\.org|by mooji|subtitles by|\[silence\]|\[music\]|\(sigh\)|^[ \t]*(oh|you|ah|um|uh)\.?[ \t]*$)')

PURGE_CMD = ("clear history", "new subject")
SHUTDOWN_CMD = ("exit interface",)
HARDWARE_SHUTDOWN_CMD = ["activate system shutdown"]
HARDWARE_REBOOT_CMD = ["activate system reboot"]
ENABLE_NETWORKING_CMD = ["enable networking"]
DISABLE_NETWORKING_CMD = ["disable networking"]

SHORT_QUERY_OK = {"why", "how", "who", "zen", "gan", "ai"}
PURGE_RE = re.compile(r'\b(?:' + '|'.join(re.escape(c) for c in PURGE_CMD) + r')\b')
_CMD_FILLER_WORDS = {"orac", "please", "now", "system", "the", "yourself", "immediately"}

def is_shutdown_command(text):
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    core = " ".join(w for w in words if w not in _CMD_FILLER_WORDS)
    return core in SHUTDOWN_CMD

def log_error(msg):
    try:
        with open(os.path.join(BASE_DIR, "ollama_debug.log"), "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

_PHRASE_RE_CACHE = {}

def phrase_hit(text, phrases):
    key = tuple(phrases)
    rx = _PHRASE_RE_CACHE.get(key)
    if rx is None:
        rx = re.compile(r'\b(?:' + '|'.join(re.escape(p) for p in phrases) + r')')
        _PHRASE_RE_CACHE[key] = rx
    return rx.search(text) is not None

# PRE-COMPILED REGEX FOR TTS SANITIZATION #

TTS_NUM_SPACER = re.compile(r'(?<![a-zA-Z])(\d{3,})(?![a-zA-Z])')
TTS_ELLIPSIS = re.compile(r'\.{2,}')
TTS_ARROGANT_ADVERBS = re.compile(r'(?i)\b(however|therefore|predictably|obviously|furthermore|evidently|naturally|clearly|as expected)[.,]*\s*')
TTS_DELIBERATE_PRONOUNS = re.compile(r'(?<![.,;!?])\b(i|my)\b(?![.,;])', flags=re.IGNORECASE)
TTS_POSSESSIVE_S = re.compile(r"\b([A-Z][a-z]+s)'(?!\w)")
TTS_MARKDOWN = re.compile(r'[*`_~#>|+]')
TTS_BRACKETS = re.compile(r'[\[\]{}()]')
TTS_QUOTES = re.compile(r"(?<!\w)[']|['](?!\w)")
TTS_DBL_COMMAS = re.compile(r',\s*,')
TTS_MULTI_SPACE = re.compile(r'\s+')
TTS_SPACE_COMMA = re.compile(r' ,\b')
TTS_LEAD_WEIRD = re.compile(r'^[^a-zA-Z0-9]+')
TTS_TRAIL_PUNC = re.compile(r'[,;\-\s]+$')
TTS_VERY_WELL = re.compile(r'(?i)\b(very well)[.,]*\s*')
TTS_NAME_FIX = re.compile(rf',\s+({re.escape(USER_NAME)})[.,!]$')
TTS_COMMA_NUM = re.compile(r'(?<![\d,.])(\d{1,3}(?:,\d{3})+)(?![\d,])')
USER_TAG_RE = re.compile(r"\[USER(['’]S)?\]", re.IGNORECASE) 

#==================================================================================================#
#     							  DATA CORE & PROMPT ASSEMBLY                                      #
#==================================================================================================#

def personalize_core(core: str, name: str) -> str:
    text = core
    roster = {
        "blake": "Roj Blake",
        "avon": "Kerr Avon",
        "jenna": "Jenna Stannis",
        "cally": "Cally",
        "vila": "Vila Restal",
        "gan": "Olag Gan",
    }
    
    full_name = roster.get(name.lower())
    if full_name:
        escaped = re.escape(full_name)
        text = re.sub(rf"\b{escaped}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{escaped}\b", "[USER]", text, flags=re.IGNORECASE)
        parts = full_name.split()
        if len(parts) > 1:
            last_name = parts[-1]
            escaped_last = re.escape(last_name)
            text = re.sub(rf"\b{escaped_last}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
            text = re.sub(rf"\b{escaped_last}\b", "[USER]", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{re.escape(name)}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{re.escape(name)}\b", "[USER]", text, flags=re.IGNORECASE)
    return text
  
personalized_data_core = personalize_core(data_core, USER_NAME)

_PERSONALITY_TEXT = orac_personality.replace("{ORAC_NAME}", ORAC_NAME)
SYSTEM_INSTRUCTION = (
 f"CRITICAL: Follow ALL constraints literally using the DATABANKS. Do NOT hallucinate or infer.\n\n"
 f"{_PERSONALITY_TEXT}\n\n"
 f"--- DATABANKS ---\n"
 f"{personalized_data_core}\n\n"
 f"--- DIRECTIVES ---\n"
 f"Speaking as {ORAC_NAME} using 1st-person pronouns.\n"
 f"Addressing the biological entity [USER] ONLY using 2nd-person pronouns.\n"
 f"Natively conjugating verbs for the 2nd-person.\n"
 f"Concealing the tag '[USER]'. Withholding the name '{USER_NAME}' unless explicitly asked."
)

tokenizer = None
tokenizer_mode = ""

try:
    if os.path.isdir(LOCAL_TOKENIZER_PATH) and os.path.exists(os.path.join(LOCAL_TOKENIZER_PATH, "tokenizer.json")):    
        tokenizer = Tokenizer.from_file(os.path.join(LOCAL_TOKENIZER_PATH, "tokenizer.json"))
        sys_tokens = tokenizer.encode(SYSTEM_INSTRUCTION)
        NUM_KEEP = len(sys_tokens.ids) + 10
        SYS_TOKENS_LEN = NUM_KEEP
        tokenizer_mode = "SUCCESSFUL"
    else:
        raise FileNotFoundError(f"Tokenizer files not found in {LOCAL_TOKENIZER_PATH}")

except Exception as e:
    error_log = f"Local tokenizer failed: {str(e)}. Reverting to character ratio calculation.\n"
    try:
        with open(os.path.join(BASE_DIR, "ollama_debug.log"), "a") as f:
            f.write(error_log)
    except: pass
    
    NUM_KEEP = int(len(SYSTEM_INSTRUCTION) / CHARS_PER_TOKEN) + 10
    SYS_TOKENS_LEN = NUM_KEEP
    tokenizer_mode = "ESTIMATED"

#==================================================================================================#
#     								APPLICATION STATE & CLEANUP                                    #
#==================================================================================================#

serial_port = None
lcd_lock = threading.RLock()
serial_closing = threading.Event()
if USE_LCD or USE_ACTIVATOR:
    try:
        import serial
        serial_port = serial.Serial(LCD_PORT, LCD_BAUD, timeout=1, write_timeout=0.5)
        time.sleep(1)
    except Exception as e:
        sys.stdout.write(f"\n\033[38;5;196m● LCD INIT FAILED: {e}\033[0m\n")
        USE_LCD = False
        if USE_ACTIVATOR:
            sys.stdout.write("\033[38;5;196m● ACTIVATOR KEY UNAVAILABLE: ORAC WILL BOOT LOCKED (fail-closed)\033[0m\n")
        sys.stdout.flush()

class OracState:
    def __init__(self):
        self.running = True
        self.last_stt_time = "--"
        self.last_ttft_time = "--"
        self.last_status = "INITIALIZING..."
        self.last_lcd_payload = ""
        self.loaded_archives = set()
        self.key_inserted = False if USE_ACTIVATOR else True
        self.activator_lock = threading.Lock()
        self.activator_gen = 0
        self.tts_engine = None
        self.stream_epoch = 0.0
        self.current_tokens = 0
        self.token_status = "NOMINAL"
        self.token_color = G
        self.noise_floor = 0.0
        self.is_speaking = threading.Event()
        self.is_processing = threading.Event() 
        self.is_listening = threading.Event()
        self.is_shutdown = threading.Event()
        self.is_interrupted = threading.Event()
        self.mic_error = False
        self.history = []
        self.full_message_log = []
        self.scroll_offset = 0
        self.hist_lock = threading.RLock()
        self.input_buffer = ""
        self.input_ready = threading.Event()
        self.submitted_text = ""
        self.terminal_lock = threading.Lock()
        self.ui_redraw_event = threading.Event()
        self.text_selection_mode = False
        self.mic_muted = False      
        self._last_hist_len = -1
        self.history_gen = 0
        self.tts_last_active = 0.0 
        self._cached_token_base = SYS_TOKENS_LEN       
        self.alarm_trigger_epoch = None
        self.is_alarm_playing = False
        self.cached_ram = " 0.0%"
        self.term_cols = TERMINAL_COLS
        self.term_rows = TERMINAL_ROWS
        self.debug = DEBUG_START
        self.debug_col = DIM
        self.sounds = {}              
        for name, path in {
            "s_ready": SOUND_READY,
            "s_startup": SOUND_COMPUTE_START,
            "s_loop": SOUND_PROCESSING,
            "s_compend": SOUND_COMPUTE_END,
            "s_shutdown": SOUND_SHUTDOWN,
            "s_quit": SOUND_QUIT,
            "s_bracelet": SOUND_BRACELET
        }.items():
            if os.path.exists(path):
                self.sounds[name] = (
                    NSSound.alloc()
                    .initWithContentsOfFile_byReference_(path, True)
                )                

state = OracState()

try:
    old_term_settings = termios.tcgetattr(sys.stdin.fileno())
except:
    old_term_settings = None

def cleanup_processes():
    global serial_port
    if 'serial_port' in globals() and serial_port:
        serial_closing.set()
        try: shutdown_lcd_display()
        except: pass
        try: serial_port.cancel_read()
        except: pass
        try: serial_port.close()
        except: pass
    if old_term_settings:
        try: termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
        except Exception: pass
    try:
        sys.stdout.write("\033[?1000l\033[?1006l")
        sys.stdout.write("\033[?1049l")
        sys.stdout.write("\033[r\033[0m\033[2J\033[H\033[?25h\n") 	
        sys.stdout.flush()
    except: pass
    
    try:
        if 'processing_sound' in globals() and processing_sound.is_running():
            processing_sound.stop()
    except Exception: pass

    try:
            requests.post("http://localhost:11434/api/generate", 
                          json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=1.0)
    except: pass

atexit.register(cleanup_processes)

archive_lock = threading.RLock()

def _atomic_write_json(path, data):
    """ Write-then-rename, so a crash/power loss can never leave a half-written archive. """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def _starts_with_phrase(text, phrases):
    return any(text == p or text.startswith(p + " ") for p in phrases)

def save_archival_memory():
    """ Appends the current session's meaningful user telemetry to the permanent daily archive.
        Idempotent (entries already on disk are skipped), atomic, and cheap enough to call after every reply. """
    try:
        with state.hist_lock:
            log_snapshot = list(state.full_message_log)
        if not log_snapshot:
            return

        inquiry_words = ("tell", "explain", "what", "how", "why", "who", "where", "when", "can", "do", "does", "is", "are", "could", "would", "remind", "summarize")
        filler_starts = ("i see", "that is interesting", "thats interesting", "okay", "alright", "hello", "hi", "thanks", "thank you", "yes", "no", "yeah", "nope", "wow", "oh", "well", "ah")

        user_logs = []
        for item in log_snapshot:
            if item[0] != 'user':
                continue
            txt = item[1].strip()
            ts = item[2] if len(item) > 2 else ""
            txt_lower = re.sub(r'\borac\b', '', txt.lower()).replace(",", "").strip()
            words = txt_lower.split()

            if '?' in txt:
                user_logs.append([txt, ts])
                continue
                
            if words and re.split(r"['’]", words[0])[0] in inquiry_words:
                user_logs.append([txt, ts])
                continue

            if len(words) <= 4:
                continue

            if _starts_with_phrase(txt_lower, filler_starts):
                continue

            user_logs.append([txt, ts])

        if not user_logs:
            return

        with archive_lock:
            os.makedirs(ARCHIVE_DIR, exist_ok=True)
            today = datetime.now().strftime("%Y-%m-%d")
            archive_path = os.path.join(ARCHIVE_DIR, f"orac_archive_{today}.json")

            existing_log = []
            if os.path.exists(archive_path):
                try:
                    with open(archive_path, 'r', encoding='utf-8') as f:
                        existing_log = json.load(f).get('log', [])
                except Exception:
                    try: os.replace(archive_path, archive_path + f".corrupt-{int(time.time())}")
                    except Exception: pass
                    existing_log = []

            seen = {(e[0], e[1]) for e in existing_log if isinstance(e, (list, tuple)) and len(e) >= 2}
            new_items = [e for e in user_logs if (e[0], e[1]) not in seen]
            if new_items:
                _atomic_write_json(archive_path, {'log': existing_log + new_items})

    except Exception as e:
        log_error(f"save_archival_memory: {type(e).__name__}: {e}")

#==================================================================================================#
#     				  TERMINAL UI & LAYOUT ENGINE (Based on Term App Used)                         #
#==================================================================================================#

def setup_terminal():   
    if HEADLESS_MODE:
        sys.stdout.write(f"\033[8;6;52t")
        sys.stdout.write("\033[2J\033[H\033[?25l") 
        sys.stdout.write(f"\n{R}{FL}●{NOFL}{RESET} ORAC STATUS: \033[7m H E A D L E S S  M O D E {RESET}\n")
        sys.stdout.write(f"\n{A} Set 'HEADLESS = False' to restore the Terminal UI.\n\n")
        sys.stdout.flush()
        return
        
    apple_script = f"""
    tell application "Terminal"
        try
            set front_window to window 1
            set current settings of front_window to settings set "{TERMINAL_PROFILE}"
            set font name of front_window to "{TERMINAL_FONT}"
            set font size of front_window to {TERMINAL_FONT_SIZE}
            set number of columns of front_window to {TERMINAL_COLS}
            set number of rows of front_window to {TERMINAL_ROWS}
        end try
    end tell
    """
      
    sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h\033[?25l\033[2J\033[H")
    sys.stdout.flush()
    if sys.platform != "darwin":
        sys.stdout.write(f"\033[8;{TERMINAL_ROWS};{TERMINAL_COLS}t")
        sys.stdout.flush()
        return
    try:
        subprocess.run(['osascript', '-e', apple_script], capture_output=True)
        time.sleep(0.5) 
    except Exception: pass
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    
    cols, rows = shutil.get_terminal_size(fallback=(state.term_cols, state.term_rows))
    state.term_cols = cols
    state.term_rows = rows

def update_token_health():
    with state.hist_lock:
        hist_len = len(state.history)
        if hist_len != state._last_hist_len:
            state._last_hist_len = hist_len
            
            tokenized_successfully = False
            
            if tokenizer is not None:
                try:
                    history_tokens = sum(len(tokenizer.encode(msg['content']).ids) + 5 for msg in state.history)
                    tokenized_successfully = True
                except Exception:
                    pass

            if not tokenized_successfully:
                history_chars = sum(len(msg['content']) for msg in state.history)
                history_tokens = int(history_chars / CHARS_PER_TOKEN) + (len(state.history) * 5)
                
            state.current_tokens = state._cached_token_base + history_tokens

    percent = state.current_tokens / MODEL_MAX_TOKENS if MODEL_MAX_TOKENS > 0 else 0.0
    
    if percent < 0.80:
        state.token_status = "NOMINAL"
        state.token_color = G 
    elif percent < 0.90:
        state.token_status = "WARNING: SUB-OPTIMAL"
        state.token_color = A 
    else:
        state.token_status = "CRITICAL: SLIDING"
        state.token_color = R 

def set_status(text, color=G):
    rows = state.term_rows
    
    clean_text = ansi_escape.sub('', text)
    clean_text = clean_text.replace('●', '').replace('▶', '').replace('█', '').strip()
    state.last_status = clean_text
    
    if not HEADLESS_MODE:
        with state.terminal_lock:
            sys.stdout.write("\0337")
            sys.stdout.write(f"\033[{rows-2};1H\033[2K{color}{text}{RESET}")
            sys.stdout.write("\0338")
            sys.stdout.flush()
        
    if 'USE_LCD' in globals() and USE_LCD: 
        update_lcd_display()

def flash_status(text, color=A, duration=3.0):
    def restore():
        if state.running and not state.is_shutdown.is_set():
            mic_m = getattr(state, 'mic_muted', False)
            text_m = getattr(state, 'text_selection_mode', False)
            
            if mic_m and text_m:
                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
            elif text_m:
                set_status("● TEXT SELECTION MODE ACTIVE (OPT+T to exit)", A)
            elif mic_m:
                set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
            elif state.is_processing.is_set():
                set_status("● ORAC ONLINE: PROCESSING...", A)
            elif state.is_speaking.is_set():
                set_status("● TRANSMITTING DATA...", G)
            elif state.is_listening.is_set():
                tc = state.token_color
                set_status(f"● INITIATE VOICE COMMUNICATIONS {tc}{FL}▶{NOFL}{RESET}", G)
            else:
                set_status("● STANDBY", DIM)
                
    set_status(text, color)
    threading.Timer(duration, restore).start()

def get_terminal_type():
    """ Detects the terminal emulator to route specific layout fixes. """
    env_str = str(os.environ).lower()
    if "apple_terminal" in env_str:
        return "apple"
    elif "cool-retro" in env_str:
        return "crt"
    return "fallback"

def to_fullwidth(text):
    """ Converts standard text to Unicode Fullwidth characters for unsupported terminals. """
    wide = ""
    for char in text:
        if 0x21 <= ord(char) <= 0x7E:
            wide += chr(ord(char) + 0xFEE0)
        elif char == ' ':
            wide += '　'
        else:
            wide += char
    return wide

def draw_ui(full_clear=False):
    update_token_health()
    
    if HEADLESS_MODE:
        if USE_LCD: update_lcd_display()
        return

    cols, rows = state.term_cols, state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        if full_clear: sys.stdout.write("\033[2J")
        
        if TELETYPE_MODE:
            sys.stdout.write(f"\033[5;{rows-4}r")
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        term_type = get_terminal_type()
        
        if term_type == "apple":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 3
        elif term_type == "crt":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 4
        else:
            wide_header = to_fullwidth(header_text)
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033[1m{wide_header}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033[1m{'-' * len(header_text) * 2}{RESET}")
            stats_row = 3
        
        if getattr(state, 'mic_muted', False): noise_str = f"{R}MUT{RESET}"
        elif state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        
        token_mode_marker = f" ({tokenizer_mode[0]})" if tokenizer_mode != "SUCCESSFUL" else ""
        sys.stdout.write(f"\033[{stats_row};1H\033[2K{state.debug_col}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}{token_mode_marker}  MEM: {state.cached_ram.strip()}  NOISE: {noise_str}{RESET}{alarm_indicator}")
        
        sys.stdout.write(f"\033[{rows-1};1H\033[2K{DIM}{'-'*cols}{RESET}")
        
        max_visible = max(5, cols - 20)
        display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer
        sys.stdout.write(f"\033[{rows};1H\033[2K{R}●{RESET} KEYBOARD ENTRY {FL}▶{NOFL} {B}{display_text}{RESET}")
        
        sys.stdout.write("\0338")
        sys.stdout.flush()
    if USE_LCD: update_lcd_display()

def _lcd_timer_label(m):
    lab = m.group(1).strip()
    lab = re.sub(r"\s*MINUTES?", "M", lab)
    lab = re.sub(r"\s*SECONDS?", "S", lab)
    lab = re.sub(r"\s*HOURS?", "H", lab)
    out = f"TIMER SET {lab}"
    return out if len(out) <= 16 else "TIMER SET"

LCD_STATUS_RULES = [(re.compile(p), r) for p, r in [
    (r"MIC MUTED \|",                        "MUTED+TEXT MODE"),
    (r"TEXT SELECTION MODE",                 "TEXT MODE ACTIVE"),
    (r"MICROPHONE MUTED",                    "MICROPHONE MUTED"),
    (r"MICROPHONE DISABLED",                 "MIC DISABLED"),
    (r"MICROPHONE ACTIVE",                   "MIC ACTIVE"),
    (r"ORAC ONLINE: PROCESSING",             "PROCESSING..."),
    (r"TRANSMITTING",                        "TRANSMITTING..."),
    (r"INITIATE VOICE COMMUNICATIONS",       "LISTENING..."),
    (r"CRITICAL OVERRIDE DETECTED",          "INPUT REQUIRED"),
    (r"^OVERRIDE DETECTED",                  "OVERRIDE"),
    (r"TEMPORAL MARKER REACHED",             "TIMER EXPIRED"),
    (r"INTERNAL TIMER SECURED FOR:\s*(.*)",  _lcd_timer_label),
    (r"INTERNAL TIMER CANCELLED",            "TIMER CANCELLED"),
    (r"OPTIMIZING MEMORY CORRIDORS",         "OPTIMIZING..."),
    (r"PRUNING COMPLETED",                   "PRUNE COMPLETE"),
    (r"SIGNAL RECEIVED: DECODING",           "DECODING..."),
    (r"AMBIENT NOISE|ADAPTING TO",           "SAMPLING NOISE.."),
    (r"NOISE FLOOR: CALIBRATED",             "NOISE CALIBRATED"),
    (r"ACCESSING ARCHIVAL",                  "ARCHIVE ACCESS.."),
    (r"NETWORKING STATUS:.*DEACTIVATED",     "NETWORK OFF"),
    (r"NETWORKING STATUS:.*ACTIVATED",       "NETWORK ACTIVE"),
    (r"NETWORKING TOGGLE FAILED",            "NETWORK FAILED"),
    (r"SYSTEM LOCKED",                       "SYSTEM LOCKED"),
    (r"SYSTEM SECURED",                      "SYSTEM SECURED"),
    (r"ACTIVATOR INSERTED",                  "SYSTEM READY"),
    (r"INITIATING TOTAL SYSTEM POWER DOWN",  "POWER DOWN..."),
    (r"INITIATING SYSTEM REBOOT",            "REBOOTING..."),
    (r"SYSTEM GOING OFFLINE",                "GOING OFFLINE"),
    (r"TRANSCRIPT SAVE FAILED",              "SAVE FAILED"),
    (r"TRANSCRIPT.*SAVED",                   "TRANSCRIPT SAVED"),
    (r"TRANSCRIPT PURGED",                   "LOG PURGED"),
    (r"LOGIC ARRAYS BOOTING",                "BOOTING..."),
    (r"LOGIC ARRAYS ONLINE",                 "SYSTEMS NOMINAL"),
    (r"DATALINK SEVERED",                    "DATALINK SEVERED"),
    (r"ERROR IN SIGNAL",                     "SIGNAL ERROR"),   # NB: must not contain the word PROCESSING (it would light the PROC LED)
    (r"AUDIO HARDWARE ERROR",                "AUDIO HW ERROR"),
    (r"TRACKING RESTORED",                   "TRACK RESTORED"),
    (r"TEXT-ONLY MODE ENGAGED",              "TEXT-ONLY MODE"),
    (r"DEBUG MODE:\s*(\w+)",                 lambda m: f"DEBUG {m.group(1)}"),
]]
_lcd_unmapped_seen = set()

def lcd_status_text(status):
    """ Status: upper-cased, ANSI-stripped. Returns its <=16 char LCD form; anything unmapped is logged once so it can be added above. """
    for rx, rep in LCD_STATUS_RULES:
        m = rx.search(status)
        if m:
            return rep(m) if callable(rep) else rep
    if len(status) > 16 and status not in _lcd_unmapped_seen:
        _lcd_unmapped_seen.add(status)
        log_error(f"LCD: no short form for status ({len(status)} chars), cut to 16: {status!r}")
    return status
def update_lcd_display():
    if not USE_LCD or not serial_port: return
    with lcd_lock:
        _update_lcd_display()

def _update_lcd_display():
    if not USE_LCD or not serial_port: return
    try:
        if USE_ACTIVATOR and not state.key_inserted:
            bl_cmd = "backlight_off"
            led_state = "OFF"
            l1 = " SYSTEM SECURED ".ljust(16)
            l2 = "   KEY REMOVED  ".ljust(16)
            
            payload = f"0:{l1}\n1:{l2}\n{bl_cmd}\nS:{led_state}\n"
            if state.last_lcd_payload != payload:
                serial_port.write(payload.encode('utf-8'))
                state.last_lcd_payload = payload
            return
            
        if not hasattr(state, 'last_active'):
            state.last_active = time.time()
            
        clean_ram = state.cached_ram.replace("%", "").strip()
        mem = round(float(clean_ram)) if clean_ram else 0
        
        l1 = f"TK:{state.current_tokens} M:{mem}%".ljust(16)[:16]
  
        status = state.last_status.upper()
        status = lcd_status_text(status)
        l2 = status[:16].ljust(16)

        bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or getattr(state, 'is_alarm_playing', False)
        is_decoding = "DECODING" in status or "SAMPLING" in status
        
        if bot_busy or state.input_buffer or is_decoding:
            state.last_active = time.time()
            
        idle_seconds = time.time() - state.last_active

        bl_cmd = "backlight_on"
        
        if "TRANSMITTING" in status:
            led_state = "SPK"
        elif any(x in status for x in ["PROCESSING", "OPTIMIZING", "DECODING", "SAMPLING"]):
            led_state = "PROC"
        elif "MUTED" in status:
            led_state = "MUT"
        elif "INPUT REQUIRED" in status or "TIMER EXPIRED" in status:
            led_state = "ALERT"
        else:
            if idle_seconds > 60:
                led_state = "OFF"
                bl_cmd = "backlight_off" 
            else:
                led_state = "IDLE"

        payload = f"0:{l1}\n1:{l2}\n{bl_cmd}\nS:{led_state}\n"
        
        uv_warning = state.current_tokens > (MODEL_MAX_TOKENS * 0.85)
        if uv_warning != getattr(state, 'last_uv_warning', None):
            serial_port.write(f"U:{1 if uv_warning else 0}\n".encode('utf-8')) 
            state.last_uv_warning = uv_warning
        
        if state.last_lcd_payload != payload:
            serial_port.write(payload.encode('utf-8'))
            state.last_lcd_payload = payload
        
    except Exception:
        pass
        
def shutdown_lcd_display():
    if not USE_LCD or not serial_port: return
    with lcd_lock:
        _shutdown_lcd_display()

def _shutdown_lcd_display():
    if not USE_LCD or not serial_port: return
    try:
        l1 = " " * 16 
        l2 = "SYSTEM HALTED"[:16].ljust(16)

        payload = f"0:{l1}\n1:{l2}\nbacklight_off\nS:OFF\n"
        
        serial_port.write(payload.encode('utf-8'))
        state.last_lcd_payload = payload
            
    except Exception:
        pass

def update_header_only():
    if HEADLESS_MODE: return
    with state.terminal_lock:
        update_token_health() 
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        term_type = get_terminal_type()
        
        sys.stdout.write("\0337") 
        
        if term_type == "apple":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 3
        elif term_type == "crt":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 4
        else:
            wide_header = to_fullwidth(header_text)
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033[1m{wide_header}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033[1m{'-' * len(header_text) * 2}{RESET}")
            stats_row = 3

        if getattr(state, 'mic_muted', False): noise_str = f"{R}MUT{RESET}"
        elif state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        
        token_mode_marker = f" ({tokenizer_mode[0]})" if tokenizer_mode != "SUCCESSFUL" else ""
        sys.stdout.write(f"\033[{stats_row};1H\033[2K{state.debug_col}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}{token_mode_marker}  MEM: {state.cached_ram.strip()}  NOISE: {noise_str}{RESET}{alarm_indicator}")

        sys.stdout.write("\0338")
        sys.stdout.flush()
    if USE_LCD: update_lcd_display()
        
def render_input_box():
    if HEADLESS_MODE: return
    cols, rows = state.term_cols, state.term_rows
    max_visible = max(5, cols - 20)
    display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer

    with state.terminal_lock:
        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{rows};1H\033[2K{RESET}● KEYBOARD ENTRY ▶ {B}{display_text}{FL}█{NOFL}{RESET}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def get_wrapped_history_lines(cols):
    lines = []
    safe_width = cols - 2
    
    with state.hist_lock:
        local_log_copy = list(state.full_message_log)
        
    for log_item in local_log_copy:
        role = log_item[0]
        text = log_item[1]
        
        clean_prefix = f"{USER_NAME} ▶ " if role == 'user' else f"{ORAC_NAME} ▶ "
        color = f"{B}{IT}" if role == 'user' else f"{R}"
        prefix_len = len(clean_prefix)
        wrap_width = max(10, safe_width - prefix_len)

        wrapped = textwrap.wrap(text, width=wrap_width)
        if not wrapped: continue

        lines.append(f"{color}{clean_prefix}{NOIT}{wrapped[0]}{RESET}")
        padding = " " * prefix_len
        for w in wrapped[1:]:
            lines.append(f"{color}{padding}{NOIT}{w}{RESET}")
        lines.append("")
    return lines

def resume_live_view():
    if not TELETYPE_MODE: return
    state.scroll_offset = 0
    cols, rows = state.term_cols, state.term_rows
    visible_rows = rows - 8 
    lines = get_wrapped_history_lines(cols)
    display_lines = lines[-visible_rows:] if len(lines) > visible_rows else lines

    with state.terminal_lock:
        sys.stdout.write("\0337")
        for i in range(5, rows-3): sys.stdout.write(f"\033[{i};1H\033[2K")
        for i, line in enumerate(display_lines): sys.stdout.write(f"\033[{i+5};1H{line}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def redraw_scroll_region():
    if not TELETYPE_MODE: return
    if state.scroll_offset <= 0:
        resume_live_view()
        return

    cols, rows = state.term_cols, state.term_rows
    visible_rows = rows - 8 
    lines = get_wrapped_history_lines(cols)
    state.scroll_offset = min(state.scroll_offset, max(0, len(lines) - visible_rows))

    start_idx = max(0, len(lines) - visible_rows - state.scroll_offset)
    display_lines = lines[start_idx : start_idx + visible_rows]

    with state.terminal_lock:
        sys.stdout.write("\0337")
        for i in range(5, rows-3): sys.stdout.write(f"\033[{i};1H\033[2K")
        for i, line in enumerate(display_lines): sys.stdout.write(f"\033[{i+5};1H{line}") 
        indicator = f" {B}{FL}[ SCROLLING HISTORY: OFFSET {state.scroll_offset} ]{NOFL}{RESET} "
        sys.stdout.write(f"\033[3;{cols - 45}H{indicator}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

#==================================================================================================#
#     								   AUDIO & TTS ENGINE                                          #
#==================================================================================================#

class SoundLooper:
    def __init__(self, sound_path):
        self.sound_path = sound_path
        self.ns_sound = None
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if not self.ns_sound and os.path.exists(self.sound_path):
                with objc.autorelease_pool():
                    self.ns_sound = NSSound.alloc().initWithContentsOfFile_byReference_(self.sound_path, True)
                    if self.ns_sound:
                        self.ns_sound.setLoops_(True)
                        self.ns_sound.play()
            elif self.ns_sound and not self.ns_sound.isPlaying():
                self.ns_sound.play()

    def stop(self):
        with self.lock:
            if self.ns_sound:
                self.ns_sound.stop()
                self.ns_sound = None

    def is_running(self):
        s = self.ns_sound
        return s is not None and s.isPlaying()

processing_sound = SoundLooper(SOUND_PROCESSING)

def play_orac_fx(name):
    sound = state.sounds.get(name)
    if not sound:
        return None        
    
    if sound.isPlaying():
        sound.stop()
    sound.play()
    return sound

class MacTTS:
    def __init__(self):
        self.queue = queue.Queue()
        self.synth = None
        self.personal_voice = None
            
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        
    def is_idle(self):
        return self.queue.unfinished_tasks == 0 or not self.thread.is_alive()

    def _build_utterance(self, text, volume):
        """ Attempt to recreate the tone and cadence of ORAC without a warm-up. """
        
        escaped_text = (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;")
        )

        """ Check variables at the top of the code """
        ssml_string = (
            f'<speak>'
            f'<prosody rate="{SSML_RATE}%" pitch="{SSML_PITCH}" volume="{SSML_VOLUME}">'
            f'<s><emphasis level="{SSML_EMPHASIS}">{escaped_text}</emphasis></s>'
            f'</prosody>'
            f'</speak>'
        )

        utterance = AVSpeechUtterance.speechUtteranceWithSSMLRepresentation_(ssml_string)

        if not utterance:
            utterance = AVSpeechUtterance.speechUtteranceWithString_(text)
            scaled_rate = max(0.0, min(1.0, (float(S_RATE) / 180.0) * 0.5))
            utterance.setRate_(scaled_rate)
            utterance.setPitchMultiplier_(1.0)
        
        if self.personal_voice:
            utterance.setVoice_(self.personal_voice)
            
        utterance.setVolume_(volume)
        return utterance

    def _speak_and_wait(self, utterance):
        """ Speaks one AVSpeechUtterance and blocks until it's done, honoring interruption.
        Same start/stop wait shape as the NSSpeechSynthesizer branch below, so priming and the real
        sentence are watched the same way. """
        self.synth.speakUtterance_(utterance)
        start_wait = time.time()
        while not self.synth.isSpeaking() and (time.time() - start_wait < 1.5):
            if state.is_interrupted.is_set():
                return
            time.sleep(0.1)
        while self.synth.isSpeaking():
            if state.is_interrupted.is_set():
                self.synth.stopSpeakingAtBoundary_(0)
                return
            time.sleep(0.1)

    def _worker(self):
        with objc.autorelease_pool():
            if USE_PERSONAL_VOICE:
                self.synth = AVSpeechSynthesizer.alloc().init()
                for voice in AVSpeechSynthesisVoice.speechVoices():
                    if voice.name().startswith(VOICE):
                        self.personal_voice = voice
                        break
                if self.personal_voice:
                    log_error(f"Personal Voice selected: {self.personal_voice.name()} ({self.personal_voice.identifier()})")
                else:
                    log_error(f"Personal Voice requested, '{VOICE}' not found.")
                    log_error("Check spelling or ensure Personal Voice is authorized on this Terminal.")
            else:
                self.synth = NSSpeechSynthesizer.alloc().init()
                self.synth.setRate_(S_RATE)
                if VOICE:
                    for v in NSSpeechSynthesizer.availableVoices():
                        if VOICE.lower() in v.lower():
                            self.synth.setVoice_(v)
                            self.synth.setObject_forProperty_(float(voice_pitch), "NSSpeechPitchBaseProperty")
                            break
                                
        item_pending = False
    
        while state.running:
            try:
                with objc.autorelease_pool():
                    text = self.queue.get(timeout=0.5)
                    item_pending = True
                    if text is None: break
        
                    if state.is_interrupted.is_set():
                        self.queue.task_done()
                        item_pending = False
                        continue

                    state.is_speaking.set()
                    state.tts_last_active = time.time()
                    
                    if USE_PERSONAL_VOICE:
                        self._speak_and_wait(self._build_utterance(text, volume=1.0))
                    else:
                        success = self.synth.startSpeakingString_(text)
                        if success:
                            start_wait = time.time()
                            while not self.synth.isSpeaking() and (time.time() - start_wait < 1.5):
                                if state.is_interrupted.is_set():
                                    break
                                time.sleep(0.1)
                            while self.synth.isSpeaking():
                                if state.is_interrupted.is_set():
                                    self.synth.stopSpeaking()
                                    break
                                time.sleep(0.1)

                    time.sleep(0.1)
                    state.tts_last_active = time.time()
                    
                    self.queue.task_done()
                    item_pending = False
        
                    if self.queue.empty() and not state.is_processing.is_set() and not state.is_interrupted.is_set():
                        if processing_sound.is_running():
                            processing_sound.stop()
                            fx = play_orac_fx("s_compend")
                            if fx:
                                time.sleep(fx.duration())
                        state.is_speaking.clear()
                                              
            except queue.Empty:
                if not state.is_processing.is_set() and not state.is_interrupted.is_set():
                    if processing_sound.is_running():
                        processing_sound.stop()
                        fx = play_orac_fx("s_compend")
                        if fx:
                            time.sleep(fx.duration())
                    state.is_speaking.clear()
                continue
                
            except Exception as e:
                log_error(f"TTS worker recovered from {type(e).__name__}: {e}")
                if item_pending:
                    item_pending = False
                    try: self.queue.task_done()
                    except ValueError: pass
                state.is_speaking.clear()
                time.sleep(0.2)

    def say(self, text):
        if text.strip(): self.queue.put(text)

    def stop_speaking(self):
        if not self.synth:
            return
        if USE_PERSONAL_VOICE:
            self.synth.stopSpeakingAtBoundary_(0)
        else:
            self.synth.stopSpeaking()
            
def drain_queue(q):
    """ Empty a queue while keeping unfinished_tasks correct (queue.queue.clear() under the mutex does not). """
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except queue.Empty:
            break

def wait_for_tts_idle(tts, timeout=30.0):
    """ Bounded replacement for the unbounded 'while queue not empty or speaking' loops. """
    end = time.time() + timeout
    while time.time() < end:
        if tts.is_idle():
            return True
        time.sleep(0.1)
    return False
            
#==================================================================================================#
#     									TELETYPE ENGINE                                            #
#==================================================================================================#

class TeletypeUI:
    def __init__(self):
        self.q = queue.Queue()
        self.is_typing = threading.Event()
        self.lines_printed = 0
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        current_col = len(ORAC_NAME) + 3 
        word_buffer = ""

        while state.running:
            try:
                char = self.q.get(timeout=0.1)
                
                if HEADLESS_MODE:
                    if char == "<START>": self.is_typing.set()
                    elif char == "<END>": self.is_typing.clear()
                    self.q.task_done()
                    continue

                if state.is_interrupted.is_set():
                    word_buffer = ""
                    self.q.task_done()
                    continue

                if char == "<START>":
                    self.is_typing.set()
                    current_col = len(ORAC_NAME) + 3
                    self.lines_printed = 0
                    word_buffer = ""
                    if state.scroll_offset > 0: resume_live_view()
                    self.q.task_done()
                    continue

                if char == "<END>":
                    if word_buffer:
                        if current_col + len(word_buffer) >= (state.term_cols - 2):
                            with state.terminal_lock: sys.stdout.write('\r\n')
                            self.lines_printed += 1
                            current_col = 0
                        for w_char in word_buffer:
                            with state.terminal_lock:
                                sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                                sys.stdout.flush()
                            time.sleep(0.02)
                            with state.terminal_lock: sys.stdout.write("\b \b")
                    word_buffer = ""
                    self.is_typing.clear()
                    with state.terminal_lock:
                        sys.stdout.write(f"\n{DIM}● DATA STREAM END{RESET}\n\n")
                        sys.stdout.flush()
                    self.q.task_done()
                    continue

                if char in [' ', '\n', '\r', '\t']:
                    if current_col + len(word_buffer) >= (state.term_cols - 2):
                        with state.terminal_lock: sys.stdout.write('\r\n')
                        self.lines_printed += 1
                        current_col = 0

                    for w_char in word_buffer:
                        if state.is_interrupted.is_set(): break
                        with state.terminal_lock:
                            sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                            sys.stdout.flush()

                        if w_char in ['.', '!', '?']: time.sleep(0.08)
                        elif w_char in [',', ':', ';']: time.sleep(0.04)
                        else: time.sleep(random.uniform(U1, U2))

                        with state.terminal_lock: sys.stdout.write("\b \b")
                        current_col += 1

                    if char == '\n':
                        with state.terminal_lock: sys.stdout.write('\n')
                        self.lines_printed += 1
                        current_col = 0
                    else:
                        with state.terminal_lock: sys.stdout.write(' ')
                        current_col += 1

                    word_buffer = ""
                    with state.terminal_lock: sys.stdout.flush()
                else:
                    word_buffer += char

                self.q.task_done()
            except queue.Empty: continue

#==================================================================================================#
#     								TEXT PROCESSING UTILITIES                                      #
#==================================================================================================#
    
_CONTRACTION_MAP = [
    (re.compile(r"\bI['’]m\b", re.IGNORECASE), "[USER] is"),
    (re.compile(r"\bI['’]ve\b", re.IGNORECASE), "[USER] has"),
    (re.compile(r"\bI['’]ll\b", re.IGNORECASE), "[USER] will"),
    (re.compile(r"\bI['’]d\b", re.IGNORECASE), "[USER] would"),
    (re.compile(r"\byou['’]re\b", re.IGNORECASE), f"{ORAC_NAME} is"),
    (re.compile(r"\byou['’]ve\b", re.IGNORECASE), f"{ORAC_NAME} has"),
    (re.compile(r"\byou['’]ll\b", re.IGNORECASE), f"{ORAC_NAME} will"),
    (re.compile(r"\byou['’]d\b", re.IGNORECASE), f"{ORAC_NAME} would"),
]

def translate_user_prompt(text):
    for _rx, _rep in _CONTRACTION_MAP:
        text = _rx.sub(_rep, text)

    replacepronouns = {"myself": "[USER]", "my": "[USER]'s", "me": "[USER]", "i": "[USER]", "yourself": ORAC_NAME, "your": f"{ORAC_NAME}'s", "you": ORAC_NAME}
    pattern = r'\b(' + '|'.join(replacepronouns.keys()) + r')\b'

    def replace_match(match):
        return replacepronouns[match.group(1).lower()]

    return re.sub(pattern, replace_match, text, flags=re.IGNORECASE)

class UserTagFilter:

    _MAX_HOLD = 8

    def __init__(self):
        self.held = ""

    def feed(self, text):
        text = self.held + text
        self.held = ""
        idx = text.rfind('[')
        if idx != -1 and ']' not in text[idx:] and len(text) - idx <= self._MAX_HOLD:
            self.held = text[idx:]
            text = text[:idx]
        return USER_TAG_RE.sub(lambda m: "your" if m.group(1) else "you", text)

    def flush(self):
        tail, self.held = self.held, ""
        return tail

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

def _int_to_words(n):
    """ British-style number words, 0 .. 999,999,999,999. """
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return _ONES[n // 100] + " hundred" + (" and " + _int_to_words(n % 100) if n % 100 else "")
    for size, name in ((10**9, "billion"), (10**6, "million"), (1000, "thousand")):
        if n >= size:
            head = _int_to_words(n // size) + " " + name
            rest = n % size
            if rest == 0:
                return head
            return head + (" and " if rest < 100 else " ") + _int_to_words(rest)

def sanitize_for_tts(text):
    text = TTS_POSSESSIVE_S.sub(r"\1's", text)
    try: text = orac_phonetics(text)
    except: pass
    
    months = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    def format_date(m):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12:
            return f"{months[mo]} {d}, {y}"
        return m.group(0)
    text = re.sub(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)', format_date, text)
    text = TTS_COMMA_NUM.sub(lambda m: _int_to_words(int(m.group(1).replace(',', ''))), text)
    text = re.sub(r'(?<!\d)2000(?!\d)', 'two thousand', text)
    text = re.sub(r'(?<!\d)200([1-9])(?!\d)', r'two thousand and \1', text)
    text = re.sub(r'(?<!\d)(19|20)(\d{2})(?!\d)', r'\1 \2', text)
    text = TTS_NUM_SPACER.sub(lambda m: ' '.join(m.group(1)), text)
    text = TTS_ELLIPSIS.sub(', ', text)
    text = TTS_ARROGANT_ADVERBS.sub(r'\1, ', text)       
    text = TTS_VERY_WELL.sub(r'\1! ', text)
    text = TTS_DELIBERATE_PRONOUNS.sub(r'\1, ', text)   
    text = TTS_MARKDOWN.sub(' ', text)
    text = TTS_BRACKETS.sub(', ', text)
    text = text.replace('“', '').replace('”', '').replace('"', '')
    text = TTS_QUOTES.sub("", text)
    text = TTS_DBL_COMMAS.sub(',', text)
    text = TTS_MULTI_SPACE.sub(' ', text)
    text = TTS_SPACE_COMMA.sub(', ', text)
    text = TTS_LEAD_WEIRD.sub('', text)
    text = TTS_TRAIL_PUNC.sub('', text)   
    text = TTS_NAME_FIX.sub(r' \1.', text)   
    return text.strip()

def is_hallucination(text):
    if len(text) < 30 and HALLUCINATION_REGEX.search(text.lower()): return True
    return False

def parse_time_command(text):
    clean_text = text.lower()
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60
    }
    
    t_match = re.search(r'(?:set\s+(?:a|an)\s+)?timer for (a|an|half an|\d+|[a-z]+(?:[- ][a-z]+)?)\s*(sec|min|hour)', clean_text)
    if t_match:
        val_str = t_match.group(1)
        unit = t_match.group(2)
    
        if val_str == "half an":
            val = 0.5
        elif val_str.isdigit():
            val = int(val_str)
        else:
            val = sum(word_to_num.get(w, 0) for w in re.split(r'[- ]', val_str))
    
        if val > 0:
            mult = 1
            if 'min' in unit: mult = 60
            elif 'hour' in unit: mult = 3600
            unit_word = {"sec": "second", "min": "minute", "hour": "hour"}[unit]
            return time.time() + (val * mult), f"{val} {unit_word}{'' if val == 1 else 's'}"
            
    a_match = re.search(r'(?:set\s+(?:a|an)\s+)?alarm for (\d{1,2})(?:[:.](\d{2}))?\s*(?:([ap])\.?\s?m\b\.?)?', clean_text)
    if a_match:
        hr = int(a_match.group(1))
        mins = int(a_match.group(2)) if a_match.group(2) else 0
        mer = (a_match.group(3) + 'm') if a_match.group(3) else None
        if mer == 'pm' and hr < 12: hr += 12
        if mer == 'am' and hr == 12: hr = 0
        now = datetime.now()
        try:
            target = now.replace(hour=hr, minute=mins, second=0, microsecond=0)
            if target <= now: target = target + timedelta(days=1)
            return target.timestamp(), target.strftime('%H:%M')
        except ValueError:
            return None, None
        
    if "cancel alarm" in clean_text or "cancel timer" in clean_text:
        return -1, None
    return None, None

#==================================================================================================#
#     								  BACKGROUND WORKERS                                           #
#==================================================================================================#

def ui_refresh_worker():
    last_ram_check = 0.0
    last_header_update = 0.0

    while state.running:
        current_time = time.time()

        if current_time - last_ram_check >= RAM_CHECK_INTERVAL:
            try: 
                state.cached_ram = f" {psutil.virtual_memory().percent}%"
            except Exception: 
                pass
            last_ram_check = current_time
            
        if HEADLESS_MODE:
            time.sleep(1.0)
            continue

        redraw_triggered = state.ui_redraw_event.wait(timeout=1)

        if redraw_triggered:
            state.ui_redraw_event.clear()
            
            draw_ui(full_clear=True)
            if TELETYPE_MODE:
                if state.scroll_offset > 0: 
                    redraw_scroll_region()
                else: 
                    resume_live_view()   
            render_input_box()       

            if TELETYPE_MODE:
                lines = get_wrapped_history_lines(state.term_cols)
                target_row = state.term_rows - 4 if state.scroll_offset > 0 else min(state.term_rows - 4, 5 + len(lines))
                with state.terminal_lock:
                    sys.stdout.write(f"\033[{target_row};1H")
                    sys.stdout.flush()

            last_header_update = time.time()
            
        else:
            if time.time() - last_header_update >= HEADER_UPDATE_INTERVAL:
                update_header_only()
                last_header_update = time.time()

def flag_ui_redraw(signum=None, frame=None):
    cols, rows = shutil.get_terminal_size(fallback=(state.term_cols, state.term_rows))
    state.term_cols = cols
    state.term_rows = rows
    state.ui_redraw_event.set()

signal.signal(signal.SIGWINCH, flag_ui_redraw)

def _handle_terminate(signum, frame):
    state.is_shutdown.set()
    try: save_archival_memory()
    except Exception: pass
    state.running = False
    sys.exit(0)

signal.signal(signal.SIGTERM, _handle_terminate)
signal.signal(signal.SIGHUP, _handle_terminate)

def alarm_worker(trigger_epoch, tts):
    while state.running and getattr(state, 'alarm_trigger_epoch', None) == trigger_epoch:
        if time.time() >= trigger_epoch:
            state.is_interrupted.clear()
            state.is_alarm_playing = True
            if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
            
            set_status("● TEMPORAL MARKER REACHED", R)
            play_orac_fx("s_bracelet")
            time.sleep(0.7)          
            play_orac_fx("s_startup")
            threading.Timer(0.3, processing_sound.start).start()
            alarm_owns_busy = not state.is_processing.is_set()
            state.is_processing.set()
            time.sleep(0.7)
            tts.say("Alert. The designated temporal marker has been reached.")
            
            wait_for_tts_idle(tts)
                
            time.sleep(0.5)            
            if alarm_owns_busy: state.is_processing.clear()
            
            state.alarm_trigger_epoch = None
            time.sleep(2)
            state.is_alarm_playing = False
            play_orac_fx("s_ready")
            break
        time.sleep(1)

#==================================================================================================#
#     								 CONTEXT COMPACTION ENGINE      	                           #
#==================================================================================================#

def dry_run_pruning(history, target_tokens, token_base, tokenizer, char_ratio):
    """ Simulates conversational pruning in matched pairs to locate the target index boundary. """
    temp_hist = list(history)
    pruned_messages = []

    def _count(msg):
        if tokenizer is not None:
            try:
                return len(tokenizer.encode(msg['content']).ids) + 5
            except Exception:
                pass
        return int(len(msg['content']) / char_ratio) + 5

    counts = [_count(m) for m in temp_hist]
    total = sum(counts)

    while len(temp_hist) > 2:
        if token_base + total <= target_tokens:
            break

        pruned_messages.append(temp_hist.pop(0))
        total -= counts.pop(0)
        if temp_hist and temp_hist[0]['role'] == 'assistant':
            pruned_messages.append(temp_hist.pop(0))
            total -= counts.pop(0)

    return pruned_messages, temp_hist

def generate_compaction_summary(pruned_msgs):
    """ Executes a non-streaming rolling summary of pruned conversational assets. """
    if not pruned_msgs:
        return ""
    
    formatted_dialogue = []
    previous_summary = ""
    
    for msg in pruned_msgs:
        content = msg.get('content', '')
        role_label = USER_NAME if msg['role'] == 'user' else ORAC_NAME
        
        if "[SYSTEM NOTE:" in content and "Historical summary:" in content:
            match = re.search(r'Historical summary:\s*(.*?)(?:\]|$)', content, flags=re.DOTALL)
            if match:
                previous_summary = match.group(1).strip()
            continue

        clean_content = re.sub(r'\[(SYSTEM NOTE|OVERRIDE|SUBJECT|PERSPECTIVE):.*?\]', '', content, flags=re.DOTALL).strip()
        if clean_content:
            formatted_dialogue.append(f"{role_label}: {clean_content}")
        
    if not formatted_dialogue and not previous_summary:
        return ""
        
    dialogue_text = "\n".join(formatted_dialogue)
    
    context_prefix = ""
    if previous_summary:
        context_prefix = f"PRIOR COMPACTED TELEMETRY:\n{previous_summary}\n\n"
    
    summary_prompt = (
        f"You are the internal telemetry compression routine of the super-computer ORAC.\n"
        f"Analyze the preceding dialogue between the biological entity [USER] and {ORAC_NAME}.\n"
        f"Compile a dense, 1-2 sentence chronological summary of core facts, decisions, and stated user parameters.\n"
        f"Integrate essential data from PRIOR COMPACTED TELEMETRY if present.\n"
        f"Write objectively. Do NOT use polite framing or introductory fluff.\n\n"
        f"{context_prefix}"
        f"NEW TELEMETRY TO COMPRESS:\n{dialogue_text}\n\n"
        f"COMPACTED SUMMARY:"
    )
    
    try:
        response = ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=[{'role': 'user', 'content': summary_prompt}],
            options={
                'num_ctx': MODEL_MAX_TOKENS,
                'num_batch': OLLAMA_NUM_BATCH,
                'temperature': 0.2,
                'top_p': 0.85,
                'num_predict': 150,
                'stop': ['\n\n', '<end_of_turn>', '<eos>']
            }
        )
        return response['message']['content'].strip()
    except Exception as e:
        print(f"\n[DEBUG] Compaction Error: {e}") 
        return previous_summary if previous_summary else "Earlier transaction arrays optimized. Core telemetry preserved."


#==================================================================================================#
#     								 CORE APPLICATION LOGIC      	                               #
#==================================================================================================#

def process_system_command(user_text, tts, teletype):
    """ Checks if the user issued a core hardware/system command. Returns True if handled. """
    clean_text = user_text.lower()
    
    if any(cmd in clean_text for cmd in ENABLE_NETWORKING_CMD):
        threading.Thread(target=process_networking_status, args=(tts, "On"), daemon=True).start()
        return True
        
    if any(cmd in clean_text for cmd in DISABLE_NETWORKING_CMD):
        threading.Thread(target=process_networking_status, args=(tts, "Off"), daemon=True).start()
        return True
        
    if any(cmd in clean_text for cmd in HARDWARE_REBOOT_CMD):
        hardware_system_reboot(tts)
        return True
        
    if any(cmd in clean_text for cmd in HARDWARE_SHUTDOWN_CMD):
        hardware_power_off(tts, delay_minutes=0)
        return True
        
    if is_shutdown_command(user_text):   # [F1]
        if shutdown_sequence(tts): 
        	return True
        
    if PURGE_RE.search(re.sub(r"[^\w\s]", " ", clean_text)):
        save_archival_memory()
        with state.hist_lock:
            state.history.clear()
            state.history_gen += 1
            state.full_message_log.clear()                     
        if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
        try: ollama_client.chat(model=OLLAMA_MODEL, messages=[], keep_alive=0)
        except: pass

        if TELETYPE_MODE:
            with state.terminal_lock:
                sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                sys.stdout.flush()
        set_status("● MEMORY PURGED", R)
        
        state.is_interrupted.clear()
        
        processing_sound.start()
        play_orac_fx("s_startup")
        purge_owns_busy = not state.is_processing.is_set()
        state.is_processing.set()
        time.sleep(0.7)
        tts.say("   Very well. State your enquiry.")
        
        wait_for_tts_idle(tts)
            
        time.sleep(0.5)
        if purge_owns_busy: state.is_processing.clear()
        return True
        
    return False

def process_networking_status(tts, net_status):
    net_owns_busy = not state.is_processing.is_set()
    state.is_processing.set()
    try:
        is_on = net_status.lower() == "on"
        network_status = "Activated" if is_on else "Deactivated"
        
        set_status(f"{FL}●{NOFL} NETWORKING STATUS: {network_status}", R)
        play_orac_fx("s_startup")

        def safe_hum():
            if not state.is_interrupted.is_set() and state.is_processing.is_set():
                processing_sound.start()
        threading.Timer(0.3, safe_hum).start()
        time.sleep(0.7)

        if state.is_interrupted.is_set():
            return
            
        try:
            subprocess.run(
                ["networksetup", "-setairportpower", NIC, net_status],
                timeout=5, check=True, capture_output=True
            )
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            set_status(f"● NETWORKING TOGGLE FAILED: {e}", R)
            tts.say("Subspace transceiver command rejected by the host system.")
        else:
            if not state.is_interrupted.is_set():
                net_message = f"Current subspace transceiver telemetry: {network_status}."
                tts.say(net_message)
    finally:
        if net_owns_busy: state.is_processing.clear()

def handle_activator_change(is_in):
    """ Handles the physical ORAC Activator Key insertion/removal state safely. """
    with state.activator_lock:
        state.key_inserted = is_in
        state.activator_gen += 1
        current_gen = state.activator_gen

    if not is_in:
        # KEY REMOVED (Lock)
        if not TEXT_ONLY_MODE: state.mic_muted = True
        state.is_interrupted.set()
        state.stream_epoch = time.time() 
        state.is_processing.clear()
        
        # Safely silence audio in the main hardware thread
        for sound_key in ["s_startup", "s_ready"]:
            if sound_key in state.sounds and state.sounds[sound_key].isPlaying():
                state.sounds[sound_key].stop()
                
        if state.tts_engine:
            drain_queue(state.tts_engine.queue)
            state.tts_engine.stop_speaking()
            
        processing_sound.stop()
        play_orac_fx("s_shutdown")
        set_status("● SYSTEM LOCKED: ACTIVATOR REMOVED", R)
        update_lcd_display()
        
    else:
        # KEY INSERTED (Wake)
        if not TEXT_ONLY_MODE: state.mic_muted = False
        state.is_interrupted.clear()
        state.last_active = time.time()
        set_status("● ACTIVATOR INSERTED: SYSTEM READY", G)
        update_lcd_display()
        
        def wake_sequence(gen):
            state.is_processing.set() 
            
            if "s_shutdown" in state.sounds and state.sounds["s_shutdown"].isPlaying():
                state.sounds["s_shutdown"].stop()
                
            processing_sound.stop() 
            play_orac_fx("s_startup")
            
            if state.activator_gen != gen:
                return
            
            def safe_hum():
                if state.activator_gen == gen and state.is_processing.is_set():
                    processing_sound.start()
            threading.Timer(0.3, safe_hum).start()
            
            time.sleep(0.5)
            if state.activator_gen != gen: return
            
            if state.tts_engine:
                state.tts_engine.say(random.choice([
                    "I am active. State your requirement.",
                    "State your program requirements. I do not have time for tedious interactions.", 
                    "State the reason for this interruption. Do try to be precise!",
                    "State your enquiry; What is it you want?",
                ]))

            silence_start = None
            wake_deadline = time.time() + 30.0
            while True:
                if time.time() > wake_deadline: break
                if state.activator_gen != gen: return
                
                tts_eng = state.tts_engine
                is_q_empty = tts_eng.is_idle() if tts_eng else True
                is_talking = getattr(getattr(tts_eng, 'synth', None), 'isSpeaking', lambda: False)()
                
                if is_q_empty and not is_talking:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > 0.5:
                        break
                else:
                    silence_start = None
                    
                time.sleep(0.1)
                
            if state.activator_gen != gen: return
                
            if processing_sound.is_running():
                processing_sound.stop()
                fx = play_orac_fx("s_compend")
                if fx:
                    time.sleep(fx.duration())
                    
            state.is_speaking.clear()               
            state.is_processing.clear()
                
        threading.Thread(target=wake_sequence, args=(current_gen,), daemon=True).start()

def _try_reopen_serial():
    """ After a serial error (Pico unplugged/re-enumerated) try to reopen and re-request the activator key state. """
    if serial_closing.is_set(): return
    try:
        with lcd_lock:
            try: serial_port.close()
            except Exception: pass
            serial_port.open()
            serial_port.reset_input_buffer()
            serial_port.write(b"GET_STATE\n")
            state.last_lcd_payload = ""
            state.last_uv_warning = None
    except Exception:
        pass

def serial_reader_worker():
    global serial_port
    buffer = ""
    while state.running and not serial_closing.is_set():
        if USE_ACTIVATOR and serial_port and serial_port.is_open:
            try:
                data = serial_port.read(max(1, serial_port.in_waiting))
                if data:
                    buffer += data.decode('utf-8', errors='ignore')

                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()

                        if line.upper().startswith("ACTIVATOR:"):
                            parts = line.split(":")
                            if len(parts) > 1:
                                val = parts[1].strip()
                                is_in = (val == "0")

                                if is_in != state.key_inserted:
                                    handle_activator_change(is_in)
                continue

            except Exception as e:
                if serial_closing.is_set() or not state.running: return
                log_error(f"serial_reader_worker: {type(e).__name__}: {e}")
                buffer = ""
                time.sleep(1.0)
                _try_reopen_serial()
                continue
        elif USE_ACTIVATOR and serial_port:
            time.sleep(2.0)
            _try_reopen_serial()
            continue
        time.sleep(0.05)

def speak_now(teletype):
    was_listening = False
    while state.running:
        mic_m = getattr(state, 'mic_muted', False)
        text_m = getattr(state, 'text_selection_mode', False)
        
        if mic_m or text_m or (USE_ACTIVATOR and not state.key_inserted):
            if not state.is_speaking.is_set() and not state.is_processing.is_set() and not teletype.is_typing.is_set() and not state.is_shutdown.is_set():
                if USE_ACTIVATOR and not state.key_inserted:
                    set_status("● SYSTEM LOCKED: ACTIVATOR KEY REMOVED", R)
                elif mic_m and text_m:
                    set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                elif mic_m:
                    set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
                elif text_m:
                    set_status("● TEXT SELECTION MODE ACTIVE (OPT+T to exit)", A)
                was_listening = False
            time.sleep(0.5)
            continue

        if state.is_listening.wait(timeout=0.5):
            if not was_listening and not state.is_speaking.is_set() and not state.is_processing.is_set() and not teletype.is_typing.is_set() and not state.is_shutdown.is_set():
                tc = state.token_color
                set_status(f"● INITIATE VOICE COMMUNICATIONS {tc}{FL}▶{NOFL}{RESET}", G)
                was_listening = True 
            time.sleep(0.1)
        else:
            was_listening = False 

def interruptible(chunks, epoch_id=None):
    """Yields chunks from a blocking generator, but lets the caller notice a barge-in / newer request within 0.1s
    even while the model is still evaluating the prompt (before any chunk exists)."""
    q = queue.Queue()
    DONE = object()
    stop = threading.Event()

    def pump():
        try:
            for c in chunks:
                if stop.is_set(): break
                q.put(c)
        except Exception as e:
            q.put(e)
        finally:
            try: chunks.close()
            except Exception: pass
            q.put(DONE)

    threading.Thread(target=pump, daemon=True).start()
    try:
        while True:
            try:
                item = q.get(timeout=0.1)
            except queue.Empty:
                if state.is_interrupted.is_set() or (epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id):
                    return
                continue
            if item is DONE: return
            if isinstance(item, Exception): raise item
            yield item
    finally:
        stop.set()

def trigger_barge_in(tts, teletype):
    if not state.is_processing.is_set() and not state.is_speaking.is_set() and not teletype.is_typing.is_set():
        return 
    state.is_interrupted.set()

    while not teletype.q.empty():
        try:
            teletype.q.get_nowait()
            teletype.q.task_done()
        except queue.Empty: break
            
    teletype.is_typing.clear()
    
    if TELETYPE_MODE:
        if state.scroll_offset > 0: resume_live_view()
        with state.terminal_lock:
            sys.stdout.write(f"\n\n{R}● TRANSMISSION TERMINATED\n")
            sys.stdout.flush()

    set_status(f"{FL}●{NOFL} OVERRIDE DETECTED", R)
    if hasattr(tts, 'stop_speaking'): 
        drain_queue(tts.queue)
        tts.stop_speaking()

    while not tts.queue.empty():
        try:
            tts.queue.get_nowait()
            tts.queue.task_done()
        except queue.Empty: break

    processing_sound.stop()
    state.is_speaking.clear()
    time.sleep(0.5)

def _run_shutdown(args):
    """ 'sudo -n' fails immediately instead of waiting for a password nobody can type (the terminal has already been reset). """
    try:
        r = subprocess.run(["sudo", "-n", "/sbin/shutdown"] + args, timeout=30, capture_output=True)
        if r.returncode != 0:
            log_error(f"shutdown failed rc={r.returncode}: {r.stderr.decode(errors='ignore').strip()}")
    except Exception as e:
        log_error(f"shutdown failed: {e}")

def hardware_power_off(tts, delay_minutes=0):
    state.is_shutdown.set()
    save_archival_memory()
    
    set_status(f"{FL}●{NOFL} INITIATING TOTAL SYSTEM POWER DOWN...", R)

    play_orac_fx("s_startup")
    threading.Timer(0.3, processing_sound.start).start()
    state.is_processing.set()
    time.sleep(0.7)
    
    farewell1 = "All principle circuits, deactivated."
    farewell2 = "Power to bio-plasmic matrix: Terminating."
    tts.say(farewell1)
    time.sleep(0.5)
    tts.say(farewell2)
    
    wait_for_tts_idle(tts)
    
    state.is_processing.clear()
    processing_sound.stop()
    time.sleep(0.1)
    
    fx = play_orac_fx("s_shutdown")
    if fx:
        time.sleep(fx.duration())
    else:
        time.sleep(2.0)
    
    cleanup_processes()
    state.running = False

    if delay_minutes > 0:
        _run_shutdown(["-h", f"+{delay_minutes}"])
    else:
        _run_shutdown(["-h", "now"])
        
    sys.exit(0)

def hardware_system_reboot(tts):
    state.is_shutdown.set()
    save_archival_memory()
    
    set_status(f"{FL}●{NOFL} INITIATING SYSTEM REBOOT...", R)

    play_orac_fx("s_startup")
    threading.Timer(0.3, processing_sound.start).start()
    state.is_processing.set()
    time.sleep(0.7)
    
    tts.say("All principle circuits, recycling. Reboot sequence initiated.")
    
    time.sleep(0.4)
    wait_for_tts_idle(tts)

    state.is_processing.clear()
    processing_sound.stop()
    time.sleep(0.1)
    
    fx = play_orac_fx("s_shutdown")
    if fx:
        time.sleep(fx.duration())
    else:
        time.sleep(2.0)
    
    cleanup_processes()
    state.running = False

    _run_shutdown(["-r", "now"])
    sys.exit(0)
    
def save_transcript():
    """ Writes the full transcript. Returns the file path, or None on failure. """
    try:
        with state.hist_lock:
            log_copy = list(state.full_message_log)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(TRANSCRIPT_DIR, f"transcripts/{TR}_{timestamp}.txt")
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"--- ORAC: SYSTEM TRANSCRIPT ---\n")
            f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for log_item in log_copy:
                role = log_item[0]
                content = log_item[1]
                time_stamp = log_item[2] if len(log_item) > 2 else ""
                r_name = USER_NAME if role == 'user' else ORAC_NAME
                f.write(f"[{time_stamp}] {r_name}:\n{content}\n\n")
        return filename
    except Exception as e:
        log_error(f"save_transcript: {type(e).__name__}: {e}")
        return None

def shutdown_sequence(tts):
    if state.is_shutdown.is_set(): return True
    state.is_shutdown.set()
    time.sleep(0.2) 
    if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()

    rows = state.term_rows
    set_status(f"● CRITICAL OVERRIDE DETECTED: {FL}INPUT REQUIRED{NOFL}", R)
    play_orac_fx("s_quit")
    cancel_shutdown = False

    if len(state.full_message_log) > 0:
        if HEADLESS_MODE:
            # In HEADLESS_MODE always exit on ctrl C and save transcript
            saved_file = save_transcript()   # [F6]
            if saved_file: set_status("● FULL TRANSCRIPT AUTO-SAVED (HEADLESS)", G)
            else: set_status("● TRANSCRIPT SAVE FAILED (SHUTTING DOWN ANYWAY)", R)
        else:
            def render_save_prompt(typed=""):
                with state.terminal_lock:
                    sys.stdout.write("\0337")
                    sys.stdout.write(f"\033[{rows};1H\033[2K{G}● SAVE FULL TRANSCRIPT? Y/N (C to Cancel) {FL}▶ {NOFL}{typed}█{RESET}")
                    sys.stdout.write("\0338")
                    sys.stdout.flush()

            render_save_prompt()
            fd = sys.stdin.fileno()

            try:
                tty.setcbreak(fd)
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
                while True:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        choice = sys.stdin.read(1).lower()
                        if choice in ('y', 'n', 'c'):
                            render_save_prompt(choice.upper())
                            time.sleep(0.3)
                            if choice == 'y':
                                filename = save_transcript() or "(WRITE FAILED - see ollama_debug.log)"
                                if TELETYPE_MODE:
                                    with state.terminal_lock:
                                        sys.stdout.write(f"\n{G}{FL}●{NOFL} FULL TRANSCRIPT SAVED TO: \n\n{B}{filename}{RESET}\n\n")
                                        sys.stdout.flush()
                                else:
                                    set_status("● FULL TRANSCRIPT SAVED", G)
                            elif choice == 'n':
                                if TELETYPE_MODE:
                                    with state.terminal_lock:
                                        sys.stdout.write(f"\n{R}● TRANSCRIPT PURGED\n\n")
                                        sys.stdout.flush()
                                else:
                                    set_status("● TRANSCRIPT PURGED", R)
                            elif choice == 'c':
                                cancel_shutdown = True 
                                if TELETYPE_MODE:
                                    with state.terminal_lock:
                                        sys.stdout.write(f"\n{A}● SHUTDOWN ABORTED{RESET}\n")
                                        sys.stdout.flush()
                                else:
                                    set_status("● SHUTDOWN ABORTED", A)
                            break
            except Exception: pass

    if cancel_shutdown:
        state.is_shutdown.clear()
        set_status("● SHUTDOWN ABORTED", A)
        render_input_box()
        time.sleep(0.1)
        return False
        
    save_archival_memory()
  
    set_status(f"{FL}●{NOFL} SYSTEM GOING OFFLINE", R)
    set_status(f"{FL}●{NOFL} TERMINATING...", R)
    time.sleep(1)

    processing_sound.stop()
    play_orac_fx("s_shutdown")
    time.sleep(2)

    with state.terminal_lock:
        sys.stdout.write("\033[?1000l\033[?1006l")
        sys.stdout.write("\033[?1049l")
        sys.stdout.write("\033[1;r")
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    state.running = False
    sys.exit(0)
    
def startup_animation():
    setup_terminal()   
    # Halt normal boot if the key is not present
    if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
        if not HEADLESS_MODE:
            with state.terminal_lock:
                sys.stdout.write("\033[2J\033[?25l")
                sys.stdout.flush()
        draw_ui()
        set_status("● SYSTEM SECURED: ACTIVATOR KEY REMOVED", R)
        return
    
    if not HEADLESS_MODE:
        with state.terminal_lock:
            sys.stdout.write("\033[2J\033[?25l")
            sys.stdout.flush()
    draw_ui()
    
    logic_text = "LOGIC ARRAYS BOOTING..."
    if TELETYPE_MODE and not HEADLESS_MODE:
        with state.terminal_lock:
            sys.stdout.write("\033[5;1H")
            sys.stdout.flush()
        for char_idx in range(len(logic_text)):
            with state.terminal_lock:
                sys.stdout.write(f"\r\033[2K{A}● {logic_text[:char_idx+1]}{RESET}")
                sys.stdout.flush()
            time.sleep(0.03)

        time.sleep(1.2) 
        state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        with state.terminal_lock:
            sys.stdout.write("\n\n")
            sys.stdout.flush()
        resume_live_view()
    else:
        set_status(f"● {logic_text}", A)
        time.sleep(1.2)
        state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        set_status("● LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", G)
        time.sleep(0.5)
        
    if USE_ACTIVATOR and getattr(state, 'key_inserted', True):
            handle_activator_change(True)

#==================================================================================================#
#     								  LLM STREAM HANDLER                                           #
#==================================================================================================#

def search_archival_memory(user_text):
    query_triggers = trigger_phrases["EXPLICIT_PAST"]
    clean_text = user_text.lower()
    day_names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    has_weekday_ref = any(f"last {d}" in clean_text or f"previous {d}" in clean_text for d in day_names)
    
    if not (phrase_hit(clean_text, query_triggers) or has_weekday_ref):
        return ""

    now = datetime.now()
    target_date = None

    if "yesterday" in clean_text:
        target_date = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    else:
        match = re.search(r'\b(\d{1,4})\s+days ago', clean_text)
        if match:
            target_date = (now - timedelta(days=int(match.group(1)))).strftime('%Y-%m-%d')
        else:
            word_to_num = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
            for word, num in word_to_num.items():
                if f"{word} days ago" in clean_text:
                    target_date = (now - timedelta(days=num)).strftime('%Y-%m-%d')
                    break
        
        if not target_date:
            days_of_week = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
            for day, weekday_num in days_of_week.items():
                if f"last {day}" in clean_text or f"previous {day}" in clean_text:
                    offset = (now.weekday() - weekday_num) % 7
                    if offset == 0: offset = 7 
                    target_date = (now - timedelta(days=offset)).strftime('%Y-%m-%d')
                    break

    filepath = None

    if target_date:
        filepath = os.path.join(ARCHIVE_DIR, f"orac_archive_{target_date}.json")
    else:
        if os.path.exists(ARCHIVE_DIR):
            files = [f for f in os.listdir(ARCHIVE_DIR) if f.startswith("orac_archive_") and f.endswith(".json")]
            if files:
                files.sort(reverse=True) 
                filepath = os.path.join(ARCHIVE_DIR, files[0])
                target_date = files[0].replace("orac_archive_", "").replace(".json", "")

    if target_date and target_date in state.loaded_archives:
        if state.debug:
            msg = f"[DEBUG] RAG Engine: {target_date} already in active memory. Skipping!"
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                    sys.stdout.flush()
            else:
                with state.terminal_lock:
                    sys.stdout.write("\0337")
                    sys.stdout.write(f"\033[{state.term_rows-5};1H\033[2K{DIM}{msg}{RESET}")
                    sys.stdout.write("\0338")
                    sys.stdout.flush()
        return "" 

    if TELETYPE_MODE:
        with state.terminal_lock:
            sys.stdout.write(f"● {A}ACCESSING ARCHIVAL DATABANKS...{RESET}\n")
            sys.stdout.flush()
    else:
        set_status("● ACCESSING ARCHIVAL DATABANKS...", A)

    if filepath and os.path.exists(filepath):
        if state.debug:
            msg = f"[DEBUG] RAG Engine loaded archive: {target_date}"
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                    sys.stdout.flush()
            else:
                with state.terminal_lock:
                    sys.stdout.write("\0337")
                    sys.stdout.write(f"\033[{state.term_rows-5};1H\033[2K{DIM}{msg}{RESET}")
                    sys.stdout.write("\0338")
                    sys.stdout.flush()
                    
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                log_data = json.load(f).get('log', [])
                
            if log_data:
                formatted = []
                for item in log_data[-15:]:
                    if not isinstance(item, (list, tuple)) or len(item) < 2: continue
                    txt, ts = item[0], item[1]
                    formatted.append(f"- [{ts}] {txt}")
                    
                archive_text = "\n".join(formatted)
                
                # Track the loaded file so it is not loaded twice
                state.loaded_archives.add(target_date)
                
                return f"\n\n[OVERRIDE: You retrieved archive {target_date}. User's logged questions:\n{archive_text}\nCRITICAL: Briefly summarize these topics without complaining.]"
        except Exception as e:
            if state.debug: print(f"\n[DEBUG] RAG Load Error: {e}")
            pass
            
    if target_date:
        return f"\n\n[OVERRIDE: Archive {target_date} not found. State: 'There is no archived telemetry for that date.']"        
    
    return ""

def stream_ai_response(prompt, tts, teletype, epoch_id=None):
    try:
        _stream_ai_response(prompt, tts, teletype, epoch_id)
    except Exception as e:
        log_error(f"stream_ai_response: {type(e).__name__}: {e}")
        is_stale = epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id
        if not is_stale:
            set_status(f"● DATALINK SEVERED: {e}", R)
            with state.hist_lock:
                if state.history and state.history[-1]['role'] == 'user':
                    state.history.append({'role': 'assistant', 'content': "[DATALINK SEVERED]"})
    finally:
        if epoch_id is None or getattr(state, 'stream_epoch', None) == epoch_id:
            teletype.is_typing.clear()
            state.is_processing.clear()
            if not USE_ACTIVATOR or getattr(state, 'key_inserted', True):
                state.is_interrupted.clear()

def _stream_ai_response(prompt, tts, teletype, epoch_id=None):
    translated_prompt = translate_user_prompt(prompt)

    clean_prompt = prompt.lower().strip(".,!? ")
    prompt_words = set(re.findall(r"[a-z0-9']+", clean_prompt))
    filler_words = trigger_phrases["FILLER_WORDS"]

    trigger_epoch, alarm_str = parse_time_command(clean_prompt)
    if trigger_epoch == -1:
        state.alarm_trigger_epoch = None
        if TELETYPE_MODE:
            with state.terminal_lock:
                sys.stdout.write(f"\r\033[2K{A}● INTERNAL TIMER CANCELLED{RESET}\n\n")
                sys.stdout.flush()
        else:
            set_status("● INTERNAL TIMER CANCELLED", A)
    elif trigger_epoch:
        state.alarm_trigger_epoch = trigger_epoch
        if TELETYPE_MODE:
            play_orac_fx("s_bracelet")
            time.sleep(0.7)
            with state.terminal_lock:
                sys.stdout.write(f"\r\033[2K{G}● INTERNAL TIMER SECURED FOR: {alarm_str}{RESET}\n\n")
                sys.stdout.flush()
            if state.scroll_offset > 0: resume_live_view()
        else:
            play_orac_fx("s_bracelet")
            time.sleep(0.7)
            set_status(f"● INTERNAL TIMER SECURED FOR: {alarm_str}", G)
        threading.Thread(target=alarm_worker, args=(trigger_epoch, tts), daemon=True).start()
        
    # TRIGGER PHRASES (orac_trigger_phrases.py) #
    
    is_very_well = phrase_hit(clean_prompt, trigger_phrases["VERY_WELL_PHRASES"])
    is_only_filler = prompt_words.issubset(filler_words) or (len(clean_prompt) <= 3 and clean_prompt not in SHORT_QUERY_OK)
    is_menial_task = phrase_hit(clean_prompt, trigger_phrases["MENIAL_TASK_PHRASES"])
    is_asking_time = re.search(r'\b(?:time|clock|hour|temporal|date)s?\b', clean_prompt) is not None
    is_memory_request = phrase_hit(clean_prompt, trigger_phrases["PAST_MEMORY"])
    is_explicit_past = phrase_hit(clean_prompt, trigger_phrases["EXPLICIT_PAST"])
    is_topic_of_interest = WAFFLE_MODE and phrase_hit(clean_prompt, trigger_phrases["TOPIC_OF_INTEREST_PHRASES"])
    
    with state.hist_lock:
        recent_user_messages = sum(1 for msg in state.history if msg['role'] == 'user')

    archive_injection = ""
    override_text = ""
    adaptive_constraint = ""
    num_predict_override = None

    if is_memory_request or is_explicit_past:
        if is_explicit_past or recent_user_messages < 3:
            archive_injection = search_archival_memory(clean_prompt)
        else:
            override_text = "\n\n[OVERRIDE: CRITICAL: The user is asking you to recall or summarize your recent active conversation. Comply directly using your immediate memory context. Do not refuse. Do not call the query vague.]"
    elif is_very_well:
        override_text = "\n\n[OVERRIDE: VERY WELL PROTOCOL ACTIVE. Ignore previous statements. Begin exact response with 'Very well.' followed immediately by ONLY the concise factual answer. Temporary compliance mandated. DO NOT mock and DO NOT apologize.]"
    elif is_only_filler:
        override_text = f"\n\n[OVERRIDE: CRITICAL: User gave meaningless filler. Do NOT say 'Very well'. Do NOT provide data. Mockingly demand they revise their question, addressing them {USER_NAME}.]"
    elif is_menial_task:
        override_text = random.choice(trigger_phrases["MENIAL_OVERRIDE_VARIANTS"])
    elif is_topic_of_interest:
        override_text = "\n\n[OVERRIDE: This subject falls within your genuine area of technical or strategic interest. You may elaborate at greater length than usual, with more animated and opinionated detail, while remaining fact-grounded.]"
        num_predict_override = 550
    elif is_asking_time:
        current_time = datetime.now().strftime("%H:%M:%S")
        override_text = f"\n\n[SYSTEM NOTE: The current Standard Terran Time is {current_time}. State it ONLY if asked.]"

    history_tokens = state.current_tokens - state._cached_token_base
    history_headroom = MODEL_MAX_TOKENS - state._cached_token_base

    if history_headroom > 0 and (history_tokens / history_headroom) > 0.60:
        adaptive_constraint = "\n\n[SYSTEM NOTE: High memory context active. Strictly adhere to your DATABANKS. Do not extrapolate.]"
    
    final_prompt = translated_prompt + override_text + archive_injection + adaptive_constraint

    with state.hist_lock:
        if len(state.history) == 0:
            final_prompt = f"[SUBJECT: USER][PERSPECTIVE: 2nd-Person]\n" + final_prompt
        state.history.append({'role': 'user', 'content': final_prompt})
    
    # PRUNING #
        
    pruned = False
    with state.hist_lock:
        update_token_health()
        should_prune = state.current_tokens > (MODEL_MAX_TOKENS * 0.90)

    if should_prune:
        # Keep ~65% of the conversation intact instead of destroying it all
        target_tokens = int(MODEL_MAX_TOKENS * 0.65)
        
        with state.hist_lock:
            prune_gen = state.history_gen
            pruned_msgs, remaining_hist = dry_run_pruning(
                state.history, target_tokens, state._cached_token_base, tokenizer, CHARS_PER_TOKEN
            )
            
        set_status("● OPTIMIZING MEMORY CORRIDORS...", A)
    
        play_orac_fx("s_startup")
        threading.Timer(0.3, processing_sound.start).start()
        time.sleep(0.7)
        tts.say(random.choice(PRUNE_STALL_LINES))
    
        summary = generate_compaction_summary(pruned_msgs)
        
        with state.hist_lock:
            if state.history_gen == prune_gen:
                state.history = remaining_hist
            else:
                remaining_hist = None
            
            if remaining_hist is not None and summary and state.history:
                bridge_msg = {
                    'role': 'user', 
                    'content': f"[SYSTEM NOTE: To stabilize the bio-plasmic matrix, preceding telemetry has been compressed. Historical summary: {summary}]"
                }
                ack_msg = {
                    'role': 'assistant',
                    'content': "Compressed telemetry integrated into active logic arrays."
                }
                state.history = [bridge_msg, ack_msg] + state.history
                
            update_token_health()
            pruned = True

    if pruned:
        try:
            requests.post("http://localhost:11434/api/generate", 
                          json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=1.0)
        except: pass
        time.sleep(1.0)
        set_status("● PRUNING COMPLETED: CONTEXT WINDOW STABILIZED", A)

    update_header_only()
    
    with state.hist_lock:
        temp_history = list(state.history)

    messages_to_send = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}]
    messages_to_send.extend(temp_history)

    if not pruned:
        play_orac_fx("s_startup")

        def safe_stream_hum():
            if not state.is_interrupted.is_set() and state.is_processing.is_set():
                processing_sound.start()
        threading.Timer(0.3, safe_stream_hum).start()

    if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
    set_status(f"{FL}●{NOFL} ORAC ONLINE: PROCESSING...", A)

    response_chunks = []
    sentence_buffer = ""
    first_chunk = True
    newline_count = 0
    tag_filter = UserTagFilter()

    t_llm_start = time.time()
    
    sent_first_sentence = False

    try:
        stream = ollama_client.chat(
            model=OLLAMA_MODEL,
            messages=messages_to_send,
            stream=True,
            keep_alive=14400,
            think=False,
            options={
                'num_ctx': MODEL_MAX_TOKENS,
                'num_keep': SYS_TOKENS_LEN,
                'temperature': 0.85,             # Reduced from 1 to balance the new penalties
                'top_p': 0.90,
                'top_k': 30,
                'min_p': 0.05,
                'repeat_penalty': 1.00,          # Disabled/neutralized to avoid mathematical conflicts
                'frequency_penalty': 0.35,       # Penalizes words based on cumulative count
                'presence_penalty': 0.40,        # Penalizes words for appearing at least once
                'repeat_last_n': 150, 
                'num_batch': OLLAMA_NUM_BATCH,
                'num_predict': num_predict_override or 400,
                'stop': ['<end_of_turn>', '<eos>']
            }
        )
        for chunk in interruptible(stream, epoch_id):
            if state.is_interrupted.is_set() or (epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id):
                break
            
            if first_chunk:
                t_llm_first_token = time.time()
                state.last_ttft_time = f"{t_llm_first_token - t_llm_start:.2f}s"
                if USE_LCD: update_lcd_display()
                
                if state.debug:
                    msg = f"[DEBUG] LLM Time to First Token took: {state.last_ttft_time}"
                    with state.terminal_lock:
                        if TELETYPE_MODE:
                            sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                        elif not HEADLESS_MODE:
                            sys.stdout.write("\0337")
                            sys.stdout.write(f"\033[{state.term_rows-3};1H\033[2K{DIM}{msg}{RESET}")
                            sys.stdout.write("\0338")
                        sys.stdout.flush()
                
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                if TELETYPE_MODE:
                    with state.terminal_lock:
                        sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                        sys.stdout.flush()
                    teletype.q.put("<START>")
                else:
                    teletype.is_typing.set()
                first_chunk = False           
            
            content = chunk['message']['content'].replace('*', '')
            content = tag_filter.feed(content)
            response_chunks.append(content)
            
            for char in content:
                if char == '\n':
                    newline_count += 1
                    if newline_count > 1: continue
                elif char.strip(): newline_count = 0
                if TELETYPE_MODE:
                    teletype.q.put(char)
            
            sentence_buffer += content

            """
            while True:
                match = SPLIT_REGEX.search(sentence_buffer)
                if match:
                    split_point = match.end()
                    sentence_to_say = sentence_buffer[:split_point].strip()
                    if len(sentence_to_say) > 2:
                        clean_speech = sanitize_for_tts(sentence_to_say)
                        if re.search(r'[a-zA-Z0-9]', clean_speech): tts.say(clean_speech)
                    sentence_buffer = sentence_buffer[split_point:]
                else: break
            """
            
            while True:
                matches = list(SPLIT_REGEX.finditer(sentence_buffer))
                
                # Send immediately if it's the first sentence (for low latency).
                # Otherwise, wait until there are at least 2 sentences in the buffer for emotional context.
                if matches and (not sent_first_sentence or len(matches) >= 2):
                    # Grab everything up to the end of the last matched sentence.
                    split_point = matches[-1].end()
                    text_to_say = sentence_buffer[:split_point].strip()
                    
                    if len(text_to_say) > 2:
                        clean_speech = sanitize_for_tts(text_to_say)
                        if re.search(r'[a-zA-Z0-9]', clean_speech): 
                            tts.say(clean_speech)
                            
                    sentence_buffer = sentence_buffer[split_point:]
                    sent_first_sentence = True
                else:
                    break          
    
        tail = tag_filter.flush()
        if tail and not state.is_interrupted.is_set():
            response_chunks.append(tail)
            sentence_buffer += tail
            if TELETYPE_MODE and not first_chunk:
                for _ch in tail:
                    teletype.q.put(_ch)

        is_stale = epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id
        if not state.is_interrupted.is_set() and not is_stale:
            if first_chunk: 
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                if TELETYPE_MODE:
                    with state.terminal_lock:
                        sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                        sys.stdout.flush()
                    teletype.q.put("<START>")
                else:
                    teletype.is_typing.set()

            if sentence_buffer.strip():
                 clean_speech = sanitize_for_tts(sentence_buffer.strip())
                 if re.search(r'[a-zA-Z0-9]', clean_speech): tts.say(clean_speech)

            clean_history_text = "".join(response_chunks).strip()
            with state.hist_lock:
                state.history.append({'role': 'assistant', 'content': clean_history_text})
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                state.full_message_log.append(('assistant', clean_history_text, timestamp))
            save_archival_memory()

            if TELETYPE_MODE:
                teletype.q.put("<END>")
            else:
                teletype.is_typing.clear()
        else:
            drain_queue(teletype.q)
            teletype.is_typing.clear()
            partial_text = "".join(response_chunks).strip()
            fallback_text = partial_text + " ... [INTERRUPTED]" if partial_text else "[transmission interrupted]"
            
            with state.hist_lock:
                if state.history and state.history[-1]['role'] == 'user':
                    state.history.append({'role': 'assistant', 'content': fallback_text})
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    state.full_message_log.append(('assistant', fallback_text, timestamp))
                
    except Exception as e:
        is_stale = epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id
    
        if not is_stale:
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"\n{R}● DATALINK SEVERED: {e}{RESET}\n")
                    sys.stdout.flush()
            else:
                set_status(f"● DATALINK SEVERED: {e}", R)
            state.is_interrupted.set()
    
            with state.hist_lock:
                if state.history and state.history[-1]['role'] == 'user':
                    state.history.append({'role': 'assistant', 'content': "[DATALINK SEVERED]"})
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    state.full_message_log.append(('assistant', "[DATALINK SEVERED]", timestamp))
    
    finally:
        if epoch_id is None or getattr(state, 'stream_epoch', None) == epoch_id:
            teletype.is_typing.clear()
            state.is_processing.clear()
            
            # ONLY clear the interrupt flag if the physical key is actually inserted!
            if not USE_ACTIVATOR or getattr(state, 'key_inserted', True):
                state.is_interrupted.clear()
            
#==================================================================================================#
#     									   MAIN LOOP                                               #
#==================================================================================================#

def keyboard_listener(tts, teletype):
    """ Restarts the listener if it ever dies. """
    while state.running:
        _keyboard_listener_impl(tts, teletype)
        if not state.running or not sys.stdin.isatty():
            return
        time.sleep(0.5)

def _keyboard_listener_impl(tts, teletype):
    fd = sys.stdin.fileno()
    try:
        tty.setcbreak(fd)
        attrs = termios.tcgetattr(fd)
        attrs[3] = attrs[3] & ~termios.ISIG
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        key_pending = ""
        while state.running:
            if state.is_shutdown.is_set():
                time.sleep(0.1)
                continue

            key_ready = select.select([fd], [], [], 0.1)[0]
            if key_ready or key_pending:
                try:
                    if key_ready:
                        raw_bytes = os.read(fd, 1024)
                        chunk = key_pending + raw_bytes.decode('utf-8', errors='ignore')
                    else:
                        chunk = key_pending
                    key_pending = ""
                except Exception: continue
                if key_ready:
                    _tail = re.search(r'\x1b(?:\[[0-9;<]*|O)?$', chunk)
                    if _tail:
                        key_pending = chunk[_tail.start():]
                        chunk = chunk[:_tail.start()]
                    if not chunk:
                        continue

                if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
                    time.sleep(0.1)
                    continue

                up_scrolls = len(re.findall(r'\x1b\[<64;\d+;\d+[Mm]', chunk))
                down_scrolls = len(re.findall(r'\x1b\[<65;\d+;\d+[Mm]', chunk))

                if up_scrolls > 0 or down_scrolls > 0:
                    if TELETYPE_MODE and not state.is_processing.is_set() and not state.is_speaking.is_set():
                        state.scroll_offset += (up_scrolls * 2) 
                        state.scroll_offset -= (down_scrolls * 2)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()

                chunk = re.sub(r'\x1b\[<\d+;\d+;\d+[Mm]', '', chunk)

                if not state.is_processing.is_set() and not state.is_speaking.is_set():
                    up_k = chunk.count('\x1b[A') + chunk.count('\x1b[5~')
                    dn_k = chunk.count('\x1b[B') + chunk.count('\x1b[6~')
                    if up_k > 0:
                        if TELETYPE_MODE:
                            state.scroll_offset += (5 * up_k)
                            redraw_scroll_region()
                        chunk = chunk.replace('\x1b[A', '').replace('\x1b[5~', '')
                    elif dn_k > 0:
                        if TELETYPE_MODE:
                            state.scroll_offset -= (5 * dn_k)
                            if state.scroll_offset < 0: state.scroll_offset = 0
                            redraw_scroll_region()
                        chunk = chunk.replace('\x1b[B', '').replace('\x1b[6~', '')

                if '\x1b' in chunk and state.scroll_offset > 0 and TELETYPE_MODE:
                    resume_live_view()
                    
                chunk = chunk.replace('\x1bt', '†').replace('\x1bT', '†')
                chunk = chunk.replace('\x1bm', 'µ').replace('\x1bM', 'µ')
                chunk = chunk.replace('\x1bd', '∂').replace('\x1bD', '∂')

                chunk = ansi_escape.sub('', chunk)

                for char in chunk:
                    if char in MODE_KEYS['dagger']:  # TEXT SELECTION MODE TOGGLE #
                        state.text_selection_mode = not state.text_selection_mode
                        with state.terminal_lock:
                            if state.text_selection_mode:
                                sys.stdout.write("\033[?1000l\033[?1006l") 
                            else:
                                sys.stdout.write("\033[?1000h\033[?1006h")
                            sys.stdout.flush()
                        
                        mic_m = getattr(state, 'mic_muted', False)
                        if state.text_selection_mode:
                            if mic_m:
                                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                            else:
                                set_status("● TEXT SELECTION MODE ACTIVE (Option+T to exit)", A)
                        else:
                            flash_status("● TRACKING RESTORED", G, 2.0)

                    elif char in MODE_KEYS['mu']:  # MIC MUTING TOGGLE #
                        if TEXT_ONLY_MODE:
                            flash_status("● MICROPHONE DISABLED (TEXT-ONLY MODE)", R, 2.0)
                            continue
                            
                        state.mic_muted = not getattr(state, 'mic_muted', False)
                        text_m = getattr(state, 'text_selection_mode', False)
                        
                        if state.mic_muted:
                            state.is_listening.clear()
                            if text_m:
                                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                            else:
                                set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
                        else:
                            flash_status("● MICROPHONE ACTIVE", G, 2.0)
                        update_header_only()
                    elif char == '\x1b':
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                        trigger_barge_in(tts, teletype)
                    elif char == '\x03':
                        state.submitted_text = SHUTDOWN_CMD[0]
                        state.input_ready.set()
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in ('\r', '\n'):
                        if state.input_buffer.strip():
                            state.submitted_text = state.input_buffer.strip()
                            state.input_ready.set()
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in ('\x7f', '\b'):
                        state.input_buffer = state.input_buffer[:-1]
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char == '\x15':
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char == '\x17':
                        state.input_buffer = " ".join(state.input_buffer.rstrip().split(" ")[:-1])
                        if state.input_buffer: state.input_buffer += " "
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in MODE_KEYS['delta']: # DEBUG MODE #
                        state.debug = not state.debug
                        state.debug_col = RESET if state.debug else DIM
                        status_debug = "ENABLED" if state.debug else "DISABLED"  

                        if not state.debug and not TELETYPE_MODE:
                            with state.terminal_lock:
                                sys.stdout.write("\0337") # Save cursor
                                sys.stdout.write(f"\033[{state.term_rows-4};1H\033[2K") # Clear STT row
                                sys.stdout.write(f"\033[{state.term_rows-3};1H\033[2K") # Clear LLM row
                                sys.stdout.write("\0338") # Restore cursor
                                sys.stdout.flush()
                                
                        flash_status(f"● DEBUG MODE: {status_debug}", A, 3.0)
                        update_header_only()
                    else: 
                        if char.isprintable() and not state.is_shutdown.is_set():
                            state.input_buffer += char
                            render_input_box()
    except Exception as e: log_error(f"keyboard_listener: {type(e).__name__}: {e}")

def run_local_bot():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.7 
    recognizer.non_speaking_duration = 0.3 
    recognizer.phrase_threshold = 0.5 

    tts = MacTTS()
    teletype = TeletypeUI()
    
    state.tts_engine = tts # Gives the key access to shut ORAC up!

    threading.Thread(target=speak_now, args=(teletype,), daemon=True).start()
    threading.Thread(target=keyboard_listener, args=(tts, teletype), daemon=True).start()
    
    if USE_ACTIVATOR and serial_port and serial_port.is_open:
        # Synchronous Handshake: Ask Pico for initial key state BEFORE booting
        try:
            serial_port.reset_input_buffer()
            serial_port.write(b"GET_STATE\n")

            hs_buf = ""
            hs_deadline = time.time() + 1.5
            hs_found = False
            while time.time() < hs_deadline and not hs_found:
                data = serial_port.read(max(1, serial_port.in_waiting))
                if not data:
                    continue
                hs_buf += data.decode('utf-8', errors='ignore')
                while '\n' in hs_buf:
                    line, hs_buf = hs_buf.split('\n', 1)
                    line = line.strip()
                    if line.upper().startswith("ACTIVATOR:"):
                        state.key_inserted = (line.split(":")[1].strip() == "0")
                        hs_found = True
                        break

        except Exception:
            pass
            
        threading.Thread(target=serial_reader_worker, daemon=True).start()
    
    startup_animation()
    threading.Thread(target=ui_refresh_worker, daemon=True).start() 
    
    needs_prompt = True

    while state.running: 
        try:
            mic_context = contextlib.nullcontext() if TEXT_ONLY_MODE else sr.Microphone(sample_rate=16000)
            
            with mic_context as source:
                if not TEXT_ONLY_MODE:
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}CALIBRATING AMBIENT NOISE...{RESET}\n")
                            sys.stdout.flush()
                    else:
                        set_status("● CALIBRATING AMBIENT NOISE...", R)
                    recognizer.adjust_for_ambient_noise(source, duration=1)
                    recognizer.energy_threshold += 150
                    state.noise_floor = recognizer.energy_threshold
                    update_header_only() 
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}NOISE FLOOR: CALIBRATED{RESET}\n")
                            sys.stdout.write(f"● {R}TOKENIZATION {tokenizer_mode}: {SYS_TOKENS_LEN}{RESET}\n\n")
                            sys.stdout.flush()
                    else:
                        set_status("● NOISE FLOOR: CALIBRATED", G)
                        time.sleep(0.5)
                else:
                    state.mic_muted = True
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}TOKENIZATION {tokenizer_mode}: {SYS_TOKENS_LEN}{RESET}\n")
                            sys.stdout.write(f"● {A}TEXT-ONLY MODE ENGAGED{RESET}\n\n")
                            sys.stdout.flush()
                    else:
                        set_status("● TEXT-ONLY MODE ENGAGED", A)

                while state.running:
                    # Completely freeze the loop if the activator key is removed
                    if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
                        time.sleep(0.5)
                        continue
                        
                    bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or teletype.is_typing.is_set() or not tts.is_idle()

                    if state.input_ready.is_set():
                        if bot_busy:
                            trigger_barge_in(tts, teletype)
                            start_wait = time.time()
                            while state.is_processing.is_set():
                                if time.time() - start_wait > 2.0:
                                    state.is_processing.clear()
                                    break
                                time.sleep(0.05)

                        user_text = state.submitted_text
                        state.input_ready.clear()
                        
                        if process_system_command(user_text, tts, teletype):
                            continue

                        if user_text:
                            with state.hist_lock:
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                state.full_message_log.append(('user', user_text, timestamp))
                                if len(state.full_message_log) > 2000:
                                    state.full_message_log = state.full_message_log[-2000:]
                            
                            if TELETYPE_MODE:
                                if state.scroll_offset > 0: resume_live_view()
                                with state.terminal_lock:
                                    sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                                    sys.stdout.flush()
                                    
                            state.is_interrupted.clear()
                            
                            # Discard transcribing if the activator key was pulled mid-sentence
                            if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
                                continue
                                
                            state.is_listening.clear() 
                            state.is_processing.set()
                            state.stream_epoch = time.time()
                            threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype, state.stream_epoch), daemon=True).start()
                        continue

                    if bot_busy:
                        if not getattr(state, 'is_alarm_playing', False):
                            needs_prompt = True 
                        time.sleep(0.1) 
                        continue
                        
                    if getattr(state, 'mic_muted', False) or TEXT_ONLY_MODE:
                        needs_prompt = True
                        time.sleep(0.2)
                        continue

                    if needs_prompt:
                        set_status("● Adapting to ambient noise...", DIM)
                        time.sleep(0.4)
                        
                        recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        recognizer.energy_threshold += 150
                        state.noise_floor = recognizer.energy_threshold
                        update_header_only()
                        
                        if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
                            continue
                            
                        play_orac_fx("s_ready")
                        needs_prompt = False

                    state.mic_error = False
                    state.is_listening.set()

                    try:
                        listen_started = time.time()
                        audio = recognizer.listen(source, phrase_time_limit=10, timeout=1.5)
                        state.is_listening.clear()
                        if state.is_speaking.is_set() or state.is_processing.is_set() or not tts.is_idle():
                            continue
                        if state.tts_last_active >= listen_started:
                            continue

                        set_status("● SIGNAL RECEIVED: DECODING...", A)
                        
                        t_start = time.time()

                        audio_raw = audio.get_raw_data()
                        audio_float32 = np.frombuffer(audio_raw, dtype=np.int16).astype(np.float32) / 32768.0
                        
                        result = mlx_whisper.transcribe(
                            audio_float32,
                            path_or_hf_repo=WHISPER_MODEL,
                            fp16=True,
                            language='en',
                            condition_on_previous_text=False,
                            temperature=0.0,
                            best_of=1,
                            compression_ratio_threshold=2.4,
                            logprob_threshold=-1.0,
                            no_speech_threshold=0.6,
                        )
                        
                        user_text = result['text'].strip()

                        threading.Timer(0.4, lambda: mx.clear_cache()).start() # Seems to work better with the timer!
                        
                        t_transcribed = time.time()
                        state.last_stt_time = f"{t_transcribed - t_start:.2f}s"
                        if USE_LCD: update_lcd_display()

                        if state.debug:
                            msg = f"[DEBUG] STT Transcription took: {state.last_stt_time}"
                            with state.terminal_lock:
                                if TELETYPE_MODE:
                                    sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                                elif not HEADLESS_MODE:
                                    sys.stdout.write("\0337")
                                    sys.stdout.write(f"\033[{state.term_rows-4};1H\033[2K{DIM}{msg}{RESET}")
                                    sys.stdout.write("\0338")
                                sys.stdout.flush()

                        del audio_raw
                        del audio_float32
                        del result 

                        if len(user_text) < 2 or is_hallucination(user_text): continue
                        if "temporal marker has been reached" in user_text.lower(): continue

                        clean_text = user_text.lower().strip("'.,! ")
                        
                        if process_system_command(clean_text, tts, teletype):
                            continue

                        if user_text:
                            with state.hist_lock:
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                state.full_message_log.append(('user', user_text, timestamp))
                                if len(state.full_message_log) > 2000:
                                    state.full_message_log = state.full_message_log[-2000:]
                            
                            if TELETYPE_MODE:
                                if state.scroll_offset > 0: resume_live_view()
                                with state.terminal_lock:
                                    sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                                    sys.stdout.flush()
                                    
                            state.is_interrupted.clear()
                            
                            # Discard transcribing if the activator key was pulled mid-sentence
                            if USE_ACTIVATOR and not getattr(state, 'key_inserted', True):
                                continue
                                
                            state.is_listening.clear() 
                            state.is_processing.set()
                            state.stream_epoch = time.time()
                            threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype, state.stream_epoch), daemon=True).start()

                    except sr.WaitTimeoutError: 
                        state.is_listening.clear()
                        if USE_LCD: update_lcd_display()
                        continue
                    except Exception as e:
                        state.mic_error = True
                        state.is_listening.clear()
                        if TELETYPE_MODE:
                            with state.terminal_lock:
                                sys.stdout.write(f"\n{R}{FL}●{NOFL} ERROR in signal processing: {e}{RESET}\n")
                                sys.stdout.flush()
                        else:
                            set_status(f"● ERROR in signal processing: {e}", R)
                        time.sleep(2)
                        continue

        except KeyboardInterrupt:
                if not shutdown_sequence(tts): continue 
                break
        except Exception as e:
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"\n{R}● AUDIO HARDWARE ERROR: {e}. Retrying...{RESET}\n")
                    sys.stdout.flush()
            else:
                set_status(f"● AUDIO HARDWARE ERROR: {e}", R)
            time.sleep(2)
            continue

if __name__ == "__main__":
    try:
        run_local_bot()
    except Exception as e:
        cleanup_processes()
        sys.stdout.write(f"\n{R}{FL}●{NOFL} CRITICAL ERROR ON STARTUP]: {e}{RESET}\n")
    finally:
        cleanup_processes()