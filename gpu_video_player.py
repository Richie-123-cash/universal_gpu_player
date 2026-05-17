#!/usr/bin/env python3
import argparse
import subprocess
import re
import shutil
import tempfile
import os
import sys
import socket
from urllib.parse import urlparse

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


def _detect_gpu_context():
    """Pick the best mpv --gpu-context based on the running display server."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "waylandvk"   # Wayland + Vulkan
    elif os.environ.get("DISPLAY"):
        return "x11vk"       # X11 + Vulkan
    return "auto"            # headless / unknown — let mpv decide


def _detect_hwdec():
    """Pick the best hardware decoder based on the installed GPU."""
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True).stdout.lower()
        if "nvidia" in out:
            return "nvdec"
        if "amd" in out or "radeon" in out:
            return "vaapi"
        if "intel" in out:
            return "vaapi"
    except Exception:
        pass
    return "auto"


def build_mpv_base_cmd(start_seconds, no_gpu):
    """
    Return the base mpv invocation (launcher + mpv + start + GPU flags).
    Extra flags (yt-dlp format, cookies, target URL) are appended by the caller.
    """
    launcher = ["prime-run"] if (not no_gpu and shutil.which("prime-run")) else []
    base = launcher + ["mpv", f"--start={start_seconds}"]
    if not no_gpu:
        base += [
            f"--hwdec={_detect_hwdec()}",
            "--hwdec-codecs=all",
            "--vo=gpu-next",
            f"--gpu-context={_detect_gpu_context()}",
        ]
    return base

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

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--lang=en-US,en",
]

_CONTEXT_KWARGS = {
    "user_agent": BROWSER_UA,
    "viewport": {"width": 1920, "height": 1080},
    "locale": "en-US",
    "timezone_id": "America/New_York",
    "extra_http_headers": {
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
    },
}

# Minimal stealth init script — masks the most detectable headless signals.
# Used as fallback if playwright-stealth is not installed.
_STEALTH_INIT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
"""

# JS snippet run inside the browser to extract all m3u8 URLs baked into the page.
# Uses a split-on-extension approach to avoid regex escape conflicts between Python and JS.
# Many streaming sites embed a full list of CDN mirrors in window vars or script text —
# we collect them all and pick the first one whose hostname resolves on this system.
_JS_EXTRACT_M3U8 = """
() => {
    const found = new Set();
    let src = '';
    try { src += document.documentElement.outerHTML; } catch(e) {}
    try { src += JSON.stringify(window); } catch(e) {}
    const parts = src.split('.m3u8');
    for (let i = 0; i < parts.length - 1; i++) {
        const chunk = parts[i];
        const start = chunk.lastIndexOf('http');
        if (start < 0) continue;
        // Strip any JSON escape backslashes and stop at quote/whitespace/angle-bracket
        let url = chunk.slice(start).replace(/\\\\/g, '').replace(/[\\s"'<>]/g, '');
        found.add(url + '.m3u8');
    }
    return [...found];
}
"""

def _dns_ok(host):
    socket.setdefaulttimeout(3)
    try:
        socket.getaddrinfo(host, 443)
        return True
    except socket.gaierror:
        return False

def intercept_video_traffic(url):
    """
    Launch a headless browser, navigate to URL, and find a playable video stream.

    Strategy:
      1. Extract all m3u8 URLs embedded in the page's JS (streaming sites often list
         multiple CDN mirrors). Pick the first one whose hostname resolves on this system.
      2. Fall back to watching network request events for .m3u8 URLs (covers sites that
         build the URL dynamically after page load rather than embedding it in JS).
      3. If only raw .ts segments are seen, assemble a local M3U8 playlist.

    Returns (target_url_or_path, cookie_str, referer) or (None, None, None) on failure.
    The cookie_str and referer must be forwarded to mpv so the CDN accepts the request.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Error: 'playwright' is not installed. Please install it to use this feature.")
        return None, None, None

    print(f"Launching headless browser to inspect: {url}")
    print("Please wait while we capture network traffic...")

    req_m3u8 = []   # URLs seen via request events (may include unresolvable hosts)
    found_ts = []

    try:
        from playwright_stealth import Stealth
        _stealth = Stealth(
            navigator_user_agent_override=BROWSER_UA,
            navigator_platform_override="Win32",
            navigator_languages_override=("en-US", "en"),
        )
        _pw_ctx_mgr = _stealth.use_sync(sync_playwright())
        _stealth_available = True
    except ImportError:
        _pw_ctx_mgr = sync_playwright()
        _stealth_available = False

    with _pw_ctx_mgr as p:
        browser = p.chromium.launch(headless=True, args=_LAUNCH_ARGS)
        context = browser.new_context(**_CONTEXT_KWARGS)
        if not _stealth_available:
            context.add_init_script(_STEALTH_INIT_JS)
        page = context.new_page()

        def handle_request(request):
            req_url = request.url
            if ".m3u8" in req_url and req_url not in req_m3u8:
                req_m3u8.append(req_url)
            elif ".ts" in req_url and req_url not in found_ts:
                found_ts.append(req_url)

        page.on("request", handle_request)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            print("Page loaded, scanning for video streams...")

            # Wait for player scripts to initialize (up to 10s).
            # We always wait at least 5s so window vars are populated before JS extraction,
            # even if a request event fires early (request fires before DNS resolves).
            for i in range(10):
                page.wait_for_timeout(1000)
                if i >= 4 and req_m3u8:
                    break

            if not req_m3u8 and found_ts:
                print(f"Found {len(found_ts)} segments, waiting for more...")
                page.wait_for_timeout(5000)

            # Extract all m3u8 URLs baked into page JS (mirrors list)
            try:
                js_urls = page.evaluate(_JS_EXTRACT_M3U8)
            except Exception as js_err:
                print(f"JS extraction error: {js_err}")
                js_urls = []

        except Exception as e:
            print(f"Error during browser navigation: {e}")
            js_urls = []
        finally:
            all_cookies = context.cookies()
            browser.close()

    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in all_cookies) if all_cookies else ""

    # Merge JS-extracted URLs with request-event URLs, JS list first (more complete)
    # Normalise escaped backslashes that some sites use in JS strings
    all_m3u8 = list(dict.fromkeys(
        u.replace("\\/", "/") for u in (js_urls + req_m3u8)
    ))

    if all_m3u8:
        print(f"Found {len(all_m3u8)} playlist candidate(s), picking first resolvable...")
        for candidate in all_m3u8:
            host = urlparse(candidate).hostname
            if host and _dns_ok(host):
                print(f"Using playlist: {candidate}")
                return candidate, cookie_str, url
        print("No playlist candidates had a resolvable hostname.")

    if found_ts:
        unique_ts = sorted(list(set(found_ts)), key=natural_sort_key)
        print(f"Collected {len(unique_ts)} unique video segments.")

        fd, path = tempfile.mkstemp(suffix=".m3u8", text=True)
        with os.fdopen(fd, 'w') as f:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            for ts_url in unique_ts:
                f.write("#EXTINF:-1,\n")
                f.write(f"{ts_url}\n")
            f.write("#EXT-X-ENDLIST\n")

        print(f"Generated playlist at: {path}")
        return path, cookie_str, url

    print("No video streams found.")
    return None, None, None

def main():
    parser = argparse.ArgumentParser(
        description="GPU-accelerated video player (mpv wrapper)."
    )
    parser.add_argument("url", nargs="?", help="File path or URL to play")
    parser.add_argument(
        "--start", metavar="mm:ss",
        help="Start position (mm:ss or hh:mm:ss)", default=""
    )
    parser.add_argument(
        "--no-gpu", action="store_true",
        help="Disable GPU rendering and hardware decoding (software render)"
    )
    args = parser.parse_args()

    if not shutil.which("mpv"):
        sys.exit("Error: 'mpv' is not installed or not on PATH.")

    url = args.url or input("Enter file path or URL: ").strip()
    start_input = args.start or (
        input("Start at (mm:ss or hh:mm:ss, leave empty for 0): ").strip()
        if not args.url else ""
    )
    start_seconds = parse_start_time(start_input)
    no_gpu = args.no_gpu

    # Check method
    use_browser = False
    if not is_ytdl_supported(url) and (url.startswith("http://") or url.startswith("https://")):
        print("URL not supported by yt-dlp (or yt-dlp missing).")
        choice = input("Attempt to sniff video with headless browser? [Y/n]: ").strip().lower()
        if choice in ('', 'y', 'yes'):
            use_browser = True

    final_target = url
    browser_cookies = ""
    browser_referer = ""

    if use_browser:
        sniffed_target, browser_cookies, browser_referer = intercept_video_traffic(url)
        if sniffed_target:
            final_target = sniffed_target
        else:
            print("Falling back to original URL...")

    cmd = build_mpv_base_cmd(start_seconds, no_gpu)

    if is_ytdl_supported(final_target) and final_target == url:
        cmd += ["--ytdl-format=bestvideo[codec!=vp9][codec!=av1]+bestaudio/best"]

    if use_browser and final_target != url:
        # Sniffed HLS stream: disable yt-dlp hook (mpv handles HLS natively)
        # and pass the browser's auth context so the CDN accepts the request.
        cmd += ["--ytdl=no"]
        cmd += [f"--user-agent={BROWSER_UA}"]
        if browser_referer:
            cmd += [f"--referrer={browser_referer}"]
        if browser_cookies:
            cmd += [f"--http-header-fields-append=Cookie: {browser_cookies}"]

    cmd.append(final_target)

    label = "software" if no_gpu else "GPU"
    print(f"Launching ({label}): {' '.join(cmd)}")
    result = subprocess.run(cmd)

    if result.returncode != 0 and not no_gpu:
        print(f"[warn] mpv exited with code {result.returncode} — retrying without GPU flags...")
        fallback = ["mpv", f"--start={start_seconds}"]
        # Re-append yt-dlp / browser auth flags but NOT GPU flags
        if is_ytdl_supported(final_target) and final_target == url:
            fallback += ["--ytdl-format=bestvideo[codec!=vp9][codec!=av1]+bestaudio/best"]
        if use_browser and final_target != url:
            fallback += ["--ytdl=no", f"--user-agent={BROWSER_UA}"]
            if browser_referer:
                fallback += [f"--referrer={browser_referer}"]
            if browser_cookies:
                fallback += [f"--http-header-fields-append=Cookie: {browser_cookies}"]
        fallback.append(final_target)
        print(f"Fallback: {' '.join(fallback)}")
        subprocess.run(fallback)

    # Cleanup temp file if we created one
    if final_target != url and final_target.endswith(".m3u8") and os.path.exists(final_target) and "tmp" in final_target:
        try:
            os.remove(final_target)
        except OSError:
            pass

if __name__ == "__main__":
    main()
