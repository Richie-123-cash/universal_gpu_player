# Universal GPU Player

A lightweight framework that manages and optimizes GPU usage for video playback, AI tasks, or rendering pipelines. Designed for simplicity, portability, and efficiency.

## Why Universal GPU Player?

No heavy setups, no daemons, no unnecessary bloat. Perfect for users who want full GPU acceleration without letting it drain their battery in ten minutes. Works out-of-the-box for standard videos and can handle more complex, embedded streams with a little extra guidance.

## Features

- Cross-platform GPU task handling  
- Dynamic load balancing  
- Lightweight and portable — minimal dependencies  
- Ideal for developers, power users, and efficiency enthusiasts  

## Installation

Install dependencies with:

```bash
pip install -r requirements.txt
```
## Usage

Run the script and follow the prompt:
'''bash
python gpu_video_player.py
'''
 Enter the URL of your video.

 The script will automatically detect GPU availability and accelerate playback using mpv and yt-dlp.

 Once playback finishes, you can simply close MPV and rerun the script for another video.

Extracting embedded video URLs (advanced — developer tools)

Some webpages (especially sites with custom or embedded players) hide the actual video stream behind scripts or dynamic requests. Do not copy the URL from the browser address bar — that’s usually just the wrapper page. Instead:

Example (Chromium / Chrome):

    Open the page with the embedded player (e.g., demo site).

    Open Developer Tools: Ctrl + Shift + I (or via the browser menu → More tools → Developer tools).

    Select the Network tab. Start playback to see network requests.

    Look for requests that resemble media files (.m3u8, .mp4, .ts) or large videoplayback requests.

    Click the request and copy the Request URL.

    Paste the real stream URL into the script’s prompt — the player will handle playback.

Important: This method is intended for troubleshooting, personal recordings, or content you have permission to access. Do not use it to bypass paywalls, DRM-protected content, or copyrighted material. Example URLs are purely for demonstration; you are responsible for proper use.

## License

MIT License

    Author: Richie-123-cash
    Version: 0.1.0
