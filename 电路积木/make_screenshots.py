"""make_screenshots.py — 无头渲染界面截图，用于开发时检查视觉效果。

用法： python make_screenshots.py
输出： screenshots/*.png
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame

from circuit_game import App


def save(app: App, name: str) -> None:
    app.update(0.016)
    app.draw()
    path = os.path.join("screenshots", name)
    pygame.image.save(app.screen, path)
    print("saved", path)


def part_of(app: App, kind: str):
    return next(p for p in app.circuit.parts.values() if p.kind == kind)


def clear_hover(app: App, pos=(400, 400)) -> None:
    app.mouse_pos = pos
    app.hover_uid = None
    app.hover_terminal = None
    app.hover_wire = None


def run_until(app: App, predicate, limit: int = 600) -> int:
    """推进仿真直到条件成立，返回用掉的帧数。"""
    for frame in range(limit):
        app.update(1.0 / 60.0)
        if predicate():
            return frame
    return limit


def main() -> None:
    os.makedirs("screenshots", exist_ok=True)
    app = App()

    # 1) 启动画面：示例电路 + 常显 U/I/R
    clear_hover(app)
    app.notice_text = ""
    save(app, "01_start.png")

    # 2) 悬浮在灯泡上：tooltip
    bulb = part_of(app, "bulb")
    view = app.views[bulb.uid]
    app.mouse_pos = (int(view.x), int(view.y))
    app._on_mouse_move(app.mouse_pos)
    save(app, "02_hover.png")

    # 3) 选中灯泡：右栏参数面板
    app.selected_uid = bulb.uid
    app.selected_wire = None
    clear_hover(app, (1000, 650))
    save(app, "03_panel.png")

    # 4) 从零件栏拖出电池的幽灵预览
    battery_slot = dict(app.palette_slots())["battery"]
    app.drag = {"mode": "palette", "part_kind": "battery", "start": battery_slot.center}
    app.mouse_pos = (520, 620)
    save(app, "04_drag_new.png")
    app.drag = None

    # 5) 断开开关后：灯泡熄灭
    switch = part_of(app, "switch")
    app.toggle_switch(switch.uid)
    app.notice_text = ""
    clear_hover(app, (10, 10))
    save(app, "05_switch_off.png")
    app.toggle_switch(switch.uid)
    app.notice_text = ""

    # 6) 帮助浮层
    app.help_open = True
    save(app, "06_help.png")
    app.help_open = False

    # 7) 连线状态
    app.load_demo(0)
    app.notice_text = ""
    battery = part_of(app, "battery")
    app.drag = {"mode": "wire", "start": (battery.uid, 1)}
    app.mouse_pos = (520, 520)
    app.hover_terminal = None
    app.selected_uid = None
    save(app, "07_wire_drag.png")
    app.drag = None
    app.notice_text = ""

    # 8) 显示方式：悬浮 —— 只有鼠标指向的零件显示 U/I/R
    bulbs = [p.uid for p in app.circuit.parts.values() if p.kind == "bulb"]
    app.display_mode = "hover"
    app.selected_uid = None
    first = app.views[bulbs[0]]
    app.mouse_pos = (int(first.x), int(first.y))
    app._on_mouse_move(app.mouse_pos)
    save(app, "08_display_hover.png")

    # 9) 显示方式：单击 —— 只有选中的零件显示 U/I/R
    app.display_mode = "click"
    clear_hover(app, (1000, 650))
    app.selected_uid = bulbs[1]
    save(app, "09_display_click.png")
    app.display_mode = "always"

    # 10) 电压表 + 电流表示例
    app.load_demo(1)
    app.notice_text = ""
    voltmeter = part_of(app, "voltmeter")
    app.selected_uid = voltmeter.uid
    clear_hover(app, (1000, 650))
    save(app, "10_meters.png")

    # 11) 电容 RC 充电中（τ=1s，充到 1.2s 左右）
    app.load_demo(2)
    app.notice_text = ""
    for _ in range(72):
        app.update(1.0 / 60.0)
    capacitor = part_of(app, "capacitor")
    app.selected_uid = capacitor.uid
    clear_hover(app, (1000, 650))
    save(app, "11_rc_charge.png")

    # 12) 剪刀工具悬停在一根导线上（高亮待剪）
    app.load_demo(0)
    app.notice_text = ""
    app.set_tool("cut")
    app.notice_text = ""
    points = app.wire_geometry(2)[4]
    middle = points[len(points) // 2]
    app.mouse_pos = (int(middle[0]), int(middle[1]))
    app._on_mouse_move(app.mouse_pos)
    app.selected_uid = None
    save(app, "12_scissors_hover.png")

    # 13) 剪断之后：断路 + 断口
    app.cut_wire(2)
    app.notice_text = "导线被剪断，电路断路了"
    app.selected_wire = None
    clear_hover(app, (1000, 650))
    save(app, "13_wire_cut.png")
    app.set_tool("select")

    # 14) 全真模式：电阻过载烧毁冒烟
    app.circuit.clear()
    app.views.clear()
    app.effects.clear()
    app.set_realistic(True)
    app.notice_text = ""
    battery = app.add_part_at("battery", (400, 380))
    resistor = app.add_part_at("resistor", (840, 380))
    app.circuit.add_wire((battery.uid, 1), (resistor.uid, 0))
    app.circuit.add_wire((resistor.uid, 1), (battery.uid, 0))
    app.selected_uid = None
    app.solve()
    run_until(app, lambda: resistor.damaged)
    run_until(app, lambda: len(app.effects.smoke) > 0 or len(app.effects.particles) > 0, 20)
    for _ in range(8):
        app.update(1.0 / 60.0)
    app.notice_text = ""
    clear_hover(app, (1000, 650))
    save(app, "14_burn.png")

    # 15) 全真模式：电容过压爆炸（火花 + 烟雾 + 闪光 + 震屏）
    app.circuit.clear()
    app.views.clear()
    app.effects.clear()
    app.set_realistic(True)
    app.notice_text = ""
    battery = app.add_part_at("battery", (420, 380))
    battery.value = 24.0
    battery.r_internal = 10.0
    capacitor = app.add_part_at("capacitor", (760, 380))
    app.circuit.add_wire((battery.uid, 1), (capacitor.uid, 0))
    app.circuit.add_wire((capacitor.uid, 1), (battery.uid, 0))
    app.solve()
    run_until(app, lambda: capacitor.damaged, 400)
    for _ in range(18):
        app.update(1.0 / 60.0)
    app.selected_uid = None
    clear_hover(app, (1000, 650))
    save(app, "15_explosion.png")

    # 16) 元件旋转：竖放的电池/电压表/电流表字标依然正立
    app.circuit.clear()
    app.views.clear()
    app.effects.clear()
    app.set_realistic(False)
    app.tool = "select"
    app.notice_text = ""
    battery = app.add_part_at("battery", (420, 380))
    app.views[battery.uid].angle = 90
    ammeter = app.add_part_at("ammeter", (640, 380))
    voltmeter = app.add_part_at("voltmeter", (760, 520))
    app.views[voltmeter.uid].angle = 90
    resistor = app.add_part_at("resistor", (900, 380))
    app.views[resistor.uid].angle = 90
    app.circuit.add_wire((battery.uid, 0), (ammeter.uid, 0))
    app.circuit.add_wire((ammeter.uid, 1), (resistor.uid, 0))
    app.circuit.add_wire((resistor.uid, 1), (battery.uid, 1))
    app.circuit.add_wire((ammeter.uid, 1), (voltmeter.uid, 0))
    app.circuit.add_wire((voltmeter.uid, 1), (battery.uid, 1))
    app.selected_uid = resistor.uid
    app.solve()
    app.notice_text = ""
    clear_hover(app, (1000, 650))
    save(app, "16_rotate.png")

    # 17) 电路图模式：由已组电路自动生成标准电路图
    app.circuit.clear()
    app.views.clear()
    app.effects.clear()
    app.board_ortho = False
    app.tool = "select"
    app.notice_text = ""
    app.load_demo(0)
    app.enter_schematic()
    app.notice_text = ""
    app.selected_uid = None
    clear_hover(app, (1000, 650))
    save(app, "17_schematic.png")

    # 18) 电路图里导出 SVG / 网表（文件写到工程目录，截图展示按钮反馈）
    app.notice_text = ""
    app.export_svg("circuit_diagram.svg")
    app.export_netlist("circuit_netlist.txt")
    save(app, "18_export.png")

    # 19) 生成电路：回到画板，正交导线 + 可仿真
    app.leave_schematic(apply=True)
    app.notice_text = ""
    app.selected_uid = None
    clear_hover(app, (1000, 650))
    save(app, "19_applied.png")

    # 20) 剪刀剪元件：点一下元件本体，它变成断路
    app.circuit.clear()
    app.views.clear()
    app.effects.clear()
    app.board_ortho = False
    app.load_demo(0)
    bulb = part_of(app, "bulb")
    view = app.views[bulb.uid]
    app.set_tool("cut")
    app.cut_part(bulb.uid)
    app.selected_uid = None
    app.mouse_pos = (int(view.x), int(view.y))
    app._on_mouse_move(app.mouse_pos)
    app.notice_text = ""
    app.update(0.016)
    app.draw()
    pygame.image.save(app.screen, os.path.join("screenshots", "20_cut_part.png"))
    print("saved screenshots/20_cut_part.png")

    # 21) 灯泡热惯性：刚放上去的冷灯丝（暗红、冲击电流大）
    app.load_demo(0)
    app.effects.clear()
    app.set_tool("select")
    app.board_ortho = False
    for p in app.circuit.parts.values():
        if p.kind == "bulb":
            p.temp = 0.0
    app.solve(transient=True) if False else None
    app.update(1.0 / 60.0)
    cold_bulb = part_of(app, "bulb")
    app.selected_uid = cold_bulb.uid
    app.mouse_pos = (1000, 650)
    app.hover_uid = None
    app.notice_text = (
        f"通电瞬间：灯丝 {cold_bulb.filament_k:.0f}K，电阻只有 {cold_bulb.resistance:.2f}Ω"
        f" → 电流 {abs(cold_bulb.i):.2f}A（稳态只有 0.5A）"
    )
    app.notice_until = app.time + 30
    app.draw()
    pygame.image.save(app.screen, os.path.join("screenshots", "21_thermal_cold.png"))
    print("saved screenshots/21_thermal_cold.png")

    # 22) 通电 2 秒后：灯丝烧到 ~2800K，阻值升高、电流回落、灯光变暖白
    app.notice_text = ""
    for _ in range(120):
        app.update(1.0 / 60.0)
    app.mouse_pos = (1000, 650)
    app.hover_uid = None
    save(app, "22_thermal_hot.png")

    # 23) 手机横屏窗口：等比缩放 + 黑边，触屏提示
    app.window = pygame.display.set_mode((1600, 720))
    app.set_touch_mode(True)
    app.mouse_pos = (400, 400)
    app.draw()
    pygame.image.save(app.window, os.path.join("screenshots", "23_mobile.png"))
    print("saved screenshots/23_mobile.png")
    app.window = pygame.display.set_mode((1280, 800))
    app.set_touch_mode(False)

    pygame.quit()


if __name__ == "__main__":
    main()
