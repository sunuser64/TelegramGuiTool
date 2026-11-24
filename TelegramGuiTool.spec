# PyInstaller one-file Windows x64 build. Only explicitly listed public assets.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
hidden = collect_submodules('pywinauto', filter=lambda name: '.tests' not in name)
hidden += collect_submodules('comtypes.gen')
hidden += ['pyautogui', 'pyperclip', 'psutil', 'comtypes.stream', 'comtypes.persist']
a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'app' / 'assets'), 'app/assets'),
           (str(root / 'data' / 'sample.txt'), 'data')],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineQuick', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtTest', 'tkinter', 'unittest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
          name='TelegramGuiTool', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, disable_windowed_traceback=False)
