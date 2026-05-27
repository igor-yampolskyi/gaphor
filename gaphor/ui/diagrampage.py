import functools
import importlib
import logging

from gaphas.connector import ConnectionSink
from gaphas.connector import Connector as ConnectorAspect
from gaphas.guide import GuidePainter
from gaphas.item import matrix_i2i
from gaphas.painter import FreeHandPainter, HandlePainter, PainterChain
from gaphas.segment import LineSegmentPainter, Segment
from gaphas.tool.itemtool import default_find_item_and_handle_at_point
from gaphas.tool.rubberband import RubberbandPainter, RubberbandState
from gaphas.view import GtkView
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from gaphor.action import action
from gaphor.core import event_handler, gettext
from gaphor.core.modeling import StyleSheet
from gaphor.core.modeling.diagram import StyledDiagram
from gaphor.core.modeling.event import (
    AttributeUpdated,
    StyleSheetUpdated,
)
from gaphor.core.styling import PrefersColorScheme
from gaphor.diagram.diagramtoolbox import get_tool_def, tooliter
from gaphor.diagram.painter import DiagramTypePainter, ItemPainter
from gaphor.diagram.presentation import ElementPresentation, LinePresentation
from gaphor.diagram.tools import (
    apply_default_tool_set,
    apply_magnet_tool_set,
    apply_placement_tool_set,
)
from gaphor.diagram.tools.magnet import MagnetPainter
from gaphor.i18n import translated_ui_string
from gaphor.transaction import Transaction
from gaphor.ui.actiongroup import apply_action_group
from gaphor.ui.clipboard import Clipboard
from gaphor.ui.event import ToolSelected

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def placement_icon_base():
    f = importlib.resources.files("gaphor") / "ui" / "placement-icon-base.png"
    return GdkPixbuf.Pixbuf.new_from_file_at_scale(str(f), 64, 64, True)


if hasattr(GtkView, "set_css_name"):
    GtkView.set_css_name("diagramview")


def new_builder():
    builder = Gtk.Builder()
    builder.add_from_string(translated_ui_string("gaphor.ui", "diagrampage.ui"))
    return builder


@functools.cache
def get_placement_icon(display, icon_name):
    if display is None:
        display = Gdk.Display.get_default()
    pixbuf = placement_icon_base().copy()
    theme_icon = Gtk.IconTheme.get_for_display(display).lookup_icon(
        icon_name,
        None,
        24,
        1,
        Gtk.TextDirection.NONE,
        Gtk.IconLookupFlags.FORCE_SYMBOLIC,
    )
    icon = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        theme_icon.get_file().get_path(), 32, 32, True
    )
    icon.copy_area(
        0,
        0,
        icon.get_width(),
        icon.get_height(),
        pixbuf,
        9,
        15,
    )
    return Gdk.Texture.new_for_pixbuf(pixbuf)


def get_placement_cursor(display, icon_name):
    return Gdk.Cursor.new_from_texture(get_placement_icon(display, icon_name), 1, 1)


class DiagramPage:
    def __init__(self, diagram, event_manager, element_factory, modeling_language):
        self.event_manager = event_manager
        self.element_factory = element_factory
        self.diagram = diagram
        self.modeling_language = modeling_language
        self.clipboard = Clipboard(event_manager, element_factory)
        self.style_manager = Adw.StyleManager.get_default()

        self.view: GtkView | None = None
        self.alignment_button: Gtk.Button | None = None
        self.diagram_css: Gtk.CssProvider | None = None

        self.rubberband_state = RubberbandState()
        self.context_menu = Gtk.PopoverMenu.new_from_model(popup_model(diagram))

        self.event_manager.subscribe(self._on_attribute_updated)
        self.event_manager.subscribe(self._on_style_sheet_updated)
        self.event_manager.subscribe(self._on_tool_selected)

    @property
    def title(self):
        return self.diagram and self.diagram.name or gettext("<None>")

    def get_diagram(self):
        return self.diagram

    def get_view(self):
        return self.view

    def construct(self):
        """Create the widget.

        Returns: the newly created widget.
        """
        assert self.diagram

        builder = new_builder()
        view: GtkView = builder.get_object("view")
        view.add_css_class(self._css_class())
        view.connect("delete", delete_selected_items, self.event_manager)
        view.connect("cut-clipboard", self.clipboard.cut)
        view.connect("copy-clipboard", self.clipboard.copy)
        view.connect("paste-clipboard", self.clipboard.paste_link)
        view.connect("paste-full-clipboard", self.clipboard.paste_full)
        self.clipboard.clipboard.connect(
            "notify::content", self._clipboard_content_changed
        )

        self.diagram_css = Gtk.CssProvider.new()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.diagram_css,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )

        self.style_manager.connect("notify::dark", self._on_notify_dark)

        view.model = self.diagram
        self.view = view
        self.context_menu.set_parent(view)

        self.select_tool("toolbox-pointer")

        self._on_notify_dark(self.style_manager)
        self.update_drawing_style()

        diagrampage = builder.get_object("diagrampage")
        apply_action_group(self, "diagram", diagrampage)
        self._clipboard_content_changed(self.clipboard.clipboard)

        self.alignment_button = builder.get_object("alignment-button")

        return diagrampage

    def apply_tool_set(self, tool_name):
        """Return a tool associated with an id (action name).

        Tool sets can't be changed if a transaction is active,
        because it could ruin the user (inter)action.
        """

        if Transaction.in_transaction():
            log.warning("Cannot change tool set while in a transaction.")
            return False

        if tool_name == "toolbox-pointer":
            apply_default_tool_set(
                self.view,
                self.modeling_language,
                self.event_manager,
                self.rubberband_state,
            )
            if self.view:
                self.view.add_controller(
                    context_menu_controller(self.context_menu, self)
                )

        elif tool_name == "toolbox-magnet":
            apply_magnet_tool_set(
                self.view,
                self.modeling_language,
                self.event_manager,
            )
        else:
            tool_def = get_tool_def(self.modeling_language, tool_name)
            item_factory = tool_def.item_factory
            handle_index = tool_def.handle_index
            apply_placement_tool_set(
                self.view,
                item_factory=item_factory,
                modeling_language=self.modeling_language,
                event_manager=self.event_manager,
                handle_index=handle_index,
            )
        return True

    def get_tool_icon_name(self, tool_name):
        if tool_name == "toolbox-pointer":
            return None
        return next(
            t
            for t in tooliter(self.modeling_language.toolbox_definition)
            if t.id == tool_name
        ).icon_name

    def _css_class(self):
        return f"diagram-{id(self)}"

    @event_handler(ToolSelected)
    def _on_tool_selected(self, event: ToolSelected):
        self.select_tool(event.tool_name)

    @event_handler(AttributeUpdated)
    def _on_attribute_updated(self, event: AttributeUpdated):
        if event.property.name == "name" and self.view:
            self.view.update_back_buffer()

    @event_handler(StyleSheetUpdated)
    def _on_style_sheet_updated(self, _event):
        self.update_drawing_style()
        self.diagram.update(self.diagram.ownedPresentation)

    def _clipboard_content_changed(self, clipboard, _pspec=None):
        if not self.view:
            return

        enabled = self.clipboard.can_paste()
        self.view.action_set_enabled("clipboard.paste", enabled)
        self.view.action_set_enabled("clipboard.paste-full", enabled)

    def _on_notify_dark(self, style_manager, _gparam=None):
        self.update_drawing_style()

    def close(self):
        """Tab is destroyed.

        Do the same thing that would be done if Close was pressed.
        """
        assert self.view

        Gtk.StyleContext.remove_provider_for_display(
            Gdk.Display.get_default(),
            self.diagram_css,
        )

        self.event_manager.unsubscribe(self._on_attribute_updated)
        self.event_manager.unsubscribe(self._on_style_sheet_updated)
        self.event_manager.unsubscribe(self._on_tool_selected)
        self.view = None

    def select_tool(self, tool_name: str):
        if not self.view:
            return

        if self.apply_tool_set(tool_name):
            if icon_name := self.get_tool_icon_name(tool_name):
                self.view.set_cursor(get_placement_cursor(None, icon_name))
            else:
                self.view.set_cursor(None)

    def update_drawing_style(self):
        """Set the drawing style for the diagram based on the active style
        sheet."""
        assert self.view
        assert self.diagram_css

        prefers_color_scheme = (
            PrefersColorScheme.DARK
            if self.style_manager.get_dark()
            else PrefersColorScheme.LIGHT
        )

        view = self.view
        style_sheet = self.element_factory.style_sheet or StyleSheet()
        item_painter = ItemPainter(
            view.selection,
            functools.partial(
                style_sheet.compute_style, prefers_color_scheme=prefers_color_scheme
            ),
        )

        style = style_sheet.compute_style(
            StyledDiagram(self.diagram), prefers_color_scheme
        )
        bg = style.get("background-color", (0.0, 0.0, 0.0, 0.0))
        self.diagram_css.load_from_string(
            f".{self._css_class()} {{ background-color: rgba({int(255 * bg[0])}, {int(255 * bg[1])}, {int(255 * bg[2])}, {bg[3]}); }}",
        )

        if sloppiness := style.get("line-style", 0.0):
            item_painter = FreeHandPainter(item_painter, sloppiness=sloppiness)

        view.bounding_box_painter = item_painter
        view.painter = (
            PainterChain()
            .append(item_painter)
            .append(HandlePainter(view))
            .append(LineSegmentPainter(view.selection))
            .append(GuidePainter(view))
            .append(MagnetPainter(view))
            .append(RubberbandPainter(self.rubberband_state))
            .append(
                DiagramTypePainter(
                    self.diagram,
                    functools.partial(
                        style_sheet.compute_style,
                        prefers_color_scheme=prefers_color_scheme,
                    ),
                )
            )
        )

        view.request_update(self.diagram.get_all_items())

    @action(name="diagram.reset-line", label="Straighten Line")
    def reset_line(self, item_id: str):
        item = self.diagram.lookup(item_id)
        if not isinstance(item, LinePresentation):
            return

        with Transaction(self.event_manager):
            item.orthogonal = False
            item.horizontal = False
            while len(item.handles()) > 2:
                segment = Segment(item, self.diagram)
                segment.merge_segment(0)
            item.request_update()

        self.diagram.update({item})
        if self.view:
            self.view.request_update([item])

    @action(name="diagram.remove-bend-point", label="Remove Bend Point")
    def remove_bend_point(self, target: str):
        item_id, handle_index = parse_remove_bend_point_target(target)
        if item_id is None or handle_index is None:
            return

        item = self.diagram.lookup(item_id)
        if (
            not isinstance(item, LinePresentation)
            or handle_index <= 0
            or handle_index >= len(item.handles()) - 1
        ):
            return

        with Transaction(self.event_manager):
            if item.orthogonal and len(item.handles()) <= 3:
                item.orthogonal = False
                item.horizontal = False
            segment = Segment(item, self.diagram)
            segment.merge_segment(handle_index - 1)
            item.request_update()

        self.diagram.update({item})
        if self.view:
            self.view.request_update([item])

    @action(name="diagram.make-line-vertical", label="Make Vertical")
    def make_line_vertical(self, item_id: str):
        self.align_line(item_id, "vertical")

    @action(name="diagram.make-line-horizontal", label="Make Horizontal")
    def make_line_horizontal(self, item_id: str):
        self.align_line(item_id, "horizontal")

    def align_line(self, item_id: str, orientation: str):
        item = self.diagram.lookup(item_id)
        if not can_align_line(item, orientation):
            return

        coordinate = alignment_coordinate(item, orientation)
        if coordinate is None:
            return

        positions = [
            (handle, aligned_handle_position(item, handle, orientation, coordinate))
            for handle in (item.head, item.tail)
        ]

        with Transaction(self.event_manager):
            item.orthogonal = False
            item.horizontal = False
            for handle, position in positions:
                handle.pos = position
            for handle, _position in positions:
                reconnect_connected_handle(item, handle)
            item.request_update()

        self.diagram.update({item})
        if self.view:
            self.view.request_update([item])


def delete_selected_items(view: GtkView, event_manager):
    with Transaction(event_manager):
        items = view.selection.selected_items
        for i in list(items):
            i.unlink()


def context_menu_controller(context_menu, page):
    def on_show_popup(ctrl, n_press, x, y):
        if (
            Transaction.in_transaction()
            or ctrl.get_last_event() is None
            or not ctrl.get_last_event().triggers_context_menu()
        ):
            return

        view = ctrl.get_widget()
        item, handle = default_find_item_and_handle_at_point(view, (x, y))
        subject = item.subject if item and item.subject else page.diagram
        handle_index = handle_index_for_item(item, handle)

        context_menu.set_menu_model(
            popup_model(subject, item, handle_index, view.selection.selected_items)
        )

        gdk_rect = Gdk.Rectangle()
        gdk_rect.x = x
        gdk_rect.y = y
        gdk_rect.width = gdk_rect.height = 1

        context_menu.set_has_arrow(False)
        context_menu.set_pointing_to(gdk_rect)
        context_menu.popup()

    ctrl = Gtk.GestureClick.new()
    ctrl.set_button(0)
    ctrl.connect("pressed", on_show_popup)
    return ctrl


def can_reset_line(item) -> bool:
    return isinstance(item, LinePresentation) and len(item.handles()) > 2


def handle_index_for_item(item, handle) -> int | None:
    if isinstance(item, LinePresentation) and handle and handle in item.handles():
        handle_index: int = item.handles().index(handle)
        return handle_index
    return None


def can_remove_bend_point(item, handle_index) -> bool:
    return (
        isinstance(item, LinePresentation)
        and handle_index is not None
        and 0 < handle_index < len(item.handles()) - 1
    )


def can_align_line(item, orientation: str | None = None) -> bool:
    if not isinstance(item, LinePresentation) or len(item.handles()) != 2:
        return False

    head_x, head_y = item.head.pos.tuple()
    tail_x, tail_y = item.tail.pos.tuple()
    if head_x == tail_x or head_y == tail_y:
        return False

    if orientation is not None:
        return alignment_coordinate(item, orientation) is not None

    return any(
        alignment_coordinate(item, line_orientation) is not None
        for line_orientation in ("vertical", "horizontal")
    )


def can_align_selected_items(selected_items) -> bool:
    return (
        sum(
            1
            for selected_item in selected_items
            if isinstance(selected_item, ElementPresentation)
        )
        > 1
    )


def alignment_coordinate(item, orientation: str) -> float | None:
    head_x, head_y = item.head.pos.tuple()
    preferred = float(head_x if orientation == "vertical" else head_y)
    ranges = [
        connected_item_axis_range(item, handle, orientation)
        for handle in (item.head, item.tail)
        if item.diagram.connections.get_connection(handle)
    ]

    if not ranges:
        return preferred

    lower_bound = max(axis_range[0] for axis_range in ranges)
    upper_bound = min(axis_range[1] for axis_range in ranges)
    if lower_bound > upper_bound:
        return None

    return min(max(preferred, lower_bound), upper_bound)


def connected_item_axis_range(item, handle, orientation: str) -> tuple[float, float]:
    cinfo = item.diagram.connections.get_connection(handle)
    assert cinfo

    left, top, right, bottom = connected_item_bounds(item, cinfo.connected)
    return (left, right) if orientation == "vertical" else (top, bottom)


def aligned_handle_position(item, handle, orientation: str, coordinate: float):
    cinfo = item.diagram.connections.get_connection(handle)
    if not cinfo:
        x, y = handle.pos.tuple()
        return (coordinate, y) if orientation == "vertical" else (x, coordinate)

    left, top, right, bottom = connected_item_bounds(item, cinfo.connected)
    other_x, other_y = item.opposite(handle).pos.tuple()

    if orientation == "vertical":
        center_y = (top + bottom) / 2
        y = bottom if other_y > center_y else top
        return coordinate, y

    center_x = (left + right) / 2
    x = right if other_x > center_x else left
    return x, coordinate


def connected_item_bounds(item, connected) -> tuple[float, float, float, float]:
    matrix = matrix_i2i(connected, item)
    points = [matrix.transform_point(*handle.pos) for handle in connected.handles()]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def reconnect_connected_handle(item, handle):
    cinfo = item.diagram.connections.get_connection(handle)
    if not cinfo:
        return

    sink = ConnectionSink(cinfo.connected, distance=float("inf"))
    connector = ConnectorAspect(item, handle, item.diagram.connections)
    connector.reconnect_handle(sink)


def remove_bend_point_target(item_id: str, handle_index: int) -> str:
    return f"{item_id}:{handle_index}"


def parse_remove_bend_point_target(target: str) -> tuple[str | None, int | None]:
    try:
        item_id, handle_index = target.rsplit(":", 1)
        return item_id, int(handle_index)
    except ValueError:
        return None, None


def popup_model(element, item=None, handle_index=None, selected_items=()):
    model = Gio.Menu.new()
    part = Gio.Menu.new()

    menu_item = Gio.MenuItem.new(
        gettext("Show in Model Browser"),
        "win.show-in-model-browser",
    )
    menu_item.set_attribute_value("target", GLib.Variant.new_string(element.id))

    part.append_item(menu_item)
    model.append_section(None, part)

    if can_reset_line(item):
        part = Gio.Menu.new()
        menu_item = Gio.MenuItem.new(
            gettext("Straighten Line"),
            "diagram.reset-line",
        )
        menu_item.set_attribute_value("target", GLib.Variant.new_string(item.id))
        part.append_item(menu_item)
        if can_remove_bend_point(item, handle_index):
            menu_item = Gio.MenuItem.new(
                gettext("Remove Bend Point"),
                "diagram.remove-bend-point",
            )
            menu_item.set_attribute_value(
                "target",
                GLib.Variant.new_string(
                    remove_bend_point_target(item.id, handle_index)
                ),
            )
            part.append_item(menu_item)
        model.append_section(None, part)
    elif can_align_line(item):
        part = Gio.Menu.new()
        for label, action_name, orientation in (
            (gettext("Make Vertical"), "diagram.make-line-vertical", "vertical"),
            (gettext("Make Horizontal"), "diagram.make-line-horizontal", "horizontal"),
        ):
            if not can_align_line(item, orientation):
                continue
            menu_item = Gio.MenuItem.new(label, action_name)
            menu_item.set_attribute_value("target", GLib.Variant.new_string(item.id))
            part.append_item(menu_item)
        model.append_section(None, part)

    if can_align_selected_items(selected_items):
        append_alignment_actions(model)

    return model


def append_alignment_actions(model: Gio.Menu) -> None:
    for action_group in (
        (
            (gettext("Align Left"), "left"),
            (gettext("Align Right"), "right"),
            (gettext("Align Vertical Center"), "vertical-center"),
        ),
        (
            (gettext("Align Top"), "top"),
            (gettext("Align Bottom"), "bottom"),
            (gettext("Align Horizontal Center"), "horizontal-center"),
        ),
        (
            (gettext("Distribute Horizontally"), "distribute-horizontal"),
            (gettext("Distribute Vertically"), "distribute-vertical"),
        ),
        (
            (gettext("Max Width"), "max-width"),
            (gettext("Max Height"), "max-height"),
            (gettext("Max Size"), "max-size"),
            (gettext("Min Width"), "min-width"),
            (gettext("Min Height"), "min-height"),
            (gettext("Min Size"), "min-size"),
        ),
    ):
        part = Gio.Menu.new()
        for label, target in action_group:
            menu_item = Gio.MenuItem.new(label, "win.diagram-align")
            menu_item.set_attribute_value("target", GLib.Variant.new_string(target))
            part.append_item(menu_item)
        model.append_section(None, part)
