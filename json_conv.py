import json
from typing import List, Dict, Any, Optional

from model import DlgRow, VARIANT_KEYS


def to_json_data(rows: List[DlgRow]) -> Dict[str, Any]:
    """
    Конвертирует список DlgRow в словарь, готовый для сериализации в JSON.
    """
    nodes = []
    for row in rows:
        node_data = {
            "index": row.index,
            "male": row.male,
            "female": row.female,
            "next": row.next,
            "condition": row.condition,
            "action": row.action,
            "variants": row.get_variants()
        }
        if row.parent_npc is not None:
            node_data["parent"] = row.parent_npc
        nodes.append(node_data)

    return {
        "metadata": {
            "format": "vtmb_dlg_2.0",
            "columns": ["index", "male", "female", "next", "condition", "action"] + VARIANT_KEYS,
            "note": "next=null corresponds to '#'. 'parent' is inferred for layout."
        },
        "nodes": nodes
    }


def from_json_data(data: Dict[str, Any]) -> Optional[List[DlgRow]]:
    """
    Конвертирует словарь из JSON в список DlgRow.
    Поддерживает обратную совместимость.
    """
    if "nodes" not in data:
        return None

    dlg_rows = []
    for node_data in data["nodes"]:
        variants = node_data.get("variants", {})

        # Обратная совместимость: если есть поле "clan" с "malkavian"
        if not variants.get("malkavian") and "clan" in node_data and "malkavian" in node_data["clan"]:
            variants["malkavian"] = node_data["clan"]["malkavian"]

        try:
            row = DlgRow(
                index=int(node_data["index"]),
                male=node_data.get("male", ""),
                female=node_data.get("female", ""),
                next=node_data.get("next"),  # next может быть null
                condition=node_data.get("condition", ""),
                action=node_data.get("action", ""),
                unknown01=variants.get("unknown01", ""),
                unknown02=variants.get("unknown02", ""),
                unknown03=variants.get("unknown03", ""),
                unknown04=variants.get("unknown04", ""),
                unknown05=variants.get("unknown05", ""),
                unknown06=variants.get("unknown06", ""),
                malkavian=variants.get("malkavian", ""),
                parent_npc=node_data.get("parent")
            )
            dlg_rows.append(row)
        except (ValueError, TypeError) as e:
            print(f"Skipping invalid node in JSON: {node_data}, error: {e}")
            continue

    return dlg_rows


def export_json(filepath: str, rows: List[DlgRow]) -> bool:
    """Сохраняет данные в JSON файл."""
    try:
        data = to_json_data(rows)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error exporting JSON: {e}")
        return False


def import_json(filepath: str) -> Optional[List[DlgRow]]:
    """Загружает данные из JSON файла."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return from_json_data(data)
    except Exception as e:
        print(f"Error importing JSON: {e}")
        return None
