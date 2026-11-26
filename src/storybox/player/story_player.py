#!/usr/bin/env python3
import json, os, re, socket, subprocess, sys, time
from pathlib import Path
from threading import Event, Thread

BASE = Path("/home/admin")
CATALOG = BASE / "story-library.json"
STORIES_DIR = BASE / "stories"
PROMPTS_DIR = BASE / "story-prompts"
WELCOME_PROMPT = PROMPTS_DIR / "welcome.wav"
MPV_SOCKET = "/tmp/lunii-player.sock"
DEBOUNCE_SECONDS = 0.50

# GPIO lines used by physical buttons. GPIO 9 is reserved for the potentiometer.
BUTTONS = {6:"play_pause",1:"next",0:"previous",3:"ok",8:"home"}
ENCODER_CLK = 2   # Orange Pi physical pin 22 (PA2)
ENCODER_DT = 21   # Orange Pi physical pin 26 (PA21)
ENCODER_LINES = (ENCODER_CLK, ENCODER_DT)
POT_GPIO = 9      # Orange Pi physical pin 33
POT_SAMPLES = 15
POT_MIN_MS = 0.20
POT_MAX_MS = 1.05
POT_TIMEOUT_MS = 20
POT_FILTER_ALPHA = 0.50
POT_VOLUME_DEADBAND = 4
POT_CONFIRM_BATCHES = 2

last_press = {line:0.0 for line in BUTTONS}
QUADRATURE = {
    (0b00, 0b01): 1, (0b01, 0b11): 1,
    (0b11, 0b10): 1, (0b10, 0b00): 1,
    (0b01, 0b00): -1, (0b11, 0b01): -1,
    (0b10, 0b11): -1, (0b00, 0b10): -1,
}
selected_story, mode = 0, "menu"

def stories():
    try:
        result = json.loads(CATALOG.read_text())
        return [x for x in result if (STORIES_DIR / x["filename"]).is_file()]
    except Exception:
        return []

def start_mpv():
    try: os.unlink(MPV_SOCKET)
    except FileNotFoundError: pass
    return subprocess.Popen(["mpv","--idle=yes","--really-quiet","--no-video","--no-audio-display",
        "--ao=alsa","--audio-device=alsa/plughw:0,0","--input-ipc-server="+MPV_SOCKET,
        "--volume=70","--keep-open=yes","--force-window=no"])

def send(command):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(2); client.connect(MPV_SOCKET)
        client.sendall((json.dumps({"command":command})+"\n").encode())
        while not client.recv(4096).endswith(b"\n"): pass

def play(path):
    send(["loadfile",str(path),"replace"]); send(["set_property","pause",False])

def announce(items):
    play(PROMPTS_DIR / items[selected_story]["prompt"])

def start_selected(items):
    global mode
    mode="playing"; play(STORIES_DIR / items[selected_story]["filename"])

def handle(action):
    global selected_story, mode
    items=stories()
    if not items: return
    selected_story=min(selected_story,len(items)-1)
    print(f"Button: {action}",flush=True)
    if action=="next":
        selected_story=(selected_story+1)%len(items)
        start_selected(items) if mode=="playing" else announce(items)
    elif action=="previous":
        selected_story=(selected_story-1)%len(items)
        start_selected(items) if mode=="playing" else announce(items)
    elif action=="ok" and mode=="menu": start_selected(items)
    elif action=="play_pause":
        start_selected(items) if mode=="menu" else send(["cycle","pause"])
    elif action=="home":
        mode="menu"; play(WELCOME_PROMPT)

def potentiometer_volume_loop(stop_event):
    """Read the RC charge time on GPIO 9 and map it to MPV volume."""
    chip = None
    request = None
    try:
        import gpiod
        from datetime import timedelta
        from gpiod import LineSettings
        from gpiod.line import Direction, Value, Edge

        chip = gpiod.Chip("/dev/gpiochip0")
        request = chip.request_lines(
            consumer="storybox-pot-volume",
            config={
                POT_GPIO: LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE
                )
            }
        )
        print("Potentiometer volume control active on GPIO line 9.", flush=True)

        filtered_ms = None
        last_volume = None
        pending_direction = 0
        pending_batches = 0
        pot_batch_count = 0

        while not stop_event.is_set():
            readings = []

            for _ in range(POT_SAMPLES):
                if stop_event.is_set():
                    break

                # Discharge the capacitor before measuring its next charge.
                request.reconfigure_lines({
                    POT_GPIO: LineSettings(
                        direction=Direction.OUTPUT,
                        output_value=Value.INACTIVE
                    )
                })
                time.sleep(0.01)

                request.reconfigure_lines({
                    POT_GPIO: LineSettings(
                        direction=Direction.INPUT,
                        edge_detection=Edge.RISING
                    )
                })
                # Start timing only after the GPIO is configured as input.
                # This excludes variable reconfiguration overhead from the RC measurement.
                start_ns = time.monotonic_ns()

                if request.wait_edge_events(
                    timeout=timedelta(milliseconds=POT_TIMEOUT_MS)
                ):
                    event = request.read_edge_events()[0]
                    elapsed_ms = (event.timestamp_ns - start_ns) / 1_000_000
                    if 0.01 <= elapsed_ms <= 5.0:
                        readings.append(elapsed_ms)

            # Require most of the batch to be valid; ignore incomplete batches.
            if len(readings) >= 8:
                pot_batch_count += 1
                median_ms = sorted(readings)[len(readings) // 2]
                # Temporary diagnostic: show raw timing samples about once per second.
                if pot_batch_count % 10 == 0:
                    raw_text = ", ".join(f"{value:.3f}" for value in readings)
                    print(
                        f"Pot raw diagnostic: [{raw_text}] ms; median {median_ms:.3f} ms",
                        flush=True
                    )
                if filtered_ms is None:
                    filtered_ms = median_ms
                else:
                    filtered_ms = (
                        POT_FILTER_ALPHA * median_ms
                        + (1.0 - POT_FILTER_ALPHA) * filtered_ms
                    )

                # More resistance means a longer charge time and lower volume.
                # Clockwise produces shorter times, therefore louder volume.
                position = (POT_MAX_MS - filtered_ms) / (POT_MAX_MS - POT_MIN_MS)
                volume = max(0, min(100, round(position * 100)))

                if last_volume is None:
                    try:
                        send(["set_property", "volume", volume])
                        last_volume = volume
                        print(
                            f"Pot volume: {volume}% "
                            f"(charge {filtered_ms:.3f} ms, "
                            f"{len(readings)}/{POT_SAMPLES} samples)",
                            flush=True
                        )
                    except Exception as exc:
                        print(f"Potentiometer volume update failed: {exc}", flush=True)
                else:
                    difference = volume - last_volume
                    direction = 1 if difference > 0 else -1 if difference < 0 else 0

                    # Ignore small changes. Require movement in the same
                    # direction across consecutive batches before updating.
                    if abs(difference) >= POT_VOLUME_DEADBAND:
                        if direction == pending_direction:
                            pending_batches += 1
                        else:
                            pending_direction = direction
                            pending_batches = 1

                        if pending_batches >= POT_CONFIRM_BATCHES:
                            try:
                                send(["set_property", "volume", volume])
                                last_volume = volume
                                print(
                                    f"Pot volume: {volume}% "
                                    f"(charge {filtered_ms:.3f} ms, "
                                    f"{len(readings)}/{POT_SAMPLES} samples)",
                                    flush=True
                                )
                            except Exception as exc:
                                print(f"Potentiometer volume update failed: {exc}", flush=True)
                            pending_direction = 0
                            pending_batches = 0
                    else:
                        pending_direction = 0
                        pending_batches = 0

            stop_event.wait(0.02)

    except Exception as exc:
        print(f"Potentiometer volume control unavailable: {exc}", flush=True)
    finally:
        if request is not None:
            request.release()
        if chip is not None:
            chip.close()

def main():
    mpv=start_mpv()
    for _ in range(50):
        if os.path.exists(MPV_SOCKET): break
        time.sleep(.1)
    else: sys.exit("MPV socket failed")

    pot_stop = Event()
    pot_thread = Thread(
        target=potentiometer_volume_loop,
        args=(pot_stop,),
        name="storybox-pot-volume",
        daemon=True
    )
    pot_thread.start()

    gpio=subprocess.Popen(["gpiomon","-c","gpiochip0","-b","pull-up","-e","both",
        "--format","%E gpiochip0 %o",
        "6","1","0","3","8",str(ENCODER_CLK),str(ENCODER_DT)],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    pattern=re.compile(r"(falling|rising)\s+gpiochip0\s+(\d+)")
    # HW-040 channels idle high with the requested pull-ups.
    encoder_state = 0b11
    encoder_steps = 0
    if WELCOME_PROMPT.exists(): play(WELCOME_PROMPT)
    try:
        for output in gpio.stdout:
            match=pattern.search(output)
            if not match: continue
            edge=match.group(1)
            line=int(match.group(2))
            now=time.monotonic()
            if line in BUTTONS:
                # Existing pushbuttons remain active-low; ignore their rising edges.
                if edge != "falling": continue
                if now-last_press[line]>=DEBOUNCE_SECONDS:
                    last_press[line]=now
                    try:
                        handle(BUTTONS[line])
                    except Exception as exc:
                        print(f"Button handler failed: {exc}", flush=True)
            elif line in ENCODER_LINES:
                # Decode both channels together; one complete quadrature cycle is one click.
                previous_state=encoder_state
                level=1 if edge=="rising" else 0
                if line==ENCODER_CLK:
                    encoder_state=(encoder_state & 0b01) | (level << 1)
                else:
                    encoder_state=(encoder_state & 0b10) | level
                step=QUADRATURE.get((previous_state,encoder_state),0)
                if step:
                    encoder_steps += step
                elif previous_state != encoder_state:
                    # Ignore invalid two-bit jumps caused by contact bounce or missed edges.
                    encoder_steps=0
                if encoder_steps >= 4:
                    encoder_steps=0
                    try:
                        print("Rotary encoder: next",flush=True)
                        handle("next")
                    except Exception as exc:
                        print(f"Encoder handler failed: {exc}",flush=True)
                elif encoder_steps <= -4:
                    encoder_steps=0
                    try:
                        print("Rotary encoder: previous",flush=True)
                        handle("previous")
                    except Exception as exc:
                        print(f"Encoder handler failed: {exc}",flush=True)
    finally:
        pot_stop.set()
        pot_thread.join(timeout=3)
        gpio.terminate()
        try:
            gpio.wait(timeout=3)
        except subprocess.TimeoutExpired:
            gpio.kill()
            gpio.wait()

        mpv.terminate()
        try:
            mpv.wait(timeout=3)
        except subprocess.TimeoutExpired:
            mpv.kill()
            mpv.wait()

if __name__=="__main__": main()
