import os
from unittest.mock import Mock

from playwright.sync_api import Error
import portal_browser


def test_driver_and_installer_share_the_persistent_cache(monkeypatch,tmp_path):
    monkeypatch.delenv('PLAYWRIGHT_BROWSERS_PATH',raising=False)
    monkeypatch.delenv('CYCLADES_CHROMIUM_EXECUTABLE',raising=False)
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    seen = []
    def driver():
        seen.append(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
        return pw
    def install(*args, **kwargs):
        seen.append(os.environ['PLAYWRIGHT_BROWSERS_PATH'])
    pw = Mock()
    pw.chromium.launch.side_effect=[Error("Executable doesn't exist"),'ready']
    monkeypatch.setattr(portal_browser,'sync_playwright',driver)
    monkeypatch.setattr(portal_browser.shutil,'which',lambda _:None)
    monkeypatch.setattr(portal_browser.subprocess,'run',install)
    assert portal_browser.launch_chromium(portal_browser.persistent_playwright())=='ready'
    assert seen==[str(tmp_path/'cyclades-browser')]*2


def test_existing_cache_and_executable_are_respected(monkeypatch,tmp_path):
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH',str(tmp_path))
    monkeypatch.setenv('CYCLADES_CHROMIUM_EXECUTABLE','/usr/bin/chromium')
    pw=Mock()
    monkeypatch.setattr(portal_browser,'sync_playwright',lambda:pw)
    assert portal_browser.launch_chromium(portal_browser.persistent_playwright())==pw.chromium.launch.return_value
    pw.chromium.launch.assert_called_once_with(executable_path='/usr/bin/chromium')
    assert os.environ['PLAYWRIGHT_BROWSERS_PATH']==str(tmp_path)
