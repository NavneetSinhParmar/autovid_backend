import subprocess
import os

FFMPEG = r"C:\ffmpeg-2025-12-28-git-9ab2a437a1-full_build\bin\ffmpeg.exe"
OUTPUT = "repro_output.mp4"

# The current failing logic from video_renderer.py
# FONT = "C:/Windows/Fonts/arial.ttf".replace(":", "\\\\:")
# This results in C\\:/Windows/Fonts/arial.ttf
FONT_FAIL = "C:/Windows/Fonts/arial.ttf".replace(":", "\\\\:")

def run_test(font_path_str, name):
    print(f"--- Running Test: {name} ---")
    print(f"Font string: {font_path_str}")
    
    cmd = [
        FFMPEG,
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=640x360:d=1",
        "-vf", f"drawtext=fontfile='{font_path_str}':text='Test Text':x=100:y=100:fontsize=40:fontcolor=white",
        OUTPUT
    ]
    
    print("Command:", " ".join(cmd))
    
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if result.returncode != 0:
        print("FAILED!")
        print(result.stderr[-500:]) # Print last 500 chars of stderr
    else:
        print("SUCCESS!")

# Test 1: The current logic
run_test(FONT_FAIL, "Current Logic (Double Backslash)")

# Test 2: Single Backslash 
# replace(":", "\:") -> literal \:
FONT_SINGLE = "C:/Windows/Fonts/arial.ttf".replace(":", "\:")
run_test(FONT_SINGLE, "Single Backslash")

# Test 3: Forward Slash Only (No escaping)
# Just C:/Windows...
FONT_NO_ESCAPE = "C:/Windows/Fonts/arial.ttf"
run_test(FONT_NO_ESCAPE, "No Escaping")

# Test 4: Escape the backslash itself? 
# Maybe just replace \ with / is enough and verify colon usage
# On Windows FFmpeg, sometimes drive letters need special handling like \:
