import collections
from typing import List, Dict, Tuple, Set, Optional

from model import DlgRow

# Базовые значения (используются как дефолт)
NODE_W_BASE, NODE_H_BASE = 300, 90
H_GAP_BASE, V_GAP_BASE = 60, 110
BARYCENTER_ITERATIONS = 5


def auto_gaps(n_nodes: int) -> Tuple[int, int]:
    """
    Эвристика для больших графов: чем больше узлов — тем компактнее интервалы.
    Возвращает (H_GAP, V_GAP).
    """
    # Базовая идея: масштаб ~ sqrt(N); сжимаем от 1.0 до 0.5
    if n_nodes <= 300:
        k = 1.0
    elif n_nodes <= 800:
        k = 0.8
    elif n_nodes <= 1200:
        k = 0.65
    else:
        k = 0.55
    return max(20, int(H_GAP_BASE * k)), max(60, int(V_GAP_BASE * k))


def _ensure_parents(rows: List[DlgRow]):
    """Заполняем parent_npc по порядку (если не задан)."""
    current_npc = None
    for r in rows:
        if not r.is_pc_reply():
            current_npc = r.index
        else:
            if r.parent_npc is None:
                r.parent_npc = current_npc


def _build_components(rows: List[DlgRow]) -> List[Set[int]]:
    nodes_map = {r.index: r for r in rows}
    visited: Set[int] = set()
    components: List[Set[int]] = []

    _ensure_parents(rows)

    # Обход по смешанным связям: NPC->PC (parent_npc), PC->NPC (next)
    for r in rows:
        if r.index in visited:
            continue
        comp: Set[int] = set()
        dq = collections.deque([r.index])
        visited.add(r.index)
        while dq:
            idx = dq.popleft()
            comp.add(idx)
            node = nodes_map[idx]
            # NPC -> PC дети
            children = [x.index for x in rows if x.parent_npc == idx]
            for ch in children:
                if ch not in visited:
                    visited.add(ch)
                    dq.append(ch)
            # PC -> NPC цель
            if node.is_pc_reply() and node.next in nodes_map:
                if node.next not in visited:
                    visited.add(node.next)
                    dq.append(node.next)
        components.append(comp)
    return components


def calculate_layout(
    rows: List[DlgRow],
    *,
    node_w: int = NODE_W_BASE,
    node_h: int = NODE_H_BASE,
    h_gap: int = H_GAP_BASE,
    v_gap: int = V_GAP_BASE,
) -> Dict[int, Tuple[float, float]]:
    """
    Слоистая раскладка (метод Сугиямы). Оставлена как «ленточный» вариант.
    """
    if not rows:
        return {}

    nodes_map = {row.index: row for row in rows}
    _ensure_parents(rows)

    # 1) Формирование слоёв
    layers: Dict[int, List[int]] = collections.defaultdict(list)
    node_to_layer: Dict[int, int] = {}
    components = _build_components(rows)

    q = collections.deque([(r.index, 0) for r in rows if r.parent_npc is None and not r.is_pc_reply()])

    while q:
        node_idx, level = q.popleft()
        if node_idx in node_to_layer:
            continue
        node_to_layer[node_idx] = level
        layers[level].append(node_idx)
        node = nodes_map[node_idx]
        if not node.is_pc_reply():
            children = [r.index for r in rows if r.parent_npc == node_idx]
            for child_idx in children:
                q.append((child_idx, level + 1))
        else:
            if node.next and node.next in nodes_map:
                q.append((node.next, level + 1))

    # 2) Барицентрический порядок
    for _ in range(BARYCENTER_ITERATIONS):
        for level in sorted(layers.keys()):
            barycenters = {}
            for node_idx in layers[level]:
                node = nodes_map[node_idx]
                neighbors = []
                if node.is_pc_reply() and node.parent_npc is not None:
                    neighbors.append(node.parent_npc)
                else:
                    neighbors = [r.index for r in rows if r.next == node_idx]
                if not neighbors:
                    barycenters[node_idx] = 0
                else:
                    prev = layers.get(level - 1, [])
                    pos = [prev.index(n) for n in neighbors if n in prev]
                    barycenters[node_idx] = sum(pos) / len(pos) if pos else 0
            layers[level].sort(key=lambda i: barycenters.get(i, 0))

    # 3) Координаты
    positions: Dict[int, Tuple[float, float]] = {}
    component_offset_x = 0
    for comp in components:
        if not comp:
            continue
        comp_layers: Dict[int, List[int]] = collections.defaultdict(list)
        min_level = 10 ** 9
        for node_idx, lvl in node_to_layer.items():
            if node_idx in comp:
                min_level = min(min_level, lvl)
                comp_layers[lvl].append(node_idx)

        max_width = 0
        for level in sorted(comp_layers.keys()):
            ordered = [n for n in layers.get(level, []) if n in comp_layers[level]]
            y = (level - min_level) * (node_h + v_gap)
            layer_width = len(ordered) * (node_w + h_gap)
            max_width = max(max_width, layer_width)
            start_x = component_offset_x - layer_width / 2
            for i, idx in enumerate(ordered):
                x = start_x + i * (node_w + h_gap)
                positions[idx] = (x, y)
        component_offset_x += max_width + h_gap * 4
    return positions


def calculate_tree_layout(
    rows: List[DlgRow],
    *,
    orientation: str = "vertical",
    node_w: int = NODE_W_BASE,
    node_h: int = NODE_H_BASE,
    h_gap: int = H_GAP_BASE,
    v_gap: int = V_GAP_BASE,
) -> Dict[int, Tuple[float, float]]:
    """
    Деревообразная раскладка (лес) с чередованием слоёв NPC→PC→NPC.
    orientation: 'vertical' — корни сверху; 'horizontal' — слева.
    ВАЖНО: компоненты теперь пакуются в сетку (grid), а не в один «широкий ряд».
    """
    if not rows:
        return {}

    # --- Подготовка ---
    nodes_map = {r.index: r for r in rows}

    # Если у PC отсутствует parent_npc, пытаемся восстановить из входящих NPC
    def _ensure_parents(rows: List[DlgRow]):
        idx2row = {r.index: r for r in rows}
        for r in rows:
            if r.is_pc_reply() and r.parent_npc is None:
                # ищем NPC, который ведёт на этот PC
                candidates = [n.index for n in rows if (not n.is_pc_reply()) and any(x.parent_npc == n.index for x in rows if x.is_pc_reply())]
                # быстрая эвристика: если у PC есть ровно один NPC-«родитель» по parent_npc в данных — оставим как есть
                # иначе ничего не делаем (не навредить)
                # (в твоих данных parent_npc обычно уже проставлен)
                pass
    _ensure_parents(rows)

    # --- 1) Корни (NPC без входящих PC→NPC) ---
    incoming_to_npc: Dict[int, int] = {r.index: 0 for r in rows if not r.is_pc_reply()}
    for r in rows:
        if r.is_pc_reply() and r.next in incoming_to_npc:
            incoming_to_npc[r.next] += 1

    roots = [idx for idx, cnt in incoming_to_npc.items() if cnt == 0]
    if not roots:
        # fallback: первый встретившийся NPC
        first_npc = next((r.index for r in rows if not r.is_pc_reply()), None)
        if first_npc is not None:
            roots = [first_npc]

    # --- 2) Компоненты и послойка внутри каждого компонента ---
    components: List[List[int]] = []                  # список индексов узлов по компонентам
    layers_by_comp: List[Dict[int, List[int]]] = []   # для каждой компоненты: {layer -> [indices]}
    visited: Set[int] = set()

    # Обход только по «деревянным» ребрам: NPC→PC (parent_npc), PC→NPC (next)
    def _bfs_layers(root_idx: int) -> Tuple[List[int], Dict[int, List[int]]]:
        comp_nodes: Set[int] = set()
        layers: Dict[int, List[int]] = collections.defaultdict(list)
        dq = collections.deque([(root_idx, 0)])
        visited.add(root_idx)
        while dq:
            idx, lvl = dq.popleft()
            comp_nodes.add(idx)
            layers[lvl].append(idx)
            node = nodes_map[idx]
            if not node.is_pc_reply():  # NPC → дети PC
                for ch in (x.index for x in rows if x.parent_npc == idx):
                    if ch not in visited:
                        visited.add(ch); dq.append((ch, lvl + 1))
            else:                        # PC → целевой NPC
                if node.next in nodes_map and node.next not in visited:
                    visited.add(node.next); dq.append((node.next, lvl + 1))
        return list(comp_nodes), layers

    for root in roots:
        if root not in visited:
            comp, layers = _bfs_layers(root)
            components.append(comp)
            layers_by_comp.append(layers)

    # Добавим «отвалившиеся» куски, если корни не покрыли все узлы
    for r in rows:
        if r.index not in visited:
            comp, layers = _bfs_layers(r.index)
            components.append(comp)
            layers_by_comp.append(layers)

    # --- 3) Упорядочивание слоёв барицентром (минимизация пересечений) ---
    for layers in layers_by_comp:
        # Несколько итераций для стабилизации
        for _ in range(BARYCENTER_ITERATIONS):
            for lvl in sorted(layers.keys()):
                layer_nodes = layers[lvl]
                b = {}
                for idx in layer_nodes:
                    node = nodes_map[idx]
                    neighbors = []
                    if node.is_pc_reply():
                        if node.parent_npc is not None:
                            neighbors.append(node.parent_npc)
                    else:
                        neighbors = [x.index for x in rows if x.is_pc_reply() and x.next == idx]
                    prev = layers.get(lvl - 1, [])
                    pos_list = [prev.index(n) for n in neighbors if n in prev]
                    b[idx] = (sum(pos_list) / len(pos_list)) if pos_list else 0.0
                layer_nodes.sort(key=lambda i: b.get(i, 0.0))

    # --- 4) КООРДИНАТЫ: упаковка компонентов в «сетку» ---
    positions: Dict[int, Tuple[float, float]] = {}

    # Предварительно оценим габариты каждой компоненты
    comp_infos: List[Tuple[int, Dict[int, List[int]], int, int]] = []  # (comp_idx, layers, width_px, height_px)
    for comp_idx, _comp_nodes in enumerate(components):
        layers = layers_by_comp[comp_idx]
        if not layers:
            comp_infos.append((comp_idx, layers, node_w + h_gap, node_h + v_gap))
            continue
        max_nodes_per_layer = max(len(layers[l]) for l in layers)
        num_layers = (max(layers.keys()) - min(layers.keys()) + 1)
        comp_w = max_nodes_per_layer * (node_w + h_gap)
        comp_h = num_layers * (node_h + v_gap)
        comp_infos.append((comp_idx, layers, comp_w, comp_h))

    # Эвристика числа столбцов: примерно √N
    ncomps = len(comp_infos)
    cols = max(1, int(round(ncomps ** 0.5)))
    margin_x = h_gap * 4   # расстояние между компонентами по «вторичной» оси
    margin_y = v_gap * 3   # расстояние между рядами

    row_primary_offset = 0.0   # для vertical это Y
    i = 0
    while i < ncomps:
        row = comp_infos[i:i + cols]
        i += cols

        # Высота ряда = max высоты компонентов; ширина ряда не критична — идём слева направо
        row_height = max((h for *_t, h in row), default=(node_h + v_gap))

        cur_secondary = 0.0  # для vertical это X
        for comp_idx, layers, comp_w, _comp_h in row:
            min_lvl = min(layers.keys()) if layers else 0

            for lvl in sorted(layers.keys()):
                indices = layers[lvl]
                secondary_span = len(indices) * (node_w + h_gap)
                start_secondary = cur_secondary + (comp_w - secondary_span) / 2.0
                for j, idx in enumerate(indices):
                    secondary = start_secondary + j * (node_w + h_gap)
                    primary = row_primary_offset + (lvl - min_lvl) * (node_h + v_gap)
                    if orientation == "vertical":
                        x, y = secondary, primary
                    else:
                        x, y = primary, secondary
                    positions[idx] = (x, y)

            cur_secondary += comp_w + margin_x

        row_primary_offset += row_height + margin_y

    return positions
