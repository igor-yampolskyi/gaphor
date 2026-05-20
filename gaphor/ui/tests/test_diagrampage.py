import os

import pytest
import pytest_asyncio
from gaphas.segment import Segment
from gi.repository import Gdk, GLib

from gaphor import UML
from gaphor.core.modeling import Diagram
from gaphor.diagram.general import Box
from gaphor.diagram.presentation import LinePresentation
from gaphor.ui.diagrampage import (
    DiagramPage,
    delete_selected_items,
    get_placement_cursor,
    placement_icon_base,
    popup_model,
)
from gaphor.UML import Comment
from gaphor.UML.diagramitems import ClassItem, PackageItem
from gaphor.UML.general.comment import CommentItem


@pytest_asyncio.fixture
async def page(diagram, event_manager, element_factory, modeling_language):
    page = DiagramPage(diagram, event_manager, element_factory, modeling_language)
    page.construct()
    assert page.diagram == diagram
    assert page.view.model == diagram
    yield page
    page.close()


def test_creation(page, element_factory):
    assert len(element_factory.lselect()) == 1
    assert len(element_factory.lselect(Diagram)) == 1


def test_placement(diagram, page, element_factory):
    box = diagram.create(Box)
    page.view.request_update([box])

    diagram.create(CommentItem, subject=element_factory.create(Comment))
    assert len(element_factory.lselect()) == 4


@pytest.mark.skipif(
    bool(os.environ.get("GDK_PIXBUF_MODULEDIR")),
    reason="Causes a SegFault when run from VSCode",
)
def test_placement_icon_base_is_loaded_once():
    icon1 = placement_icon_base()
    icon2 = placement_icon_base()

    assert icon1 is icon2


@pytest.mark.skipif(
    bool(os.environ.get("GDK_PIXBUF_MODULEDIR")),
    reason="Causes a SegFault when run from VSCode",
)
def test_placement_cursor():
    display = Gdk.Display.get_default()
    cursor = get_placement_cursor(display, "gaphor-box-symbolic")

    assert cursor


@pytest.mark.asyncio
async def test_delete_selected_items(create, diagram, view, event_manager):
    package_item = create(PackageItem, UML.Package)
    view.selection.select_items(package_item)
    await view.update()

    delete_selected_items(view, event_manager)

    assert not diagram.ownedPresentation


def test_delete_selected_owner(create, diagram, view, event_manager, sanitizer_service):
    class_item = create(ClassItem, UML.Class)
    diagram.element = class_item.subject
    view.selection.select_items(class_item)

    delete_selected_items(view, event_manager)

    assert not diagram.ownedPresentation
    assert diagram.element is None


@pytest.mark.asyncio
async def test_not_delete_selected_package_owner(
    create, diagram, view, event_manager, sanitizer_service
):
    package_item = create(PackageItem, UML.Package)
    package = package_item.subject
    diagram.element = package_item.subject
    view.selection.select_items(package_item)
    await view.update()

    delete_selected_items(view, event_manager)

    assert not diagram.ownedPresentation
    assert diagram.element is package


def test_reset_line(page, diagram):
    line = diagram.create(LinePresentation)
    segment = Segment(line, diagram)
    segment.split((5, 5))
    segment = Segment(line, diagram)
    segment.split((10, 10))
    line.orthogonal = True
    line.horizontal = True

    assert len(line.handles()) > 2

    page.set_context_menu_item_id(line.id)
    page.reset_line()

    assert len(line.handles()) == 2
    assert not line.orthogonal
    assert not line.horizontal


def test_popup_model_contains_straighten_line_for_bent_line(diagram):
    line = diagram.create(LinePresentation)
    segment = Segment(line, diagram)
    segment.split((5, 5))

    menu = popup_model(diagram, line)

    assert menu.get_n_items() == 2
    section = menu.get_item_link(1, "section")
    assert section is not None
    assert section.get_n_items() == 1
    label = section.get_item_attribute_value(
        0, "label", GLib.VariantType.new("s")
    ).get_string()
    action = section.get_item_attribute_value(
        0, "action", GLib.VariantType.new("s")
    ).get_string()

    assert label == "Straighten Line"
    assert action == "diagram.reset-line"
