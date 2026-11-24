import json
import os
import tempfile
from pathlib import Path
from .database import now


def export_run(database, run_id, path):
    report = database.snapshot(run_id)
    report['run_id'] = report.pop('id')
    report['created_at'] = now()
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, target)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return target
