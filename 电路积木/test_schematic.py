"""test_schematic.py — 电路图模块测试（纯 Python，不需要 pygame）。

覆盖：正交走线、自动排版、SVG 导出、文字网表、元件参数文字。
运行：
    python -m unittest test_schematic -v
"""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

import schematic
from circuit_core import DAMAGE_CUT, Circuit


def build_parallel() -> Circuit:
    circuit = Circuit()
    battery = circuit.add_part("battery")
    switch = circuit.add_part("switch")
    bulb1 = circuit.add_part("bulb")
    bulb2 = circuit.add_part("bulb")
    circuit.add_wire((battery.uid, 0), (switch.uid, 0))
    circuit.add_wire((switch.uid, 1), (bulb1.uid, 0))
    circuit.add_wire((switch.uid, 1), (bulb2.uid, 0))
    circuit.add_wire((bulb1.uid, 1), (bulb2.uid, 1))
    circuit.add_wire((bulb2.uid, 1), (battery.uid, 1))
    circuit.solve()
    return circuit


class TestWireRoute(unittest.TestCase):
    def test_route_is_orthogonal(self) -> None:
        points = schematic.wire_route((0, 0), (-1, 0), (200, 100), (1, 0))
        self.assertEqual(points[0], (0, 0))
        self.assertEqual(points[-1], (200, 100))
        for a, b in zip(points, points[1:]):
            self.assertTrue(
                abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5,
                f"斜线段 {a}->{b}",
            )

    def test_route_starts_along_direction(self) -> None:
        points = schematic.wire_route((0, 0), (0, -1), (120, 200), (1, 0))
        self.assertAlmostEqual(points[1][0], 0.0)
        self.assertLess(points[1][1], 0.0)

    def test_same_row_route_has_no_zero_length_segments(self) -> None:
        points = schematic.wire_route((0, 50), (1, 0), (200, 50), (-1, 0))
        self.assertGreaterEqual(len(points), 2)
        for a, b in zip(points, points[1:]):
            self.assertGreater(abs(a[0] - b[0]) + abs(a[1] - b[1]), 0.0)


class TestTerminals(unittest.TestCase):
    def _assert_point(self, actual, expected) -> None:
        self.assertAlmostEqual(actual[0], expected[0], places=6)
        self.assertAlmostEqual(actual[1], expected[1], places=6)

    def test_terminal_positions_follow_rotation(self) -> None:
        self._assert_point(schematic.terminal_position(100, 100, 0, 0), (40.0, 100.0))
        self._assert_point(schematic.terminal_position(100, 100, 90, 0), (100.0, 40.0))
        self._assert_point(schematic.terminal_position(100, 100, 180, 0), (160.0, 100.0))
        self._assert_point(schematic.terminal_position(100, 100, 270, 0), (100.0, 160.0))

    def test_symbol_geometry_returns_marks(self) -> None:
        geometry = schematic.symbol_geometry("voltmeter", 200, 120, 90, True)
        self.assertTrue(geometry.lines or geometry.circles or geometry.polylines)
        self.assertTrue(any(text == "V" for text, _, _ in geometry.letters))


class TestTidyLayout(unittest.TestCase):
    def test_all_parts_placed_inside_bounds(self) -> None:
        circuit = build_parallel()
        bounds = (20, 30, 700, 500)
        positions = schematic.tidy_layout(circuit, bounds)
        self.assertEqual(set(positions), set(circuit.parts))
        left, top, width, height = bounds
        for uid, (x, y, angle) in positions.items():
            self.assertGreaterEqual(x, left)
            self.assertGreaterEqual(y, top)
            self.assertLessEqual(x, left + width)
            self.assertLessEqual(y, top + height)
            self.assertIn(angle, (0, 90, 180, 270))

    def test_different_parts_get_different_positions(self) -> None:
        circuit = build_parallel()
        positions = schematic.tidy_layout(circuit, (0, 0, 780, 600))
        points = {(round(x), round(y)) for x, y, _ in positions.values()}
        self.assertEqual(len(points), len(positions))

    def test_empty_circuit(self) -> None:
        self.assertEqual(schematic.tidy_layout(Circuit(), (0, 0, 100, 100)), {})


class TestBuildSvg(unittest.TestCase):
    def setUp(self) -> None:
        self.circuit = build_parallel()
        self.positions = schematic.tidy_layout(self.circuit, (210, 58, 798, 712))
        self.svg = schematic.build_svg(self.circuit, self.positions, 798, 712)

    def test_svg_is_well_formed_xml(self) -> None:
        root = ET.fromstring(self.svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(root.get("width"), "798")
        self.assertEqual(root.get("height"), "712")

    def test_svg_has_declaration(self) -> None:
        self.assertTrue(self.svg.startswith('<?xml version="1.0" encoding="UTF-8"?>'))

    def test_svg_contains_symbols_and_labels(self) -> None:
        # 5 根导线 + 电阻/灯泡等折线符号
        self.assertGreaterEqual(self.svg.count("<polyline"), len(self.circuit.wires))
        # 灯泡圆圈、电压表圆圈等
        self.assertGreaterEqual(self.svg.count("<circle"), 2)
        # 元件名与参数标签
        self.assertIn("电池 #1", self.svg)
        self.assertIn("灯泡 #3", self.svg)
        self.assertIn("6V", self.svg)
        # 电池符号的极板
        self.assertGreaterEqual(self.svg.count("<line"), 4)

    def test_svg_escapes_text(self) -> None:
        self.circuit.parts[1].kind = "battery"
        positions = dict(self.positions)
        svg = schematic.build_svg(self.circuit, positions, 300, 200, title="A&B<C>")
        self.assertIn("A&amp;B&lt;C&gt;", svg)

    def test_broken_wire_is_dashed(self) -> None:
        self.circuit.cut_wire(1)
        svg = schematic.build_svg(self.circuit, self.positions, 798, 712)
        self.assertIn("stroke-dasharray", svg)

    def test_damaged_part_uses_damaged_color(self) -> None:
        bulb = next(p for p in self.circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_CUT
        svg = schematic.build_svg(self.circuit, self.positions, 798, 712)
        self.assertIn(schematic.DAMAGED_STROKE, svg)
        self.assertIn("被剪断", svg)


class TestNetlist(unittest.TestCase):
    def test_netlist_has_nodes_and_elements(self) -> None:
        circuit = build_parallel()
        text = schematic.build_netlist(circuit)
        self.assertIn("电路网表", text)
        self.assertIn("节点：", text)
        self.assertIn("元件：", text)
        self.assertIn("导线：", text)
        for uid in circuit.parts:
            self.assertIn(f"#{uid}", text)
        self.assertEqual(text.count("N1") >= 1, True)

    def test_parallel_bulbs_share_two_nodes(self) -> None:
        circuit = build_parallel()
        text = schematic.build_netlist(circuit)
        elements = text.split("元件：", 1)[1].split("导线：", 1)[0]
        bulb_lines = [line.strip() for line in elements.splitlines() if "灯泡" in line]
        self.assertEqual(len(bulb_lines), 2)
        node_pairs = {line.split()[-3:] and " ".join(line.split()[-3:]) for line in bulb_lines}
        self.assertEqual(len(node_pairs), 1, f"两只并联灯泡应接在同一对节点上：{bulb_lines}")

    def test_broken_wire_is_marked(self) -> None:
        circuit = build_parallel()
        circuit.cut_wire(2)
        text = schematic.build_netlist(circuit)
        self.assertIn("已剪断", text)

    def test_cut_part_marked(self) -> None:
        circuit = build_parallel()
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_CUT
        text = schematic.build_netlist(circuit)
        self.assertIn("被剪断", text)


class TestPartValueText(unittest.TestCase):
    def test_battery_and_bulb(self) -> None:
        battery = build_parallel().parts[1]
        self.assertIn("V", schematic.part_value_text(battery))
        bulb = build_parallel().parts[3]
        self.assertIn("12", schematic.part_value_text(bulb))

    def test_switch_state(self) -> None:
        circuit = build_parallel()
        switch = next(p for p in circuit.parts.values() if p.kind == "switch")
        self.assertEqual(schematic.part_value_text(switch), "闭合")
        switch.closed = False
        self.assertEqual(schematic.part_value_text(switch), "断开")


if __name__ == "__main__":
    unittest.main(verbosity=2)
