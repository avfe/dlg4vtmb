import dataclasses
from typing import Dict, List, Optional

# Константы для обратной совместимости с JSON
VARIANT_KEYS: List[str] = [
    "unknown01", "unknown02", "unknown03",
    "unknown04", "unknown05", "unknown06", "malkavian"
]

@dataclasses.dataclass
class DlgRow:
    """
    Структура данных, представляющая одну строку (.dlg) или узел диалога.
    """
    index: int
    male: str
    female: str
    next: Optional[int]  # None, если реплика NPC ('#')
    condition: str
    action: str
    unknown01: str
    unknown02: str
    unknown03: str
    unknown04: str
    unknown05: str
    unknown06: str
    malkavian: str
    parent_npc: Optional[int] = None  # Для алгоритма раскладки и трассировок

    def is_pc_reply(self) -> bool:
        """True, если это реплика игрока (PC)."""
        return self.next is not None

    def get_variants(self) -> Dict[str, str]:
        """Все дополнительные варианты."""
        return {key: getattr(self, key) for key in VARIANT_KEYS}

    def set_variants(self, variants: Dict[str, str]):
        """Установить значения вариантов из словаря."""
        for key in VARIANT_KEYS:
            setattr(self, key, variants.get(key, ""))

    def is_empty_separator(self) -> bool:
        """
        Возвращает True, если строка является «пустым разделителем»:
        NPC-строка (next is None) и все текстовые поля пустые.
        Такие строки часто используются авторами .dlg как визуальные разделители.
        """
        if self.is_pc_reply():
            return False
        if any(getattr(self, k).strip() for k in VARIANT_KEYS):
            return False
        if any(getattr(self, f).strip() for f in ("male", "female", "condition", "action")):
            return False
        return True
