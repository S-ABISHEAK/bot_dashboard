from shapely.geometry import box

from fleetnet_layout.geometry.operations import any_overlap, min_gap, subtract, within_boundary
from fleetnet_layout.geometry.primitives import GeoObject, Rect


def test_rect_to_polygon():
    r = Rect(0, 0, 10, 5)
    poly = r.to_polygon()
    assert poly.area == 50
    assert r.cx == 5 and r.cy == 2.5


def test_any_overlap_detects_overlap():
    a = GeoObject("a", "rack", box(0, 0, 10, 10))
    b = GeoObject("b", "rack", box(5, 5, 15, 15))
    c = GeoObject("c", "rack", box(20, 20, 30, 30))
    pairs = any_overlap([a, b, c])
    assert ("a", "b") in pairs or ("b", "a") in pairs
    assert len(pairs) == 1


def test_touching_not_overlap():
    a = GeoObject("a", "rack", box(0, 0, 10, 10))
    b = GeoObject("b", "rack", box(10, 0, 20, 10))
    assert any_overlap([a, b]) == []


def test_within_boundary():
    footprint = box(0, 0, 100, 100)
    inside = box(10, 10, 20, 20)
    outside = box(90, 90, 110, 110)
    assert within_boundary(inside, footprint)
    assert not within_boundary(outside, footprint)


def test_min_gap():
    a = box(0, 0, 10, 10)
    b = box(12, 0, 20, 10)
    assert min_gap(a, b) == 2


def test_subtract_carves_hole():
    base = box(0, 0, 10, 10)
    cut = box(4, 4, 6, 6)
    result = subtract(base, cut)
    assert result.area == 100 - 4
