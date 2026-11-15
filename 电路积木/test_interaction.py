"""test_interaction.py — 界面交互测试（无头运行，不需要真实显示器）。

用 pygame 的 dummy 视频驱动模拟鼠标拖拽、连线、删除、存档等操作，
覆盖「零件栏拖出 / 拖回删除 / 端点连线 / 单击调参 / U I R 显示」等核心玩法。

运行：
    python -m unittest test_interaction -v
或：
    python test_interaction.py
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from circuit_game import (
    CANVAS_RECT,
    CHIP_HIT,
    HEIGHT,
    PALETTE_RECT,
    PANEL_RECT,
    PANEL_W,
    PALETTE_W,
    TERMINAL_X,
    WIDTH,
    App,
)
from circuit_core import (
    DAMAGE_BURNED,
    DAMAGE_CUT,
    DAMAGE_EXPLODED,
    DAMAGE_OK,
    PART_ORDER,
    WIRE_R,
    Part,
)


def mouse_move(app: App, pos) -> None:
    app.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(0, 0, 0)))


def mouse_down(app: App, pos, button: int = 1) -> None:
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))


def mouse_up(app: App, pos, button: int = 1) -> None:
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button))


def click(app: App, pos, button: int = 1) -> None:
    mouse_down(app, pos, button)
    mouse_up(app, pos, button)


def drag(app: App, start, end, steps: int = 4) -> None:
    mouse_down(app, start)
    for i in range(1, steps + 1):
        t = i / steps
        mouse_move(app, (start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t))
    mouse_up(app, end)


def key(app: App, code: int) -> None:
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=code, mod=0, unicode="", scancode=0))


class AppTestCase(unittest.TestCase):
    """每个用例一个干净的 App（不带示例电路）。"""

    def setUp(self) -> None:
        self.app = App(start_demo=False)

    def tearDown(self) -> None:
        pygame.display.quit()

    # -- 辅助 --------------------------------------------------------------
    def place(self, kind: str, pos=(600, 400)):
        return self.app.add_part_at(kind, pos)

    def palette_rect(self, kind: str) -> pygame.Rect:
        for slot_kind, rect in self.app.palette_slots():
            if slot_kind == kind:
                return rect
        raise AssertionError(f"零件栏里没有 {kind}")

    def button_rect(self, ident: str) -> pygame.Rect:
        for button in self.app.toolbar_buttons():
            if button["id"] == ident:
                return button["rect"]
        raise AssertionError(f"工具栏没有 {ident}")

    def control(self, ident: str) -> dict:
        for control in self.app.panel_controls():
            if control["id"] == ident:
                return control
        raise AssertionError(f"右栏没有 {ident}")


class TestPaletteDrag(AppTestCase):
    def test_drag_from_palette_creates_part(self) -> None:
        slot = self.palette_rect("battery")
        drag(self.app, slot.center, (600, 500))
        self.assertEqual(len(self.app.circuit.parts), 1)
        part = next(iter(self.app.circuit.parts.values()))
        self.assertEqual(part.kind, "battery")
        view = self.app.views[part.uid]
        self.assertEqual((view.x, view.y), (600, 500))
        self.assertEqual(self.app.selected_uid, part.uid)

    def test_drag_outside_canvas_cancels(self) -> None:
        slot = self.palette_rect("resistor")
        drag(self.app, slot.center, (20, 795))  # 状态栏
        self.assertEqual(len(self.app.circuit.parts), 0)
        self.assertIn("取消", self.app.notice_text)

    def test_drag_back_to_palette_cancels_new_part(self) -> None:
        slot = self.palette_rect("bulb")
        drag(self.app, slot.center, (20, 300))
        self.assertEqual(len(self.app.circuit.parts), 0)

    def test_drag_part_back_to_palette_deletes(self) -> None:
        part = self.place("resistor")
        view = self.app.views[part.uid]
        drag(self.app, (view.x, view.y), (100, 300))
        self.assertEqual(len(self.app.circuit.parts), 0)
        self.assertNotIn(part.uid, self.app.views)

    def test_dragged_part_stays_inside_canvas(self) -> None:
        part = self.place("resistor", (600, 400))
        drag(self.app, (600, 400), (1270, 780))
        view = self.app.views[part.uid]
        self.assertLessEqual(view.x, CANVAS_RECT.right - 70)
        self.assertLessEqual(view.y, CANVAS_RECT.bottom - 58)
        self.assertGreaterEqual(view.x, CANVAS_RECT.left + 70)
        self.assertGreaterEqual(view.y, CANVAS_RECT.top + 62)

    def test_drag_part_moves_view_and_keeps_wires(self) -> None:
        battery = self.place("battery", (500, 400))
        resistor = self.place("resistor", (800, 400))
        self.assertTrue(self.app.circuit.add_wire((battery.uid, 1), (resistor.uid, 0)))
        self.app.solve()
        drag(self.app, (500, 400), (500, 300))
        self.assertEqual(len(self.app.circuit.wires), 1)
        self.assertAlmostEqual(self.app.views[battery.uid].y, 300)

    def test_keyboard_hotkey_places_part(self) -> None:
        mouse_move(self.app, (500, 450))
        key(self.app, pygame.K_3)
        parts = list(self.app.circuit.parts.values())
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].kind, "bulb")


class TestWiring(AppTestCase):
    def test_connect_two_terminals(self) -> None:
        battery = self.place("battery", (500, 400))
        resistor = self.place("resistor", (800, 400))
        start = self.app.terminal_pos(battery.uid, 1)
        end = self.app.terminal_pos(resistor.uid, 0)
        drag(self.app, start, end)
        self.assertEqual(len(self.app.circuit.wires), 1)
        self.assertEqual(self.app.circuit.wires[0], ((battery.uid, 1), (resistor.uid, 0)))
        self.assertIn("已连接", self.app.notice_text)

    def test_duplicate_wire_rejected(self) -> None:
        battery = self.place("battery", (500, 400))
        resistor = self.place("resistor", (800, 400))
        start = self.app.terminal_pos(battery.uid, 1)
        end = self.app.terminal_pos(resistor.uid, 0)
        drag(self.app, start, end)
        drag(self.app, start, end)
        self.assertEqual(len(self.app.circuit.wires), 1)
        self.assertIn("已经连过", self.app.notice_text)

    def test_wire_drag_to_empty_space_cancels(self) -> None:
        battery = self.place("battery", (500, 400))
        start = self.app.terminal_pos(battery.uid, 1)
        drag(self.app, start, (600, 260))
        self.assertEqual(len(self.app.circuit.wires), 0)
        self.assertIn("端点", self.app.notice_text)

    def test_wire_select_and_delete(self) -> None:
        battery = self.place("battery", (420, 400))
        resistor = self.place("resistor", (900, 400))
        self.app.circuit.add_wire((battery.uid, 1), (resistor.uid, 0))
        self.app.solve()
        points = self.app.wire_geometry(0)[4]
        midpoint = points[len(points) // 2]
        click(self.app, (int(midpoint[0]), int(midpoint[1])))
        self.assertEqual(self.app.selected_wire, 0)
        key(self.app, pygame.K_DELETE)
        self.assertEqual(len(self.app.circuit.wires), 0)
        self.assertIn("已删除导线", self.app.notice_text)

    def test_terminal_highlight_on_hover(self) -> None:
        battery = self.place("battery", (500, 400))
        terminal = (int(self.app.terminal_pos(battery.uid, 0)[0]), int(self.app.terminal_pos(battery.uid, 0)[1]))
        mouse_move(self.app, terminal)
        self.assertEqual(self.app.hover_terminal, (battery.uid, 0))

    def test_wire_drag_preview_state(self) -> None:
        battery = self.place("battery", (500, 400))
        start = self.app.terminal_pos(battery.uid, 1)
        mouse_down(self.app, start)
        mouse_move(self.app, (650, 520))
        self.assertIsNotNone(self.app.drag)
        self.assertEqual(self.app.drag["mode"], "wire")
        mouse_up(self.app, (650, 520))


class TestEditing(AppTestCase):
    def test_click_switch_toggles(self) -> None:
        switch = self.place("switch", (600, 400))
        self.assertTrue(switch.closed)
        click(self.app, (600, 400))
        self.assertFalse(switch.closed)
        self.assertIn("断开", self.app.notice_text)
        click(self.app, (600, 400))
        self.assertTrue(switch.closed)

    def test_click_selects_part(self) -> None:
        resistor = self.place("resistor", (600, 400))
        click(self.app, (600, 400))
        self.assertEqual(self.app.selected_uid, resistor.uid)

    def test_click_empty_canvas_clears_selection(self) -> None:
        self.place("resistor", (600, 400))
        click(self.app, (600, 400))
        click(self.app, (380, 700))
        self.assertIsNone(self.app.selected_uid)

    def test_delete_key_removes_selected_part(self) -> None:
        part = self.place("bulb", (600, 400))
        click(self.app, (600, 400))
        key(self.app, pygame.K_DELETE)
        self.assertEqual(len(self.app.circuit.parts), 0)
        self.assertNotIn(part.uid, self.app.views)

    def test_right_click_removes_part(self) -> None:
        self.place("resistor", (600, 400))
        click(self.app, (600, 400), button=3)
        self.assertEqual(len(self.app.circuit.parts), 0)

    def test_right_click_removes_wire(self) -> None:
        battery = self.place("battery", (420, 400))
        resistor = self.place("resistor", (900, 400))
        self.app.circuit.add_wire((battery.uid, 1), (resistor.uid, 0))
        self.app.solve()
        points = self.app.wire_geometry(0)[4]
        midpoint = points[len(points) // 2]
        click(self.app, (int(midpoint[0]), int(midpoint[1])), button=3)
        self.assertEqual(len(self.app.circuit.wires), 0)

    def test_rotate_selected_part(self) -> None:
        part = self.place("resistor", (600, 400))
        click(self.app, (600, 400))
        before = self.app.terminal_pos(part.uid, 0)
        self.assertAlmostEqual(before[0], 540)
        self.assertAlmostEqual(before[1], 400)
        key(self.app, pygame.K_r)
        self.assertEqual(self.app.views[part.uid].angle, 90)
        after = self.app.terminal_pos(part.uid, 0)
        # 旋转 90° 后端点从「左侧」变到「上方」
        self.assertAlmostEqual(after[0], 600)
        self.assertAlmostEqual(after[1], 400 - TERMINAL_X)

    def test_rotate_button_in_panel(self) -> None:
        part = self.place("bulb", (600, 400))
        self.app.selected_uid = part.uid
        click(self.app, self.control("rotate")["rect"].center)
        self.assertEqual(self.app.views[part.uid].angle, 90)
        click(self.app, self.control("rotate")["rect"].center)
        self.assertEqual(self.app.views[part.uid].angle, 180)
        self.assertIn("旋转", self.app.notice_text)

    def test_rotate_button_moves_terminals(self) -> None:
        part = self.place("voltmeter", (600, 400))
        self.app.selected_uid = part.uid
        click(self.app, self.control("rotate")["rect"].center)
        self.app.solve()
        terminal = self.app.terminal_pos(part.uid, 0)
        self.assertAlmostEqual(terminal[0], 600)
        self.assertAlmostEqual(terminal[1], 400 - TERMINAL_X)

    def test_rotate_only_when_selected(self) -> None:
        part = self.place("resistor", (600, 400))
        self.app.selected_uid = None
        key(self.app, pygame.K_r)
        self.assertEqual(self.app.views[part.uid].angle, 0)

    def test_escape_cancels_selection(self) -> None:
        self.place("resistor", (600, 400))
        click(self.app, (600, 400))
        key(self.app, pygame.K_ESCAPE)
        self.assertIsNone(self.app.selected_uid)

    def test_clear_toolbar(self) -> None:
        self.place("resistor", (600, 400))
        click(self.app, self.button_rect("clear").center)
        self.assertEqual(len(self.app.circuit.parts), 0)
        self.assertEqual(len(self.app.circuit.wires), 0)

    def test_demo_toolbar(self) -> None:
        click(self.app, self.button_rect("demo").center)
        self.assertEqual(len(self.app.circuit.parts), 4)
        self.assertEqual(len(self.app.circuit.wires), 5)
        self.assertIsNotNone(self.app.solution)
        self.assertGreater(self.app.solution.battery_current, 0.9)


class TestPanel(AppTestCase):
    def test_layout_not_clipped(self) -> None:
        self.assertEqual(PANEL_RECT.right, WIDTH)
        self.assertEqual(PANEL_RECT.left, PALETTE_W + CANVAS_RECT.w)
        self.assertEqual(CANVAS_RECT.left, PALETTE_W)
        self.assertEqual(PALETTE_RECT.right, CANVAS_RECT.left)
        self.assertEqual(PANEL_RECT.x + PANEL_RECT.w, WIDTH)

    def test_controls_fit_inside_panel(self) -> None:
        for kind in ("battery", "resistor", "bulb", "switch"):
            part = self.place(kind, (500, 400))
            self.app.selected_uid = part.uid
            for control in self.app.panel_controls():
                rect = control["rect"]
                self.assertGreaterEqual(rect.left, PANEL_RECT.left, control["id"])
                self.assertLessEqual(rect.right, PANEL_RECT.right, control["id"])
                self.assertLessEqual(rect.bottom, PANEL_RECT.bottom, control["id"])
                if control["type"] == "slider":
                    track = self.app.slider_track(control)
                    self.assertLessEqual(track.right, PANEL_RECT.right - 10, control["id"])

    def test_panel_controls_per_kind(self) -> None:
        expected = {
            "battery": {"emf", "rin", "rotate", "delete"},
            "resistor": {"r", "rotate", "delete"},
            "bulb": {"r", "rotate", "delete"},
            "switch": {"toggle", "rotate", "delete"},
        }
        for kind, ids in expected.items():
            part = self.place(kind, (400, 300 + 40 * len(self.app.circuit.parts)))
            self.app.selected_uid = part.uid
            got = {control["id"] for control in self.app.panel_controls()}
            self.assertEqual(got, ids, kind)

    def test_slider_set_bulb_resistance(self) -> None:
        bulb = self.place("bulb", (600, 400))
        self.app.selected_uid = bulb.uid
        control = self.control("r")
        track = self.app.slider_track(control)
        mouse_down(self.app, (track.left, track.centery))
        mouse_up(self.app, (track.left, track.centery))
        self.assertEqual(bulb.value, control["series"][0])
        mouse_down(self.app, (track.right, track.centery))
        mouse_up(self.app, (track.right, track.centery))
        self.assertEqual(bulb.value, control["series"][-1])

    def test_slider_updates_solution(self) -> None:
        battery = self.place("battery", (450, 400))
        bulb = self.place("bulb", (750, 400))
        self.app.circuit.add_wire((battery.uid, 0), (bulb.uid, 0))
        self.app.circuit.add_wire((battery.uid, 1), (bulb.uid, 1))
        self.app.solve()
        first = abs(bulb.i)
        self.app.selected_uid = bulb.uid
        control = self.control("r")
        track = self.app.slider_track(control)
        mouse_down(self.app, (track.right, track.centery))
        mouse_up(self.app, (track.right, track.centery))
        self.assertLess(abs(bulb.i), first)

    def test_panel_toggle_button(self) -> None:
        switch = self.place("switch", (600, 400))
        self.app.selected_uid = switch.uid
        click(self.app, self.control("toggle")["rect"].center)
        self.assertFalse(switch.closed)

    def test_panel_delete_button(self) -> None:
        self.place("resistor", (600, 400))
        self.app.selected_uid = next(iter(self.app.circuit.parts))
        click(self.app, self.control("delete")["rect"].center)
        self.assertEqual(len(self.app.circuit.parts), 0)

    def test_selected_part_readouts(self) -> None:
        battery = self.place("battery", (450, 400))
        bulb = self.place("bulb", (750, 400))
        self.app.circuit.add_wire((battery.uid, 0), (bulb.uid, 0))
        self.app.circuit.add_wire((battery.uid, 1), (bulb.uid, 1))
        self.app.solve()
        self.assertGreater(abs(bulb.u), 1.0)
        self.assertGreater(abs(bulb.i), 0.01)

    def test_no_panel_controls_without_selection(self) -> None:
        self.assertEqual(self.app.panel_controls(), [])


class TestDisplayModes(AppTestCase):
    def test_cycle_display_mode(self) -> None:
        button = self.button_rect("display")
        self.assertEqual(self.app.display_mode, "always")
        for expected in ("hover", "click", "always"):
            click(self.app, button.center)
            self.assertEqual(self.app.display_mode, expected)

    def test_badge_visibility(self) -> None:
        part = self.place("bulb", (600, 400))
        other = self.place("resistor", (850, 400))

        self.app.display_mode = "always"
        self.assertTrue(self.app._badge_visible(part.uid))
        self.assertTrue(self.app._badge_visible(other.uid))

        # 悬浮方式改用 tooltip 显示，画布上不画徽标
        self.app.display_mode = "hover"
        self.app.hover_uid = part.uid
        self.assertFalse(self.app._badge_visible(part.uid))
        self.assertFalse(self.app._badge_visible(other.uid))
        self.assertTrue(self.app._tooltip_lines(part))

        self.app.display_mode = "click"
        self.app.selected_uid = other.uid
        self.assertFalse(self.app._badge_visible(part.uid))
        self.assertTrue(self.app._badge_visible(other.uid))

    def test_badge_text_shows_uir(self) -> None:
        part = self.place("bulb", (600, 400))
        self.app.solve()
        # 热态才显示 12Ω；冷态是 1.32Ω，所以这里把灯丝置为额定温度
        part.temp = 1.0
        part.u, part.i, part.p = 5.5412, 0.4610, 2.55
        text = self.app._badge_text(part)
        self.assertIn("U=5.54V", text)
        self.assertIn("I=0.461A", text)
        self.assertIn("R=12Ω", text)

    def test_badge_text_flattens_noise(self) -> None:
        part = self.place("switch", (600, 400))
        part.u, part.i = 0.00092, 5e-6
        text = self.app._badge_text(part)
        self.assertIn("U≈0", text)
        self.assertIn("I≈0", text)
        self.assertNotIn("mV", text)

    def test_demo_badge_has_no_millivolt(self) -> None:
        self.app.load_demo()
        for part in self.app.circuit.parts.values():
            if part.kind == "switch":
                self.assertIn("≈0", self.app._badge_text(part))


class TestDemoCircuit(AppTestCase):
    def test_demo_values(self) -> None:
        self.app.load_demo()
        bulbs = [p for p in self.app.circuit.parts.values() if p.kind == "bulb"]
        self.assertEqual(len(bulbs), 2)
        # 灯泡按热态工作：灯丝温度 ~0.91，总电流约 0.995A（不是固定 12Ω 的 0.923A）
        total = self.app.solution.battery_current
        self.assertAlmostEqual(total, 0.995, delta=0.01)
        for bulb in bulbs:
            self.assertAlmostEqual(abs(bulb.i), total / 2.0, delta=0.01)
            self.assertGreater(bulb.temp, 0.85)
            self.assertAlmostEqual(bulb.brightness, bulb.temp, places=6)

    def test_demo_switch_off_turns_bulbs_off(self) -> None:
        self.app.load_demo()
        switch = next(p for p in self.app.circuit.parts.values() if p.kind == "switch")
        self.app.toggle_switch(switch.uid)
        for part in self.app.circuit.parts.values():
            if part.kind == "bulb":
                self.assertAlmostEqual(part.p, 0.0)
        # 灯丝有余热：跑 2 秒后应基本冷却、不亮了
        for _ in range(120):
            self.app.update(1 / 60)
        for part in self.app.circuit.parts.values():
            if part.kind == "bulb":
                self.assertLess(part.brightness, 0.02)

    def test_demo_layout_all_inside_canvas(self) -> None:
        self.app.load_demo()
        for view in self.app.views.values():
            self.assertTrue(CANVAS_RECT.collidepoint(view.x, view.y))
            self.assertGreater(view.x, CANVAS_RECT.left + CHIP_HIT[0])
            self.assertLess(view.y, CANVAS_RECT.bottom - CHIP_HIT[1])


class TestSaveLoad(AppTestCase):
    def test_roundtrip_with_layout(self) -> None:
        battery = self.place("battery", (450, 420))
        bulb = self.place("bulb", (780, 420))
        self.app.views[battery.uid].angle = 90
        self.app.circuit.add_wire((battery.uid, 0), (bulb.uid, 0))
        self.app.circuit.add_wire((battery.uid, 1), (bulb.uid, 1))
        self.app.solve()

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "circuit_save.json")
            self.app.save(path)
            self.assertTrue(os.path.exists(path))

            self.app.circuit.clear()
            self.app.views.clear()
            self.assertTrue(self.app.load(path))

        self.assertEqual(len(self.app.circuit.parts), 2)
        self.assertEqual(len(self.app.circuit.wires), 2)
        self.assertEqual(self.app.views[battery.uid].angle, 90)
        self.assertAlmostEqual(self.app.views[bulb.uid].x, 780)

    def test_load_missing_file(self) -> None:
        self.assertFalse(self.app.load("no_such_save_file.json"))
        self.assertIn("没有找到", self.app.notice_text)

    def test_save_button_writes_default_file(self) -> None:
        from circuit_game import SAVE_FILE

        created = not os.path.exists(SAVE_FILE)
        try:
            click(self.app, self.button_rect("save").center)
            self.assertTrue(os.path.exists(SAVE_FILE))
            self.assertIn("已保存", self.app.notice_text)
        finally:
            if created and os.path.exists(SAVE_FILE):
                os.remove(SAVE_FILE)


class TestMisc(AppTestCase):
    def test_space_pauses_simulation(self) -> None:
        self.place("resistor", (600, 400))
        self.assertTrue(self.app.sim_on)
        key(self.app, pygame.K_SPACE)
        self.assertFalse(self.app.sim_on)
        key(self.app, pygame.K_SPACE)
        self.assertTrue(self.app.sim_on)

    def test_help_toggle(self) -> None:
        self.assertFalse(self.app.help_open)
        key(self.app, pygame.K_F1)
        self.assertTrue(self.app.help_open)
        key(self.app, pygame.K_ESCAPE)
        self.assertFalse(self.app.help_open)

    def test_draw_runs_without_error(self) -> None:
        self.app.load_demo()
        self.app.draw()
        self.app.toggle_switch(next(p.uid for p in self.app.circuit.parts.values() if p.kind == "switch"))
        self.app.draw()

    def test_lit_bulb_has_glow_on_screen(self) -> None:
        self.app.load_demo()
        self.app.draw()
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        view = self.app.views[bulb.uid]
        pixel = self.app.screen.get_at((int(view.x) + 70, int(view.y)))
        self.assertNotEqual(pixel[:3], (250, 251, 254), "灯泡周围应有暖色光晕")

    def test_blank_canvas_pixel(self) -> None:
        self.app.draw()
        pixel = self.app.screen.get_at((CANVAS_RECT.left + 6, CANVAS_RECT.top + 6))
        self.assertEqual(len(pixel), 4)

    def test_pause_does_not_break_switch_toggle(self) -> None:
        switch = self.place("switch", (600, 400))
        key(self.app, pygame.K_SPACE)
        click(self.app, (600, 400))
        self.assertFalse(switch.closed)
        key(self.app, pygame.K_SPACE)
        self.assertTrue(self.app.sim_on)

    def test_notice_expires(self) -> None:
        self.app.notice("测试提示")
        self.app.time += 5.0
        self.assertGreater(self.app.time, self.app.notice_until)



# ---------------------------------------------------------------------------
# 新元件：滑动变阻器 / 电压表 / 电流表 / 电容
# ---------------------------------------------------------------------------

class TestPaletteExtras(AppTestCase):
    def test_palette_has_eight_kinds(self) -> None:
        kinds = [kind for kind, _ in self.app.palette_slots()]
        self.assertEqual(len(kinds), 8)
        self.assertEqual(set(kinds), set(PART_ORDER))

    def test_every_slot_fully_visible(self) -> None:
        area = self.app.palette_content_rect()
        for kind, rect in self.app.palette_slots():
            self.assertTrue(
                area.contains(rect),
                f"{kind} 的格子 {rect} 没有完整落在零件栏可视区 {area} 内",
            )

    def test_drag_new_kinds_from_palette(self) -> None:
        for kind in ("rheostat", "voltmeter", "ammeter", "capacitor"):
            with self.subTest(kind=kind):
                app = App(start_demo=False)
                rect = self.palette_rect(kind)
                drag(app, rect.center, (620, 420))
                kinds = [p.kind for p in app.circuit.parts.values()]
                self.assertEqual(kinds, [kind])


class TestNewPartPanels(AppTestCase):
    def test_panel_controls_per_new_kind(self) -> None:
        expected = {
            "rheostat": {"r", "rotate", "delete"},
            "capacitor": {"c", "rated", "rotate", "delete"},
            "voltmeter": {"rotate", "delete"},
            "ammeter": {"rotate", "delete"},
        }
        for kind, ids in expected.items():
            with self.subTest(kind=kind):
                app = App(start_demo=False)
                app.add_part_at(kind, (600, 400))
                controls = {control["id"] for control in app.panel_controls()}
                self.assertEqual(controls, ids)

    def test_capacitor_sliders_change_values(self) -> None:
        self.app.load_demo(2)
        capacitor = next(p for p in self.app.circuit.parts.values() if p.kind == "capacitor")
        self.app.selected_uid = capacitor.uid
        track = self.app.slider_track(self.control("c"))
        self.app._apply_slider(self.control("c"), track.x)
        self.assertAlmostEqual(capacitor.value, 0.001)
        self.app._apply_slider(self.control("c"), track.right)
        self.assertAlmostEqual(capacitor.value, 1.0)


class TestScissors(AppTestCase):
    def test_cut_wire_by_click(self) -> None:
        self.app.load_demo(0)
        self.app.set_tool("cut")
        points = self.app.wire_geometry(2)[4]
        middle = points[len(points) // 2]
        click(self.app, (int(middle[0]), int(middle[1])))
        self.assertEqual(self.app.circuit.broken_count(), 1)
        self.assertTrue(self.app.circuit.is_wire_broken(2))
        self.assertIn("剪断", self.app.notice_text)
        self.assertEqual(self.app.selected_wire, 2)

    def test_cut_breaks_the_circuit(self) -> None:
        self.app.load_demo(0)
        bulb2 = [
            p for p in self.app.circuit.parts.values()
            if p.kind == "bulb" and p.uid == 4
        ][0]
        self.assertGreater(abs(bulb2.i), 0.1)
        self.app.cut_wire(2)
        self.assertAlmostEqual(bulb2.i, 0.0, places=6)

    def test_cut_same_wire_twice(self) -> None:
        self.app.load_demo(0)
        self.app.cut_wire(2)
        self.app.cut_wire(2)
        self.assertEqual(self.app.circuit.broken_count(), 1)
        self.assertIn("已经断了", self.app.notice_text)

    def test_scissors_on_empty_space_does_nothing(self) -> None:
        self.app.load_demo(0)
        self.app.set_tool("cut")
        before = len(self.app.circuit.wires)
        click(self.app, (260, 700))
        self.assertEqual(self.app.circuit.broken_count(), 0)
        self.assertEqual(len(self.app.circuit.wires), before)

    def test_toolbar_scissors_toggles_tool(self) -> None:
        click(self.app, self.button_rect("scissors").center)
        self.assertEqual(self.app.tool, "cut")
        click(self.app, self.button_rect("scissors").center)
        self.assertEqual(self.app.tool, "select")

    def test_wire_panel_offers_cut_and_repair(self) -> None:
        self.app.load_demo(0)
        self.app.selected_uid = None
        self.app.selected_wire = 2
        self.assertEqual(
            {control["id"] for control in self.app.panel_controls()},
            {"cut_wire", "delete_wire"},
        )
        click(self.app, self.control("cut_wire")["rect"].center)
        self.assertTrue(self.app.circuit.is_wire_broken(2))
        self.assertEqual(
            {control["id"] for control in self.app.panel_controls()},
            {"repair_wire", "delete_wire"},
        )
        click(self.app, self.control("repair_wire")["rect"].center)
        self.assertFalse(self.app.circuit.is_wire_broken(2))
        self.assertIn("修复", self.app.notice_text)

    def test_repair_all_button(self) -> None:
        self.app.load_demo(0)
        self.app.cut_wire(2)
        click(self.app, self.button_rect("repair").center)
        self.assertEqual(self.app.circuit.broken_count(), 0)
        self.assertIn("修复", self.app.notice_text)


class TestRealisticMode(AppTestCase):
    def _burn_a_bulb(self) -> Part:
        self.app.set_realistic(True)
        battery = self.app.add_part_at("battery", (420, 380))
        battery.value = 24.0
        bulb = self.app.add_part_at("bulb", (760, 380))
        self.app.circuit.add_wire((battery.uid, 1), (bulb.uid, 0))
        self.app.circuit.add_wire((bulb.uid, 1), (battery.uid, 0))
        self.app.solve()
        for _ in range(240):
            self.app.update(1.0 / 60.0)
            if bulb.damaged:
                break
        return bulb

    def test_toolbar_toggles_realistic(self) -> None:
        self.assertFalse(self.app.realistic)
        click(self.app, self.button_rect("realistic").center)
        self.assertTrue(self.app.realistic)
        self.assertIn("全真", self.app.notice_text)
        click(self.app, self.button_rect("realistic").center)
        self.assertFalse(self.app.realistic)

    def test_overloaded_bulb_burns_out(self) -> None:
        bulb = self._burn_a_bulb()
        self.assertTrue(bulb.damaged)
        self.assertEqual(bulb.state, DAMAGE_BURNED)
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertTrue(self.app.effects.smoke or self.app.effects.particles)
        self.assertIn("烧毁", self.app.notice_text)

    def test_burn_effects_decay(self) -> None:
        self._burn_a_bulb()
        for _ in range(240):
            self.app.update(1.0 / 60.0)
        self.assertFalse(self.app.effects.particles)
        self.assertFalse(self.app.effects.smoke)
        self.assertAlmostEqual(self.app.effects.flash_alpha, 0.0)

    def test_repair_all_restores_burnt_part(self) -> None:
        bulb = self._burn_a_bulb()
        click(self.app, self.button_rect("repair").center)
        self.assertFalse(bulb.damaged)
        self.assertEqual(bulb.state, DAMAGE_OK)
        self.assertEqual(bulb.heat, 0.0)
        self.assertGreater(abs(bulb.i), 0.1)

    def test_replace_button_swaps_part(self) -> None:
        bulb = self._burn_a_bulb()
        self.app.selected_uid = bulb.uid
        self.app.selected_wire = None
        ids = {control["id"] for control in self.app.panel_controls()}
        self.assertIn("replace", ids)
        click(self.app, self.control("replace")["rect"].center)
        self.assertFalse(bulb.damaged)
        self.assertIn("更换", self.app.notice_text)

    def test_no_damage_when_realistic_off(self) -> None:
        battery = self.app.add_part_at("battery", (420, 380))
        battery.value = 24.0
        bulb = self.app.add_part_at("bulb", (760, 380))
        self.app.circuit.add_wire((battery.uid, 1), (bulb.uid, 0))
        self.app.circuit.add_wire((bulb.uid, 1), (battery.uid, 0))
        self.app.solve()
        for _ in range(240):
            self.app.update(1.0 / 60.0)
        self.assertFalse(bulb.damaged)

    def test_explosion_for_battery(self) -> None:
        self.app.set_realistic(True)
        battery = self.app.add_part_at("battery", (420, 380))
        battery.value = 12.0
        self.app.circuit.add_wire((battery.uid, 1), (battery.uid, 0))
        self.app.solve()
        for _ in range(240):
            self.app.update(1.0 / 60.0)
            if battery.damaged:
                break
        self.assertTrue(battery.damaged)
        self.assertEqual(battery.state, DAMAGE_EXPLODED)
        self.assertIn("爆炸", self.app.notice_text)


class TestCapacitorTransient(AppTestCase):
    def test_capacitor_charges_over_time(self) -> None:
        self.app.load_demo(2)
        capacitor = next(p for p in self.app.circuit.parts.values() if p.kind == "capacitor")
        self.assertAlmostEqual(abs(capacitor.u), 0.0, delta=0.1)
        for _ in range(72):                       # 1.2 s，τ = 1 s
            self.app.update(1.0 / 60.0)
        self.assertAlmostEqual(abs(capacitor.u), 4.19, delta=0.25)
        for _ in range(240):                      # 再充 4 s 基本充满
            self.app.update(1.0 / 60.0)
        self.assertGreater(abs(capacitor.u), 5.8)

    def test_pause_freezes_charging(self) -> None:
        self.app.load_demo(2)
        capacitor = next(p for p in self.app.circuit.parts.values() if p.kind == "capacitor")
        self.app.sim_on = False
        self.app.solve()
        for _ in range(120):
            self.app.update(1.0 / 60.0)
        self.assertAlmostEqual(abs(capacitor.u), 0.0, delta=0.05)

    def test_capacitor_panel_readouts(self) -> None:
        self.app.load_demo(2)
        capacitor = next(p for p in self.app.circuit.parts.values() if p.kind == "capacitor")
        self.app.selected_uid = capacitor.uid
        for _ in range(30):
            self.app.update(1.0 / 60.0)
        texts = [control.get("label", "") for control in self.app.panel_controls()]
        self.assertIn("容量 C", texts)
        self.assertIn("耐压 U_max", texts)


class TestDemoCycles(AppTestCase):
    def test_three_demos_cycle(self) -> None:
        self.app.load_demo(0)
        self.assertEqual(len(self.app.circuit.parts), 4)
        self.app.load_demo(1)
        kinds = {p.kind for p in self.app.circuit.parts.values()}
        self.assertEqual(kinds, {"battery", "switch", "ammeter", "resistor", "voltmeter"})
        ammeter = next(p for p in self.app.circuit.parts.values() if p.kind == "ammeter")
        voltmeter = next(p for p in self.app.circuit.parts.values() if p.kind == "voltmeter")
        self.assertAlmostEqual(abs(ammeter.i), 0.571, delta=0.01)
        self.assertAlmostEqual(abs(voltmeter.u), 5.71, delta=0.05)
        self.app.load_demo(2)
        kinds = {p.kind for p in self.app.circuit.parts.values()}
        self.assertEqual(kinds, {"battery", "switch", "resistor", "capacitor"})

    def test_demo_button_advances(self) -> None:
        click(self.app, self.button_rect("demo").center)
        first = {p.kind for p in self.app.circuit.parts.values()}
        click(self.app, self.button_rect("demo").center)
        second = {p.kind for p in self.app.circuit.parts.values()}
        self.assertNotEqual(first, second)

    def test_demo_layout_inside_canvas(self) -> None:
        for index in range(3):
            with self.subTest(demo=index):
                self.app.load_demo(index)
                for view in self.app.views.values():
                    self.assertTrue(CANVAS_RECT.collidepoint(view.x, view.y))


class TestToolCursor(AppTestCase):
    def test_draw_with_scissors_does_not_crash(self) -> None:
        self.app.load_demo(0)
        self.app.set_tool("cut")
        points = self.app.wire_geometry(2)[4]
        self.app.mouse_pos = (int(points[3][0]), int(points[3][1]))
        self.app._on_mouse_move(self.app.mouse_pos)
        self.app.draw()

    def test_hovered_wire_is_remembered_in_cut_mode(self) -> None:
        self.app.load_demo(0)
        self.app.set_tool("cut")
        points = self.app.wire_geometry(2)[4]
        middle = points[len(points) // 2]
        self.app.mouse_pos = (int(middle[0]), int(middle[1]))
        self.app._on_mouse_move(self.app.mouse_pos)
        self.assertEqual(self.app.hover_wire, 2)


class TestSaveLoadExtras(AppTestCase):
    def test_broken_and_damaged_state_survives_roundtrip(self) -> None:
        self.app.load_demo(0)
        self.app.cut_wire(2)
        bulb = next(iter(self.app.circuit.parts.values()))
        bulb.state = DAMAGE_BURNED
        bulb.heat = 1.0
        path = os.path.join(tempfile.mkdtemp(), "extra.json")
        self.assertTrue(self.app.save(path))
        self.app.load_demo(1)
        self.assertTrue(self.app.load(path))
        self.assertEqual(self.app.circuit.broken_count(), 1)
        self.assertTrue(any(p.damaged for p in self.app.circuit.parts.values()))
        self.assertTrue(self.app.views)


class TestSchematicMode(AppTestCase):
    """电路图模式：自动排版、正交连线、导出 SVG / 网表、生成电路。"""

    def enter(self) -> None:
        self.app.load_demo(0)
        self.original = {
            uid: (view.x, view.y, view.angle) for uid, view in self.app.views.items()
        }
        click(self.app, self.button_rect("schematic").center)

    def test_board_toolbar_has_schematic_button(self) -> None:
        ids = [button["id"] for button in self.app.toolbar_buttons()]
        self.assertIn("schematic", ids)

    def test_enter_schematic_switches_mode_and_toolbar(self) -> None:
        self.enter()
        self.assertEqual(self.app.mode, "schematic")
        ids = [button["id"] for button in self.app.toolbar_buttons()]
        self.assertEqual(
            ids, ["back", "tidy", "export_svg", "netlist", "apply", "clear", "help"]
        )
        # 自动整理后所有零件都在画布里
        for view in self.app.views.values():
            self.assertTrue(CANVAS_RECT.collidepoint(view.x, view.y))

    def test_enter_saves_board_views(self) -> None:
        self.enter()
        self.assertEqual(set(self.app.board_views), set(self.app.circuit.parts))
        for uid, view in self.app.board_views.items():
            self.assertEqual((view.x, view.y, view.angle), self.original[uid])

    def test_back_restores_board_views(self) -> None:
        self.enter()
        click(self.app, self.button_rect("back").center)
        self.assertEqual(self.app.mode, "board")
        for uid, view in self.app.views.items():
            self.assertEqual((view.x, view.y, view.angle), self.original[uid])

    def test_apply_keeps_schematic_layout_and_solves(self) -> None:
        self.enter()
        battery = next(p for p in self.app.circuit.parts.values() if p.kind == "battery")
        before = abs(battery.i)
        click(self.app, self.button_rect("apply").center)
        self.assertEqual(self.app.mode, "board")
        self.assertTrue(self.app.board_ortho)
        self.assertAlmostEqual(abs(battery.i), before, delta=1e-3)
        for view in self.app.views.values():
            self.assertTrue(CANVAS_RECT.collidepoint(view.x, view.y))

    def test_tidy_button_rearranges(self) -> None:
        self.enter()
        self.app.views[1].x = 250
        self.app.views[1].y = 700
        click(self.app, self.button_rect("tidy").center)
        for view in self.app.views.values():
            self.assertTrue(CANVAS_RECT.collidepoint(view.x, view.y))

    def test_export_svg_and_netlist(self) -> None:
        self.enter()
        folder = tempfile.mkdtemp()
        svg_path = os.path.join(folder, "diagram.svg")
        net_path = os.path.join(folder, "netlist.txt")
        self.app.export_svg(svg_path)
        self.app.export_netlist(net_path)
        with open(svg_path, encoding="utf-8") as handle:
            svg = handle.read()
        self.assertTrue(svg.startswith('<?xml version="1.0" encoding="UTF-8"?>'))
        self.assertIn("<svg", svg)
        self.assertIn("电池 #1", svg)
        self.assertEqual(svg.count("<polyline") >= 5, True)
        with open(net_path, encoding="utf-8") as handle:
            netlist = handle.read()
        self.assertIn("电路网表", netlist)
        self.assertIn("节点", netlist)

    def test_palette_drag_in_schematic_snaps_to_grid(self) -> None:
        self.enter()
        slot = self.palette_rect("resistor")
        drag(self.app, slot.center, (520, 620))
        self.assertEqual(len(self.app.circuit.parts), 5)
        part = max(self.app.circuit.parts.values(), key=lambda p: p.uid)
        view = self.app.views[part.uid]
        self.assertEqual((view.x - CANVAS_RECT.left) % 24, 0)
        self.assertEqual((view.y - CANVAS_RECT.top) % 24, 0)

    def test_schematic_wires_are_orthogonal(self) -> None:
        self.enter()
        for index in range(len(self.app.circuit.wires)):
            points = self.app.wire_geometry(index)[4]
            for a, b in zip(points, points[1:]):
                self.assertTrue(
                    abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5,
                    f"导线 #{index} 出现斜线 {a}->{b}",
                )

    def test_draw_schematic_does_not_crash(self) -> None:
        self.enter()
        self.app.mouse_pos = (600, 400)
        self.app._on_mouse_move(self.app.mouse_pos)
        self.app.draw()
        self.app.display_mode = "hover"
        self.app.draw()
        self.app.display_mode = "click"
        self.app.draw()

    def test_save_in_schematic_keeps_board_layout(self) -> None:
        self.enter()
        path = os.path.join(tempfile.mkdtemp(), "schematic_save.json")
        self.assertTrue(self.app.save(path))
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        views = data["views"]
        for uid, (x, y, angle) in self.original.items():
            self.assertAlmostEqual(views[str(uid)]["x"], x)
            self.assertAlmostEqual(views[str(uid)]["y"], y)

    def test_scissors_cuts_component(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.set_tool("cut")
        click(self.app, (int(self.app.views[bulb.uid].x), int(self.app.views[bulb.uid].y)))
        self.assertEqual(bulb.state, DAMAGE_CUT)
        self.assertTrue(bulb.damaged)
        self.app.solve()
        self.assertAlmostEqual(bulb.i, 0.0, places=6)
        self.assertIn("断路", self.app._badge_text(bulb))

    def test_scissors_on_component_keeps_other_bulb_lit(self) -> None:
        self.app.load_demo(0)
        bulbs = [p for p in self.app.circuit.parts.values() if p.kind == "bulb"]
        self.app.set_tool("cut")
        first = self.app.views[bulbs[0].uid]
        click(self.app, (int(first.x), int(first.y)))
        self.app.solve()
        currents = [abs(p.i) for p in bulbs]
        self.assertAlmostEqual(min(currents), 0.0, places=6)
        self.assertGreater(max(currents), 0.3)

    def test_scissors_on_component_twice_shows_notice(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.set_tool("cut")
        view = self.app.views[bulb.uid]
        click(self.app, (int(view.x), int(view.y)))
        click(self.app, (int(view.x), int(view.y)))
        self.assertIn("已经断开", self.app.notice_text)

    def test_cut_component_panel_and_tooltip(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.cut_part(bulb.uid)
        self.app.selected_uid = bulb.uid
        self.app.draw()
        lines = " ".join(self.app._tooltip_lines(bulb))
        self.assertIn("剪断", lines)

    def test_repair_all_restores_cut_component(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.cut_part(bulb.uid)
        self.app.repair_all()
        self.assertFalse(bulb.damaged)
        self.app.solve()
        self.assertGreater(abs(bulb.i), 0.3)

    def test_cut_part_draws_without_crash(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.cut_part(bulb.uid)
        self.app.selected_uid = bulb.uid
        self.app.draw()
        self.enter()
        self.app.draw()


class TestLongRun(AppTestCase):
    """整帧循环跑一段时间：更新 + 绘制都执行，确保长时间运行不崩。"""

    def test_300_frames_with_realistic_mode(self) -> None:
        self.app.load_demo(0)
        self.app.set_realistic(True)
        self.app.set_tool("cut")
        for _ in range(300):
            self.app.update(1.0 / 60.0)
            self.app.draw()
        self.assertTrue(self.app.running)
        self.assertGreater(len(self.app.circuit.parts), 0)

    def test_300_frames_in_schematic_mode(self) -> None:
        self.app.load_demo(1)
        self.app.enter_schematic()
        self.app.display_mode = "hover"
        for _ in range(200):
            self.app.update(1.0 / 60.0)
            self.app.draw()
        self.assertEqual(self.app.mode, "schematic")


def finger(app: App, kind: str, nx: float, ny: float, dx: float = 0.0, dy: float = 0.0) -> None:
    """模拟手指事件：FINGER* 的 x/y 是 0..1 的窗口归一化坐标。"""
    app.handle_event(
        pygame.event.Event(
            getattr(pygame, kind),
            x=nx,
            y=ny,
            dx=dx,
            dy=dy,
            finger_id=0,
            touch_id=0,
        )
    )


class TestTouchAndScaling(AppTestCase):
    """手机触控与窗口缩放适配。"""

    def test_logical_pos_identity_when_window_matches(self) -> None:
        self.app.draw()
        self.assertEqual(self.app._logical_pos((640, 400)), (640.0, 400.0))

    def test_logical_pos_scales_letterboxed_window(self) -> None:
        self.app.window = pygame.display.set_mode((1600, 720))
        self.app.draw()
        viewport = self.app.viewport
        self.assertEqual(viewport.size, (1152, 720))
        center = (viewport.x + viewport.w / 2, viewport.y + viewport.h / 2)
        lx, ly = self.app._logical_pos(center)
        self.assertAlmostEqual(lx, WIDTH / 2, delta=1.0)
        self.assertAlmostEqual(ly, 800 / 2, delta=1.0)

    def test_mobile_aspect_keeps_whole_canvas_visible(self) -> None:
        self.app.window = pygame.display.set_mode((720, 1280))
        self.app.draw()
        viewport = self.app.viewport
        self.assertLessEqual(viewport.w, 720)
        self.assertLessEqual(viewport.h, 1280)
        self.assertAlmostEqual(viewport.w / viewport.h, WIDTH / 800, delta=0.02)

    def test_touch_mode_enlarges_hit_area(self) -> None:
        part = self.app.add_part_at("resistor", (400, 300))
        view = self.app.views[part.uid]
        # 命中区外沿：正常模式点不到，触屏模式能点到
        probe = (view.x + CHIP_HIT[0] / 2 + 6, view.y)
        self.app.set_touch_mode(False)
        self.assertIsNone(self.app.hit_part(probe))
        self.app.set_touch_mode(True)
        self.assertEqual(self.app.hit_part(probe), part.uid)

    def test_finger_drag_moves_part(self) -> None:
        part = self.app.add_part_at("bulb", (400, 300))
        view = self.app.views[part.uid]
        win_w, win_h = self.app.window.get_size()
        nx, ny = view.x / WIDTH, view.y / HEIGHT
        finger(self.app, "FINGERDOWN", nx, ny)
        finger(self.app, "FINGERMOTION", nx + 0.1, ny + 0.05, dx=0.1, dy=0.05)
        finger(self.app, "FINGERUP", nx + 0.1, ny + 0.05)
        self.assertGreater(view.x, 400)
        self.assertTrue(self.app.touch_mode)
        self.assertEqual(win_w, self.app.window.get_width())

    def test_double_tap_rotates_part(self) -> None:
        part = self.app.add_part_at("voltmeter", (500, 400))
        view = self.app.views[part.uid]
        nx, ny = view.x / WIDTH, view.y / HEIGHT
        for _ in range(2):
            finger(self.app, "FINGERDOWN", nx, ny)
            finger(self.app, "FINGERUP", nx, ny)
        self.assertEqual(view.angle % 360, 90)

    def test_keyboard_still_works_in_desktop_mode(self) -> None:
        self.app.add_part_at("resistor", (500, 400))
        self.app.selected_uid = list(self.app.circuit.parts)[0]
        key(self.app, pygame.K_r)
        self.assertEqual(self.app.views[self.app.selected_uid].angle % 360, 90)

    def test_touch_mode_draws_status_without_crash(self) -> None:
        self.app.set_touch_mode(True)
        self.app.load_demo(0)
        self.app.draw()
        self.assertTrue(self.app.touch_mode)

    def test_bulb_thermal_ui_mentions_filament(self) -> None:
        self.app.load_demo(0)
        bulb = next(p for p in self.app.circuit.parts.values() if p.kind == "bulb")
        self.app.selected_uid = bulb.uid
        self.app.draw()
        lines = " ".join(self.app._tooltip_lines(bulb))
        self.assertIn("灯丝", lines)
        self.assertIn("冷态", lines)
        self.assertGreater(bulb.temp, 0.5)

    def test_new_bulb_starts_cold_and_heats_up(self) -> None:
        self.app.circuit.clear()
        self.app.views.clear()
        battery = self.app.add_part_at("battery", (300, 300))
        bulb = self.app.add_part_at("bulb", (700, 300))
        circuit = self.app.circuit
        circuit.add_wire((battery.uid, 1), (bulb.uid, 0))
        circuit.add_wire((bulb.uid, 1), (battery.uid, 0))
        bulb.temp = 0.0  # 从冷态灯丝开始（加入元件时会先算到稳态）
        self.app.update(1.0 / 60.0)
        self.assertLess(bulb.temp, 0.2)
        self.assertGreater(abs(bulb.i), 1.5)  # 冷态冲击电流远大于稳态
        for _ in range(90):
            self.app.update(1.0 / 60.0)
        self.assertGreater(bulb.temp, 0.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
