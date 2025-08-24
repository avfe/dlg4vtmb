import re
from typing import List, Tuple, Optional

from model import DlgRow

# Список кодировок для попытки чтения .dlg файлов
COMMON_ENCODINGS = ['utf-8-sig', 'cp1251', 'utf-16-le', 'utf-16-be', 'latin-1']

# Регулярное выражение для парсинга строки DLG
# Находит 13 полей в фигурных скобках, допуская пробелы
DLG_LINE_RE = re.compile(r'\s*'.join([r'\{(.*?)\}'] * 13))


def read_dlg(filepath: str) -> Tuple[Optional[List[DlgRow]], Optional[str]]:
    """
    Читает .dlg файл, автоматически определяя кодировку.

    Args:
        filepath: Путь к файлу.

    Returns:
        Кортеж из (список DlgRow, определенная кодировка) или (None, None) в случае ошибки.
    """
    last_exception = None
    for encoding in COMMON_ENCODINGS:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                lines = f.readlines()

            dlg_rows = []
            for line_text in lines:
                match = DLG_LINE_RE.match(line_text.strip())
                if not match:
                    continue

                groups = list(match.groups())

                # Декодируем символ ']' обратно в '}' для внутренней модели
                groups = [g.replace(']', '}') for g in groups]

                index_str, male, female, next_str, condition, action, *variants = groups

                try:
                    index = int(index_str)
                    next_val = None if next_str.strip() in ('#', '') else int(next_str)
                except ValueError:
                    continue  # Пропускаем некорректные строки

                dlg_rows.append(DlgRow(
                    index=index,
                    male=male,
                    female=female,
                    next=next_val,
                    condition=condition,
                    action=action,
                    unknown01=variants[0],
                    unknown02=variants[1],
                    unknown03=variants[2],
                    unknown04=variants[3],
                    unknown05=variants[4],
                    unknown06=variants[5],
                    malkavian=variants[6]
                ))
            return dlg_rows, encoding
        except (UnicodeDecodeError, Exception) as e:
            last_exception = e
            continue

    print(f"Failed to read DLG file with all attempted encodings. Last error: {last_exception}")
    return None, None


def write_dlg(filepath: str, rows: List[DlgRow], encoding: str) -> bool:
    """
    Записывает данные в .dlg файл в указанной кодировке.

    Args:
        filepath: Путь для сохранения файла.
        rows: Список DlgRow для записи.
        encoding: Кодировка файла.

    Returns:
        True в случае успеха, False в случае ошибки.
    """
    try:
        with open(filepath, 'w', encoding=encoding) as f:
            for row in rows:
                # Важно: заменяем '}' на ']' перед записью, чтобы не сломать формат
                values = [
                    str(row.index),
                    row.male,
                    row.female,
                    '#' if row.next is None else str(row.next),
                    row.condition,
                    row.action,
                    row.unknown01,
                    row.unknown02,
                    row.unknown03,
                    row.unknown04,
                    row.unknown05,
                    row.unknown06,
                    row.malkavian
                ]

                sanitized_values = [str(v).replace('}', ']') for v in values]
                f.write(''.join(f'{{{v}}}' for v in sanitized_values) + '\n')
        return True
    except Exception as e:
        print(f"Error writing DLG file: {e}")
        return False
