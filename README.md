# DOWNTOWN // Universal Video Extractor

![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![Cloudflare WARP](https://img.shields.io/badge/Cloudflare_WARP-F38020?style=for-the-badge&logo=cloudflare&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)

**DownTown** is a high-performance, containerized video extraction and streaming web application. Unlike standard media scrapers that instantly get rate-limited or blocked by datacenter IP restrictions (HTTP 429 / BotGuard), DownTown routes its extraction engine through an **automated, user-space Cloudflare WARP residential proxy tunnel** baked directly into the Docker environment.

---

## Architectural Highlights

### 100% Datacenter IP Bypass (Auto-WARP Tunnel)
Cloud providers (Render, AWS, GCP, Oracle) use datacenter IP ranges that are heavily throttled or blocked by modern video CDNs. DownTown solves this natively without cookies or burner accounts:
* On container boot, an automated bootloader (`start.sh`) registers an ephemeral, anonymous **Cloudflare WARP consumer identity** using `wgcf`.
* It launches `wireproxy`, a lightweight user-space WireGuard client that binds an encrypted residential proxy tunnel to local port `40000` (`socks5://127.0.0.1:40000`).
* All media scraping and URL decryption requests are routed through this tunnel, making the cloud server appear as a standard consumer residential device.

### Zero-Disk Memory Streaming Loop
To prevent filling up server hard drives or running out of cloud storage, DownTown operates with **zero disk writing**:
* Video streams are fetched over the WireGuard tunnel and piped directly into the server's standard output buffer (`stdout`).
* The Flask backend runs a multi-threaded Python generator loop that captures **1 MB memory chunks** and immediately streams them out to the user's browser.
* **Result:** You can download 4K video files without consuming a single megabyte of server disk space.

### Native EJS Challenge Solving
YouTube constantly rotates its JavaScript player ciphers and throttling parameter (`n`-sig) algorithms. DownTown embeds a native **Node.js runtime** within the Linux container, allowing the backend engine to dynamically fetch and execute official GitHub external JavaScript solvers (`ejs:github`) on the fly.

### Cool Minimalistic UI
The frontend is built with zero external UI libraries—just pure semantic HTML5, custom CSS3, and vanilla asynchronous JavaScript:
* Features a dynamic Japanese Katakana matrix rain background animation.
* High-contrast Neo-Brutalist layout with hard comic-book styling and interactive progress indicators.
* Handles real-time chunk assembly and native browser downloads via Blob URLs.

---

## Tech Stack

* **Frontend:** HTML5, CSS3 (Neo-Brutalism Theme), Vanilla JS (Fetch API)
* **Backend:** Python 3.11, Flask, Gunicorn (Multi-threaded WSGI HTTP Server)
* **Networking Engine:** `wgcf` (Cloudflare WARP CLI), `wireproxy` (User-space WireGuard SOCKS5 Proxy)
* **Extraction Core:** `yt-dlp` powered by embedded Node.js runtime (`ejs:github`)
* **DevOps / Deployment:** Docker, Debian Slim Linux Kernel

---

## Getting Started

### Prerequisites
* Docker installed on your local machine or cloud VPS.

### 1. Clone the Repository
```bash
git clone [https://github.com/](https://github.com/)<your-username>/downtown-extractor.git
cd downtown-extractor
```
### 2. Build the Docker Container
The included Dockerfile automatically pulls Python, Node.js, and the required ARM64/AMD64 networking binaries:

```Bash
docker build -t downtown-app .
```
### 3. Run the Container
Map port 5000 (or 80 for web traffic) to start the server:

```Bash
docker run -d \
  --name downtown \
  --restart unless-stopped \
  -p 5000:5000 \
  downtown-app
```
Visit http://localhost:5000 in your web browser to use the application!

## ⚠️ Disclaimer & Educational Notice
This project is created strictly for educational and personal software engineering portfolio purposes to demonstrate advanced Linux networking, proxy tunneling, and zero-disk memory streaming architectures.

Downloading copyrighted media without authorization or violating a platform's Terms of Service is discouraged. The creator assumes no liability for how this software is deployed or utilized by third parties.

## 📄 License
This project is open-sourced under the MIT License.
