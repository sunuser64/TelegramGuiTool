from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import shutil

RESOURCE_ROOT = Path(__file__).resolve().parent.parent


def data_root(frozen=None, environ=None):
    environ = os.environ if environ is None else environ
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if environ.get('TGNL_DATA_DIR'):
        return Path(environ['TGNL_DATA_DIR']).expanduser().resolve()
    if frozen:
        local = Path(environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
        return local / 'TelegramGuiTool'
    return RESOURCE_ROOT


ROOT = data_root()
DB_PATH = ROOT / 'data' / 'progress.db'
SAMPLE_PATH = RESOURCE_ROOT / 'data' / 'sample.txt'


def configure_logging():
    for name in ('data', 'logs', 'exports'):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    sample = ROOT / 'data' / 'sample.txt'
    if not sample.exists() and SAMPLE_PATH.exists():
        shutil.copyfile(SAMPLE_PATH, sample)
    handler = RotatingFileHandler(ROOT / 'logs' / 'app.log', maxBytes=2_000_000,
                                  backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
