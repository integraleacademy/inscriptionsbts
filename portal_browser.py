"""Start Playwright with the same browser cache for the driver and installer."""
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys

from playwright.sync_api import Error, sync_playwright


def persistent_playwright():
    # The Node driver snapshots its environment when the context is entered.
    # Reuse Cyclades' existing Chromium installation across jobs and deploys.
    default = Path(os.environ.get('DATA_DIR', '/data')) / 'cyclades-browser'
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(default))
    return sync_playwright()


def launch_chromium(driver):
    executable = os.environ.get('CYCLADES_CHROMIUM_EXECUTABLE') or shutil.which('chromium')
    try:
        return driver.chromium.launch(executable_path=executable)
    except Error as exc:
        if executable or "Executable doesn't exist" not in str(exc):
            raise
    # The Playwright installer serializes concurrent installs in the shared cache.
    logging.getLogger(__name__).info('Installation de Chromium dans le cache des portails.')
    subprocess.run([sys.executable, '-m', 'playwright', 'install', '--only-shell', 'chromium'],
                   check=True, timeout=180, stdout=subprocess.DEVNULL)
    return driver.chromium.launch()
