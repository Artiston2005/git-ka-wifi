# Git ka Wifi (GIT Jaipur Automator)
A system tray utility, built with Python, that automatically logs you into the GIT Jaipur captive Wi-Fi portal.

![Python 3.13](https://img.shields.io/badge/Python-3.13-blue?style=for-the-badge&logo=python)
![License: MIT](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
<a href="https://github.com/Artiston2005/git-ka-wifi/releases/latest"><img alt="Latest Release" src="https://img.shields.io/github/v/release/Artiston2005/git-ka-wifi?style=for-the-badge&logo=github"></a>

This app runs silently in the background, detects when you've connected to the "git" network, and automatically logs you in using your saved credentials.

### 📸 Screenshot

*(**How to add your screenshot:** After you paste this text, just drag-and-drop your `Screenshot 2025-11-16 140548.png` file directly into this text box. GitHub will upload it and give you a link that looks like `![image](...)`)*

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

---

### 🚀 How to Use (For GIT Students)
This is the simple way to install the app.

1.  Go to the [**Releases**](https://github.com/Artiston2005/git-ka-wifi/releases) page of this repository.
2.  Under the latest release (e.g., `v1.0.0`), download the `main.exe` file.
3.  Place `main.exe` in a folder where you'll keep it (like `C:\Program Files\GitKaWifi`).
4.  Run `main.exe`.
5.  The app will open. Enter your profile info, save it, and you're done!
6.  For the best experience, go to `Settings > Application` and check **"Run on Windows startup"**.

---

### 👨‍💻 For Developers (How to Run from Source)
If you want to run the app directly from the Python code:

**1. Clone the repository:**
```bash
git clone [https://github.com/Artiston2005/git-ka-wifi.git](https://github.com/Artiston2005/git-ka-wifi.git)
cd git-ka-wifi
