from dataclasses import dataclass
from pathlib import Path


class LoadCancelled(Exception):
    pass


@dataclass
class LoadedFile:
    path: str
    encoding: str
    lines: list[str]


def load_txt(path, remove_empty=True, cancelled=lambda: False):
    """Strict decoding; CP1251 is the fallback. Never modifies the source."""
    source = Path(path)
    if source.suffix.lower() != '.txt':
        raise ValueError('Выберите файл TXT.')
    raw = bytearray()
    with source.open('rb') as stream:
        while chunk := stream.read(65536):
            if cancelled():
                raise LoadCancelled()
            raw.extend(chunk)
    if cancelled():
        raise LoadCancelled()
    if b'\x00' in raw:
        raise ValueError('Двоичный файл или неподдерживаемая кодировка (например UTF-16).')
    encoding = 'utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'utf-8'
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        if encoding == 'utf-8-sig':
            raise ValueError('Повреждённый UTF-8 BOM файл.') from None
        encoding = 'cp1251'
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            raise ValueError('Не удалось определить кодировку TXT.') from None
    lines = []
    for number, line in enumerate(text.splitlines()):
        if number % 1024 == 0 and cancelled():
            raise LoadCancelled()
        if any(ord(c) < 32 and c != '\t' for c in line):
            raise ValueError('TXT содержит недопустимые управляющие символы.')
        if not remove_empty or line.strip():
            lines.append(line)
    return LoadedFile(str(source.resolve()), encoding, lines)
