"""circuit_core.py — 电路元件、导线与直流电路求解（纯 Python，无图形依赖）。

设计要点
========
1. 每个元件有两个端点（0/1）。电池的 0 号端是正极，1 号端是负极。
2. 导线和闭合开关用极小的电阻（1 mΩ）表示，这样每条导线、每个开关上
   流过的电流都能算出来，便于在界面上显示和做电流流动动画。
3. 求解采用节点电压法：
       i(a→b) = g * (Va - Vb - E)
   其中电池 g = 1/内阻、E = 电动势，相当于「内阻 + 诺顿电流源」，
   不需要额外引入电压源未知量，也不会出现纯理想电压源造成的奇异矩阵。
4. 每个电气连通块选一个节点接地（电位 = 0），再用部分主元高斯消元求解。
5. 电容用后向欧拉伴随模型参与瞬态求解：
       电容 ≈ 电阻 dt/C 与电压源 v_prev 串联
   即 g = C/dt、E = 上一次的电容电压。传入 dt 时电路逐帧演化（RC 充放电），
   不传 dt 时电容按直流稳态处理（相当于开路）。
6. 导线可以被「剪断」（broken）：剪断的导线不参与求解，等价于断路，
   用于模拟故障。元件也有状态：ok / burned（烧毁，断路）/ exploded（爆炸，断路）。
7. 所有量都带符号计算；显示时按需取绝对值。

这个模块可以被单元测试直接导入，不需要显示器或 pygame。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

WIRE_R = 1e-3            # 理想导线电阻，欧姆
SWITCH_CLOSED_R = 1e-3   # 闭合开关电阻，欧姆
MIN_RESISTANCE = 0.05    # 任何电阻元件的最小值，避免除零
DEFAULT_RATED_V = 6.0    # 灯泡额定电压
BULB_COLD_RATIO = 0.11   # 冷态电阻 / 热态电阻（钨丝冷态约为热态的 1/9）
BULB_THERMAL_TAU = 0.45  # 秒，灯丝热惯性时间常数
BULB_MAX_TEMP = 6.0      # 归一化温度上限（再高就该熔断了）
BULB_AMBIENT_K = 300.0   # 环境温度（K），只用于显示
BULB_HOT_K = 2800.0      # 额定状态下的灯丝温度（K），只用于显示

VOLTMETER_R = 1e6        # 电压表内阻（很大，几乎不分流）
AMMETER_R = 0.01         # 电流表内阻（很小，几乎不分压）
RHEOSTAT_MAX = 50.0      # 滑动变阻器最大阻值
RESISTOR_RATED_POWER = 0.5   # 普通电阻额定功率（全真模式会烧）
RHEOSTAT_RATED_POWER = 1.0   # 滑动变阻器额定功率
CAPACITY_DEFAULT = 0.01      # 电容默认容量 10 mF
CAPACITOR_RATED_V = 16.0     # 电容默认耐压

DAMAGE_OK = "ok"
DAMAGE_BURNED = "burned"
DAMAGE_EXPLODED = "exploded"
DAMAGE_CUT = "cut"       # 被剪刀剪断（断路，但没有烧毁痕迹）

PART_ORDER = (
    "battery",
    "resistor",
    "bulb",
    "switch",
    "rheostat",
    "voltmeter",
    "ammeter",
    "capacitor",
)
PART_LABELS = {
    "battery": "电池",
    "resistor": "电阻",
    "bulb": "灯泡",
    "switch": "开关",
    "rheostat": "滑动变阻器",
    "voltmeter": "电压表",
    "ammeter": "电流表",
    "capacitor": "电容",
}
PART_UNITS = {
    "battery": "V",
    "resistor": "Ω",
    "bulb": "Ω",
    "switch": "",
    "rheostat": "Ω",
    "voltmeter": "Ω",
    "ammeter": "Ω",
    "capacitor": "F",
}

PART_DEFAULTS = {
    "battery": dict(value=6.0, r_internal=0.5),
    "resistor": dict(value=10.0),
    "bulb": dict(value=12.0, rated_v=DEFAULT_RATED_V),
    "switch": dict(closed=True),
    "rheostat": dict(value=10.0),
    "voltmeter": dict(value=VOLTMETER_R),
    "ammeter": dict(value=AMMETER_R),
    "capacitor": dict(value=CAPACITY_DEFAULT, rated_v=CAPACITOR_RATED_V),
}

Endpoint = Tuple[int, int]          # (元件 uid, 端点编号 0/1)
Wire = Tuple[Endpoint, Endpoint]    # 一根导线连接的两个端点（内部按规范顺序存储）


# ---------------------------------------------------------------------------
# 单位格式化
# ---------------------------------------------------------------------------

def fmt_number(value: float, digits: int = 3) -> str:
    """用 3 位有效数字格式化，尽量短（6.0 → '6'，0.2666 → '0.267'）。"""
    if value is None:
        return "—"
    if isinstance(value, float) and math.isinf(value):
        return "∞"
    if abs(value) < 1e-15:
        return "0"
    return f"{value:.{digits}g}"


def fmt_si(value: Optional[float], unit: str = "", none: str = "—") -> str:
    """带 SI 前缀的格式化：6.0V → '6V'，0.0048A → '4.8mA'，1500Ω → '1.5kΩ'。"""
    if value is None:
        return none
    if isinstance(value, float) and math.isinf(value):
        return "∞" + unit
    a = abs(value)
    if a < 1e-12:
        return "0" + unit
    if a >= 1e6:
        return fmt_number(value / 1e6) + "M" + unit
    if a >= 1e3:
        return fmt_number(value / 1e3) + "k" + unit
    if a >= 1e-2:
        return fmt_number(value) + unit
    if a >= 1e-5:
        return fmt_number(value / 1e-3) + "m" + unit
    return fmt_number(value / 1e-6) + "µ" + unit


def fmt_voltage(value: Optional[float]) -> str:
    return fmt_si(value, "V")


def fmt_current(value: Optional[float]) -> str:
    return fmt_si(value, "A")


def fmt_resistance(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and math.isinf(value):
        return "∞Ω"
    return fmt_si(value, "Ω")


def fmt_power(value: Optional[float]) -> str:
    return fmt_si(value, "W")


def fmt_capacitance(value: Optional[float]) -> str:
    return fmt_si(value, "F")


# ---------------------------------------------------------------------------
# 元件
# ---------------------------------------------------------------------------

@dataclass
class Part:
    """一个两端元件。

    value：电池 = 电动势(V)；电阻/灯泡/滑动变阻器 = 阻值(Ω)；
           电容 = 容量(F)；电压表/电流表 = 内阻(Ω)。
    """

    uid: int
    kind: str
    value: float = 1.0
    r_internal: float = 0.5     # 仅电池
    closed: bool = True         # 仅开关
    rated_v: float = DEFAULT_RATED_V  # 灯泡额定电压 / 电容耐压

    # 全真模式下的损坏状态
    state: str = DAMAGE_OK      # ok / burned / exploded / cut
    heat: float = 0.0           # 0..1，累积到 1 就损坏

    # 灯泡灯丝温度（归一化：0 = 常温，1 = 额定工作温度）
    temp: float = 0.0

    # 下面三个量由 Circuit.solve() 写入
    u: float = 0.0              # 端电压 Va - Vb（伏）
    i: float = 0.0              # 从 a 端流向 b 端的电流（安）
    p: float = 0.0              # 吸收的电功率 u*i（瓦）

    # -- 派生属性 ----------------------------------------------------------
    @property
    def label(self) -> str:
        return PART_LABELS.get(self.kind, self.kind)

    @property
    def damaged(self) -> bool:
        return self.state != DAMAGE_OK

    @property
    def rated_power(self) -> float:
        if self.kind == "bulb":
            return self.rated_v ** 2 / max(self.value, MIN_RESISTANCE)
        if self.kind == "resistor":
            return RESISTOR_RATED_POWER
        if self.kind == "rheostat":
            return RHEOSTAT_RATED_POWER
        return 0.0

    @property
    def stress(self) -> float:
        """0..1+ 的负载率：实际功率 / 额定功率（没有额定功率的元件返回 0）。"""
        rated = self.rated_power
        if rated <= 0:
            return 0.0
        return abs(self.p) / rated

    @property
    def hot_resistance(self) -> float:
        """灯泡额定工作温度下的灯丝电阻（也就是面板里调的那个 R）。"""
        return max(self.value, MIN_RESISTANCE)

    @property
    def cold_resistance(self) -> float:
        """灯泡冷态电阻：钨丝冷态约为热态的 1/9，所以开灯瞬间电流会大很多。"""
        if self.kind != "bulb":
            return self.hot_resistance
        return max(self.hot_resistance * BULB_COLD_RATIO, MIN_RESISTANCE)

    @property
    def resistance(self) -> float:
        """当前实际电阻：灯泡随灯丝温度升高而变大。"""
        if self.kind == "battery":
            return max(self.r_internal, 1e-4)
        if self.kind == "switch":
            return 0.0 if self.closed else math.inf
        if self.kind == "capacitor":
            return math.inf
        if self.kind == "bulb":
            ratio = BULB_COLD_RATIO + (1.0 - BULB_COLD_RATIO) * max(self.temp, 0.0)
            return max(self.value * ratio, MIN_RESISTANCE)
        return max(self.value, MIN_RESISTANCE)

    @property
    def filament_k(self) -> float:
        """灯丝温度（开尔文），只用于显示。"""
        return BULB_AMBIENT_K + (BULB_HOT_K - BULB_AMBIENT_K) * max(self.temp, 0.0)

    @property
    def brightness(self) -> float:
        """灯泡亮度 0..1：白炽灯是热的，亮度跟灯丝温度走（冷态不亮）。"""
        if self.kind != "bulb" or self.damaged or self.rated_power <= 0:
            return 0.0
        return max(0.0, min(1.0, self.temp))

    @property
    def overloaded(self) -> bool:
        return (
            self.kind == "bulb"
            and not self.damaged
            and self.rated_power > 0
            and abs(self.p) > 1.2 * self.rated_power
        )

    # -- 对求解器暴露的导纳 ------------------------------------------------
    def branch(self, dt: Optional[float], v_prev: float) -> Optional[Tuple[float, float]]:
        """返回 (电导 g, 等效电动势 E)；None 表示开路。"""
        if self.damaged:
            return None
        if self.kind == "battery":
            return 1.0 / max(self.r_internal, 1e-4), self.value
        if self.kind in ("resistor", "bulb", "rheostat"):
            return 1.0 / self.resistance, 0.0
        if self.kind == "switch":
            return (1.0 / SWITCH_CLOSED_R, 0.0) if self.closed else None
        if self.kind == "voltmeter":
            return 1.0 / VOLTMETER_R, 0.0
        if self.kind == "ammeter":
            return 1.0 / AMMETER_R, 0.0
        if self.kind == "capacitor":
            if dt is None:
                return None
            capacitance = max(self.value, 1e-9)
            return capacitance / dt, v_prev
        return None

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "kind": self.kind,
            "value": self.value,
            "r_internal": self.r_internal,
            "closed": self.closed,
            "rated_v": self.rated_v,
            "state": self.state,
            "heat": self.heat,
            "temp": self.temp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Part":
        return cls(
            uid=int(data["uid"]),
            kind=str(data["kind"]),
            value=float(data.get("value", 1.0)),
            r_internal=float(data.get("r_internal", 0.5)),
            closed=bool(data.get("closed", True)),
            rated_v=float(data.get("rated_v", DEFAULT_RATED_V)),
            state=str(data.get("state", DAMAGE_OK)),
            heat=float(data.get("heat", 0.0)),
            temp=float(data.get("temp", 0.0)),
        )


@dataclass
class Solution:
    """一次求解的结果摘要。"""

    ok: bool = True
    error: str = ""
    warnings: List[str] = field(default_factory=list)
    wire_currents: List[float] = field(default_factory=list)
    total_power: float = 0.0       # 所有电阻/灯泡/导线消耗的功率之和
    battery_current: float = 0.0   # 电池电流绝对值之和
    node_voltages: Dict[Tuple[int, int], float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 电路
# ---------------------------------------------------------------------------

def _norm_wire(a: Endpoint, b: Endpoint) -> Wire:
    return (a, b) if a <= b else (b, a)


class Circuit:
    """元件 + 导线的集合，可以求解、存档、读档。"""

    def __init__(self) -> None:
        self.parts: Dict[int, Part] = {}
        self.wires: List[Wire] = []       # 规范化的端点对
        self.broken: set = set()          # 被剪断的导线（规范化端点对，仍在 wires 里）
        self._next_uid = 1
        self.last_solution: Optional[Solution] = None

    # -- 元件 --------------------------------------------------------------
    def add_part(self, kind: str, **params) -> Part:
        if kind not in PART_LABELS:
            raise ValueError(f"未知元件类型: {kind!r}")
        defaults = dict(PART_DEFAULTS[kind])
        defaults.update(params)
        part = Part(uid=self._next_uid, kind=kind, **defaults)
        self._next_uid += 1
        self.parts[part.uid] = part
        return part

    def remove_part(self, uid: int) -> bool:
        if uid not in self.parts:
            return False
        del self.parts[uid]
        keep = []
        for pair in self.wires:
            if pair[0][0] == uid or pair[1][0] == uid:
                self.broken.discard(pair)
            else:
                keep.append(pair)
        self.wires = keep
        return True

    def get_part(self, uid: int) -> Optional[Part]:
        return self.parts.get(uid)

    def repair_all(self) -> int:
        """修好所有损坏的元件和剪断的导线，返回处理过的数量。"""
        count = 0
        for part in self.parts.values():
            if part.damaged or part.heat:
                part.state = DAMAGE_OK
                part.heat = 0.0
                count += 1
        count += len(self.broken)
        self.broken.clear()
        return count

    def replace_part(self, uid: int) -> bool:
        """更换一个损坏的元件（恢复成额定状态，参数保留）。"""
        part = self.parts.get(uid)
        if part is None:
            return False
        part.state = DAMAGE_OK
        part.heat = 0.0
        return True

    # -- 导线 --------------------------------------------------------------
    def has_wire(self, a: Endpoint, b: Endpoint) -> bool:
        pair = _norm_wire(a, b)
        return pair in self.wires

    def add_wire(self, a: Endpoint, b: Endpoint) -> bool:
        """连接两个端点。同一端点自身、重复导线会被拒绝。

        注意：允许把同一个零件的两端连起来（相当于用导线短路该零件），
        电池被短接时 solve() 会在 warnings 里给出短路提示，这是教学场景。
        """
        if a == b:
            return False
        if a[0] not in self.parts or b[0] not in self.parts:
            return False
        if a[1] not in (0, 1) or b[1] not in (0, 1):
            return False
        pair = _norm_wire(a, b)
        if pair in self.wires:
            return False
        self.wires.append(pair)
        return True

    def remove_wire(self, index: int) -> bool:
        if 0 <= index < len(self.wires):
            pair = self.wires.pop(index)
            self.broken.discard(pair)
            return True
        return False

    def remove_wire_between(self, a: Endpoint, b: Endpoint) -> bool:
        pair = _norm_wire(a, b)
        if pair in self.wires:
            self.wires.remove(pair)
            self.broken.discard(pair)
            return True
        return False

    def is_wire_broken(self, index: int) -> bool:
        if not (0 <= index < len(self.wires)):
            return False
        return self.wires[index] in self.broken

    def cut_wire(self, index: int) -> bool:
        """剪断一根导线（保留在画布上，但电路上变成断路）。"""
        if not (0 <= index < len(self.wires)):
            return False
        pair = self.wires[index]
        if pair in self.broken:
            return False
        self.broken.add(pair)
        return True

    def repair_wire(self, index: int) -> bool:
        if not (0 <= index < len(self.wires)):
            return False
        pair = self.wires[index]
        if pair not in self.broken:
            return False
        self.broken.discard(pair)
        return True

    def broken_count(self) -> int:
        return sum(1 for pair in self.wires if pair in self.broken)

    def wire_links(self, uid: int) -> int:
        """该元件连出的导线数量。"""
        return sum(1 for a, b in self.wires if a[0] == uid or b[0] == uid)

    def clear(self) -> None:
        self.parts.clear()
        self.wires.clear()
        self.broken.clear()
        self._next_uid = 1
        self.last_solution = None

    # -- 求解 --------------------------------------------------------------
    def _element_list(self, dt: Optional[float], previous: Dict[int, float]):
        """返回 (端点 → 节点编号映射, [(na, nb, g, E, tag), ...])。"""
        node_of: Dict[Endpoint, int] = {}
        for uid in self.parts:
            node_of[(uid, 0)] = len(node_of)
            node_of[(uid, 1)] = len(node_of)

        elements = []
        for part in self.parts.values():
            branch = part.branch(dt, previous.get(part.uid, 0.0))
            if branch is None:
                continue
            g, emf = branch
            elements.append(
                (
                    node_of[(part.uid, 0)],
                    node_of[(part.uid, 1)],
                    g,
                    emf,
                    ("part", part.uid),
                )
            )
        for index, ((ua, ta), (ub, tb)) in enumerate(self.wires):
            if self.wires[index] in self.broken:
                continue
            elements.append(
                (node_of[(ua, ta)], node_of[(ub, tb)], 1.0 / WIRE_R, 0.0, ("wire", index))
            )
        return node_of, elements

    def solve(self, dt: Optional[float] = None) -> Solution:
        """求解整个电路，把结果写入每个 Part，并返回 Solution。

        dt=None：直流稳态（电容视为开路，灯泡灯丝温度迭代到热平衡）。
        dt=秒数：瞬态推进一帧（电容后向欧拉，灯泡灯丝按热惯性升温 / 降温）。
        """
        bulbs = [
            part
            for part in self.parts.values()
            if part.kind == "bulb" and not part.damaged and part.rated_power > 0
        ]
        if dt is None:
            solution = self._solve_once(None)
            if not bulbs or not solution.ok:
                return solution
            for _ in range(60):
                delta = 0.0
                for bulb in bulbs:
                    target = min(BULB_MAX_TEMP, max(0.0, abs(bulb.p) / bulb.rated_power))
                    new_temp = bulb.temp + 0.35 * (target - bulb.temp)
                    delta = max(delta, abs(new_temp - bulb.temp))
                    bulb.temp = new_temp
                solution = self._solve_once(None)
                if not solution.ok or delta < 1e-4:
                    break
            return solution

        solution = self._solve_once(dt)
        if not solution.ok:
            return solution
        for bulb in bulbs:
            rated = bulb.rated_power
            heating = abs(bulb.p) - rated * bulb.temp
            step = heating / max(rated * BULB_THERMAL_TAU, 1e-9)
            bulb.temp = min(BULB_MAX_TEMP, max(0.0, bulb.temp + dt * step))
        return solution

    def _solve_once(self, dt: Optional[float] = None) -> Solution:
        """解一次线性电路（灯泡电阻用当前灯丝温度，不做温度迭代）。"""
        previous = {
            part.uid: part.u for part in self.parts.values() if part.kind == "capacitor"
        }
        for part in self.parts.values():
            part.u = part.i = part.p = 0.0

        sol = Solution()
        node_of, elements = self._element_list(dt, previous)
        n_nodes = len(node_of)
        sol.wire_currents = [0.0] * len(self.wires)
        if n_nodes == 0:
            self.last_solution = sol
            return sol

        # 电气连通块（只考虑有电导的支路）
        adj: List[List[int]] = [[] for _ in range(n_nodes)]
        for na, nb, _g, _e, _tag in elements:
            adj[na].append(nb)
            adj[nb].append(na)

        seen = [False] * n_nodes
        voltages = [0.0] * n_nodes

        for start in range(n_nodes):
            if seen[start] or not adj[start]:
                seen[start] = True
                continue
            stack = [start]
            seen[start] = True
            comp: List[int] = []
            while stack:
                node = stack.pop()
                comp.append(node)
                for other in adj[node]:
                    if not seen[other]:
                        seen[other] = True
                        stack.append(other)
            if len(comp) < 2:
                continue
            ground = comp[0]
            local = {node: i for i, node in enumerate(n for n in comp if n != ground)}
            size = len(local)
            matrix = [[0.0] * size for _ in range(size)]
            rhs = [0.0] * size

            def stamp(na: int, nb: int, g: float, emf: float) -> None:
                ra = local.get(na)
                rb = local.get(nb)
                if ra is not None:
                    matrix[ra][ra] += g
                    rhs[ra] += g * emf
                if rb is not None:
                    matrix[rb][rb] += g
                    rhs[rb] -= g * emf
                if ra is not None and rb is not None:
                    matrix[ra][rb] -= g
                    matrix[rb][ra] -= g

            for na, nb, g, emf, _tag in elements:
                if na in local or nb in local:
                    stamp(na, nb, g, emf)

            root = _gaussian_solve(matrix, rhs)
            if root is None:
                sol.ok = False
                sol.error = "电路无法求解（存在互相冲突的理想电源）"
                for part in self.parts.values():
                    part.u = part.i = part.p = 0.0
                self.last_solution = sol
                return sol

            for node, index in local.items():
                voltages[node] = root[index]

        # 各支路电流
        parts_with_element = set()
        for na, nb, g, emf, tag in elements:
            current = g * (voltages[na] - voltages[nb] - emf)
            kind, key = tag
            if kind == "part":
                part = self.parts.get(key)
                if part is not None:
                    parts_with_element.add(key)
                    part.u = voltages[na] - voltages[nb]
                    part.i = current
                    part.p = part.u * part.i
            else:
                sol.wire_currents[key] = current

        # 没有参与求解的元件（断开的开关、电容（直流）、损坏的元件）也要显示端电压
        for part in self.parts.values():
            if part.uid not in parts_with_element:
                part.u = voltages[node_of[(part.uid, 0)]] - voltages[node_of[(part.uid, 1)]]
                part.i = 0.0
                part.p = 0.0

        # 汇总
        sol.node_voltages = {endpoint: voltages[node] for endpoint, node in node_of.items()}
        sol.total_power = sum(
            part.p
            for part in self.parts.values()
            if part.p > 0 and part.kind in ("resistor", "bulb", "rheostat", "capacitor")
        ) + sum(WIRE_R * current * current for current in sol.wire_currents)
        batteries = [p for p in self.parts.values() if p.kind == "battery"]
        sol.battery_current = sum(abs(p.i) for p in batteries)
        sol.warnings = self._collect_warnings(sol, batteries)
        self.last_solution = sol
        return sol

    def _collect_warnings(self, sol: Solution, batteries: Sequence[Part]) -> List[str]:
        warnings: List[str] = []
        if not self.parts:
            warnings.append("画布是空的：从左边拖一个电池出来试试")
            return warnings
        if not batteries:
            warnings.append("没有电源：放一个电池试试")
            return warnings

        active_batteries = [p for p in batteries if not p.damaged]
        if not active_batteries:
            warnings.append("电池已经报废了，换一节新的吧")
            return warnings

        shorted = any(
            abs(p.i) > max(3.0, 0.75 * p.value / max(p.r_internal, 1e-4))
            for p in active_batteries
        )
        if shorted:
            warnings.append("短路！电池电流过大")

        if all(abs(p.i) < 1e-6 for p in active_batteries):
            charged = any(
                p.kind == "capacitor" and abs(p.u) > 0.05 for p in self.parts.values()
            )
            if charged:
                warnings.append("电容已充满：直流稳态下不再有电流")
            else:
                warnings.append("电路未闭合：检查开关和导线")

        for part in self.parts.values():
            if part.kind == "bulb" and part.overloaded:
                warnings.append(f"灯泡 #{part.uid} 过载，小心烧坏")
            if part.kind == "capacitor" and abs(part.u) > part.rated_v * 0.95:
                warnings.append(f"电容 #{part.uid} 过压，可能爆裂")
            if part.kind == "ammeter" and abs(part.i) > 3.0:
                warnings.append(f"电流表 #{part.uid} 过流，小心烧表")
            if part.state == DAMAGE_BURNED:
                warnings.append(f"{part.label} #{part.uid} 已烧毁")
            elif part.state == DAMAGE_EXPLODED:
                warnings.append(f"{part.label} #{part.uid} 已爆炸")
            elif part.state == DAMAGE_CUT:
                warnings.append(f"{part.label} #{part.uid} 被剪断（断路）")
        broken = self.broken_count()
        if broken:
            warnings.append(f"有 {broken} 根导线被剪断（断路）")
        return warnings

    # -- 存档 --------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "next_uid": self._next_uid,
            "parts": [p.to_dict() for p in self.parts.values()],
            "wires": [[list(a), list(b)] for a, b in self.wires],
            "broken": [[list(a), list(b)] for a, b in self.broken],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Circuit":
        circuit = cls()
        for raw in data.get("parts", []):
            part = Part.from_dict(raw)
            circuit.parts[part.uid] = part
        for raw_a, raw_b in data.get("wires", []):
            a = (int(raw_a[0]), int(raw_a[1]))
            b = (int(raw_b[0]), int(raw_b[1]))
            if a[0] in circuit.parts and b[0] in circuit.parts and a != b:
                circuit.wires.append(_norm_wire(a, b))
        for raw_a, raw_b in data.get("broken", []):
            a = (int(raw_a[0]), int(raw_a[1]))
            b = (int(raw_b[0]), int(raw_b[1]))
            pair = _norm_wire(a, b)
            if pair in circuit.wires:
                circuit.broken.add(pair)
        circuit._next_uid = int(
            data.get("next_uid", max((p.uid for p in circuit.parts.values()), default=0) + 1)
        )
        return circuit

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Circuit":
        return cls.from_dict(json.loads(text))


# ---------------------------------------------------------------------------
# 线性方程组：部分主元高斯消元
# ---------------------------------------------------------------------------

def _gaussian_solve(matrix: List[List[float]], rhs: List[float]) -> Optional[List[float]]:
    """就地求解 A x = b；矩阵奇异时返回 None。"""
    n = len(rhs)
    if n == 0:
        return []
    a = [row[:] for row in matrix]
    b = rhs[:]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        if pivot != col:
            a[col], a[pivot] = a[pivot], a[col]
            b[col], b[pivot] = b[pivot], b[col]
        pivot_value = a[col][col]
        for row in range(col + 1, n):
            factor = a[row][col] / pivot_value
            if factor == 0.0:
                continue
            a[row][col] = 0.0
            for k in range(col + 1, n):
                a[row][k] -= factor * a[col][k]
            b[row] -= factor * b[col]
    x = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = b[row]
        for k in range(row + 1, n):
            total -= a[row][k] * x[k]
        x[row] = total / a[row][row]
    return x
