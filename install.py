import subprocess
import sys
import os

VENV_DIR = ".venv"

print("Creating virtual environment...")
subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)

pip = os.path.join(VENV_DIR, "Scripts" if sys.platform == "win32" else "bin", "pip")
python = os.path.join(VENV_DIR, "Scripts" if sys.platform == "win32" else "bin", "python")

print("Installing package...")
subprocess.run([pip, "install", "-e", "."], check=True)

print("Installing Playwright browser...")
subprocess.run([python, "-m", "playwright", "install", "chromium"], check=True)

activate = r".venv\Scripts\activate" if sys.platform == "win32" else "source .venv/bin/activate"
print(f"\nDone! Activate the environment with:\n  {activate}")
