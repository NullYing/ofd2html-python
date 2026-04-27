"""Unit tests for the OFD AbbreviatedData -> SVG `d` conversion."""

from ofd2html.render.path import abbr_data_to_svg_d


def test_move_line_close():
    d = abbr_data_to_svg_d("M 0 0 L 10 0 L 10 10 L 0 10 C")
    assert d == "M 0 0 L 10 0 L 10 10 L 0 10 Z"


def test_cubic_bezier_maps_to_C():
    d = abbr_data_to_svg_d("M 0 0 B 1 1 2 2 3 3")
    assert d == "M 0 0 C 1 1 2 2 3 3"


def test_quadratic_passes_through():
    d = abbr_data_to_svg_d("M 0 0 Q 1 1 2 2")
    assert d == "M 0 0 Q 1 1 2 2"


def test_arc_passes_through():
    d = abbr_data_to_svg_d("M 0 0 A 5 5 0 0 1 10 0")
    assert d == "M 0 0 A 5 5 0 0 1 10 0"


def test_start_op_becomes_move():
    d = abbr_data_to_svg_d("S 1 2 L 3 4")
    assert d == "M 1 2 L 3 4"


def test_empty_input():
    assert abbr_data_to_svg_d("") == ""
