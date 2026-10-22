#!/usr/bin/env python3
import json, os, re, socket, subprocess, sys, time
from pathlib import Path

BASE = Path(os.environ.get("STORYBOX_HOME", str(Path.home())))
CATALOG = BASE / "story-library.json"
STORIES_DIR = BASE / "stories"
PROMPTS_DIR = BASE / "story-prompts"
WELCOME_PROMPT = PROMPTS_DIR / "welcome.wav"
MPV_SOCKET = "/tmp/lunii-player.sock"
DEBOUNCE_SECONDS = 0.50
BUTTONS = {6:"play_pause",1:"next",0:"previous",3:"ok",7:"volume_down",8:"home",9:"volume_up"}
last_press = {line:0.0 for line in BUTTONS}
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
    gpio=subprocess.Popen(["gpiomon","-c","gpiochip0","-b","pull-up","-e","falling",
        "6","1","0","3","7","8","9"],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    pattern=re.compile(r"falling\s+gpiochip0\s+(\d+)")
    if WELCOME_PROMPT.exists(): play(WELCOME_PROMPT)
    try:
        for output in gpio.stdout:
            match=pattern.search(output)
            if not match: continue
            line=int(match.group(1)); now=time.monotonic()
            if line in BUTTONS and now-last_press[line]>=DEBOUNCE_SECONDS:
                last_press[line]=now; handle(BUTTONS[line])
    finally:
        gpio.terminate(); mpv.terminate()

if __name__=="__main__": main()
