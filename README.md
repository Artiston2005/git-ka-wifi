# Git ka Wifi (GIT Jaipur WIFI Automator)
A system tray utility, built with Python, that automatically logs you into the GIT Jaipur captive Wi-Fi portal.

![Python 3.13](https://img.shields.io/badge/Python-3.13-blue?style=for-the-badge&logo=python)
![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
<a href="https://github.com/Artiston2005/git-ka-wifi/releases/latest"><img alt="Latest Release" src="https://img.shields.io/github/v/release/Artiston2005/git-ka-wifi?style=for-the-badge&logo=github"></a>

This app runs silently in the background, detects when you've connected to the "git" network, and automatically logs you in using your saved credentials.

### 📸 Screenshot
<img width="2559" height="1366" alt="Screenshot 2025-11-16 152656" src="https://github.com/user-attachments/assets/527c5aa2-8cc6-4193-a587-1db3094600aa" />

---

### ✨ Features
* **Automatic Login:** No more opening the browser to log in.
* **SSID Awareness:** Activates only when you connect to a "git" network.
* **Smart Keepalive:** Runs in the background to keep your session active and handles disconnects.
* **Encrypted Profiles:** Securely saves your username and password on your device.
* **System Tray Icon:** Minimizes to the tray with a dynamic icon title (Online/Offline).
* **Run on Startup:** Can be set to launch automatically with Windows.
* **Advanced Tools:** Includes a network diagnostics tab and an integrated speed test.
* **Custom Themes:** Personalize the app's look from the settings menu.
* **Speed Test:** Do speed test from the app itself. (**Disabled needs enabling by the user by rebuilding exe**)
* (To make the speed test working refer to `Developers section`)

---

### 🚀 How to Use (For GIT Students)
This is the simple way to install the app.

1.  Go to the [**Releases**](https://github.com/Artiston2005/git-ka-wifi/releases) page of this repository.
2.  Under the latest release (e.g., `v1.0.0`), download the `gitkawifi_ashwin.exe` file.
3.  Place `gitkawifi_ashwin.exe` in a folder where you'll keep it (like `C:\Program Files\GitKaWifi`).
4.  Run `gitkawifi_ashwin.exe`.
5.  The app will open. Enter your profile info, save it, and you're done!
6.  For the best experience, go to `Settings > Application` and check **"Run on Windows startup"**.
---

### 👨‍💻 For Developers (How to Run from Source)
If you want to run the app directly from the Python code:

**1. Clone the repository:**
```bash
git clone [https://github.com/Artiston2005/git-ka-wifi.git](https://github.com/Artiston2005/git-ka-wifi.git)
cd git-ka-wifi
```

**2. Install Dependencies (For Speed Test):**
```bash
pip install -r requirements.txt
```
**3. To build EXE:**
Download every file from this Github Repo into folder(Git Ka Wifi)
Right click in windows explorer to open terminal in that folder
**Install Dpendency**
```bash
pip install -r requirements.txt
pyinstaller --onefile --windowed --icon=8.ico --add-data "7.png;." main.py
```
Now find the exe file in dist folder
