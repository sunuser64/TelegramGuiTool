"""Build a redistributable EXE and ZIP; never package runtime user data."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from app import __version__

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-tests', action='store_true', help='Only for a previously tested source tree')
    arguments = parser.parse_args()
    if sys.platform != 'win32' or platform.machine().upper() not in ('AMD64', 'X86_64'):
        raise SystemExit('Build on Windows x64 with Python x64.')
    environment = os.environ.copy()
    environment['PYINSTALLER_CONFIG_DIR'] = str(ROOT / 'build' / 'cache')
    # Ignore an operator's portable-data override when checking the source tree.
    environment.pop('TGNL_DATA_DIR', None)
    if not arguments.skip_tests:
        test_environment = environment.copy()
        test_environment['QT_QPA_PLATFORM'] = 'offscreen'
        subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                       cwd=ROOT, env=test_environment, check=True)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build' / 'pyinstaller'),
                    str(ROOT / 'TelegramGuiTool.spec')], cwd=ROOT, env=environment, check=True)
    destination = ROOT / 'dist'
    executable = destination / 'TelegramGuiTool.exe'
    digest = hashlib.sha256(executable.read_bytes()).hexdigest()
    packages = {name: importlib.metadata.version(name) for name in
                ('PyInstaller', 'PySide6', 'pywinauto', 'PyAutoGUI', 'pyperclip', 'psutil', 'comtypes', 'pywin32')}
    info = {'version': __version__, 'built_at_utc': datetime.now(timezone.utc).isoformat(),
            'python': platform.python_version(), 'architecture': platform.machine(),
            'onefile': True, 'console': False, 'digitally_signed': False,
            'source_tests_executed': not arguments.skip_tests,
            'executable': executable.name, 'size_bytes': executable.stat().st_size,
            'sha256': digest, 'packages': packages}
    (destination / 'build-info.json').write_text(json.dumps(info, indent=2), encoding='utf-8')
    (destination / 'SHA256SUMS.txt').write_text(f'{digest}  {executable.name}\n', encoding='utf-8')
    shutil.copy2(ROOT / 'README.md', destination / 'README.md')
    shutil.copy2(ROOT / 'MANUAL.md', destination / 'MANUAL.md')
    shutil.copy2(ROOT / 'data' / 'sample.txt', destination / 'sample.txt')
    with (destination / 'requirements-lock.txt').open('w', encoding='utf-8') as output:
        subprocess.run([sys.executable, '-m', 'pip', 'freeze'], stdout=output, check=True)
    archive = destination / f'TelegramGuiTool-{__version__}-windows-x64.zip'
    # Explicit allowlist excludes progress.db, logs, exports and any TXT uploads.
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in ('TelegramGuiTool.exe', 'README.md', 'MANUAL.md', 'sample.txt', 'build-info.json', 'SHA256SUMS.txt',
                     'requirements-lock.txt'):
            bundle.write(destination / name, arcname=f'TelegramGuiTool/{name}')
    print(f'EXE: {executable}\nZIP: {archive}\nSHA256: {digest}', flush=True)


if __name__ == '__main__':
    main()
