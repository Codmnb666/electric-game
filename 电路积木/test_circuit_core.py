"""test_circuit_core.py — 电路内核（circuit_core.py）的单元测试。

运行：
    python -m unittest test_circuit_core -v
或：
    python test_circuit_core.py
"""

from __future__ import annotations

import json
import math
import unittest

from circuit_core import ( BULB_COLD_RATIO,
    AMMETER_R,
    DAMAGE_BURNED,
    DAMAGE_CUT,
    DAMAGE_EXPLODED,
    DAMAGE_OK,
    MIN_RESISTANCE,
    PART_DEFAULTS,
    RHEOSTAT_MAX,
    RHEOSTAT_RATED_POWER,
    SWITCH_CLOSED_R,
    WIRE_R,
    Circuit,
    Part,
    Solution,
    fmt_current,
    fmt_power,
    fmt_resistance,
    fmt_si,
    fmt_voltage,
)


def build_series() -> Circuit:
    """6V 电池(内阻 0.5Ω) + 两个 10Ω 电阻串联成回路。"""
    circuit = Circuit()
    battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
    r1 = circuit.add_part("resistor", value=10.0)
    r2 = circuit.add_part("resistor", value=10.0)
    assert circuit.add_wire((battery.uid, 1), (r1.uid, 0))
    assert circuit.add_wire((r1.uid, 1), (r2.uid, 0))
    assert circuit.add_wire((r2.uid, 1), (battery.uid, 0))
    return circuit


def build_parallel() -> Circuit:
    """6V 电池(内阻 0.5Ω) + 两只 12Ω 灯泡并联。"""
    circuit = Circuit()
    battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
    bulb1 = circuit.add_part("bulb", value=12.0, rated_v=6.0)
    bulb2 = circuit.add_part("bulb", value=12.0, rated_v=6.0)
    circuit.add_wire((battery.uid, 1), (bulb1.uid, 0))
    circuit.add_wire((battery.uid, 1), (bulb2.uid, 0))
    circuit.add_wire((bulb1.uid, 1), (battery.uid, 0))
    circuit.add_wire((bulb2.uid, 1), (battery.uid, 0))
    return circuit


class TestSeries(unittest.TestCase):
    def setUp(self) -> None:
        self.circuit = build_series()
        self.solution = self.circuit.solve()

    def test_solution_ok(self) -> None:
        self.assertTrue(self.solution.ok)
        self.assertEqual(self.solution.error, "")
        self.assertEqual(len(self.solution.wire_currents), 3)

    def test_current(self) -> None:
        # I = E / (r + R1 + R2 + 3 根导线的电阻)，导线电阻 1mΩ 不可忽略
        expected = 6.0 / (0.5 + 20.0 + 3 * WIRE_R)
        battery = self.circuit.parts[1]
        r1 = self.circuit.parts[2]
        self.assertAlmostEqual(abs(battery.i), expected, places=6)
        self.assertAlmostEqual(abs(r1.i), expected, places=6)
        self.assertAlmostEqual(abs(r1.u), expected * 10.0, places=6)

    def test_battery_terminal_voltage(self) -> None:
        battery = self.circuit.parts[1]
        # 端电压 U = E - I·r
        self.assertAlmostEqual(
            abs(battery.u), 6.0 - abs(battery.i) * 0.5, places=6
        )
        self.assertGreater(abs(battery.u), 5.0)

    def test_power_balance(self) -> None:
        battery = self.circuit.parts[1]
        supplied = abs(battery.u * battery.i)
        consumed = sum(
            abs(p.p) for p in self.circuit.parts.values() if p.kind in ("resistor", "bulb")
        )
        wire_loss = sum(WIRE_R * current * current for current in self.solution.wire_currents)
        self.assertAlmostEqual(supplied, self.solution.total_power, places=6)
        self.assertAlmostEqual(self.solution.total_power, consumed + wire_loss, places=6)

    def test_each_resistor_power(self) -> None:
        current = 6.0 / (0.5 + 20.0 + 3 * WIRE_R)
        expected = current * current * 10.0
        for uid in (2, 3):
            self.assertAlmostEqual(abs(self.circuit.parts[uid].p), expected, places=6)


class TestParallel(unittest.TestCase):
    def setUp(self) -> None:
        self.circuit = build_parallel()
        self.solution = self.circuit.solve()

    def test_total_current(self) -> None:
        # 灯泡是热惯性元件：稳态时灯丝温度由 P = 额定功率 × 温度 决定，
        # 所以总电流要看最终热态电阻，而不是固定的 12Ω。
        bulb = self.circuit.parts[2]
        self.assertGreater(bulb.temp, 0.8)
        self.assertAlmostEqual(abs(bulb.p), bulb.rated_power * bulb.temp, delta=0.02)
        expected = 6.0 / (0.5 + (bulb.resistance + 2 * WIRE_R) / 2.0)
        self.assertAlmostEqual(self.solution.battery_current, expected, places=6)

    def test_bulbs_share_current(self) -> None:
        bulb1 = self.circuit.parts[2]
        bulb2 = self.circuit.parts[3]
        self.assertAlmostEqual(abs(bulb1.i), abs(bulb2.i), places=6)
        self.assertAlmostEqual(
            abs(bulb1.i), self.solution.battery_current / 2.0, places=6
        )
        self.assertAlmostEqual(abs(bulb1.p), abs(bulb2.p), places=6)

    def test_bulb_brightness(self) -> None:
        bulb = self.circuit.parts[2]
        self.assertAlmostEqual(bulb.rated_power, 3.0, places=6)
        self.assertGreater(bulb.brightness, 0.7)
        self.assertLessEqual(bulb.brightness, 1.0)
        self.assertFalse(bulb.overloaded)


class TestOpenSwitch(unittest.TestCase):
    def setUp(self) -> None:
        self.circuit = Circuit()
        self.battery = self.circuit.add_part("battery", value=6.0, r_internal=0.5)
        self.switch = self.circuit.add_part("switch", closed=False)
        self.resistor = self.circuit.add_part("resistor", value=10.0)
        self.circuit.add_wire((self.battery.uid, 1), (self.switch.uid, 0))
        self.circuit.add_wire((self.switch.uid, 1), (self.resistor.uid, 0))
        self.circuit.add_wire((self.resistor.uid, 1), (self.battery.uid, 0))
        self.solution = self.circuit.solve()

    def test_no_current(self) -> None:
        self.assertAlmostEqual(abs(self.battery.i), 0.0, places=9)
        self.assertAlmostEqual(abs(self.resistor.i), 0.0, places=9)

    def test_open_switch_holds_full_voltage(self) -> None:
        # 断开开关承担全部电动势
        self.assertAlmostEqual(abs(self.switch.u), 6.0, places=6)
        self.assertEqual(self.switch.i, 0.0)

    def test_warning(self) -> None:
        self.assertTrue(any("未闭合" in w for w in self.solution.warnings))

    def test_warning_disappears_when_closed(self) -> None:
        self.switch.closed = True
        solution = self.circuit.solve()
        self.assertGreater(abs(self.battery.i), 0.1)
        self.assertFalse(any("未闭合" in w for w in solution.warnings))


class TestShortCircuit(unittest.TestCase):
    def test_wire_across_battery(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
        circuit.add_wire((battery.uid, 0), (battery.uid, 1))
        solution = circuit.solve()
        self.assertTrue(solution.ok, solution.error)
        self.assertGreater(abs(battery.i), 3.0)
        self.assertTrue(any("短路" in w for w in solution.warnings))

    def test_remove_short_clears_warning(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
        circuit.add_wire((battery.uid, 0), (battery.uid, 1))
        circuit.solve()
        circuit.remove_wire(0)
        solution = circuit.solve()
        self.assertFalse(any("短路" in w for w in solution.warnings))


class TestMiscCircuit(unittest.TestCase):
    def test_no_battery_warning(self) -> None:
        circuit = Circuit()
        resistor = circuit.add_part("resistor", value=10.0)
        circuit.solve()
        self.assertEqual(resistor.u, 0.0)
        self.assertTrue(any("没有电源" in w for w in circuit.last_solution.warnings))

    def test_empty_circuit(self) -> None:
        circuit = Circuit()
        solution = circuit.solve()
        self.assertTrue(solution.ok)
        self.assertEqual(solution.wire_currents, [])
        self.assertEqual(solution.warnings, [])

    def test_duplicate_wire_rejected(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery")
        resistor = circuit.add_part("resistor")
        self.assertTrue(circuit.add_wire((battery.uid, 1), (resistor.uid, 0)))
        self.assertFalse(circuit.add_wire((resistor.uid, 0), (battery.uid, 1)))
        self.assertEqual(len(circuit.wires), 1)

    def test_self_loop_rejected(self) -> None:
        circuit = Circuit()
        resistor = circuit.add_part("resistor")
        self.assertFalse(circuit.add_wire((resistor.uid, 0), (resistor.uid, 0)))
        self.assertEqual(len(circuit.wires), 0)

    def test_part_bypass_allowed(self) -> None:
        # 用导线短接零件本身是合法的（灯泡被短接后不亮）
        circuit = Circuit()
        battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
        bulb = circuit.add_part("bulb", value=12.0)
        circuit.add_wire((battery.uid, 0), (bulb.uid, 0))
        circuit.add_wire((battery.uid, 1), (bulb.uid, 1))
        self.assertTrue(circuit.add_wire((bulb.uid, 0), (bulb.uid, 1)))
        solution = circuit.solve()
        self.assertTrue(solution.ok)
        # 灯泡被 1mΩ 导线旁路，只剩极小的漏电流
        self.assertLess(bulb.p, 1e-3)
        self.assertLess(bulb.brightness, 0.001)

    def test_wire_to_missing_part_rejected(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery")
        self.assertFalse(circuit.add_wire((battery.uid, 1), (999, 0)))

    def test_remove_part_removes_wires(self) -> None:
        circuit = build_series()
        self.assertEqual(len(circuit.wires), 3)
        # 删掉中间的电阻：只删除与它相连的两根线，剩下的线把电池和另一只电阻直接连起来
        circuit.remove_part(2)
        self.assertEqual(len(circuit.wires), 1)
        for a, b in circuit.wires:
            self.assertNotEqual(a[0], 2)
            self.assertNotEqual(b[0], 2)
        circuit.remove_part(2)  # 再删一次不应报错
        self.assertNotIn(2, circuit.parts)

    def test_unknown_kind(self) -> None:
        circuit = Circuit()
        with self.assertRaises(ValueError):
            circuit.add_part("motor")

    def test_defaults(self) -> None:
        circuit = Circuit()
        for kind, values in PART_DEFAULTS.items():
            part = circuit.add_part(kind)
            for key, value in values.items():
                self.assertEqual(getattr(part, key), value, f"{kind}.{key}")

    def test_part_resistance(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", r_internal=0.8)
        switch = circuit.add_part("switch", closed=True)
        resistor = circuit.add_part("resistor", value=47.0)
        bulb = circuit.add_part("bulb", value=12.0)
        self.assertAlmostEqual(battery.resistance, 0.8)
        self.assertAlmostEqual(switch.resistance, 0.0)
        self.assertAlmostEqual(resistor.resistance, 47.0)
        # 灯泡冷态电阻只有热态的 11%，通电升温后才到 12Ω
        self.assertAlmostEqual(bulb.resistance, 12.0 * 0.11)
        self.assertAlmostEqual(bulb.cold_resistance, 12.0 * 0.11)
        self.assertAlmostEqual(bulb.hot_resistance, 12.0)
        bulb.temp = 1.0
        self.assertAlmostEqual(bulb.resistance, 12.0)
        switch.closed = False
        self.assertTrue(math.isinf(switch.resistance))

    def test_min_resistance_clamp(self) -> None:
        circuit = Circuit()
        resistor = circuit.add_part("resistor", value=0.0)
        self.assertAlmostEqual(resistor.resistance, MIN_RESISTANCE)

    def test_overload(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", value=12.0, r_internal=0.01)
        bulb = circuit.add_part("bulb", value=12.0, rated_v=6.0)
        circuit.add_wire((battery.uid, 0), (bulb.uid, 0))
        circuit.add_wire((battery.uid, 1), (bulb.uid, 1))
        circuit.solve()
        self.assertTrue(bulb.overloaded)
        self.assertAlmostEqual(bulb.brightness, 1.0)
        self.assertTrue(any("过载" in w for w in circuit.last_solution.warnings))


class TestFormatting(unittest.TestCase):
    def test_si_prefixes(self) -> None:
        self.assertEqual(fmt_voltage(6.0), "6V")
        self.assertEqual(fmt_current(0.0048), "4.8mA")
        self.assertEqual(fmt_resistance(1500.0), "1.5kΩ")
        self.assertEqual(fmt_power(2.55), "2.55W")
        self.assertEqual(fmt_si(0.0, "A"), "0A")
        self.assertEqual(fmt_si(float("inf"), "V"), "∞V")
        self.assertEqual(fmt_si(None, "V"), "—")
        self.assertEqual(fmt_resistance(float("inf")), "∞Ω")
        self.assertEqual(fmt_resistance(None), "—")

    def test_three_significant_digits(self) -> None:
        self.assertEqual(fmt_voltage(5.5412), "5.54V")
        self.assertEqual(fmt_voltage(0.92345), "0.923V")


class TestPersistence(unittest.TestCase):
    def test_roundtrip(self) -> None:
        circuit = build_parallel()
        circuit.parts[1].r_internal = 0.7
        circuit.parts[2].value = 20.0
        circuit.parts[3].rated_v = 9.0
        text = circuit.to_json()
        clone = Circuit.from_json(text)

        self.assertEqual(len(clone.parts), len(circuit.parts))
        self.assertEqual(clone.wires, circuit.wires)
        self.assertEqual(clone.parts[2].value, 20.0)
        self.assertEqual(clone.parts[3].rated_v, 9.0)
        self.assertAlmostEqual(clone.parts[1].r_internal, 0.7)

        clone.solve()
        original = circuit.solve()
        self.assertAlmostEqual(clone.last_solution.battery_current, original.battery_current, places=9)

    def test_next_uid_continues(self) -> None:
        circuit = Circuit()
        circuit.add_part("resistor")
        circuit.add_part("resistor")
        clone = Circuit.from_json(circuit.to_json())
        new_part = clone.add_part("bulb")
        self.assertNotIn(new_part.uid, circuit.parts)
        self.assertEqual(new_part.uid, 3)

    def test_switch_state_saved(self) -> None:
        circuit = Circuit()
        switch = circuit.add_part("switch", closed=False)
        clone = Circuit.from_json(circuit.to_json())
        self.assertFalse(clone.parts[switch.uid].closed)

    def test_json_is_readable(self) -> None:
        circuit = build_series()
        data = json.loads(circuit.to_json())
        self.assertEqual(len(data["parts"]), 3)
        self.assertEqual(len(data["wires"]), 3)
        self.assertEqual(data["wires"][0], [[1, 1], [2, 0]])


class TestSolutionObject(unittest.TestCase):
    def test_defaults(self) -> None:
        solution = Solution()
        self.assertTrue(solution.ok)
        self.assertEqual(solution.warnings, [])
        self.assertEqual(solution.wire_currents, [])

    def test_last_solution_recorded(self) -> None:
        circuit = build_series()
        circuit.solve()
        self.assertIsInstance(circuit.last_solution, Solution)
        self.assertEqual(len(circuit.last_solution.node_voltages), 6)

    def test_part_defaults(self) -> None:
        part = Part(uid=7, kind="bulb")
        self.assertEqual(part.label, "灯泡")
        self.assertEqual(part.u, 0.0)
        self.assertEqual(part.brightness, 0.0)



# ---------------------------------------------------------------------------
# 新增元件：滑动变阻器 / 电压表 / 电流表 / 电容
# ---------------------------------------------------------------------------

def build_loop(kind: str, battery_v: float = 6.0, **params) -> "Circuit":
    """电池 + 开关 + 待测元件 的简单串联回路。"""
    circuit = Circuit()
    battery = circuit.add_part("battery", value=battery_v, r_internal=0.5)
    switch = circuit.add_part("switch")
    extra = circuit.add_part(kind, **params)
    circuit.add_wire((battery.uid, 1), (switch.uid, 0))
    circuit.add_wire((switch.uid, 1), (extra.uid, 0))
    circuit.add_wire((extra.uid, 1), (battery.uid, 0))
    circuit.solve()
    return circuit


class TestRheostat(unittest.TestCase):
    def test_inserted_resistance(self) -> None:
        circuit = build_loop("rheostat", value=10.0)
        solution = circuit.solve()
        self.assertTrue(solution.ok)
        # 6V / (0.5 + 10 + 3 根导线 * 1mΩ)
        expected = 6.0 / (0.5 + 10.0 + 3 * WIRE_R)
        rheostat = next(p for p in circuit.parts.values() if p.kind == "rheostat")
        self.assertAlmostEqual(abs(rheostat.i), expected, places=3)

    def test_minimum_and_maximum(self) -> None:
        circuit = build_loop("rheostat", value=RHEOSTAT_MAX)
        rheostat = next(p for p in circuit.parts.values() if p.kind == "rheostat")
        circuit.solve()
        low = abs(rheostat.i)
        self.assertAlmostEqual(rheostat.resistance, RHEOSTAT_MAX)
        rheostat.value = 1.0
        circuit.solve()
        self.assertGreater(abs(rheostat.i), low * 5)
        self.assertAlmostEqual(rheostat.resistance, 1.0)
        rheostat.value = 0.0
        self.assertGreaterEqual(rheostat.resistance, MIN_RESISTANCE)

    def test_rated_power(self) -> None:
        rheostat = Part(uid=1, kind="rheostat", value=5.0)
        self.assertAlmostEqual(rheostat.rated_power, RHEOSTAT_RATED_POWER)
        self.assertAlmostEqual(rheostat.stress, 0.0)


class TestMeters(unittest.TestCase):
    def test_voltmeter_reads_parallel_voltage(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery")
        resistor = circuit.add_part("resistor", value=10.0)
        voltmeter = circuit.add_part("voltmeter")
        circuit.add_wire((battery.uid, 1), (resistor.uid, 0))
        circuit.add_wire((resistor.uid, 1), (battery.uid, 0))
        circuit.add_wire((resistor.uid, 0), (voltmeter.uid, 0))
        circuit.add_wire((resistor.uid, 1), (voltmeter.uid, 1))
        circuit.solve()
        self.assertAlmostEqual(abs(voltmeter.u), abs(resistor.u), places=3)
        self.assertLess(abs(voltmeter.i), 1e-5)

    def test_ammeter_reads_series_current(self) -> None:
        circuit = build_loop("ammeter")
        solution = circuit.solve()
        self.assertTrue(solution.ok)
        ammeter = next(p for p in circuit.parts.values() if p.kind == "ammeter")
        # 串联回路电流由电池内阻决定（电流表几乎不分压）
        expected = 6.0 / (0.5 + AMMETER_R + 3 * WIRE_R + SWITCH_CLOSED_R)
        self.assertAlmostEqual(abs(ammeter.i), expected, places=3)
        self.assertLess(abs(ammeter.u), 0.2)

    def test_ammeter_overcurrent_warning(self) -> None:
        circuit = build_loop("ammeter", battery_v=6.0)
        ammeter = next(p for p in circuit.parts.values() if p.kind == "ammeter")
        ammeter.value = AMMETER_R
        circuit.solve()
        self.assertTrue(any("电流表" in w for w in circuit.last_solution.warnings))


class TestCapacitor(unittest.TestCase):
    def test_dc_blocks_current(self) -> None:
        circuit = build_loop("capacitor")
        capacitor = next(p for p in circuit.parts.values() if p.kind == "capacitor")
        # 直流稳态：电容开路，没有电流，端电压等于电源电动势
        self.assertAlmostEqual(capacitor.i, 0.0, places=6)
        self.assertAlmostEqual(abs(capacitor.u), 6.0, delta=0.05)

    def test_rc_charging_follows_tau(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
        switch = circuit.add_part("switch")
        resistor = circuit.add_part("resistor", value=100.0)
        capacitor = circuit.add_part("capacitor", value=0.01, rated_v=16.0)
        circuit.add_wire((battery.uid, 0), (switch.uid, 0))
        circuit.add_wire((switch.uid, 1), (resistor.uid, 0))
        circuit.add_wire((resistor.uid, 1), (capacitor.uid, 0))
        circuit.add_wire((capacitor.uid, 1), (battery.uid, 1))
        dt = 1.0 / 240.0
        steps = int(round(1.0 / dt))      # 1 秒 = 1 个时间常数
        for _ in range(steps):
            circuit.solve(dt)
        tau = (100.0 + 0.5 + 3 * WIRE_R) * 0.01
        expected = 6.0 * (1.0 - math.exp(-1.0 / tau))
        self.assertAlmostEqual(abs(capacitor.u), expected, delta=0.08)
        # 继续充到 5 个时间常数后基本充满
        for _ in range(steps * 5):
            circuit.solve(dt)
        self.assertGreater(abs(capacitor.u), 5.9)

    def test_overvoltage_warning(self) -> None:
        circuit = build_loop("capacitor", battery_v=24.0, rated_v=16.0)
        circuit.solve()
        self.assertTrue(any("过压" in w for w in circuit.last_solution.warnings))

    def test_energy_grows_while_charging(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery", value=6.0, r_internal=0.5)
        resistor = circuit.add_part("resistor", value=100.0)
        capacitor = circuit.add_part("capacitor", value=0.01, rated_v=16.0)
        circuit.add_wire((battery.uid, 0), (resistor.uid, 0))
        circuit.add_wire((resistor.uid, 1), (capacitor.uid, 0))
        circuit.add_wire((capacitor.uid, 1), (battery.uid, 1))
        circuit.solve(1.0 / 240.0)
        before = abs(capacitor.u)
        self.assertGreater(before, 0.0)
        for _ in range(60):
            circuit.solve(1.0 / 240.0)
        self.assertGreater(abs(capacitor.u), before)
        self.assertGreater(capacitor.p, 0.0)


# ---------------------------------------------------------------------------
# 剪断导线 / 元件损坏 / 检修
# ---------------------------------------------------------------------------

class TestCutWires(unittest.TestCase):
    def test_cut_makes_open_circuit(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        # 热平衡后电流由热态电阻决定
        self.assertTrue(0.3 < abs(bulb.i) < 0.7)
        before = abs(bulb.i)
        self.assertTrue(circuit.cut_wire(0))
        self.assertTrue(circuit.is_wire_broken(0))
        self.assertEqual(circuit.broken_count(), 1)
        solution = circuit.solve()
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertTrue(any("剪断" in w for w in solution.warnings))
        self.assertAlmostEqual(solution.wire_currents[0], 0.0, places=6)
        self.assertTrue(circuit.repair_wire(0))
        circuit.solve()
        self.assertAlmostEqual(abs(bulb.i), before, delta=0.01)

    def test_cut_twice_and_repair(self) -> None:
        circuit = build_loop("bulb")
        self.assertTrue(circuit.cut_wire(1))
        self.assertFalse(circuit.cut_wire(1))
        self.assertFalse(circuit.repair_wire(0))
        self.assertTrue(circuit.repair_wire(1))
        self.assertEqual(circuit.broken_count(), 0)

    def test_invalid_index(self) -> None:
        circuit = build_loop("bulb")
        self.assertFalse(circuit.cut_wire(99))
        self.assertFalse(circuit.repair_wire(-1))
        self.assertFalse(circuit.is_wire_broken(42))

    def test_remove_wire_clears_broken_mark(self) -> None:
        circuit = build_loop("bulb")
        circuit.cut_wire(0)
        circuit.remove_wire(0)
        self.assertEqual(circuit.broken_count(), 0)

    def test_repair_all(self) -> None:
        circuit = build_loop("bulb")
        circuit.cut_wire(0)
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_BURNED
        self.assertEqual(circuit.repair_all(), 2)
        self.assertEqual(circuit.broken_count(), 0)
        self.assertEqual(bulb.state, DAMAGE_OK)

    def test_broken_state_saved(self) -> None:
        circuit = build_loop("bulb")
        circuit.cut_wire(0)
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_EXPLODED
        bulb.heat = 1.0
        clone = Circuit.from_json(circuit.to_json())
        self.assertEqual(clone.broken_count(), 1)
        clone_bulb = next(p for p in clone.parts.values() if p.kind == "bulb")
        self.assertEqual(clone_bulb.state, DAMAGE_EXPLODED)
        self.assertAlmostEqual(clone_bulb.heat, 1.0)


class TestDamage(unittest.TestCase):
    def test_burned_part_is_open(self) -> None:
        circuit = Circuit()
        battery = circuit.add_part("battery")
        resistor = circuit.add_part("resistor", value=10.0)
        circuit.add_wire((battery.uid, 1), (resistor.uid, 0))
        circuit.add_wire((resistor.uid, 1), (battery.uid, 0))
        resistor.state = DAMAGE_BURNED
        solution = circuit.solve()
        self.assertAlmostEqual(resistor.i, 0.0, places=6)
        self.assertTrue(any("烧毁" in w for w in solution.warnings))

    def test_replace_part_restores(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_BURNED
        bulb.heat = 1.0
        circuit.solve()
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertTrue(circuit.replace_part(bulb.uid))
        circuit.solve()
        self.assertGreater(abs(bulb.i), 0.1)
        self.assertEqual(bulb.heat, 0.0)

    def test_replace_missing_part(self) -> None:
        circuit = build_loop("bulb")
        self.assertFalse(circuit.replace_part(99))

    def test_stress_and_rated_power(self) -> None:
        bulb = Part(uid=1, kind="bulb", value=12.0, rated_v=6.0)
        self.assertAlmostEqual(bulb.rated_power, 3.0)
        bulb.u, bulb.i = 8.0, 0.6
        bulb.p = bulb.u * bulb.i
        self.assertAlmostEqual(bulb.stress, 1.6)
        self.assertTrue(bulb.overloaded)
        # 冷态不亮；灯丝到额定温度才是满亮度
        self.assertAlmostEqual(bulb.brightness, 0.0)
        bulb.temp = 1.0
        self.assertAlmostEqual(bulb.brightness, 1.0)
        self.assertAlmostEqual(bulb.filament_k, 2800.0)


class TestThermalBulb(unittest.TestCase):
    """灯泡灯丝的热惯性：冷态电阻低、通电升温后电阻变大、断电后有余热。"""

    def test_cold_and_hot_resistance(self) -> None:
        bulb = Part(uid=1, kind="bulb", value=12.0, rated_v=6.0)
        self.assertAlmostEqual(bulb.resistance, 12.0 * BULB_COLD_RATIO)
        self.assertAlmostEqual(bulb.cold_resistance, 12.0 * BULB_COLD_RATIO)
        bulb.temp = 0.5
        self.assertAlmostEqual(bulb.resistance, 12.0 * (BULB_COLD_RATIO + 0.5 * (1 - BULB_COLD_RATIO)))
        bulb.temp = 1.0
        self.assertAlmostEqual(bulb.resistance, 12.0)

    def test_inrush_current_higher_than_steady(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.temp = 0.0           # 从冷态开始
        circuit.solve(1 / 240)
        inrush = abs(bulb.i)
        for _ in range(240):
            circuit.solve(1 / 240)
        steady = abs(bulb.i)
        self.assertGreater(inrush, steady * 2.0)
        self.assertGreater(bulb.temp, 0.85)

    def test_heating_time_constant(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.temp = 0.0
        self.assertAlmostEqual(bulb.temp, 0.0)
        # 约 1 个热时间常数（0.45s）后灯丝升到一多半温度
        for _ in range(int(round(0.45 / (1 / 240)))):
            circuit.solve(1 / 240)
        self.assertGreater(bulb.temp, 0.4)
        self.assertLess(bulb.temp, 0.99)

    def test_bulb_cools_after_power_removed(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        for _ in range(360):
            circuit.solve(1 / 240)
        hot_temp = bulb.temp
        self.assertGreater(hot_temp, 0.85)
        switch = next(p for p in circuit.parts.values() if p.kind == "switch")
        switch.closed = False
        for _ in range(480):
            circuit.solve(1 / 240)
        self.assertLess(bulb.temp, hot_temp * 0.1)

    def test_temperature_survives_save_load(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        circuit.solve()
        restored = Circuit.from_json(circuit.to_json())
        restored_bulb = next(p for p in restored.parts.values() if p.kind == "bulb")
        self.assertAlmostEqual(restored_bulb.temp, bulb.temp, places=3)

    def test_equilibrium_matches_rated_power(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        circuit.solve()
        self.assertAlmostEqual(abs(bulb.p), bulb.rated_power * bulb.temp, delta=0.02)


class TestCutPart(unittest.TestCase):
    def test_cut_part_is_open(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_CUT
        solution = circuit.solve()
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertTrue(bulb.damaged)
        self.assertTrue(any("剪断" in w for w in solution.warnings))

    def test_replace_part_restores_cut(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_CUT
        circuit.solve()
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertTrue(circuit.replace_part(bulb.uid))
        circuit.solve()
        self.assertGreater(abs(bulb.i), 0.1)

    def test_repair_all_restores_cut_and_broken_wires(self) -> None:
        circuit = build_loop("bulb")
        bulb = next(p for p in circuit.parts.values() if p.kind == "bulb")
        bulb.state = DAMAGE_CUT
        circuit.cut_wire(1)
        circuit.solve()
        self.assertGreaterEqual(circuit.broken_count(), 1)
        circuit.repair_all()
        circuit.solve()
        self.assertEqual(bulb.state, DAMAGE_OK)
        self.assertEqual(circuit.broken_count(), 0)
        self.assertGreater(abs(bulb.i), 0.1)

    def test_cut_state_survives_roundtrip(self) -> None:
        circuit = build_loop("resistor")
        resistor = next(p for p in circuit.parts.values() if p.kind == "resistor")
        resistor.state = DAMAGE_CUT
        circuit.solve()
        clone = Circuit.from_dict(json.loads(json.dumps(circuit.to_dict())))
        clone_resistor = clone.parts[resistor.uid]
        self.assertEqual(clone_resistor.state, DAMAGE_CUT)
        self.assertTrue(clone_resistor.damaged)
        clone.solve()
        self.assertAlmostEqual(clone_resistor.i, 0.0, places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
