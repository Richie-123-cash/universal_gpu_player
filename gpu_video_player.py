#!/usr/bin/env python3
import subprocess
import re
import shutil
import time
import tempfile
import os
import sys

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

def natural_sort_key(s):
    """Key for natural sorting (e.g. vid1, vid2, vid10)"""
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]

def intercept_video_traffic(url):
    """
    Launch a headless browser, navigate to URL, and sniff for .m3u8 or .ts files.
    Returns a path to a generated local playlist file or a direct URL.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: 'playwright' is not installed. Please install it to use this feature.")
        return None

    print(f"Launching headless browser to inspect: {url}")
    print("Please wait while we capture network traffic...")

    found_m3u8 = []
    found_ts = []

    with sync_playwright() as p:
        # Launch browser. Headless=True is default, but explicit is good.
        # Use a user-agent to mimic a real browser to avoid some bot detection.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        page = context.new_page()

        def handle_request(request):
            url = request.url
            if ".m3u8" in url:
                found_m3u8.append(url)
                print(f"Found Playlist: {url}")
            elif ".ts" in url:
                found_ts.append(url)
                # print(f"Found Segment: {url}") # Verbose

        page.on("request", handle_request)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait a bit for scripts to run and requests to fire
            print("Page loaded, listening for video segments...")
            
            # Heuristic: Wait up to 15 seconds, or until we find a playlist
            for _ in range(15):
                if found_m3u8:
                    break
                page.wait_for_timeout(1000)
            
            # If we only have TS files, wait a bit more to catch a sequence
            if not found_m3u8 and found_ts:
                print(f"Found {len(found_ts)} segments, waiting for more...")
                page.wait_for_timeout(5000)

        except Exception as e:
            print(f"Error during browser navigation: {e}")
        finally:
            browser.close()

    if found_m3u8:
        # Prefer the master playlist if found
        print(f"Using found playlist: {found_m3u8[-1]}")
        return found_m3u8[-1]
    
    if found_ts:
        # Sort segments naturally
        unique_ts = sorted(list(set(found_ts)), key=natural_sort_key)
        print(f"Collected {len(unique_ts)} unique video segments.")
        
        # Create a local M3U8 playlist
        # This assumes segments are sequential and compatible.
        fd, path = tempfile.mkstemp(suffix=".m3u8", text=True)
        with os.fdopen(fd, 'w') as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            # We don't know the duration, but putting a default might help certain players.
            # However, mpv is robust.
            for ts_url in unique_ts:
                f.write("#EXTINF:-1,\n")
                f.write(f"{ts_url}\n")
            f.write("#EXT-X-ENDLIST\n")
        
        print(f"Generated playlist at: {path}")
        return path

    print("No video streams found.")
    return None

def main():
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("Enter file path or URL: ").strip()
    
    start_input = ""
    # Only ask for start time if not passed via args (keep it simple for now)
    if len(sys.argv) <= 1:
        start_input = input("Start at (mm:ss or hh:mm:ss, leave empty for 0): ").strip()
    
    start_seconds = parse_start_time(start_input)
    cmd = ["prime-run", "mpv", f"--start={start_seconds}", "--hwdec=auto"]

    # Check method
    use_browser = False
    
    if not is_ytdl_supported(url) and (url.startswith("http://") or url.startswith("https://")):
        print("URL not supported by yt-dlp (or yt-dlp missing).")
        choice = input("Attempt to sniff video with headless browser? [Y/n]: ").strip().lower()
        if choice in ('', 'y', 'yes'):
            use_browser = True
    
    final_target = url

    if use_browser:
        sniffed_target = intercept_video_traffic(url)
        if sniffed_target:
            final_target = sniffed_target
        else:
            print("Falling back to original URL...")

    if is_ytdl_supported(final_target) and final_target == url:
         cmd += ["--ytdl-format=bestvideo[codec!=vp9][codec!=av1]+bestaudio/best"]
    
    cmd.append(final_target)

    print(f"Launching video on NVIDIA GPU: {final_target}")
    subprocess.run(cmd)

    # Cleanup temp file if we created one
    if final_target != url and final_target.endswith(".m3u8") and os.path.exists(final_target) and "tmp" in final_target:
        try:
            os.remove(final_target)
        except OSError:
            pass

if __name__ == "__main__":
    main()
