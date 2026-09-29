import sys
import time
import _thread
import random
import uselect
from machine import I2C, Pin, Timer
from I2C_LCD import I2CLcd

# Optional: stops a stray Ctrl-C byte (0x03) on the USB serial line from killing this program.
# Leave it commented while you develop in Thonny: it also disables Thonny's Stop button.
# import micropython; micropython.kbd_intr(-1)

BOOT_HOLD_MS = 500      # How long to wait before reading the key and serving the Mac. (Was 2000: the Mac only waits 1.5s for the
                        # GET_STATE reply, so a slow boot could miss the handshake. Raise it if you like the "BOOTING" text visible longer.)

# Initialize LCD
time.sleep(1)
i2c = I2C(0, sda=Pin(0), scl=Pin(1))
lcd = I2CLcd(i2c, 0x27, 2, 16)
lcd.clear()
lcd.putstr("ORAC: BOOTING...")

# Define LED GPIO pins
led_pins = [4, 5, 6, 7, 8, 9, 16, 17, 18, 19, 20, 21]
leds = [Pin(p, Pin.OUT) for p in led_pins]

uv_leds = [Pin(10, Pin.OUT), Pin(11, Pin.OUT)]

activator_pin = Pin(15, Pin.IN, Pin.PULL_UP)
onboard_led = Pin(25, Pin.OUT) # PICO LED

for led in leds: led.value(0)
for uv in uv_leds: uv.value(0)
onboard_led.value(0)

current_state = "IDLE"
uv_warning_active = False

time.sleep_ms(BOOT_HOLD_MS)

initial_val = activator_pin.value()
stable_activator_val = initial_val
onboard_led.value(0 if initial_val == 1 else 1)     # FIX: the on-board LED only followed CHANGES, so a key already inserted at boot left it off
# Kept on purpose: this line is how the Mac learns that the Pico has just (re)booted, and the key state after a reset.
print(f"ACTIVATOR:{initial_val}")

uv_pulse_pattern = [1, 0, 1, 0, 0, 0, 0, 0, 0]
uv_pulse_step = 0

def uv_pulse_tick(timer):
    global uv_pulse_step
    if current_state == "OFF":
        uv_leds[1].value(0)
        return
    if not uv_warning_active:
        uv_leds[1].value(1)
        return
    uv_leds[1].value(uv_pulse_pattern[uv_pulse_step])
    uv_pulse_step = (uv_pulse_step + 1) % len(uv_pulse_pattern)
    
uv_timer = Timer()
uv_timer.init(period=100, mode=Timer.PERIODIC, callback=uv_pulse_tick)


# ========================================== #
#      CORE 1: LED ANIMATION THREAD          #
# ========================================== #

def hold(st, ms):
    """Sleep for up to `ms`, but return within ~20ms as soon as the state changes.
    (Was time.sleep: leaving MUT could take up to 1.9s to show, because the whole off-phase was one blocking sleep.)"""
    end = time.ticks_add(time.ticks_ms(), ms)
    while current_state == st and time.ticks_diff(end, time.ticks_ms()) > 0:
        time.sleep_ms(20)

def led_animation_loop():
    global current_state

    while True:
        try:
            state = current_state

            uv_leds[0].value(0 if state == "OFF" else 1)

            if state == "OFF":
                for led in leds: led.value(0)
                hold("OFF", 100)

            elif state == "IDLE":
                for i in range(12):
                    if current_state != "IDLE": break
                    for led in leds: led.value(0)
                    leds[i].value(1)
                    hold("IDLE", 150)

            elif state == "PROC":
                for i in range(12):
                    if current_state != "PROC": break
                    for led in leds: led.value(0)
                    leds[i].value(1)
                    leds[(i + 6) % 12].value(1)
                    hold("PROC", 40)

            elif state == "SPK":
                # One random number for all 12 LEDs. (Was random.choice([0, 1]) x12 per frame: a new list each time, which
                # fills the heap and triggers garbage collection pauses on BOTH cores.)
                bits = random.getrandbits(12)
                for i in range(12):
                    leds[i].value((bits >> i) & 1)
                hold("SPK", 50 + random.getrandbits(6))       # 50..113 ms (was uniform 50..120)

            elif state == "ALERT":
                for led in leds: led.value(1)
                hold("ALERT", 100)
                for led in leds: led.value(0)
                hold("ALERT", 100)

            elif state == "MUT":
                for led in leds: led.value(1)
                hold("MUT", 100)
                for led in leds: led.value(0)
                hold("MUT", 1900)

            else:
                time.sleep_ms(100)
        except Exception:
            time.sleep_ms(100) # Prevents thread crash if the state gets corrupted

_thread.start_new_thread(led_animation_loop, ())


# ========================================== #
#      CORE 0: SERIAL & ACTIVATOR CHECK      #
# ========================================== #

poll_obj = uselect.poll()
poll_obj.register(sys.stdin, uselect.POLLIN)

# Start these matching the actual boot value to avoid phantom debounces
last_activator_val = initial_val  
debounce_time = time.ticks_ms()

while True:
    # Hardware Debounce Logic
    current_val = activator_pin.value()
    
    if current_val != last_activator_val:
        last_activator_val = current_val
        debounce_time = time.ticks_ms()
        
    if time.ticks_diff(time.ticks_ms(), debounce_time) > 100:
        if current_val != stable_activator_val:
            stable_activator_val = current_val
            
            # Turn on PICO's built-in LED when activator key is presented
            onboard_led.value(0 if stable_activator_val == 1 else 1)
            
            print(f"ACTIVATOR:{stable_activator_val}")

    # Non-Blocking Serial Reader
    if poll_obj.poll(20):
        try:
            text_data = sys.stdin.readline().strip()
            if text_data:
                if text_data == "GET_STATE":
                    print(f"ACTIVATOR:{stable_activator_val}")
                elif text_data == "backlight_on":
                    lcd.backlight_on()
                elif text_data == "backlight_off":
                    lcd.backlight_off()
                elif text_data.lower() == "clear":          # not sent by orac_chat.py; handy for manual tests from a terminal
                    lcd.clear()
                elif text_data.startswith("S:"):
                    current_state = text_data[2:]
                elif text_data.startswith("U:"):
                    uv_warning_active = (text_data[2:] == "1")          
                elif len(text_data) >= 2 and text_data[1] == ':':
                    try:
                        row = int(text_data[0])
                        msg = text_data[2:]
                        padded_msg = msg + " " * (16 - len(msg))
                        lcd.move_to(0, row)
                        lcd.putstr(padded_msg[:16])
                    except ValueError:
                        pass
        except Exception:
            # Silently catch serial frame errors or bad bytes so the hardware doesn't lock up
            pass
