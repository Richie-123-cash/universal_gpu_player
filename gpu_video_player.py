#!/usr/bin/env python3
import subprocess
import re
import shutil

def parse_start_time(start_str):
    """Convert mm:ss or hh:mm:ss to seconds"""
    if not start_str:
        return 0
    parts = list(map(int, start_str.split(":")))
    if len(parts) == 2:  # mm:ss
        return parts[0]*60 + parts[1]
    elif len(parts) == 3:  # hh:mm:ss
        return parts[0]*3600 + parts[1]*60 + parts[2]
    else:
        return int(parts[0])  # seconds

def is_ytdl_supported(url):
    """Check if yt-dlp can handle this URL"""
    yt_dlp_path = shutil.which("yt-dlp")
    if not yt_dlp_path:
        return False
    try:
        result = subprocess.run(
            [yt_dlp_path, "--simulate", "--no-warnings", "--quiet", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.returncode == 0
    except Exception:
        return False

def main():
    url = input("Enter file path or URL: ").strip()
    start_input = input("Start at (mm:ss or hh:mm:ss, leave empty for 0): ").strip()
    start_seconds = parse_start_time(start_input)

    cmd = ["prime-run", "mpv", f"--start={start_seconds}", "--hwdec=auto"]

    if is_ytdl_supported(url):
        # yt-dlp supported URL (YouTube, other supported sites)
        cmd += ["--ytdl-format=bestvideo[codec!=vp9][codec!=av1]+bestaudio/best"]

    cmd.append(url)

    print("Launching video on NVIDIA GPU...")
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
