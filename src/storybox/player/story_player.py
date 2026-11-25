#!/usr/bin/env python3
import json, os, re, socket, subprocess, sys, time
from pathlib import Path

BASE = Path("/home/admin")
CATALOG = BASE / "story-library.json"
STORIES_DIR = BASE / "stories"
PROMPTS_DIR = BASE / "story-prompts"
WELCOME_PROMPT = PROMPTS_DIR / "welcome.wav"
MPV_SOCKET = "/tmp/lunii-player.sock"
DEBOUNCE_SECONDS = 0.50
BUTTONS = {6:"play_pause",1:"next",0:"previous",3:"ok",7:"volume_down",8:"home",9:"volume_up"}
ENCODER_CLK = 2   # Orange Pi physical pin 22 (PA2)
ENCODER_DT = 21   # Orange Pi physical pin 26 (PA21)
ENCODER_LINES = (ENCODER_CLK, ENCODER_DT)
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
    elif action=="volume_up": send(["add","volume",5])
    elif action=="volume_down": send(["add","volume",-5])
    elif action=="home":
        mode="menu"; play(WELCOME_PROMPT)

def main():
    mpv=start_mpv()
    for _ in range(50):
        if os.path.exists(MPV_SOCKET): break
        time.sleep(.1)
    else: sys.exit("MPV socket failed")
    gpio=subprocess.Popen(["gpiomon","-c","gpiochip0","-b","pull-up","-e","both",
        "--format","%E gpiochip0 %o",
        "6","1","0","3","7","8","9",str(ENCODER_CLK),str(ENCODER_DT)],
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
