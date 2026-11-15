"""把电路转换成「电路图」：标准符号 + 正交走线。

这个模块只做纯数据计算，不依赖 pygame，所以既能给游戏界面画电路图，
也能直接导出成 SVG（矢量文本，不是图片）和 SPICE 风格的网表文本。

    >>> from circuit_core import Circuit
    >>> from schematic import tidy_layout, build_svg, build_netlist
    >>> circuit = Circuit()
    >>> ...  # 添加元件和导线
    >>> positions = tidy_layout(circuit, (0, 0, 798, 712))
    >>> open("circuit_diagram.svg", "w").write(build_svg(circuit, positions, 798, 712))

坐标约定和 circuit_game.py 一致：x 向右、y 向下；角度 0 表示引脚在左右两侧。
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Tuple

from circuit_core import (
    DAMAGE_CUT,
    DAMAGE_EXPLODED,
    PART_LABELS,
    Circuit,
    Part,
    fmt_capacitance,
    fmt_power,
    fmt_resistance,
    fmt_si,
    fmt_voltage,
)

TERMINAL_X = 60.0        # 端点到元件中心的距离
SYMBOL_W = 60            # 符号主体最大宽度

# 电路图配色（也用于导出 SVG）
KIND_STROKE = {
    "battery": "#d05a5a",
    "resistor": "#3f7fd0",
    "bulb": "#d98318",
    "switch": "#1f9e83",
    "rheostat": "#8256c8",
    "voltmeter": "#1f7fa6",
    "ammeter": "#c4702a",
    "capacitor": "#5f5bb4",
}
DAMAGED_STROKE = "#6a625b"
WIRE_STROKE = "#9a8c80"
WIRE_BROKEN_STROKE = "#c25a4a"
LABEL_FILL = "#59606f"
TITLE_FILL = "#2c3240"
FONT_FAMILY = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, sans-serif"

Point = Tuple[float, float]

# ---------------------------------------------------------------------------
# 几何基础
# ---------------------------------------------------------------------------
def rotate(x: float, y: float, angle: int) -> Point:
    """按角度旋转局部坐标（屏幕坐标，y 轴向下，角度顺时针为正）。"""
    angle %= 360
    if angle == 0:
        return x, y
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def terminal_position(x: float, y: float, angle: int, terminal: int) -> Point:
    local_x = -TERMINAL_X if terminal == 0 else TERMINAL_X
    dx, dy = rotate(local_x, 0.0, angle)
    return x + dx, y + dy


def terminal_direction(angle: int, terminal: int) -> Point:
    local_x = -1.0 if terminal == 0 else 1.0
    return rotate(local_x, 0.0, angle)


class Geometry:
    """一个元件的符号图元（世界坐标）。"""

    __slots__ = ("lines", "polylines", "circles", "letters")

    def __init__(self) -> None:
        self.lines: List[Tuple[Point, Point, int]] = []
        self.polylines: List[Tuple[List[Point], int]] = []
        self.circles: List[Tuple[Point, float, int, bool]] = []
        self.letters: List[Tuple[str, Point, int]] = []


def _local_geometry(kind: str, closed: bool) -> Geometry:
    """元件符号在本地坐标（中心为原点）里的图元。"""
    geo = Geometry()

    def line(a: Point, b: Point, width: int = 2) -> None:
        geo.lines.append((a, b, width))

    def leads(left_x: float, right_x: float) -> None:
        line((-TERMINAL_X, 0), (left_x, 0))
        line((right_x, 0), (TERMINAL_X, 0))

    if kind == "battery":
        leads(-10, 10)
        line((-10, -14), (-10, 14), 4)
        line((10, -7), (10, 7), 4)
        geo.letters.append(("+", (-24, -18), 11))
        geo.letters.append(("−", (24, -18), 11))
    elif kind == "resistor":
        leads(-26, 26)
        points = [(-26, 0)]
        for i in range(6):
            points.append((-18 + i * 7.2, -8 if i % 2 == 0 else 8))
        points.append((26, 0))
        geo.polylines.append((points, 2))
    elif kind == "bulb":
        leads(-17, 17)
        geo.circles.append(((0, 0), 15, 2, False))
        line((-10, -10), (10, 10), 2)
        line((-10, 10), (10, -10), 2)
    elif kind == "switch":
        leads(-22, 22)
        geo.circles.append(((-22, 0), 3, 2, True))
        geo.circles.append(((22, 0), 3, 2, True))
        if closed:
            line((-22, 0), (22, 0), 3)
        else:
            line((-22, 0), (8, -15), 3)
    elif kind == "rheostat":
        leads(-24, 24)
        line((-24, -11), (24, -11), 2)
        line((24, -11), (24, 11), 2)
        line((24, 11), (-24, 11), 2)
        line((-24, 11), (-24, -11), 2)
        line((-32, 16), (20, -16), 2)
        line((20, -16), (10, -14), 2)
        line((20, -16), (14, -24), 2)
    elif kind in ("voltmeter", "ammeter"):
        leads(-16, 16)
        geo.circles.append(((0, 0), 16, 2, False))
        geo.letters.append(("V" if kind == "voltmeter" else "A", (0, -1), 14))
    elif kind == "capacitor":
        leads(-8, 8)
        line((-8, -16), (-8, 16), 4)
        line((8, -16), (8, 16), 4)
    return geo


def symbol_geometry(kind: str, x: float, y: float, angle: int, closed: bool = True) -> Geometry:
    """元件符号在画布上的图元（已平移、旋转；文字位置会被旋转，但字形保持正立）。"""
    local = _local_geometry(kind, closed)
    geo = Geometry()
    for a, b, width in local.lines:
        ax, ay = rotate(a[0], a[1], angle)
        bx, by = rotate(b[0], b[1], angle)
        geo.lines.append(((x + ax, y + ay), (x + bx, y + by), width))
    for points, width in local.polylines:
        geo.polylines.append(
            ([((x + rotate(px, py, angle)[0]), (y + rotate(px, py, angle)[1])) for px, py in points], width)
        )
    for (cx, cy), radius, width, filled in local.circles:
        dx, dy = rotate(cx, cy, angle)
        geo.circles.append(((x + dx, y + dy), radius, width, filled))
    for text, (lx, ly), size in local.letters:
        dx, dy = rotate(lx, ly, angle)
        geo.letters.append((text, (x + dx, y + dy), size))
    return geo


# ---------------------------------------------------------------------------
# 正交走线（电路图那种横平竖直的线）
# ---------------------------------------------------------------------------
def wire_route(p0: Point, d0: Point, p3: Point, d3: Point, stub: float = 24.0) -> List[Point]:
    """从 p0（沿 d0 出线）到 p3（沿 d3 入线）的横平竖直折线。

    同一轴上的两条引出线走中间通道（U 形），这样不会从元件身上横穿过去。
    """
    a = (p0[0] + d0[0] * stub, p0[1] + d0[1] * stub)
    b = (p3[0] + d3[0] * stub, p3[1] + d3[1] * stub)
    d0_h = abs(d0[0]) > 0.5
    d3_h = abs(d3[0]) > 0.5
    points: List[Point] = [p0, a]
    if d0_h and d3_h:
        channel = (a[1] + b[1]) / 2.0
        points.extend([(a[0], channel), (b[0], channel), b])
    elif not d0_h and not d3_h:
        channel = (a[0] + b[0]) / 2.0
        points.extend([(channel, a[1]), (channel, b[1]), b])
    elif d0_h and not d3_h:
        points.extend([(b[0], a[1]), b])
    else:
        points.extend([(a[0], b[1]), b])
    points.append(p3)
    cleaned: List[Point] = []
    for point in points:
        if not cleaned or abs(point[0] - cleaned[-1][0]) > 0.5 or abs(point[1] - cleaned[-1][1]) > 0.5:
            cleaned.append(point)
    return cleaned


def _adjacency(circuit: Circuit) -> Dict[int, set]:
    adjacency: Dict[int, set] = {uid: set() for uid in circuit.parts}
    for a, b in circuit.wires:
        if a[0] in adjacency and b[0] in adjacency and a[0] != b[0]:
            adjacency[a[0]].add(b[0])
            adjacency[b[0]].add(a[0])
    return adjacency


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def tidy_layout(
    circuit: Circuit,
    bounds: Tuple[float, float, float, float],
    column_gap: float = 190.0,
    row_gap: float = 150.0,
    margin: float = 90.0,
) -> Dict[int, Tuple[float, float, int]]:
    """按「与电池的距离」分列排布元件，返回 {uid: (x, y, angle)}。

    电路图里元件保持水平放置（引脚在左右），列内垂直居中，尽量不越界。
    """
    parts = list(circuit.parts.values())
    if not parts:
        return {}
    left, top, width, height = bounds
    adjacency = _adjacency(circuit)

    start = next((p.uid for p in parts if p.kind == "battery"), parts[0].uid)
    depth: Dict[int, int] = {start: 0}
    queue = [start]
    order: List[int] = []
    while queue:
        uid = queue.pop(0)
        order.append(uid)
        for neighbour in sorted(adjacency.get(uid, ())):
            if neighbour not in depth:
                depth[neighbour] = depth[uid] + 1
                queue.append(neighbour)

    extra = [p.uid for p in parts if p.uid not in depth]
    if extra and order:
        base = max(depth.values()) + 1
        for index, uid in enumerate(extra):
            depth[uid] = base + index // 3

    columns: Dict[int, List[int]] = {}
    for part in parts:
        columns.setdefault(depth[part.uid], []).append(part.uid)

    max_columns = max(1, int(max(1.0, width - 2 * margin) // column_gap) + 1)
    usable_height = max(120.0, height - 2 * margin)
    positions: Dict[int, Tuple[float, float, int]] = {}
    for index, depth_key in enumerate(sorted(columns)):
        uids = columns[depth_key]
        band = index // max_columns
        column = index % max_columns
        cx = left + margin + column * column_gap
        count = len(uids)
        # 列内均匀分布，并夹在画布内
        span = min(usable_height, max(0, count - 1) * row_gap)
        start_y = top + height / 2.0 - span / 2.0 + band * (usable_height + row_gap)
        for row, uid in enumerate(uids):
            cy = start_y + row * row_gap
            cx_clamped = _clamp(cx, left + margin, left + width - margin)
            cy_clamped = _clamp(cy, top + 70, top + height - 70)
            positions[uid] = (cx_clamped, cy_clamped, 0)
    return positions


# ---------------------------------------------------------------------------
# 导出：SVG（矢量文本）与网表
# ---------------------------------------------------------------------------
def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def part_value_text(part: Part) -> str:
    if part.kind == "battery":
        return fmt_voltage(part.value)
    if part.kind == "bulb":
        return f"{fmt_resistance(part.value)} / {part.rated_v:g}V"
    if part.kind == "resistor":
        return fmt_resistance(part.value)
    if part.kind == "rheostat":
        return f"0–{fmt_resistance(part.value)}"
    if part.kind == "capacitor":
        return fmt_capacitance(part.value)
    if part.kind == "switch":
        return "闭合" if part.closed else "断开"
    if part.kind == "voltmeter":
        return fmt_voltage(part.u)
    if part.kind == "ammeter":
        return f"{fmt_si(abs(part.i), 'A')}"
    return ""


def build_svg(
    circuit: Circuit,
    positions: Dict[int, Tuple[float, float, int]],
    width: int,
    height: int,
    title: str = "电路图",
) -> str:
    """生成 SVG 文本（矢量图，不是位图截图）。"""
    out: List[str] = ['<?xml version="1.0" encoding="UTF-8"?>']
    out.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT_FAMILY}">'
    )
    out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(
        f'<text x="28" y="38" font-size="22" fill="{TITLE_FILL}" font-weight="700">{_escape(title)}</text>'
    )
    out.append(
        f'<text x="28" y="62" font-size="12" fill="{LABEL_FILL}">'
        f"元件 {len(circuit.parts)} 个 · 导线 {len(circuit.wires)} 根 · 剪断 {circuit.broken_count()} 根</text>"
    )

    # 导线先画，元件后画，避免线头盖住符号
    for index, (a, b) in enumerate(circuit.wires):
        if a[0] not in positions or b[0] not in positions:
            continue
        ax, ay, aangle = positions[a[0]]
        bx, by, bangle = positions[b[0]]
        p0 = terminal_position(ax, ay, aangle, a[1])
        p3 = terminal_position(bx, by, bangle, b[1])
        d0 = terminal_direction(aangle, a[1])
        d3 = terminal_direction(bangle, b[1])
        points = wire_route(p0, d0, p3, d3)
        trace = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        if circuit.is_wire_broken(index):
            out.append(
                f'<polyline points="{trace}" fill="none" stroke="{WIRE_BROKEN_STROKE}" '
                f'stroke-width="2.5" stroke-dasharray="6 5" stroke-linecap="round"/>'
            )
        else:
            out.append(
                f'<polyline points="{trace}" fill="none" stroke="{WIRE_STROKE}" '
                f'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
            )

    for part in circuit.parts.values():
        if part.uid not in positions:
            continue
        x, y, angle = positions[part.uid]
        geo = symbol_geometry(part.kind, x, y, angle, part.closed)
        stroke = DAMAGED_STROKE if part.damaged else KIND_STROKE.get(part.kind, "#666666")
        for a, b, line_width in geo.lines:
            out.append(
                f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
                f'stroke="{stroke}" stroke-width="{line_width}" stroke-linecap="round"/>'
            )
        for points, line_width in geo.polylines:
            trace = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            out.append(
                f'<polyline points="{trace}" fill="none" stroke="{stroke}" '
                f'stroke-width="{line_width}" stroke-linecap="round" stroke-linejoin="round"/>'
            )
        for (cx, cy), radius, circle_width, filled in geo.circles:
            fill = stroke if filled else "none"
            out.append(
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{circle_width}"/>'
            )
        for text, (lx, ly), size in geo.letters:
            out.append(
                f'<text x="{lx:.1f}" y="{ly + size * 0.36:.1f}" font-size="{size}" fill="{stroke}" '
                f'text-anchor="middle">{_escape(text)}</text>'
            )
        label = f"{PART_LABELS[part.kind]} #{part.uid}"
        value = part_value_text(part)
        if part.damaged:
            value += " · " + ("已爆炸" if part.state == DAMAGE_EXPLODED else
                              ("被剪断" if part.state == DAMAGE_CUT else "已烧毁"))
        out.append(
            f'<text x="{x:.1f}" y="{y + 42:.1f}" font-size="12" fill="{LABEL_FILL}" '
            f'text-anchor="middle">{_escape(label)}</text>'
        )
        if value:
            out.append(
                f'<text x="{x:.1f}" y="{y + 58:.1f}" font-size="12" fill="{LABEL_FILL}" '
                f'text-anchor="middle">{_escape(value)}</text>'
            )

    out.append("</svg>")
    return "\n".join(out) + "\n"


def _terminal_nodes(circuit: Circuit) -> Dict[Tuple[int, int], int]:
    """用并查集把端点连成电气节点，返回 {端点: 节点编号}。"""
    parent: Dict[Tuple[int, int], Tuple[int, int]] = {}

    def find(node):
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for part in circuit.parts.values():
        for terminal in (0, 1):
            find((part.uid, terminal))
    for a, b in circuit.wires:
        union(a, b)

    numbering: Dict[Tuple[int, int], int] = {}
    result: Dict[Tuple[int, int], int] = {}
    for part in circuit.parts.values():
        for terminal in (0, 1):
            root = find((part.uid, terminal))
            if root not in numbering:
                numbering[root] = len(numbering) + 1
            result[(part.uid, terminal)] = numbering[root]
    return result


def build_netlist(circuit: Circuit) -> str:
    """生成文字网表：每个元件接在哪两个节点之间、导线是否被剪断。"""
    nodes = _terminal_nodes(circuit)
    lines: List[str] = []
    lines.append("电路网表 · Circuit Lab")
    lines.append(f"元件 {len(circuit.parts)} 个，导线 {len(circuit.wires)} 根，剪断 {circuit.broken_count()} 根")
    lines.append("")
    lines.append("节点：")
    groups: Dict[int, List[str]] = {}
    for (uid, terminal), node in nodes.items():
        part = circuit.parts.get(uid)
        if part is None:
            continue
        groups.setdefault(node, []).append(f"{PART_LABELS[part.kind]}#{uid}.{terminal}")
    for node in sorted(groups):
        lines.append(f"  N{node} = {', '.join(groups[node])}")
    lines.append("")
    lines.append("元件：")
    for part in circuit.parts.values():
        node_a = nodes.get((part.uid, 0), 0)
        node_b = nodes.get((part.uid, 1), 0)
        value = part_value_text(part)
        state = ""
        if part.state == DAMAGE_EXPLODED:
            state = " · 已爆炸（断路）"
        elif part.state == DAMAGE_CUT:
            state = " · 被剪断（断路）"
        elif part.state == "burned":
            state = " · 已烧毁（断路）"
        lines.append(
            f"  {PART_LABELS[part.kind]} #{part.uid}  {value}  N{node_a} - N{node_b}{state}"
        )
    lines.append("")
    lines.append("导线：")
    wire_nodes: Dict[int, List[str]] = {}
    for index, (a, b) in enumerate(circuit.wires):
        node = nodes.get(a, 0)
        tag = f"#{index}"
        if circuit.is_wire_broken(index):
            tag += "（已剪断）"
        wire_nodes.setdefault(node, []).append(tag)
    for node in sorted(wire_nodes):
        lines.append(f"  N{node}: {', '.join(wire_nodes[node])}")
    return "\n".join(lines) + "\n"
