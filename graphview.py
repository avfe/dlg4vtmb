import math
from functools import partial
from typing import List, Optional

from PyQt5.QtCore import (
    Qt, QPointF, QRectF, QMarginsF, pyqtSignal, QEvent, QTimer
)
from PyQt5.QtGui import (
    QPainter, QPen, QBrush, QColor, QTransform, QPainterPath,
    QPolygonF, QKeyEvent
)
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsObject, QStyleOptionGraphicsItem, QWidget,
    QGraphicsPathItem, QGraphicsEllipseItem, QMenu
)

# Цвета/стили
NODE_COLORS = {
    'npc': QColor("#e0f0ff"),
    'pc': QColor("#fff0e0"),
    'border': QColor("#555555"),
    'text': QColor("#000000"),
}

# Основные стрелки PC→NPC (синий), вторичные связи NPC→PC — сплошные и зелёные при подсветке
EDGE_STYLES = {
    'normal': (QPen(QColor("#555555"), 1.8), QBrush(QColor("#555555"))),
    'dim': (QPen(QColor("#c9c9c9"), 1.0), QBrush(QColor("#c9c9c9"))),
    'highlight': (QPen(QColor("#007bff"), 2.6), QBrush(QColor("#007bff"))),

    # NPC→PC (варианты)
    'option': QPen(QColor("#8a9099"), 1.4),
    'option_dim': QPen(QColor("#d1d5db"), 1.0),
    'option_hi': QPen(QColor("#2ecc71"), 2.2),
}

NODE_WIDTH, NODE_HEIGHT = 300, 90
MAX_TEXT_LEN = 90

# Минимальный «дыхательный» отступ вокруг контента
SCENE_MARGIN_MIN = 80


class GraphEdge(QGraphicsPathItem):
    """Ребро (PC -> NPC). Главная правка — расширенный boundingRect, чтобы не обрезалась головка стрелки."""
    def __init__(self, source: 'GraphNode', dest: 'GraphNode'):
        super().__init__()
        self.source = source
        self.dest = dest
        self._arrow_size = 12  # размер треугольника стрелки
        self.arrow_head = QPolygonF()
        self.setZValue(-1)
        self.set_style('normal')
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.update_path()

    def set_style(self, style_name: str):
        pen, brush = EDGE_STYLES.get(style_name, EDGE_STYLES['normal'])
        self.setPen(pen)
        self._arrow_brush = brush

    def boundingRect(self) -> QRectF:
        # расширяем область отрисовки на размер стрелки — иначе Qt «отрежет» кончик
        r = super().boundingRect()
        s = self._arrow_size
        return r.marginsAdded(QMarginsF(s, s, s, s))

    def update_path(self):
        if not self.source or not self.dest:
            return

        p1 = self.source.pos() + QPointF(NODE_WIDTH / 2, NODE_HEIGHT / 2)
        p2 = self.dest.pos() + QPointF(NODE_WIDTH / 2, NODE_HEIGHT / 2)

        # подбираем подходящие стороны выхода/входа
        if abs(p1.x() - p2.x()) > abs(p1.y() - p2.y()):
            p1.setY(self.source.pos().y() + NODE_HEIGHT / 2)
            p2.setY(self.dest.pos().y() + NODE_HEIGHT / 2)
            if p1.x() < p2.x():
                p1.setX(self.source.pos().x() + NODE_WIDTH)
                p2.setX(self.dest.pos().x())
            else:
                p1.setX(self.source.pos().x())
                p2.setX(self.dest.pos().x() + NODE_WIDTH)
        else:
            p1.setX(self.source.pos().x() + NODE_WIDTH / 2)
            p2.setX(self.dest.pos().x() + NODE_WIDTH / 2)
            if p1.y() < p2.y():
                p1.setY(self.source.pos().y() + NODE_HEIGHT)
                p2.setY(self.dest.pos().y())
            else:
                p1.setY(self.source.pos().y())
                p2.setY(self.dest.pos().y() + NODE_HEIGHT)

        path = QPainterPath()
        path.moveTo(p1)
        c1 = p1 + QPointF(0, 80) if p1.y() < p2.y() else p1 - QPointF(0, 80)
        c2 = p2 - QPointF(0, 80) if p1.y() < p2.y() else p2 + QPointF(0, 80)
        path.cubicTo(c1, c2, p2)
        self.setPath(path)

        angle = math.atan2(p2.y() - c2.y(), p2.x() - c2.x())
        arrow_size = self._arrow_size
        p_arrow1 = p2 + QPointF(math.sin(angle - math.pi / 3) * arrow_size,
                                -math.cos(angle - math.pi / 3) * arrow_size)
        p_arrow2 = p2 + QPointF(math.sin(angle - math.pi + math.pi / 3) * arrow_size,
                                -math.cos(angle - math.pi + math.pi / 3) * arrow_size)
        self.arrow_head.clear()
        self.arrow_head.append(p2)
        self.arrow_head.append(p_arrow1)
        self.arrow_head.append(p_arrow2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        super().paint(painter, option, widget)
        painter.setBrush(self._arrow_brush)
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(self.arrow_head)


class OptionEdge(QGraphicsPathItem):
    """Сплошная связь NPC→PC (варианты ответа)."""
    def __init__(self, source_npc: 'GraphNode', dest_pc: 'GraphNode'):
        super().__init__()
        self.source = source_npc
        self.dest = dest_pc
        self.setZValue(-2)
        self.setPen(EDGE_STYLES['option'])
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.update_path()

    def set_state(self, state: str):
        if state == 'highlight':
            self.setPen(EDGE_STYLES['option_hi'])
        elif state == 'dim':
            self.setPen(EDGE_STYLES['option_dim'])
        else:
            self.setPen(EDGE_STYLES['option'])

    def update_path(self):
        if not self.source or not self.dest:
            return
        src = self.source.pos()
        dst = self.dest.pos()
        p1 = QPointF(src.x() + NODE_WIDTH/2, src.y() + NODE_HEIGHT) \
             if src.y() <= dst.y() else QPointF(src.x() + NODE_WIDTH/2, src.y())
        p2 = QPointF(dst.x() + NODE_WIDTH/2, dst.y()) \
             if src.y() <= dst.y() else QPointF(dst.x() + NODE_WIDTH/2, dst.y() + NODE_HEIGHT)
        path = QPainterPath(p1)
        dy = abs(p2.y() - p1.y())
        c1 = p1 + QPointF(0, dy*0.35 if p1.y() < p2.y() else -dy*0.35)
        c2 = p2 - QPointF(0, dy*0.35 if p1.y() < p2.y() else -dy*0.35)
        path.cubicTo(c1, c2, p2)
        self.setPath(path)


class LinkHandle(QGraphicsEllipseItem):
    """Точка на PC-узле для перепривязки (drag-link)."""
    def __init__(self, parent_node: 'GraphNode'):
        size = 12
        super().__init__(0, 0, size, size, parent_node)
        self.setBrush(QBrush(QColor('#007bff')))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(10)
        self.parent_node = parent_node
        self.setPos(NODE_WIDTH - size/2, NODE_HEIGHT/2 - size/2)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Drag to another NPC node to relink")
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            view = self.scene().views()[0]
            view.begin_link(self.parent_node, self.mapToScene(self.boundingRect().center()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            view = self.scene().views()[0]
            view.update_link(self.mapToScene(event.pos()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            view = self.scene().views()[0]
            view.end_link(self.parent_node, self.mapToScene(event.pos()))
            event.accept()
            return
        super().mouseReleaseEvent(event)


class GraphNode(QGraphicsObject):
    """Узел диалога."""
    def __init__(self, data):
        super().__init__()
        self.data = data
        self.in_edges: List[GraphEdge] = []
        self.out_edges: List[GraphEdge] = []
        self.opt_in_edges: List[OptionEdge] = []
        self.opt_out_edges: List[OptionEdge] = []

        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setAcceptHoverEvents(True)

        self.link_handle: Optional[LinkHandle] = None
        if self.data.is_pc_reply():
            self.link_handle = LinkHandle(self)

        self._press_pos: Optional[QPointF] = None

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.boundingRect()

        color = NODE_COLORS['pc'] if self.data.is_pc_reply() else NODE_COLORS['npc']
        painter.setBrush(QBrush(color))

        pen = QPen(EDGE_STYLES['highlight'][0]) if self.isSelected() else QPen(NODE_COLORS['border'])
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 10.0, 10.0)

        painter.setPen(NODE_COLORS['text'])
        text_rect = rect.adjusted(10, 5, -10, -5)

        if self.data.is_pc_reply():
            header = f"#{self.data.index}  PC → {self.data.next}"
        else:
            header = f"#{self.data.index}  NPC"

        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(text_rect, Qt.AlignTop | Qt.AlignLeft, header)

        font.setBold(False)
        painter.setFont(font)

        text_content = self.data.male if self.data.male else self.data.female
        if len(text_content) > MAX_TEXT_LEN:
            text_content = text_content[:MAX_TEXT_LEN] + "..."
        text_rect.adjust(0, 25, 0, 0)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.TextWordWrap, text_content)

    # контекстное меню
    def contextMenuEvent(self, event):
        menu = QMenu()
        if not self.data.is_pc_reply():
            # NPC
            act_add_pc = menu.addAction("Add PC reply here…")
            chosen = menu.exec_(event.screenPos())
            if chosen == act_add_pc:
                views = self.scene().views()
                if views:
                    mw = views[0].parent()
                    if hasattr(mw, "add_pc_under_npc"):
                        npc_idx = int(self.data.index)
                        QTimer.singleShot(0, partial(mw.add_pc_under_npc, npc_idx))
                        event.accept()
                        return
        else:
            # PC
            act_add_npc = menu.addAction("Add NPC answer…")
            chosen = menu.exec_(event.screenPos())
            if chosen == act_add_npc:
                views = self.scene().views()
                if views:
                    mw = views[0].parent()
                    if hasattr(mw, "add_npc_answer_for_pc"):
                        pc_idx = int(self.data.index)
                        scene_pos = event.scenePos()
                        QTimer.singleShot(0, partial(mw.add_npc_answer_for_pc, pc_idx, scene_pos))
                        event.accept()
                        return
        super().contextMenuEvent(event)

    # двойной клик — редактирование
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            views = self.scene().views()
            if views:
                mw = views[0].parent()
                if hasattr(mw, "open_editor_for"):
                    mw.open_editor_for(self)
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_pos = self.pos()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_pos is not None:
            old_pos = self._press_pos
            new_pos = self.pos()
            if (old_pos - new_pos).manhattanLength() > 0.1:
                views = self.scene().views()
                if views:
                    mw = views[0].parent()
                    if hasattr(mw, "push_move_command"):
                        mw.push_move_command(self, old_pos, new_pos)
        self._press_pos = None
        super().mouseReleaseEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for edge in self.in_edges:
                edge.update_path()
            for edge in self.out_edges:
                edge.update_path()
            for oe in self.opt_in_edges:
                oe.update_path()
            for oe in self.opt_out_edges:
                oe.update_path()
            views = self.scene().views()
            if views:
                view = views[0]
                if hasattr(view, 'nudge_away'):
                    view.nudge_away(self)
        return super().itemChange(change, value)


class GraphView(QGraphicsView):
    """Вид с улучшенным масштабом/панорамой и drag-link."""
    zoomChanged = pyqtSignal(float)
    linkCreated = pyqtSignal(int, int)  # (pc_index, npc_index)

    MIN_ZOOM = 0.10
    MAX_ZOOM = 4.00
    _STEP_FACTOR = 1.15

    def __init__(self, scene: QGraphicsScene, parent: Optional[QWidget] = None):
        super().__init__(scene, parent)
        self._panning = False
        self._pan_start_pos = QPointF()

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setInteractive(True)

        self.grabGesture(Qt.PinchGesture)

        self._temp_edge: Optional[QGraphicsPathItem] = None
        self._link_source: Optional[GraphNode] = None

        self._resolving_collision = False

    # --- масштаб/камера ---
    def _current_zoom(self) -> float:
        return float(self.transform().m11())

    def _apply_zoom_factor(self, factor: float):
        if factor == 0:
            return
        current = self._current_zoom()
        new_zoom = current * factor
        if new_zoom < self.MIN_ZOOM:
            factor = self.MIN_ZOOM / current
        elif new_zoom > self.MAX_ZOOM:
            factor = self.MAX_ZOOM / current
        self.scale(factor, factor)
        self.zoomChanged.emit(self._current_zoom())

    def zoom(self, factor: float):
        self._apply_zoom_factor(factor)

    def reset_zoom(self):
        self.setTransform(QTransform())
        self.zoomChanged.emit(self._current_zoom())

    def current_view_center_scene(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    def restore_view_center(self, scene_point: QPointF):
        self.centerOn(scene_point)

    # --- контекстное меню на пустом месте ---
    def contextMenuEvent(self, event):
        scene_pos = self.mapToScene(event.pos())
        items_here = self.scene().items(scene_pos)
        if not any(isinstance(it, GraphNode) for it in items_here):
            menu = QMenu(self)
            act_add_npc = menu.addAction("Add NPC here…")
            chosen = menu.exec_(event.globalPos())
            if chosen == act_add_npc:
                mw = self.parent()
                if hasattr(mw, "add_npc_at"):
                    QTimer.singleShot(0, partial(mw.add_npc_at, scene_pos))
                return
        super().contextMenuEvent(event)

    # --- события клавиш/колеса/панорама ---
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            event.accept()
            return
        # Навигация стрелками: делегируем в MainWindow
        if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right):
            mw = self.parent()
            if mw and hasattr(mw, 'navigate_selection'):
                if event.key() == Qt.Key_Up:
                    mw.navigate_selection('up');
                    event.accept();
                    return
                if event.key() == Qt.Key_Down:
                    mw.navigate_selection('down');
                    event.accept();
                    return
                if event.key() == Qt.Key_Left:
                    mw.navigate_selection('left');
                    event.accept();
                    return
                if event.key() == Qt.Key_Right:
                    mw.navigate_selection('right');
                    event.accept();
                    return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.setDragMode(QGraphicsView.RubberBandDrag)
        super().keyReleaseEvent(event)

    def wheelEvent(self, event):
        delta = 0
        if not event.angleDelta().isNull():
            delta = event.angleDelta().y() / 120.0
        elif not event.pixelDelta().isNull():
            delta = event.pixelDelta().y() / 240.0
        if delta != 0:
            factor = self._STEP_FACTOR ** delta
            self._apply_zoom_factor(factor)
        event.accept()

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Gesture:
            gesture = e.gesture(Qt.PinchGesture)
            if gesture:
                sc = gesture.scaleFactor()
                if abs(sc - 1.0) > 0.01:
                    self._apply_zoom_factor(sc)
                return True
        return super().event(e)

    def mousePressEvent(self, event):
        if event.button() == Qt.MidButton:
            self._panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            delta = event.pos() - self._pan_start_pos
            hs = self.horizontalScrollBar()
            vs = self.verticalScrollBar()
            hs.setValue(hs.value() - delta.x())
            vs.setValue(vs.value() - delta.y())
            self._pan_start_pos = event.pos()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.MidButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- Fit ---
    def _nodes_bounding_rect(self) -> Optional[QRectF]:
        node_items = [it for it in self.scene().items() if isinstance(it, GraphNode)]
        if not node_items:
            return None
        r = None
        for it in node_items:
            r = it.sceneBoundingRect() if r is None else r.united(it.sceneBoundingRect())
        if r is None:
            return None
        pct = max(r.width(), r.height()) * 0.05
        margin = max(pct, SCENE_MARGIN_MIN)
        return r.marginsAdded(QMarginsF(margin, margin, margin, margin))

    def fit_to_graph(self):
        r = self._nodes_bounding_rect()
        if r is None:
            return
        self.reset_transform_preserving_center(r)

    def fit_width(self):
        r = self._nodes_bounding_rect()
        if r is None:
            return
        self.setTransform(QTransform())
        view_w = self.viewport().width()
        s = view_w / r.width() if r.width() > 0 else 1.0
        s *= 0.95
        s = max(self.MIN_ZOOM, min(self.MAX_ZOOM, s))
        self.setTransform(QTransform.fromScale(s, s))
        self.centerOn(r.center())
        self.zoomChanged.emit(self._current_zoom())

    def fit_height(self):
        r = self._nodes_bounding_rect()
        if r is None:
            return
        self.setTransform(QTransform())
        view_h = self.viewport().height()
        s = view_h / r.height() if r.height() > 0 else 1.0
        s *= 0.95
        s = max(self.MIN_ZOOM, min(self.MAX_ZOOM, s))
        self.setTransform(QTransform.fromScale(s, s))
        self.centerOn(r.center())
        self.zoomChanged.emit(self._current_zoom())

    def reset_transform_preserving_center(self, target_rect):
        self.setTransform(QTransform())
        self.fitInView(target_rect, Qt.KeepAspectRatio)
        current = self._current_zoom()
        if current < self.MIN_ZOOM:
            self._apply_zoom_factor(self.MIN_ZOOM / current)
        elif current > self.MAX_ZOOM:
            self._apply_zoom_factor(self.MAX_ZOOM / current)

    # --- «выталкивание» (смягчённый) ---
    def nudge_away(self, moved: 'GraphNode', padding: float = 10.0, max_iter: int = 10):
        if self._resolving_collision:
            return
        self._resolving_collision = True
        try:
            for _ in range(max_iter):
                r1 = moved.sceneBoundingRect()
                hit = None
                for other in self.scene().items(r1.adjusted(-padding, -padding, padding, padding)):
                    if other is moved or not isinstance(other, GraphNode):
                        continue
                    if r1.intersects(other.sceneBoundingRect()):
                        hit = other
                        break
                if not hit:
                    break

                r2 = hit.sceneBoundingRect()
                dx1 = r1.right() - r2.left()
                dx2 = r2.right() - r1.left()
                dy1 = r1.bottom() - r2.top()
                dy2 = r2.bottom() - r1.top()
                if min(abs(dx1), abs(dx2)) < min(abs(dy1), abs(dy2)):
                    shift = QPointF(-(dx1 + 2) if abs(dx1) < abs(dx2) else (dx2 + 2), 0)
                else:
                    shift = QPointF(0, -(dy1 + 2) if abs(dy1) < abs(dy2) else (dy2 + 2))
                moved.setPos(moved.pos() + shift)
        finally:
            self._resolving_collision = False

    # --- Drag-link ---
    def begin_link(self, source_node: 'GraphNode', start_scene_pos: QPointF):
        if self._temp_edge is not None:
            self.scene().removeItem(self._temp_edge)
            self._temp_edge = None
        self._temp_edge = QGraphicsPathItem()
        self._temp_edge.setZValue(-0.5)
        pen = QPen(QColor('#007bff'), 2, Qt.DashLine)
        self._temp_edge.setPen(pen)
        self.scene().addItem(self._temp_edge)
        self._link_source = source_node
        self.update_link(start_scene_pos)

    def update_link(self, scene_pos: QPointF):
        if self._temp_edge is None or self._link_source is None:
            return
        p1 = self._link_source.sceneBoundingRect().center()
        p2 = scene_pos
        path = QPainterPath()
        path.moveTo(p1)
        c1 = p1 + QPointF(0, 60)
        c2 = p2 - QPointF(0, 60)
        path.cubicTo(c1, c2, p2)
        self._temp_edge.setPath(path)

    def end_link(self, source_node: 'GraphNode', scene_pos: QPointF):
        target_node = None
        for it in self.scene().items(scene_pos):
            if isinstance(it, GraphNode):
                target_node = it
                break
        if self._temp_edge:
            self.scene().removeItem(self._temp_edge)
            self._temp_edge = None
        if target_node and (not target_node.data.is_pc_reply()):
            self.linkCreated.emit(source_node.data.index, target_node.data.index)
