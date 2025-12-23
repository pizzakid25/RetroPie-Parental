#!/usr/bin/env python3

import time
import sys
import os
import re
import argparse
import psutil
import multiprocessing
import subprocess
import datetime
import sshkeyboard
import threading
import file
import shutil
from pathlib import Path

ROOT, FILENAME = os.path.split(os.path.abspath(__file__))
ANSI_ESCAPE = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')



def secondsToday():
    now = datetime.datetime.now().replace(microsecond=0)
    seconds = int((now - now.replace(hour=0, minute=0, second=0)).total_seconds())
    return seconds

def start_timer(game, unlimited):
    timer = file.get_timer()
    timer["started"] = True
    timer["currentGame"] = game
    timer["startTime"] = secondsToday()
    timer["startTimestamp"] = datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat()
    timer["unlimited"] = unlimited
    file.save_timer(timer)

def stop_timer():
    timer = file.get_timer()
    if timer["started"]:
        duration = secondsToday() - timer["startTime"]
        timer["started"] = False
        if (not timer["unlimited"]) and (not timer["disabled"]):
            timer["remaining"] -= duration
            if timer["remaining"] < 0:
                timer["remaining"] = 0
        timer["unlimited"] = False
        timer["currentGame"] = ""
        file.save_timer(timer)
        return duration
    return 0

def remaining_time(timer):
    remaining = timer["remaining"]
    if (not timer["started"]) or timer["unlimited"] or timer["disabled"]:
        return remaining
    duration = secondsToday() - timer["startTime"]
    remaining -= duration
    if remaining < 0:
        remaining = 0
    return remaining


password_timout_startTime = time.time()
def password_timeout():
    global password_timout_startTime
    password_timout_startTime = time.time()
    while time.time() - password_timout_startTime < 2: # 2 seconds
        time.sleep(.1)
    sshkeyboard.stop_listening()

def enter_password(password):
    global password_timout_startTime
    entered = []

    def press(key):
        if key == "tab":
            key = "X"
        if key == "enter":
            key = "A"
        if key == "space":
            key = "B"
        if key == "esc":
            key = "Y"
        if key == "pageup":
            key = "lshoulder"
        if key == "pagedown":
            key = "rshoulder"
        entered.append(key)
        global password_timout_startTime
        if entered == password:
            password_timout_startTime = 0
        else:
            password_timout_startTime = time.time() # reset timout

    threading.Thread(target=password_timeout).start()
    sshkeyboard.listen_keyboard(
        on_press=press, 
        sequential=True, 
        until="q",
        delay_second_char=0.05,
        delay_other_chars=0.05
        )

    return entered == password

def banner(text):
    cmd = ["toilet", "-f", "mono12", "-t", "--gay", text]
    try:
        raw_output = subprocess.check_output(cmd, text=True)
        lines_list = raw_output.splitlines()
    except subprocess.CalledProcessError:
        return

    columns, terminal_rows = shutil.get_terminal_size()
    
    v_pad = max(0, (terminal_rows - len(lines_list)) // 2)
    
    print("\033[H\033[J", end="") 
    print("\n" * v_pad, end="")

    for line in lines_list:
        visual_width = len(ANSI_ESCAPE.sub('', line))
        h_pad = max(0, (columns - visual_width) // 2)
        print(" " * h_pad + line)

    print("\n" * (v_pad - 1), end="")

def clean_name(name):
    name = Path(name).stem.split("(",1)[0].strip()
    #put console at the end
    parts = name.split(" - ", 1)
    if len(parts) == 1:
        return name
    return parts[1] + " (" + parts[0] + ")"


def play_sound(sound):
    sound = ROOT + "/static/" + sound
    subprocess.call(["play", sound], stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)

def start_game_monitor(emulator):
    stop_game_monitor() # stop old monitors
    process = multiprocessing.Process(target=lambda: subprocess.Popen([ROOT + "/" + FILENAME,"start_monitor", emulator]))
    process.start()

def stop_game_monitor():
    for proc in psutil.process_iter():
        if proc.name() == "python3":
            if proc.cmdline()[2:3] == ["start_monitor"]:
                proc.kill()

def kill_game(process_name):
    for proc in psutil.process_iter():
        if proc.name() == process_name:
            proc.kill()

# cli
def start_game(game, emulator):
    game = clean_name(game)
    timer = file.get_timer()
    remaining = remaining_time(timer)
    disabled = timer["disabled"]

    # show time remaining
    if disabled:
        banner("UNLIMITED PLAY")
    elif remaining == 0:
        reason = timer["reason"]
        if reason == "":
            reason = "NO TIME LEFT"
        banner(reason)
    else:
        timeLeft = time.strftime("%H:%M:%S", time.gmtime(remaining))
        banner("TIME LEFT: " + timeLeft)

    # await password
    passwords = file.get_passwords()
    unlimited = enter_password(passwords["unlimited"])

    # no time left
    if remaining == 0 and not unlimited and not disabled:
        file.log("Blocked | " + game)
        sys.exit(1) # don't allow game

    # allow the game to start
    if disabled:
        file.log("Started-Disabled | " + game)
        start_game_monitor(emulator)
    elif unlimited:
        play_sound("password-success.wav")
        file.log("Started-Unlimited | " + game)
    else:
        file.log("Started | " + game)
        start_game_monitor(emulator)
    start_timer(game, unlimited)
    sys.exit(0) # allow game

# cli
def end_game(game):
    game = clean_name(game)
    duration = stop_timer()
    file.log("Ended | " + game + " | " + str(duration))
    stop_game_monitor()

# cli
def start_monitor(emulator):
    while True:
        # kill a game if its run out of time
        time.sleep(60)
        timer = file.get_timer()
        remaining = remaining_time(timer)
        disabled = timer["disabled"]
        if not disabled:
            if 1 <= remaining <= 60:
                play_sound("game-warning.wav")
            if remaining == 0:
                play_sound("game-end.wav")
                kill_game(emulator)
                break

# parse cli
def parse_cli():
    parser = argparse.ArgumentParser(description='implements parental controls for RetroPie')
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start_game", help="log that a game is starting")
    start.add_argument("game", help="name of the game that is starting")
    start.add_argument("emulator", help="the process name of the emulator that the game will use")
    end = sub.add_parser("end_game", help="log that a game is ending")
    end.add_argument("game", help="name of the game that is starting")
    monitor = sub.add_parser("start_monitor", help="monitors a running game")
    monitor.add_argument("emulator", help="the process name of the emulator that the game will use")
    args = parser.parse_args()
    if args.command == "start_game":
        start_game(args.game, args.emulator)
    elif args.command == "end_game":
        end_game(args.game)
    elif args.command == "start_monitor":
        start_monitor(args.emulator)
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    parse_cli()
