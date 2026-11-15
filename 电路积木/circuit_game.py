"""电路积木 · Circuit Lab — 一个用 pygame 写的电路小游戏。

玩法：从左侧零件栏把元件拖到画布上，用导线把端点连起来；零件下方直接显示
U / I / R（也可切换成悬浮或单击显示）。点击开关可以通断电路，灯泡会真的亮起来。

新增：
    * 滑动变阻器、电压表、电流表、电容（电容有真实的 RC 充放电过程）
    * 剪刀工具：点击导线就剪断，模拟断路故障
    * 全真模拟模式：过载的元件会发热、烧毁甚至爆炸，导线过流会被烧断

运行：
    python circuit_game.py

电路计算全部在 circuit_core.py 里完成，这个文件只负责界面和交互。
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from typing import Dict, List, Optional, Tuple

import pygame

from circuit_core import (
    AMMETER_R,
    CAPACITOR_RATED_V,
    CAPACITY_DEFAULT,
    DAMAGE_BURNED,
    DAMAGE_CUT,
    DAMAGE_EXPLODED,
    DAMAGE_OK,
    MIN_RESISTANCE,
    PART_DEFAULTS,
    PART_LABELS,
    PART_ORDER,
    RHEOSTAT_MAX,
    VOLTMETER_R,
    Circuit,
    Part,
    Solution,
    fmt_capacitance,
    fmt_current,
    fmt_power,
    fmt_resistance,
    fmt_si,
    fmt_voltage,
)
import schematic

# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 1280, 800
FPS = 60
TOOLBAR_H = 58
PALETTE_W = 210
PANEL_W = 272
STATUS_H = 30
CANVAS_RECT = pygame.Rect(
    PALETTE_W, TOOLBAR_H, WIDTH - PALETTE_W - PANEL_W, HEIGHT - TOOLBAR_H - STATUS_H
)
PANEL_RECT = pygame.Rect(PALETTE_W + CANVAS_RECT.w, TOOLBAR_H, PANEL_W, CANVAS_RECT.h)
PALETTE_RECT = pygame.Rect(0, TOOLBAR_H, PALETTE_W, CANVAS_RECT.h)
STATUS_RECT = pygame.Rect(0, HEIGHT - STATUS_H, WIDTH, STATUS_H)

TERMINAL_X = 60          # 端点到零件中心的距离
CHIP_W, CHIP_H = 100, 64
CHIP_HIT = (56, 38)      # 点选判定用的半宽/半高
TERMINAL_HIT_R = 16
WIRE_HIT_R = 8

PANEL_READOUT_TOP = PANEL_RECT.top + 84
PANEL_CONTENT_TOP = PANEL_RECT.top + 246

SAVE_FILE = "circuit_save.json"
FONT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "NotoSansSC-Subset.ttf")
WINDOW_BG = (16, 18, 24)          # 缩放留黑边的颜色
TOUCH_HIT_SCALE = 1.7             # 触屏模式把点击判定放大一点
DIAGRAM_SVG = "circuit_diagram.svg"
NETLIST_FILE = "circuit_netlist.txt"
SCHEMATIC_GRID = 24
SCHEMATIC_BG = (253, 253, 254)
SCHEMATIC_GRID_LINE = (238, 240, 246)

# ---------------------------------------------------------------------------
# 仿真参数
# ---------------------------------------------------------------------------
SIM_DT = 1.0 / 240.0      # 电容瞬态的时间步长（秒）
SIM_STEP_BUDGET = 10      # 每帧最多补算多少步，防止卡顿
HEAT_RATE = 1.7           # 过载时每秒累积的热量
COOL_RATE = 0.6           # 正常时每秒散掉的热量
BATTERY_MAX_CURRENT = 6.0   # 电池的安全电流（A）
AMMETER_MAX_CURRENT = 3.0   # 电流表量程（A）
WIRE_MAX_CURRENT = 4.0      # 导线安全电流（A）

# ---------------------------------------------------------------------------
# 配色
# ---------------------------------------------------------------------------
BG = (250, 251, 254)
PALETTE_BG = (245, 247, 252)
PANEL_BG = (255, 255, 255)
CARD_BG = (255, 255, 255)
BORDER = (226, 230, 238)
GRID_DOT = (232, 235, 242)
TEXT = (44, 50, 64)
MUTED = (139, 147, 163)
ACCENT = (62, 116, 230)
DANGER = (214, 66, 62)
WARN = (219, 140, 46)
GOOD = (34, 150, 104)
BADGE_BG = (38, 44, 58)
BADGE_TEXT = (240, 243, 250)
SELECT_COLOR = (62, 116, 230)
TOOLTIP_BG = (255, 255, 255)
HELP_BG = (255, 255, 255)

WIRE_BASE = (176, 166, 156)
WIRE_ACTIVE = (232, 192, 118)
WIRE_HOT = (238, 150, 96)
WIRE_BROKEN = (196, 130, 120)
WIRE_SELECT = (62, 116, 230)

KIND_COLORS = {
    "battery": (224, 94, 94),
    "resistor": (72, 134, 214),
    "bulb": (240, 165, 45),
    "switch": (56, 178, 146),
    "rheostat": (146, 106, 210),
    "voltmeter": (46, 152, 190),
    "ammeter": (222, 132, 58),
    "capacitor": (118, 114, 198),
}
KIND_SOFT = {
    "battery": (253, 240, 240),
    "resistor": (238, 244, 253),
    "bulb": (253, 247, 234),
    "switch": (238, 250, 246),
    "rheostat": (246, 241, 253),
    "voltmeter": (237, 248, 252),
    "ammeter": (253, 246, 238),
    "capacitor": (243, 242, 252),
}
KIND_HINTS = {
    "battery": "电源，提供电动势",
    "resistor": "固定阻值，限制电流",
    "bulb": "会发光的电阻，额定 6V",
    "switch": "控制电路通断",
    "rheostat": "阻值可调的电阻",
    "voltmeter": "并联测电压，内阻很大",
    "ammeter": "串联测电流，内阻很小",
    "capacitor": "储存电荷，有充放电过程",
}
KIND_HOTKEYS = {
    "battery": pygame.K_1,
    "resistor": pygame.K_2,
    "bulb": pygame.K_3,
    "switch": pygame.K_4,
    "rheostat": pygame.K_5,
    "voltmeter": pygame.K_6,
    "ammeter": pygame.K_7,
    "capacitor": pygame.K_8,
}

DISPLAY_LABELS = {"always": "常显", "hover": "悬浮", "click": "单击"}


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def rotate_vec(x: float, y: float, angle: int) -> Tuple[float, float]:
    """把局部坐标按 angle 度旋转（屏幕坐标，y 轴向下）。"""
    if angle % 360 == 0:
        return x, y
    radians = math.radians(angle)
    cos_a, sin_a = math.cos(radians), math.sin(radians)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a


def bezier_points(p0, p1, p2, p3, steps: int = 30) -> List[Tuple[float, float]]:
    """三次贝塞尔曲线采样点。"""
    points = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        points.append((x, y))
    return points


def point_segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = clamp(((px - ax) * dx + (py - ay) * dy) / length2, 0.0, 1.0)
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def lerp_color(a, b, t: float):
    t = clamp(t, 0.0, 1.0)
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _bulb_glass_color(lit: int) -> Tuple[int, int, int]:
    """芯片里灯泡玻璃的填充色（lit 0..8，temp 越高越白）。"""
    t = clamp(lit / 8.0, 0.0, 1.0)
    if t < 0.4:
        return lerp_color((214, 88, 56), (255, 176, 92), t / 0.4)
    return lerp_color((255, 176, 92), (255, 240, 190), (t - 0.4) / 0.6)


def _bulb_glow_color(strength: float) -> Tuple[int, int, int]:
    """灯丝温度对应的光色：冷红 → 橙 → 暖白。"""
    t = clamp(strength, 0.0, 1.0)
    if t < 0.45:
        return lerp_color((255, 96, 52), (255, 176, 92), t / 0.45)
    return lerp_color((255, 176, 92), (255, 248, 220), (t - 0.45) / 0.55)


def fmt_u_display(value: Optional[float]) -> str:
    """电压显示：接近 0 时用 ≈0，避免出现 923µV 这样的噪声。"""
    if value is None:
        return "—"
    if abs(value) < 1e-2:
        return "≈0"
    return "=" + fmt_voltage(value)


def fmt_i_display(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if abs(value) < 1e-4:
        return "≈0"
    return "=" + fmt_current(value)


def fmt_cap_display(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return "=" + fmt_capacitance(value)


# ---------------------------------------------------------------------------
# 特效：火花、烟雾、冲击波、白色闪光、震屏
# ---------------------------------------------------------------------------
class Effects:
    """全真模式下燃烧/爆炸用的粒子系统。坐标是屏幕绝对坐标。"""

    def __init__(self) -> None:
        self.particles: List[dict] = []
        self.smoke: List[dict] = []
        self.rings: List[dict] = []
        self.texts: List[dict] = []
        self.flash_alpha = 0.0
        self.flash_color = (255, 236, 190)
        self.shake = 0.0
        self._layer: Optional[pygame.Surface] = None

    # -- 生成 --------------------------------------------------------------
    def clear(self) -> None:
        self.particles.clear()
        self.smoke.clear()
        self.rings.clear()
        self.texts.clear()
        self.flash_alpha = 0.0
        self.shake = 0.0

    def spark_burst(self, pos, count: int = 18, speed: float = 240) -> None:
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            power = random.uniform(0.25, 1.0) * speed
            self.particles.append(
                {
                    "x": pos[0],
                    "y": pos[1],
                    "vx": math.cos(angle) * power,
                    "vy": math.sin(angle) * power - 40,
                    "life": random.uniform(0.28, 0.7),
                    "max": 0.7,
                    "size": random.uniform(1.6, 3.6),
                    "color": random.choice(
                        [(255, 224, 130), (255, 170, 70), (255, 244, 210), (255, 120, 60)]
                    ),
                    "gravity": 420.0,
                }
            )

    def smoke_puff(self, pos, radius: float = 26, life: float = 1.6) -> None:
        for _ in range(3):
            self.smoke.append(
                {
                    "x": pos[0] + random.uniform(-12, 12),
                    "y": pos[1] + random.uniform(-10, 10),
                    "r": radius * random.uniform(0.55, 1.0),
                    "life": life * random.uniform(0.7, 1.0),
                    "max": life,
                    "vx": random.uniform(-16, 16),
                    "vy": random.uniform(-40, -18),
                }
            )

    def shockwave(self, pos, radius: float = 20) -> None:
        self.rings.append({"x": pos[0], "y": pos[1], "r": radius, "life": 0.5, "max": 0.5})

    def float_text(self, pos, text: str, color=(255, 120, 60), size: int = 18) -> None:
        self.texts.append(
            {"x": pos[0], "y": pos[1], "text": text, "color": color, "size": size,
             "life": 1.1, "max": 1.1}
        )

    def flash(self, alpha: float = 150, color=(255, 236, 190)) -> None:
        self.flash_color = color
        self.flash_alpha = max(self.flash_alpha, alpha)

    def add_shake(self, magnitude: float) -> None:
        self.shake = min(14.0, max(self.shake, magnitude))

    # -- 更新 --------------------------------------------------------------
    def update(self, dt: float) -> None:
        for particle in self.particles:
            particle["vy"] += particle["gravity"] * dt
            particle["x"] += particle["vx"] * dt
            particle["y"] += particle["vy"] * dt
            particle["life"] -= dt
        self.particles = [p for p in self.particles if p["life"] > 0]

        for puff in self.smoke:
            puff["x"] += puff["vx"] * dt
            puff["y"] += puff["vy"] * dt
            puff["r"] += 26 * dt
            puff["life"] -= dt
        self.smoke = [p for p in self.smoke if p["life"] > 0]

        for ring in self.rings:
            ring["life"] -= dt
            ring["r"] += 340 * dt
        self.rings = [r for r in self.rings if r["life"] > 0]

        for text in self.texts:
            text["y"] -= 34 * dt
            text["life"] -= dt
        self.texts = [t for t in self.texts if t["life"] > 0]

        if self.flash_alpha > 0:
            self.flash_alpha = max(0.0, self.flash_alpha - 520 * dt)
        if self.shake > 0:
            self.shake = max(0.0, self.shake - 26 * dt)

    def offset(self) -> Tuple[float, float]:
        if self.shake < 0.25:
            return 0.0, 0.0
        magnitude = min(10.0, self.shake)
        return random.uniform(-magnitude, magnitude), random.uniform(-magnitude, magnitude)

    # -- 绘制 --------------------------------------------------------------
    def draw(self, screen: pygame.Surface, fonts: "FontBook") -> None:
        if not (self.particles or self.smoke or self.rings or self.texts):
            return
        if self._layer is None:
            self._layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        layer = self._layer
        layer.fill((0, 0, 0, 0))

        for puff in self.smoke:
            ratio = clamp(puff["life"] / puff["max"], 0.0, 1.0)
            alpha = int(120 * ratio)
            shade = int(150 - 60 * ratio)
            pygame.draw.circle(
                layer,
                (shade, shade, shade, alpha),
                (int(puff["x"]), int(puff["y"])),
                int(puff["r"]),
            )

        for ring in self.rings:
            ratio = clamp(ring["life"] / ring["max"], 0.0, 1.0)
            alpha = int(170 * ratio)
            pygame.draw.circle(
                layer,
                (255, 210, 150, alpha),
                (int(ring["x"]), int(ring["y"])),
                int(ring["r"]),
                max(1, int(6 * ratio)),
            )

        for particle in self.particles:
            alpha = int(255 * clamp(particle["life"] / 0.35, 0.0, 1.0))
            pygame.draw.circle(
                layer,
                (*particle["color"], alpha),
                (int(particle["x"]), int(particle["y"])),
                max(1, int(particle["size"])),
            )

        screen.blit(layer, (0, 0))

        for text in self.texts:
            ratio = clamp(text["life"] / text["max"], 0.0, 1.0)
            surface = fonts.text(text["text"], text["size"], text["color"], bold=True)
            surface.set_alpha(int(255 * ratio))
            screen.blit(
                surface,
                surface.get_rect(center=(int(text["x"]), int(text["y"]))),
            )


# ---------------------------------------------------------------------------
# 字体与视图
# ---------------------------------------------------------------------------
class FontBook:
    """加载系统中文字体，缓存不同字号。"""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[int, bool], pygame.font.Font] = {}
        self._path = self._pick_font()

    @staticmethod
    def _pick_font() -> Optional[str]:
        # 优先用包里自带的字体（安卓上没有微软雅黑）
        if os.path.exists(FONT_FILE):
            return FONT_FILE
        folder = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "msjh.ttc"):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return path
        return None

    def font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        cached = self._cache.get(key)
        if cached is None:
            if self._path is not None:
                cached = pygame.font.Font(self._path, size)
            else:
                cached = pygame.font.SysFont("microsoftyahei,simhei,arial", size, bold=bold)
            self._cache[key] = cached
        return cached

    def text(self, text: str, size: int = 15, color=TEXT, bold: bool = False) -> pygame.Surface:
        return self.font(size, bold).render(str(text), True, color)


class View:
    """零件在画布上的位置与角度（不进电路模型）。"""

    __slots__ = ("x", "y", "angle")

    def __init__(self, x: float, y: float, angle: int = 0) -> None:
        self.x = x
        self.y = y
        self.angle = angle


# ---------------------------------------------------------------------------
# 应用主体
# ---------------------------------------------------------------------------
class App:
    def __init__(self, start_demo: bool = True) -> None:
        pygame.init()
        self.android = bool(os.environ.get("ANDROID_ARGUMENT")) or sys.platform == "android"
        flags = pygame.FULLSCREEN if self.android else pygame.RESIZABLE
        self.window = pygame.display.set_mode((WIDTH, HEIGHT), flags)
        # 所有绘制都画在固定 1280x800 的逻辑画布上，再等比缩放到真实窗口，
        # 这样手机 / 不同分辨率的屏幕都能用同一套布局。
        self.screen = pygame.Surface((WIDTH, HEIGHT)).convert()
        pygame.display.set_caption("电路积木 · Circuit Lab")
        self.clock = pygame.time.Clock()
        self.fonts = FontBook()
        self.viewport = pygame.Rect(0, 0, WIDTH, HEIGHT)
        self.touch_mode = self.android
        self._touch_start: Optional[Tuple[float, float]] = None
        self._last_tap = (0.0, None)
        self._mouse_ignore_until = 0.0
        self._fullscreen = self.android

        self.circuit = Circuit()
        self.views: Dict[int, View] = {}
        self.mode = "board"                  # board / schematic
        self.board_views: Dict[int, View] = {}  # 进入电路图模式前的画布布局
        self.board_ortho = False             # 由电路图「生成电路」后，画板也用正交走线

        self.selected_uid: Optional[int] = None
        self.selected_wire: Optional[int] = None
        self.hover_uid: Optional[int] = None
        self.hover_terminal: Optional[Tuple[int, int]] = None
        self.hover_wire: Optional[int] = None

        self.sim_on = True
        self.display_mode = "always"      # always / hover / click
        self.realistic = False            # 全真模拟
        self.tool = "select"              # select / cut
        self.drag: Optional[dict] = None
        self.mouse_pos: Tuple[float, float] = (0.0, 0.0)

        self.notice_text = ""
        self.notice_until = 0.0
        self.help_open = False
        self.solution: Optional[Solution] = None
        self.time = 0.0

        self.effects = Effects()
        self.wire_heat: Dict[Tuple, float] = {}
        self.sim_accum = 0.0
        self.demo_index = 0
        self.palette_scroll = 0.0
        self.running = True

        self._chip_cache: Dict[Tuple, pygame.Surface] = {}
        self._icon_cache: Dict[str, pygame.Surface] = {}
        self._glow_cache: List[Optional[pygame.Surface]] = [None] * 17
        self._grid_surface = self._make_grid()
        self._schematic_grid: Optional[pygame.Surface] = None

        pygame.mouse.set_visible(not self.touch_mode)

        if start_demo:
            self.load_demo(0)
        else:
            self.solve()

    # -- 窗口缩放与坐标换算 -------------------------------------------------
    def _compute_viewport(self) -> pygame.Rect:
        """逻辑画布在窗口里的目标矩形（等比缩放 + 居中留边）。"""
        win_w, win_h = self.window.get_size()
        if (win_w, win_h) == (WIDTH, HEIGHT):
            return pygame.Rect(0, 0, WIDTH, HEIGHT)
        scale = min(win_w / WIDTH, win_h / HEIGHT)
        size = (max(1, int(WIDTH * scale)), max(1, int(HEIGHT * scale)))
        return pygame.Rect((win_w - size[0]) // 2, (win_h - size[1]) // 2, size[0], size[1])

    def _present(self) -> None:
        """把逻辑画布缩放到窗口并显示。"""
        self.viewport = self._compute_viewport()
        if self.viewport.size == (WIDTH, HEIGHT) and self.viewport.topleft == (0, 0):
            self.window.blit(self.screen, (0, 0))
        else:
            scaled = pygame.transform.smoothscale(self.screen, self.viewport.size)
            self.window.fill(WINDOW_BG)
            self.window.blit(scaled, self.viewport.topleft)
        pygame.display.flip()

    def _logical_pos(self, pos) -> Tuple[float, float]:
        """窗口坐标 → 逻辑画布坐标（触屏与缩放都要用）。"""
        self.viewport = self._compute_viewport()
        scale = self.viewport.w / WIDTH
        if scale <= 0:
            return float(pos[0]), float(pos[1])
        return (
            (pos[0] - self.viewport.x) / scale,
            (pos[1] - self.viewport.y) / scale,
        )

    def toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.window = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
        else:
            self.window = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)

    def set_touch_mode(self, enabled: bool) -> None:
        self.touch_mode = enabled
        pygame.mouse.set_visible(not enabled)

    # -- 基础资源 ----------------------------------------------------------
    def _make_grid(self) -> pygame.Surface:
        surface = pygame.Surface(CANVAS_RECT.size)
        surface.fill(BG)
        step = 24
        for y in range(step // 2, surface.get_height(), step):
            for x in range(step // 2, surface.get_width(), step):
                surface.set_at((x, y), GRID_DOT)
        return surface

    def _make_schematic_grid(self) -> pygame.Surface:
        """电路图模式的方格纸背景。"""
        surface = pygame.Surface(CANVAS_RECT.size)
        surface.fill(SCHEMATIC_BG)
        width, height = surface.get_size()
        step = SCHEMATIC_GRID
        for x in range(step, width, step):
            pygame.draw.line(surface, SCHEMATIC_GRID_LINE, (x, 0), (x, height))
        for y in range(step, height, step):
            pygame.draw.line(surface, SCHEMATIC_GRID_LINE, (0, y), (width, y))
        return surface

    def _build_glow_cache(self, level: int) -> pygame.Surface:
        """按需渲染某一级灯泡/发光元件的光晕（低分辨率逐像素渐变，再放大）。"""
        level = max(0, min(16, level))
        cached = self._glow_cache[level]
        if cached is not None:
            return cached
        size = 320
        low = 160
        half = (low - 1) / 2.0
        edge = low / 2.0 - 2.0
        strength = level / 16.0
        glow_color = _bulb_glow_color(strength)
        small = pygame.Surface((low, low), pygame.SRCALPHA)
        if strength > 0.001:
            for y in range(low):
                dy = (y - half) / edge
                dy2 = dy * dy
                for x in range(low):
                    dx = (x - half) / edge
                    r = math.sqrt(dx * dx + dy2)
                    if r >= 1.0:
                        continue
                    halo = (1.0 - r) ** 1.6
                    core = max(0.0, 1.0 - r / 0.40) ** 1.6
                    alpha = int(min(1.0, halo * 0.80 + core * 0.45) * 200 * strength)
                    if alpha > 0:
                        small.set_at((x, y), (*glow_color, alpha))
        surface = pygame.transform.smoothscale(small, (size, size))
        self._glow_cache[level] = surface
        return surface

    # -- 查询 --------------------------------------------------------------
    def selected_part(self) -> Optional[Part]:
        if self.selected_uid is None:
            return None
        return self.circuit.parts.get(self.selected_uid)

    def terminal_pos(self, uid: int, terminal: int) -> Tuple[float, float]:
        view = self.views[uid]
        local_x = -TERMINAL_X if terminal == 0 else TERMINAL_X
        dx, dy = rotate_vec(local_x, 0, view.angle)
        return view.x + dx, view.y + dy

    def terminal_dir(self, uid: int, terminal: int) -> Tuple[float, float]:
        view = self.views[uid]
        local_x = -1.0 if terminal == 0 else 1.0
        return rotate_vec(local_x, 0, view.angle)

    def hit_part(self, pos) -> Optional[int]:
        mx, my = pos
        for uid in reversed(list(self.circuit.parts)):
            view = self.views.get(uid)
            if view is None:
                continue
            lx, ly = rotate_vec(mx - view.x, my - view.y, -view.angle)
            pad = TOUCH_HIT_SCALE if self.touch_mode else 1.0
            if abs(lx) <= CHIP_HIT[0] / 2 * pad and abs(ly) <= CHIP_HIT[1] / 2 * pad:
                return uid
        return None

    def hit_terminal(self, pos) -> Optional[Tuple[int, int]]:
        mx, my = pos
        for uid in reversed(list(self.circuit.parts)):
            if uid not in self.views:
                continue
            for terminal in (0, 1):
                tx, ty = self.terminal_pos(uid, terminal)
                radius = TERMINAL_HIT_R * (TOUCH_HIT_SCALE if self.touch_mode else 1.0)
                if math.hypot(mx - tx, my - ty) <= radius:
                    return uid, terminal
        return None

    def snap(self, pos) -> Tuple[float, float]:
        """电路图模式下让零件对齐到方格。"""
        x, y = pos
        if self.mode != "schematic":
            return x, y
        x = CANVAS_RECT.left + round((x - CANVAS_RECT.left) / SCHEMATIC_GRID) * SCHEMATIC_GRID
        y = CANVAS_RECT.top + round((y - CANVAS_RECT.top) / SCHEMATIC_GRID) * SCHEMATIC_GRID
        return x, y

    def wire_geometry(self, index: int):
        if not (0 <= index < len(self.circuit.wires)):
            return None
        a, b = self.circuit.wires[index]
        if a[0] not in self.views or b[0] not in self.views:
            return None
        p0 = self.terminal_pos(*a)
        p3 = self.terminal_pos(*b)
        d0 = self.terminal_dir(*a)
        d3 = self.terminal_dir(*b)
        if self.mode == "schematic" or self.board_ortho:
            points = schematic.wire_route(p0, d0, p3, d3)
            return p0, p0, p3, p3, points
        distance = math.hypot(p3[0] - p0[0], p3[1] - p0[1])
        k = clamp(distance * 0.45, 36, 140)
        p1 = (p0[0] + d0[0] * k, p0[1] + d0[1] * k)
        p2 = (p3[0] + d3[0] * k, p3[1] + d3[1] * k)
        return p0, p1, p2, p3, bezier_points(p0, p1, p2, p3)

    def hit_wire(self, pos) -> Optional[int]:
        mx, my = pos
        for index in range(len(self.circuit.wires) - 1, -1, -1):
            geometry = self.wire_geometry(index)
            if geometry is None:
                continue
            points = geometry[4]
            for i in range(len(points) - 1):
                ax, ay = points[i]
                bx, by = points[i + 1]
                radius = WIRE_HIT_R * (TOUCH_HIT_SCALE if self.touch_mode else 1.0)
                if point_segment_distance(mx, my, ax, ay, bx, by) <= radius:
                    return index
        return None

    def terminal_wire_count(self, uid: int, terminal: int) -> int:
        count = 0
        for a, b in self.circuit.wires:
            if a == (uid, terminal) or b == (uid, terminal):
                count += 1
        return count

    # -- 布局 --------------------------------------------------------------
    def toolbar_buttons(self) -> List[dict]:
        if self.mode == "schematic":
            labels = [
                ("back", "返回画板", False),
                ("tidy", "自动整理", False),
                ("export_svg", "导出 SVG", False),
                ("netlist", "导出网表", False),
                ("apply", "生成电路", True),
                ("clear", "清空", False),
                ("help", "帮助", False),
            ]
        else:
            labels = [
                ("sim", "暂停" if self.sim_on else "继续", self.sim_on),
                ("display", f"显示：{DISPLAY_LABELS[self.display_mode]}", False),
                ("realistic", "全真：开" if self.realistic else "全真：关", self.realistic),
                ("scissors", "剪刀", self.tool == "cut"),
                ("schematic", "电路图", False),
                ("demo", "示例", False),
                ("clear", "清空", False),
                ("repair", "检修", False),
                ("save", "保存", False),
                ("load", "读取", False),
                ("help", "帮助", False),
            ]
        buttons = []
        x = PALETTE_W + 16
        y = 11
        for ident, label, active in labels:
            width = self.fonts.font(15, True).size(label)[0] + 26
            rect = pygame.Rect(x, y, width, 36)
            buttons.append({"id": ident, "label": label, "rect": rect, "active": active})
            x += width + 8
        return buttons

    def palette_content_rect(self) -> pygame.Rect:
        top = TOOLBAR_H + 74
        bottom = PALETTE_RECT.bottom - 118 - 8
        return pygame.Rect(PALETTE_RECT.x, top, PALETTE_RECT.w, bottom - top)

    def _max_palette_scroll(self) -> float:
        area = self.palette_content_rect()
        gap = 10
        height = 100
        rows = (len(PART_ORDER) + 1) // 2
        content_height = rows * height + (rows - 1) * gap
        return max(0.0, content_height - area.height)

    def palette_slots(self) -> List[Tuple[str, pygame.Rect]]:
        gap = 10
        width = (PALETTE_W - 28 - gap) // 2
        height = 100
        area = self.palette_content_rect()
        slots = []
        for index, kind in enumerate(PART_ORDER):
            col = index % 2
            row = index // 2
            rect = pygame.Rect(
                14 + col * (width + gap),
                int(area.top - self.palette_scroll + row * (height + gap)),
                width,
                height,
            )
            slots.append((kind, rect))
        return slots

    def delete_zone_rect(self) -> pygame.Rect:
        return pygame.Rect(14, PALETTE_RECT.bottom - 118, PALETTE_W - 28, 104)

    def slider_track(self, control: dict) -> pygame.Rect:
        rect = control["rect"]
        return pygame.Rect(rect.x + 10, rect.y + 36, rect.w - 20, 8)

    def _slider_control(self, ident, label, value, series, unit, field, y) -> dict:
        return {
            "id": ident,
            "type": "slider",
            "rect": pygame.Rect(PANEL_RECT.x + 20, y, PANEL_W - 40, 58),
            "label": label,
            "value": value,
            "series": series,
            "unit": unit,
            "field": field,
        }

    def panel_controls(self) -> List[dict]:
        part = self.selected_part()
        controls: List[dict] = []
        y = PANEL_CONTENT_TOP
        if part is not None:
            if part.kind == "battery":
                controls.append(
                    self._slider_control(
                        "emf", "电动势 E", part.value,
                        [round(i * 0.5, 1) for i in range(2, 49)], "V", "value", y,
                    )
                )
                y += 64
                controls.append(
                    self._slider_control(
                        "rin", "内阻 r", part.r_internal,
                        [round(i * 0.1, 1) for i in range(1, 31)], "Ω", "r_internal", y,
                    )
                )
            elif part.kind == "resistor":
                controls.append(
                    self._slider_control(
                        "r", "阻值 R", part.value,
                        [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 39, 47, 51, 68,
                         82, 100, 120, 150, 200, 300, 470, 510, 680, 820, 1000],
                        "Ω", "value", y,
                    )
                )
            elif part.kind == "bulb":
                controls.append(
                    self._slider_control(
                        "r", "灯丝电阻 R", part.value,
                        [2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 24, 30, 40, 50, 60],
                        "Ω", "value", y,
                    )
                )
            elif part.kind == "rheostat":
                controls.append(
                    self._slider_control(
                        "r", "阻值 R", part.value,
                        [float(i) for i in range(1, int(RHEOSTAT_MAX) + 1)], "Ω", "value", y,
                    )
                )
            elif part.kind == "capacitor":
                controls.append(
                    self._slider_control(
                        "c", "容量 C", part.value,
                        [0.001, 0.002, 0.0033, 0.0047, 0.01, 0.022, 0.033, 0.047,
                         0.068, 0.1, 0.22, 0.47, 1.0],
                        "F", "value", y,
                    )
                )
                y += 64
                controls.append(
                    self._slider_control(
                        "rated", "耐压 U_max", part.rated_v,
                        [6.0, 10.0, 16.0, 25.0, 35.0, 50.0], "V", "rated_v", y,
                    )
                )
            elif part.kind == "switch":
                label = "断开开关" if part.closed else "闭合开关"
                controls.append(
                    {
                        "id": "toggle",
                        "type": "button",
                        "rect": pygame.Rect(PANEL_RECT.x + 20, y, PANEL_W - 40, 44),
                        "label": label,
                        "accent": part.closed,
                    }
                )
            if part.damaged:
                controls.append(
                    {
                        "id": "replace",
                        "type": "button",
                        "rect": pygame.Rect(
                            PANEL_RECT.x + 20, PANEL_RECT.bottom - 106, PANEL_W - 40, 40
                        ),
                        "label": "更换零件",
                        "accent": True,
                    }
                )
        if part is not None:
            controls.append(
                {
                    "id": "rotate",
                    "type": "button",
                    "rect": pygame.Rect(PANEL_RECT.x + 20, PANEL_RECT.bottom - 156, PANEL_W - 40, 38),
                    "label": "旋转 90°（R）",
                }
            )
            controls.append(
                {
                    "id": "delete",
                    "type": "button",
                    "rect": pygame.Rect(PANEL_RECT.x + 20, PANEL_RECT.bottom - 58, PANEL_W - 40, 40),
                    "label": "删除零件",
                    "danger": True,
                }
            )
        elif self.selected_wire is not None:
            broken = self.circuit.is_wire_broken(self.selected_wire)
            controls.append(
                {
                    "id": "repair_wire" if broken else "cut_wire",
                    "type": "button",
                    "rect": pygame.Rect(PANEL_RECT.x + 20, PANEL_RECT.bottom - 106, PANEL_W - 40, 40),
                    "label": "修复导线" if broken else "剪断导线",
                    "accent": not broken,
                }
            )
            controls.append(
                {
                    "id": "delete_wire",
                    "type": "button",
                    "rect": pygame.Rect(PANEL_RECT.x + 20, PANEL_RECT.bottom - 58, PANEL_W - 40, 40),
                    "label": "删除导线",
                    "danger": True,
                }
            )
        return controls

    # -- 提示与动作 --------------------------------------------------------
    def notice(self, text: str, duration: float = 2.4) -> None:
        self.notice_text = text
        self.notice_until = self.time + duration

    def _has_capacitors(self) -> bool:
        return any(p.kind == "capacitor" and not p.damaged for p in self.circuit.parts.values())

    def _has_thermal_bulbs(self) -> bool:
        return any(p.kind == "bulb" and not p.damaged for p in self.circuit.parts.values())

    def _needs_transient(self) -> bool:
        """有电容（充放电）或灯泡（灯丝热惯性）时按瞬态逐步推进。"""
        return self._has_capacitors() or self._has_thermal_bulbs()

    def solve(self) -> None:
        """重新计算电路。电路里有电容时按瞬态走一小步。"""
        self.solution = None
        if not self.sim_on:
            return
        if self._has_capacitors():
            self.solution = self.circuit.solve(SIM_DT)
        else:
            self.solution = self.circuit.solve()

    def add_part_at(self, kind: str, pos) -> Part:
        x, y = pos
        x = clamp(x, CANVAS_RECT.left + 70, CANVAS_RECT.right - 70)
        y = clamp(y, CANVAS_RECT.top + 62, CANVAS_RECT.bottom - 58)
        x, y = self.snap((x, y))
        part = self.circuit.add_part(kind)
        self.views[part.uid] = View(x, y)
        self.selected_uid = part.uid
        self.selected_wire = None
        self.solve()
        if kind == "bulb":
            # 新灯泡是冷的：从冷态开始由瞬态仿真加热，能看到开机电流冲击
            part.temp = 0.0
            self.solution = self.circuit.solve(SIM_DT)
        return part

    def delete_part(self, uid: int) -> None:
        part = self.circuit.parts.get(uid)
        if part is None:
            return
        label = part.label
        self.circuit.remove_part(uid)
        self.views.pop(uid, None)
        if self.selected_uid == uid:
            self.selected_uid = None
        if self.hover_uid == uid:
            self.hover_uid = None
        self.solve()
        self.notice(f"已删除{label} #{uid}")

    def delete_wire(self, index: int) -> None:
        if self.circuit.remove_wire(index):
            if self.selected_wire == index:
                self.selected_wire = None
            elif self.selected_wire is not None and self.selected_wire > index:
                self.selected_wire -= 1
            self.hover_wire = None
            self.solve()
            self.notice("已删除导线")

    def cut_part(self, uid: int) -> None:
        """剪刀剪断一个元件本体（断路，但没有烧毁痕迹，可检修恢复）。"""
        part = self.circuit.parts.get(uid)
        if part is None:
            return
        if part.damaged:
            self.notice(f"{part.label} #{uid} 已经断开了")
            return
        view = self.views.get(uid)
        part.state = DAMAGE_CUT
        part.heat = 0.0
        if view is not None:
            self.effects.spark_burst((view.x, view.y), count=14, speed=190)
            self.effects.float_text((view.x, view.y - 38), "断路", (200, 96, 70), 16)
        self.selected_uid = uid
        self.selected_wire = None
        self.solve()
        self.notice(f"{part.label} #{uid} 被剪断了，这一段电路断路")

    def cut_wire(self, index: int) -> None:
        if not (0 <= index < len(self.circuit.wires)):
            return
        if self.circuit.is_wire_broken(index):
            self.notice("这根导线已经断了")
            return
        geometry = self.wire_geometry(index)
        if not self.circuit.cut_wire(index):
            return
        self.selected_wire = index
        self.selected_uid = None
        if geometry is not None:
            points = geometry[4]
            middle = points[len(points) // 2]
            self.effects.spark_burst(middle, count=12, speed=170)
            self.effects.float_text((middle[0], middle[1] - 22), "咔嚓！", (210, 90, 70), 16)
        self.solve()
        self.notice("导线被剪断，电路断路了")

    def repair_wire(self, index: int) -> None:
        if self.circuit.repair_wire(index):
            self.solve()
            self.notice("导线已修复")

    def repair_all(self) -> None:
        count = self.circuit.repair_all()
        self.wire_heat.clear()
        self.solve()
        if count:
            self.notice(f"已修复 {count} 处损坏")
        else:
            self.notice("电路一切正常，没有需要修复的地方")

    def replace_part(self, uid: int) -> None:
        if self.circuit.replace_part(uid):
            self.solve()
            self.notice("已更换新零件")

    def toggle_switch(self, uid: int) -> None:
        part = self.circuit.parts.get(uid)
        if part is None or part.kind != "switch" or part.damaged:
            return
        part.closed = not part.closed
        self.solve()
        self.notice("开关已闭合" if part.closed else "开关已断开")

    def set_realistic(self, enabled: bool) -> None:
        if enabled == self.realistic:
            return
        self.realistic = enabled
        if not enabled:
            for part in self.circuit.parts.values():
                part.heat = 0.0
            self.wire_heat.clear()
        self.notice(
            "全真模拟：开，过载元件会发热烧毁" if enabled else "全真模拟：关，元件不会损坏"
        )

    def set_tool(self, mode: str) -> None:
        self.tool = "cut" if mode == "cut" else "select"
        self.notice("剪刀：点击导线剪断" if self.tool == "cut" else "回到选择模式")

    def rotate_selected(self) -> None:
        if self.selected_uid is None:
            return
        view = self.views.get(self.selected_uid)
        if view is None:
            return
        view.angle = (view.angle + 90) % 360

    # -- 电路图模式 --------------------------------------------------------
    def _refresh_schematic_layout(self) -> None:
        """按电路拓扑自动排一张整洁的电路图。"""
        positions = schematic.tidy_layout(
            self.circuit,
            (CANVAS_RECT.left, CANVAS_RECT.top, CANVAS_RECT.w, CANVAS_RECT.h),
        )
        self.views = {
            uid: View(x, y, angle) for uid, (x, y, angle) in positions.items()
        }

    def enter_schematic(self) -> None:
        """把当前电路自动排成电路图，并进入电路图模式。"""
        if self.mode == "schematic":
            return
        self.board_views = {
            uid: View(view.x, view.y, view.angle) for uid, view in self.views.items()
        }
        self._ortho_before = self.board_ortho
        self._refresh_schematic_layout()
        self.mode = "schematic"
        self.drag = None
        self.selected_uid = None
        self.selected_wire = None
        self.hover_uid = None
        self.hover_terminal = None
        self.hover_wire = None
        self.notice("电路图模式：可继续画/改电路，点「生成电路」应用到画板", 3.4)

    def leave_schematic(self, apply: bool = False) -> None:
        """回到画板。apply=True 时把电路图里的布局和电路一起带回画板。"""
        if self.mode != "schematic":
            return
        restored: Dict[int, View] = {}
        for uid in self.circuit.parts:
            if apply and uid in self.views:
                view = self.views[uid]
                restored[uid] = View(
                    clamp(view.x, CANVAS_RECT.left + 70, CANVAS_RECT.right - 70),
                    clamp(view.y, CANVAS_RECT.top + 62, CANVAS_RECT.bottom - 58),
                    view.angle,
                )
            elif uid in self.board_views:
                restored[uid] = self.board_views[uid]
            elif uid in self.views:
                view = self.views[uid]
                restored[uid] = View(
                    clamp(view.x, CANVAS_RECT.left + 70, CANVAS_RECT.right - 70),
                    clamp(view.y, CANVAS_RECT.top + 62, CANVAS_RECT.bottom - 58),
                    view.angle,
                )
        self.views = restored
        self.board_views = {}
        self.mode = "board"
        self.board_ortho = True if apply else getattr(self, "_ortho_before", False)
        self.drag = None
        self.selected_uid = None
        self.selected_wire = None
        self.hover_uid = None
        self.hover_terminal = None
        self.hover_wire = None
        self.solve()
        self.notice("已生成电路，回到画板" if apply else "已回到画板", 3.0)

    def schematic_positions(self) -> Dict[int, Tuple[float, float, int]]:
        """当前视图转成导出用的相对坐标（画布左上角为原点）。"""
        positions: Dict[int, Tuple[float, float, int]] = {}
        for uid, view in self.views.items():
            positions[uid] = (
                view.x - CANVAS_RECT.left,
                view.y - CANVAS_RECT.top,
                view.angle,
            )
        return positions

    def export_svg(self, path: str = DIAGRAM_SVG) -> str:
        svg = schematic.build_svg(
            self.circuit, self.schematic_positions(), CANVAS_RECT.w, CANVAS_RECT.h
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(svg)
        self.notice(f"已导出矢量电路图 {path}（SVG 可用浏览器打开）", 3.4)
        return path

    def export_netlist(self, path: str = NETLIST_FILE) -> str:
        text = schematic.build_netlist(self.circuit)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.notice(f"已导出文字网表 {path}", 3.4)
        return path

    # -- 示例电路 ----------------------------------------------------------
    def load_demo(self, index: Optional[int] = None) -> None:
        builders = (self._demo_parallel, self._demo_meters, self._demo_rc)
        if index is None:
            index = self.demo_index % len(builders)
            self.demo_index = (index + 1) % len(builders)
        self.circuit.clear()
        self.views.clear()
        self.board_views.clear()
        self.mode = "board"
        self.board_ortho = False
        self.selected_uid = None
        self.selected_wire = None
        self.hover_uid = None
        self.hover_terminal = None
        self.hover_wire = None
        self.wire_heat.clear()
        self.effects.clear()
        self.sim_accum = 0.0
        title = builders[index % len(builders)]()
        self.solve()
        self.notice(f"示例：{title}（再点「示例」换下一个）", 3.0)

    def _add_demo_part(self, kind: str, x: float, y: float, angle: int = 0, **params) -> Part:
        part = self.circuit.add_part(kind, **params)
        self.views[part.uid] = View(x, y, angle)
        return part

    def _demo_parallel(self) -> str:
        battery = self._add_demo_part("battery", 320, 430, 90)
        switch = self._add_demo_part("switch", 560, 300, 0)
        bulb1 = self._add_demo_part("bulb", 700, 430, 90)
        bulb2 = self._add_demo_part("bulb", 880, 430, 90)
        self.circuit.add_wire((battery.uid, 0), (switch.uid, 0))
        self.circuit.add_wire((switch.uid, 1), (bulb1.uid, 0))
        self.circuit.add_wire((switch.uid, 1), (bulb2.uid, 0))
        self.circuit.add_wire((bulb1.uid, 1), (bulb2.uid, 1))
        self.circuit.add_wire((bulb2.uid, 1), (battery.uid, 1))
        return "并联灯泡"

    def _demo_meters(self) -> str:
        battery = self._add_demo_part("battery", 330, 430, 90)
        switch = self._add_demo_part("switch", 500, 300, 0)
        ammeter = self._add_demo_part("ammeter", 680, 300, 0)
        resistor = self._add_demo_part("resistor", 860, 430, 90)
        voltmeter = self._add_demo_part("voltmeter", 860, 590, 0)
        self.circuit.add_wire((battery.uid, 0), (switch.uid, 0))
        self.circuit.add_wire((switch.uid, 1), (ammeter.uid, 0))
        self.circuit.add_wire((ammeter.uid, 1), (resistor.uid, 0))
        self.circuit.add_wire((resistor.uid, 1), (battery.uid, 1))
        self.circuit.add_wire((resistor.uid, 0), (voltmeter.uid, 0))
        self.circuit.add_wire((resistor.uid, 1), (voltmeter.uid, 1))
        return "电压表 + 电流表"

    def _demo_rc(self) -> str:
        battery = self._add_demo_part("battery", 330, 300, 0)
        switch = self._add_demo_part("switch", 520, 300, 0)
        resistor = self._add_demo_part("resistor", 720, 300, 0, value=100.0)
        capacitor = self._add_demo_part("capacitor", 900, 430, 90)
        self.circuit.add_wire((battery.uid, 0), (switch.uid, 0))
        self.circuit.add_wire((switch.uid, 1), (resistor.uid, 0))
        self.circuit.add_wire((resistor.uid, 1), (capacitor.uid, 0))
        self.circuit.add_wire((capacitor.uid, 1), (battery.uid, 1))
        return "电容 RC 充电（τ=1s）"

    # -- 存档 --------------------------------------------------------------
    def save(self, path: str = SAVE_FILE) -> bool:
        data = self.circuit.to_dict()
        # 电路图模式下保存画板的布局，读档后回到画板看到原来的样子
        layout = self.board_views if self.mode == "schematic" and self.board_views else self.views
        data["views"] = {
            str(uid): {"x": view.x, "y": view.y, "angle": view.angle}
            for uid, view in layout.items()
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
        except OSError:
            self.notice(f"保存失败：{os.path.basename(path)}")
            return False
        self.notice(f"已保存到 {os.path.basename(path)}", 2.5)
        return True

    def load(self, path: str = SAVE_FILE) -> bool:
        if not os.path.exists(path):
            self.notice(f"没有找到存档：{os.path.basename(path)}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            circuit = Circuit.from_dict(data)
        except (OSError, ValueError, KeyError, TypeError):
            self.notice("存档文件读不出来")
            return False

        self.circuit = circuit
        self.mode = "board"
        self.board_ortho = False
        self.board_views.clear()
        self.views.clear()
        default_x = clamp(CANVAS_RECT.centerx, CANVAS_RECT.left + 70, CANVAS_RECT.right - 70)
        default_y = clamp(CANVAS_RECT.centery, CANVAS_RECT.top + 62, CANVAS_RECT.bottom - 58)
        for uid in self.circuit.parts:
            self.views[uid] = View(default_x, default_y)
        for key, value in (data.get("views") or {}).items():
            try:
                uid = int(key)
            except (TypeError, ValueError):
                continue
            if uid in self.circuit.parts:
                self.views[uid] = View(
                    float(value.get("x", CANVAS_RECT.centerx)),
                    float(value.get("y", CANVAS_RECT.centery)),
                    int(value.get("angle", 0)),
                )
        self.selected_uid = None
        self.selected_wire = None
        self.hover_uid = None
        self.hover_terminal = None
        self.hover_wire = None
        self.wire_heat.clear()
        self.sim_accum = 0.0
        self.solve()
        self.notice(f"已读取 {os.path.basename(path)}", 2.5)
        return True

    # -- 全真模拟：发热与损坏 ----------------------------------------------
    def _overload_ratio(self, part: Part) -> float:
        """返回过载倍率，1.0 表示刚好在额定值上。"""
        if part.kind in ("bulb", "resistor", "rheostat"):
            return part.stress
        if part.kind == "battery":
            return abs(part.i) / BATTERY_MAX_CURRENT
        if part.kind == "ammeter":
            return abs(part.i) / AMMETER_MAX_CURRENT
        if part.kind == "capacitor":
            return abs(part.u) / max(part.rated_v, 0.1)
        return 0.0

    def _part_center(self, part: Part) -> Tuple[float, float]:
        view = self.views.get(part.uid)
        if view is None:
            return CANVAS_RECT.centerx, CANVAS_RECT.centery
        return view.x, view.y

    def _destroy_part(self, part: Part, state: str) -> None:
        if part.damaged:
            return
        part.state = state
        part.heat = 1.0
        center = self._part_center(part)
        if state == DAMAGE_EXPLODED:
            self.effects.spark_burst(center, count=46, speed=330)
            self.effects.smoke_puff(center, radius=42, life=2.2)
            self.effects.smoke_puff(center, radius=30, life=1.6)
            self.effects.shockwave(center, radius=26)
            self.effects.flash(140, (255, 226, 180))
            self.effects.add_shake(11.0)
            self.effects.float_text((center[0], center[1] - 46), "爆炸！", (228, 62, 48), 22)
            self.notice(f"{part.label} #{part.uid} 爆炸了！点「检修」或选中后更换", 3.0)
        else:
            self.effects.smoke_puff(center, radius=30, life=1.8)
            self.effects.flash(70, (255, 200, 130))
            self.effects.add_shake(3.5)
            self.effects.float_text((center[0], center[1] - 40), "烧毁", (200, 80, 60), 18)
            self.notice(f"{part.label} #{part.uid} 烧毁了！点「检修」或选中后更换", 3.0)
        self.solve()

    def _failure_mode(self, part: Part) -> str:
        if part.kind in ("battery", "capacitor", "ammeter"):
            return DAMAGE_EXPLODED
        return DAMAGE_BURNED

    def _update_damage(self, dt: float) -> None:
        if not self.realistic or not self.sim_on:
            return
        for part in list(self.circuit.parts.values()):
            if part.damaged:
                continue
            ratio = self._overload_ratio(part)
            if ratio > 1.0:
                # 电池短路时升温更快：让「电池爆炸」先于导线烧断，符合直觉
                rate = HEAT_RATE * (2.0 if part.kind == "battery" else 1.0)
                part.heat = min(1.0, part.heat + dt * rate * (ratio - 0.5))
                if part.heat > 0.35 and random.random() < dt * 6:
                    center = self._part_center(part)
                    self.effects.smoke_puff(center, radius=12, life=1.1)
            else:
                part.heat = max(0.0, part.heat - dt * COOL_RATE)
            if part.heat >= 1.0:
                self._destroy_part(part, self._failure_mode(part))

        if self.solution is None:
            return
        active = set(self.circuit.wires)
        self.wire_heat = {key: value for key, value in self.wire_heat.items() if key in active}
        for index, pair in enumerate(self.circuit.wires):
            if index >= len(self.solution.wire_currents):
                break
            if self.circuit.is_wire_broken(index):
                continue
            current = self.solution.wire_currents[index]
            heat = self.wire_heat.get(pair, 0.0)
            ratio = abs(current) / WIRE_MAX_CURRENT
            if ratio > 1.0:
                heat = min(1.0, heat + dt * HEAT_RATE * (ratio - 0.5))
                self.wire_heat[pair] = heat
                geometry = self.wire_geometry(index)
                if geometry is not None and heat > 0.4 and random.random() < dt * 8:
                    points = geometry[4]
                    middle = points[len(points) // 2]
                    self.effects.spark_burst(middle, count=4, speed=90)
            else:
                heat = max(0.0, heat - dt * COOL_RATE)
                if heat > 0:
                    self.wire_heat[pair] = heat
                else:
                    self.wire_heat.pop(pair, None)
            if heat >= 1.0:
                geometry = self.wire_geometry(index)
                if self.circuit.cut_wire(index):
                    self.wire_heat.pop(pair, None)
                    if geometry is not None:
                        points = geometry[4]
                        middle = points[len(points) // 2]
                        self.effects.spark_burst(middle, count=20, speed=200)
                        self.effects.smoke_puff(middle, radius=16, life=1.2)
                        self.effects.float_text((middle[0], middle[1] - 20), "烧断！", (210, 90, 60), 16)
                    self.notice("导线过流被烧断了")
                    self.solve()
                    return

    # -- 时间推进 ----------------------------------------------------------
    def update(self, dt: float) -> None:
        dt = min(max(dt, 0.0), 0.05)
        self.time += dt
        if self.sim_on:
            if self._needs_transient():
                self.sim_accum = min(0.5, self.sim_accum + dt)
                steps = 0
                while self.sim_accum >= SIM_DT and steps < SIM_STEP_BUDGET:
                    self.solution = self.circuit.solve(SIM_DT)
                    self.sim_accum -= SIM_DT
                    steps += 1
            self._update_damage(dt)
        self.effects.update(dt)

    # -- 事件 --------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.VIDEORESIZE:
            # 窗口大小变了：下一帧按新尺寸重新算缩放
            self.viewport = self._compute_viewport()
        elif event.type == pygame.FINGERDOWN:
            self._on_finger_down(event)
        elif event.type == pygame.FINGERMOTION:
            self._on_finger_move(event)
        elif event.type == pygame.FINGERUP:
            self._on_finger_up(event)
        elif event.type == pygame.MOUSEMOTION:
            if time.time() >= self._mouse_ignore_until:
                self._on_mouse_move(self._logical_pos(event.pos))
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if time.time() >= self._mouse_ignore_until:
                self._on_mouse_down(self._logical_pos(event.pos), event.button)
        elif event.type == pygame.MOUSEBUTTONUP:
            if time.time() >= self._mouse_ignore_until:
                pos = self._logical_pos(event.pos)
                self._on_mouse_up(pos, event.button)
                if event.button == 1 and self.touch_mode:
                    self._handle_tap(pos)
        elif event.type == pygame.MOUSEWHEEL:
            self._on_wheel(event.y)
        elif event.type == pygame.KEYDOWN:
            self._on_key(event.key, getattr(event, "mod", 0))

    # -- 触屏 --------------------------------------------------------------
    def _finger_pos(self, event: pygame.event.Event) -> Tuple[float, float]:
        win_w, win_h = self.window.get_size()
        return self._logical_pos((event.x * win_w, event.y * win_h))

    def _on_finger_down(self, event: pygame.event.Event) -> None:
        self.set_touch_mode(True)
        self._mouse_ignore_until = time.time() + 1.0
        pos = self._finger_pos(event)
        self._touch_start = pos
        self._on_mouse_down(pos, 1)

    def _on_finger_move(self, event: pygame.event.Event) -> None:
        self._mouse_ignore_until = time.time() + 1.0
        self._on_mouse_move(self._finger_pos(event))

    def _on_finger_up(self, event: pygame.event.Event) -> None:
        self._mouse_ignore_until = time.time() + 1.0
        pos = self._finger_pos(event)
        start = self._touch_start
        self._touch_start = None
        self._on_mouse_up(pos, 1)
        if start is not None:
            moved = math.hypot(pos[0] - start[0], pos[1] - start[1])
            if moved < 18 and self.drag is None:
                self._handle_tap(pos)

    def _handle_tap(self, pos) -> None:
        """双击 / 双触点同一个元件 = 旋转 90°（手机上不用键盘也能转）。"""
        uid = self.hit_part(pos)
        if uid is None:
            self._last_tap = (0.0, None)
            return
        now = time.time()
        last_time, last_uid = self._last_tap
        if last_uid == uid and now - last_time < 0.45:
            self.selected_uid = uid
            self.rotate_selected()
            self._last_tap = (0.0, None)
        else:
            self._last_tap = (now, uid)

    def _over_palette(self, pos) -> bool:
        return PALETTE_RECT.collidepoint(pos)

    def _on_mouse_move(self, pos) -> None:
        self.mouse_pos = pos
        self.hover_uid = None
        self.hover_terminal = None
        self.hover_wire = None

        if self.drag is not None:
            mode = self.drag.get("mode")
            if mode == "part":
                uid = self.drag["uid"]
                view = self.views.get(uid)
                if view is not None:
                    offset_x, offset_y = self.drag["offset"]
                    new_x = clamp(
                        pos[0] - offset_x, CANVAS_RECT.left + 70, CANVAS_RECT.right - 70
                    )
                    new_y = clamp(
                        pos[1] - offset_y, CANVAS_RECT.top + 62, CANVAS_RECT.bottom - 58
                    )
                    view.x, view.y = self.snap((new_x, new_y))
                    self.drag["moved"] = True
                return
            if mode == "slider":
                self._apply_slider(self.drag["control"], int(pos[0]))
                return
            if mode == "wire":
                self.hover_terminal = self.hit_terminal(pos)
                return

        if self.help_open:
            return

        if CANVAS_RECT.collidepoint(pos):
            self.hover_terminal = self.hit_terminal(pos)
            self.hover_uid = self.hit_part(pos)
            if self.hover_uid is None:
                self.hover_wire = self.hit_wire(pos)

    def _on_mouse_down(self, pos, button: int) -> None:
        self.mouse_pos = pos
        if self.help_open:
            self.help_open = False
            return

        if button == 3:
            uid = self.hit_part(pos)
            if uid is not None:
                self.delete_part(uid)
                return
            index = self.hit_wire(pos)
            if index is not None:
                self.delete_wire(index)
            return

        if button != 1:
            return

        for item in self.toolbar_buttons():
            if item["rect"].collidepoint(pos):
                self._toolbar_action(item["id"])
                return

        for kind, rect in self.palette_slots():
            if rect.collidepoint(pos):
                self.drag = {"mode": "palette", "part_kind": kind, "start": pos}
                return

        if PANEL_RECT.collidepoint(pos):
            for control in self.panel_controls():
                if control["rect"].collidepoint(pos):
                    if control["type"] == "button":
                        self._panel_button(control["id"])
                    elif control["type"] == "slider":
                        self.drag = {"mode": "slider", "control": control}
                        self._apply_slider(control, int(pos[0]))
                    return
            return

        if self.tool == "cut":
            uid = self.hit_part(pos)
            if uid is not None:
                self.cut_part(uid)
                return
            index = self.hit_wire(pos)
            if index is not None:
                self.cut_wire(index)
            else:
                self.notice("剪刀：点导线或元件都能剪断")
            return

        terminal = self.hit_terminal(pos)
        if terminal is not None:
            self.drag = {"mode": "wire", "start": terminal}
            return

        uid = self.hit_part(pos)
        if uid is not None:
            self.selected_uid = uid
            self.selected_wire = None
            view = self.views[uid]
            self.drag = {
                "mode": "part",
                "uid": uid,
                "offset": (pos[0] - view.x, pos[1] - view.y),
                "moved": False,
            }
            return

        index = self.hit_wire(pos)
        if index is not None:
            self.selected_wire = index
            self.selected_uid = None
            return

        self.selected_uid = None
        self.selected_wire = None

    def _on_mouse_up(self, pos, button: int) -> None:
        drag = self.drag
        self.drag = None
        if drag is None or button != 1:
            return
        mode = drag.get("mode")
        if mode == "palette":
            if CANVAS_RECT.collidepoint(pos):
                self.add_part_at(drag["part_kind"], pos)
                self.notice(f"松手放好了一个{ PART_LABELS[drag['part_kind']] }")
            elif self._over_palette(pos):
                self.notice("取消放置")
            else:
                self.notice("拖到画布上松手才会放置，已取消")
        elif mode == "part":
            uid = drag["uid"]
            view = self.views.get(uid)
            if view is None:
                return
            if self._over_palette(pos):
                self.delete_part(uid)
                return
            if not drag.get("moved"):
                part = self.circuit.parts.get(uid)
                if part is not None and part.kind == "switch" and not part.damaged:
                    self.toggle_switch(uid)
            self.solve()
        elif mode == "wire":
            start = drag["start"]
            target = self.hit_terminal(pos)
            if target is None:
                self.notice("要连到另一个端点上，已取消连线")
                return
            if target == start:
                self.notice("不能连到同一个端点")
                return
            if self.circuit.add_wire(start, target):
                self.solve()
                self.notice("已连接导线")
            else:
                self.notice("这两个端点已经连过了")

    def _on_wheel(self, amount: int) -> None:
        if not PALETTE_RECT.collidepoint(self.mouse_pos):
            return
        limit = self._max_palette_scroll()
        if limit <= 0:
            return
        self.palette_scroll = clamp(self.palette_scroll - amount * 60, 0.0, limit)

    def _on_key(self, key: int, mod: int = 0) -> None:
        if key == pygame.K_F1:
            self.help_open = not self.help_open
            return
        if self.help_open:
            if key == pygame.K_ESCAPE:
                self.help_open = False
            return
        if key == pygame.K_SPACE:
            self.sim_on = not self.sim_on
            self.solve()
            self.notice("仿真已暂停" if not self.sim_on else "继续仿真")
            return
        if key == pygame.K_ESCAPE:
            self.drag = None
            self.selected_uid = None
            self.selected_wire = None
            if self.tool == "cut":
                self.tool = "select"
            return
        if key == pygame.K_DELETE or key == pygame.K_BACKSPACE:
            if self.selected_uid is not None:
                self.delete_part(self.selected_uid)
            elif self.selected_wire is not None:
                self.delete_wire(self.selected_wire)
            return
        if key == pygame.K_r:
            self.rotate_selected()
            return
        if key == pygame.K_F11:
            self.toggle_fullscreen()
            return
        if key == pygame.K_t:
            self.set_realistic(not self.realistic)
            return
        if key == pygame.K_x:
            self.set_tool("select" if self.tool == "cut" else "cut")
            return
        for kind, hotkey in KIND_HOTKEYS.items():
            if key == hotkey:
                self.add_part_at(kind, self.mouse_pos)
                return

    # -- 按钮动作 ----------------------------------------------------------
    def _toolbar_action(self, ident: str) -> None:
        if ident == "sim":
            self.sim_on = not self.sim_on
            self.solve()
            self.notice("仿真已暂停" if not self.sim_on else "继续仿真")
        elif ident == "display":
            order = ("always", "hover", "click")
            self.display_mode = order[(order.index(self.display_mode) + 1) % 3]
            self.notice(
                {
                    "always": "U/I/R 直接显示在零件上",
                    "hover": "鼠标悬浮时显示 U/I/R",
                    "click": "单击零件时显示 U/I/R",
                }[self.display_mode]
            )
        elif ident == "realistic":
            self.set_realistic(not self.realistic)
        elif ident == "scissors":
            self.set_tool("select" if self.tool == "cut" else "cut")
        elif ident == "schematic":
            self.enter_schematic()
        elif ident == "back":
            self.leave_schematic(apply=False)
        elif ident == "tidy":
            self._refresh_schematic_layout()
            self.selected_uid = None
            self.selected_wire = None
            self.notice("已重新自动整理电路图", 2.0)
        elif ident == "export_svg":
            self.export_svg()
        elif ident == "netlist":
            self.export_netlist()
        elif ident == "apply":
            self.leave_schematic(apply=True)
        elif ident == "demo":
            self.load_demo()
        elif ident == "clear":
            self.circuit.clear()
            self.views.clear()
            self.selected_uid = None
            self.selected_wire = None
            self.hover_uid = None
            self.hover_wire = None
            self.wire_heat.clear()
            self.effects.clear()
            self.solve()
            self.notice("已清空画布")
        elif ident == "repair":
            self.repair_all()
        elif ident == "save":
            self.save()
        elif ident == "load":
            self.load()
        elif ident == "help":
            self.help_open = True

    def _panel_button(self, ident: str) -> None:
        part = self.selected_part()
        if ident == "delete" and part is not None:
            self.delete_part(part.uid)
        elif ident == "toggle" and part is not None:
            self.toggle_switch(part.uid)
        elif ident == "replace" and part is not None:
            self.replace_part(part.uid)
        elif ident == "rotate" and part is not None:
            self.rotate_selected()
            self.notice(f"{part.label}已旋转 90°", 1.6)
        elif ident == "delete_wire" and self.selected_wire is not None:
            self.delete_wire(self.selected_wire)
        elif ident == "cut_wire" and self.selected_wire is not None:
            self.cut_wire(self.selected_wire)
        elif ident == "repair_wire" and self.selected_wire is not None:
            self.repair_wire(self.selected_wire)

    def _apply_slider(self, control: dict, mouse_x: int) -> None:
        part = self.selected_part()
        if part is None:
            return
        track = self.slider_track(control)
        series = control["series"]
        ratio = clamp((mouse_x - track.x) / max(1, track.w), 0.0, 1.0)
        index = int(round(ratio * (len(series) - 1)))
        value = series[index]
        field = control["field"]
        if field == "value":
            part.value = float(value)
        elif field == "r_internal":
            part.r_internal = max(0.05, float(value))
        elif field == "rated_v":
            part.rated_v = max(1.0, float(value))
        self.solve()

    # -- 绘制 --------------------------------------------------------------
    def draw(self) -> None:
        self.screen.fill(BG)
        self._draw_canvas()
        self._draw_toolbar()
        self._draw_palette()
        self._draw_panel()
        self._draw_status()
        self._draw_drag_overlays()
        self._draw_tooltip()
        if self.help_open:
            self._draw_help()
        self._draw_tool_cursor()
        if self.effects.flash_alpha > 0.5:
            overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            overlay.fill((*self.effects.flash_color, int(self.effects.flash_alpha)))
            self.screen.blit(overlay, (0, 0))
        offset_x, offset_y = self.effects.offset()
        if offset_x or offset_y:
            snapshot = self.screen.copy()
            self.screen.fill(BG)
            self.screen.blit(snapshot, (int(offset_x), int(offset_y)))
        self._present()

    def _draw_canvas(self) -> None:
        screen = self.screen
        if self.mode == "schematic":
            self._draw_schematic_canvas()
            return
        screen.blit(self._grid_surface, CANVAS_RECT.topleft)
        self._draw_glows()
        self._draw_wires()
        self._draw_parts()
        self._draw_badges()
        previous_clip = screen.get_clip()
        screen.set_clip(CANVAS_RECT)
        self.effects.draw(screen, self.fonts)
        screen.set_clip(previous_clip)

    # -- 电路图模式的绘制 --------------------------------------------------
    def _draw_schematic_canvas(self) -> None:
        screen = self.screen
        if self._schematic_grid is None:
            self._schematic_grid = self._make_schematic_grid()
        screen.blit(self._schematic_grid, CANVAS_RECT.topleft)
        self._draw_schematic_wires()
        self._draw_schematic_parts()
        self._draw_badges()
        previous_clip = screen.get_clip()
        screen.set_clip(CANVAS_RECT)
        self.effects.draw(screen, self.fonts)
        screen.set_clip(previous_clip)

    def _schematic_wire_points(self, index: int):
        geometry = self.wire_geometry(index)
        return None if geometry is None else geometry[4]

    def _draw_schematic_wires(self) -> None:
        screen = self.screen
        for index in range(len(self.circuit.wires)):
            points = self._schematic_wire_points(index)
            if not points or len(points) < 2:
                continue
            broken = self.circuit.is_wire_broken(index)
            selected = self.selected_wire == index
            hovered = self.hover_wire == index
            if broken:
                color = (196, 92, 74)
                # 中间留个断口，表示断路
                half = len(points) // 2
                pygame.draw.lines(screen, color, False, points[: max(2, half)], 2)
                pygame.draw.lines(screen, color, False, points[max(2, half - 1):], 2)
                continue
            if selected:
                color = WIRE_SELECT
                width = 4
            elif self.tool == "cut" and hovered:
                color = (224, 108, 86)
                width = 4
            else:
                color = (150, 138, 126)
                width = 2
            pygame.draw.lines(screen, color, False, points, width)
            self._draw_energy_dots(index, points)

    def _draw_schematic_parts(self) -> None:
        screen = self.screen
        for uid, part in self.circuit.parts.items():
            view = self.views.get(uid)
            if view is None:
                continue
            selected = uid == self.selected_uid
            hovered = uid == self.hover_uid
            stroke = KIND_COLORS[part.kind]
            if part.damaged:
                stroke = (126, 116, 106)
            if selected or hovered:
                box_w, box_h = (112, 84) if view.angle % 180 == 0 else (84, 112)
                box = pygame.Rect(0, 0, box_w, box_h)
                box.center = (int(view.x), int(view.y))
                color = SELECT_COLOR if selected else (208, 220, 246)
                pygame.draw.rect(screen, color, box, 2 if selected else 1, border_radius=14)
            geo = schematic.symbol_geometry(part.kind, view.x, view.y, view.angle, part.closed)
            # 灯泡点亮时先铺一层暖光
            if part.kind == "bulb" and self.sim_on and not part.damaged:
                strength = clamp(part.brightness, 0.0, 1.0)
                if strength > 0.02:
                    glow = self._build_glow_cache(max(1, min(16, int(round(strength * 16)))))
                    screen.blit(glow, glow.get_rect(center=(int(view.x), int(view.y))))
                    level = int(40 + 180 * strength)
                    pygame.draw.circle(
                        screen,
                        (255, 255, min(255, level + 40)),
                        (int(view.x), int(view.y)),
                        15,
                    )
            for a, b, width in geo.lines:
                pygame.draw.line(screen, stroke, a, b, width)
            for polyline, width in geo.polylines:
                pygame.draw.lines(screen, stroke, False, polyline, width)
            for (cx, cy), radius, width, filled in geo.circles:
                if filled:
                    pygame.draw.circle(screen, stroke, (int(cx), int(cy)), int(radius))
                else:
                    pygame.draw.circle(screen, stroke, (int(cx), int(cy)), int(radius), width)
            for text, position, size in geo.letters:
                surface = self.fonts.text(text, size, stroke, bold=True)
                screen.blit(surface, surface.get_rect(center=(int(position[0]), int(position[1]))))
            # 引脚圆点
            for terminal in (0, 1):
                tx, ty = self.terminal_pos(uid, terminal)
                pygame.draw.circle(screen, (255, 255, 255), (int(tx), int(ty)), 4)
                pygame.draw.circle(
                    screen,
                    ACCENT if self.hover_terminal == (uid, terminal) else stroke,
                    (int(tx), int(ty)),
                    4,
                    2,
                )
            # 元件名称与参数
            label = f"{PART_LABELS[part.kind]} #{uid}"
            value = schematic.part_value_text(part)
            if part.damaged:
                if part.state == DAMAGE_EXPLODED:
                    value = (value + " · 已爆炸").strip(" ·")
                elif part.state == DAMAGE_CUT:
                    value = (value + " · 被剪断").strip(" ·")
                else:
                    value = (value + " · 已烧毁").strip(" ·")
            surface = self.fonts.text(label, 11, MUTED, bold=True)
            screen.blit(surface, surface.get_rect(midtop=(int(view.x), int(view.y) + 34)))
            if value:
                surface = self.fonts.text(value, 11, MUTED)
                screen.blit(surface, surface.get_rect(midtop=(int(view.x), int(view.y) + 50)))
            if self.tool == "cut" and hovered and not part.damaged:
                pygame.draw.circle(
                    screen, (214, 66, 62), (int(view.x), int(view.y)), 44, 2
                )

    def _draw_glows(self) -> None:
        if not self.sim_on:
            return
        for uid, part in self.circuit.parts.items():
            view = self.views.get(uid)
            if view is None or part.damaged:
                continue
            strength = 0.0
            if part.kind == "bulb":
                strength = part.brightness
            if strength <= 0.02:
                continue
            level = max(1, min(16, int(round(strength * 16))))
            glow = self._build_glow_cache(level)
            self.screen.blit(glow, glow.get_rect(center=(int(view.x), int(view.y))))

    def _wire_color(self, index: int) -> Tuple[int, int, int]:
        pair = self.circuit.wires[index]
        heat = self.wire_heat.get(pair, 0.0)
        if self.circuit.is_wire_broken(index):
            return WIRE_BROKEN
        current = 0.0
        if self.solution is not None and index < len(self.solution.wire_currents):
            current = self.solution.wire_currents[index]
        color = lerp_color(WIRE_BASE, WIRE_ACTIVE, min(1.0, abs(current) / 1.2))
        if heat > 0.02:
            color = lerp_color(color, WIRE_HOT, min(1.0, heat))
        return color

    def _draw_wire_polyline(self, points, color, width: int) -> None:
        if len(points) < 2:
            return
        pygame.draw.lines(self.screen, (228, 226, 222), False, points, width + 3)
        pygame.draw.lines(self.screen, color, False, points, width)

    def _draw_wires(self) -> None:
        screen = self.screen
        for index in range(len(self.circuit.wires)):
            geometry = self.wire_geometry(index)
            if geometry is None:
                continue
            points = geometry[4]
            color = self._wire_color(index)
            broken = self.circuit.is_wire_broken(index)
            selected = self.selected_wire == index
            hovered = self.hover_wire == index

            if broken:
                left = [p for i, p in enumerate(points) if i / (len(points) - 1) <= 0.44]
                right = [p for i, p in enumerate(points) if i / (len(points) - 1) >= 0.56]
                self._draw_wire_polyline(left, color, 3)
                self._draw_wire_polyline(right, color, 3)
                for part, direction in ((left, -1), (right, 1)):
                    if len(part) < 2:
                        continue
                    end = part[-1]
                    prev = part[-3] if len(part) >= 3 else part[0]
                    dx, dy = end[0] - prev[0], end[1] - prev[1]
                    length = math.hypot(dx, dy) or 1.0
                    nx, ny = -dy / length, dx / length
                    for k in (-1, 0, 1):
                        pygame.draw.line(
                            screen,
                            (186, 112, 100),
                            (end[0], end[1]),
                            (end[0] + dx * 0.06 + nx * 4 * k,
                             end[1] + dy * 0.06 + ny * 4 * k),
                            2,
                        )
                continue

            if selected:
                self._draw_wire_polyline(points, WIRE_SELECT, 5)
            elif self.tool == "cut" and hovered:
                self._draw_wire_polyline(points, (236, 120, 96), 5)
            else:
                self._draw_wire_polyline(points, color, 4)

            self._draw_energy_dots(index, points)

    def _draw_energy_dots(self, index: int, points) -> None:
        if not self.sim_on or self.solution is None:
            return
        if index >= len(self.solution.wire_currents):
            return
        current = self.solution.wire_currents[index]
        if abs(current) < 2e-3 or self.circuit.is_wire_broken(index):
            return
        if len(points) < 2:
            return
        # 按总弧长取点，折线（正交走线）上也能匀速流动
        lengths = []
        total = 0.0
        for i in range(1, len(points)):
            dx = points[i][0] - points[i - 1][0]
            dy = points[i][1] - points[i - 1][1]
            total += math.hypot(dx, dy)
            lengths.append(total)
        if total <= 1e-6:
            return

        def sample(t: float):
            target = total * t
            for i, length in enumerate(lengths):
                if length >= target or i == len(lengths) - 1:
                    previous = lengths[i - 1] if i else 0.0
                    segment = max(length - previous, 1e-6)
                    ratio = clamp((target - previous) / segment, 0.0, 1.0)
                    ax, ay = points[i]
                    bx, by = points[i + 1]
                    return (ax + (bx - ax) * ratio, ay + (by - ay) * ratio)
            return points[-1]

        speed = 0.18 + min(abs(current), 3.0) * 0.16
        phase = (self.time * speed) % 1.0
        for k in range(3):
            t = (phase + k / 3.0) % 1.0
            if current < 0:
                t = 1.0 - t
            position = sample(t)
            pygame.draw.circle(
                self.screen, (255, 214, 130), (int(position[0]), int(position[1])), 3
            )
            pygame.draw.circle(
                self.screen, (255, 246, 200), (int(position[0]), int(position[1])), 1
            )

    def _draw_parts(self) -> None:
        screen = self.screen
        for uid, part in self.circuit.parts.items():
            view = self.views.get(uid)
            if view is None:
                continue
            lit = 0
            if part.kind == "bulb" and self.sim_on:
                lit = int(round(clamp(part.brightness, 0.0, 1.0) * 8))
            heat_bucket = int(round(clamp(part.heat, 0.0, 1.0) * 6))
            burned = part.state in (DAMAGE_BURNED, DAMAGE_EXPLODED)
            chip = self._chip_surface(
                part.kind,
                view.angle,
                uid == self.selected_uid,
                uid == self.hover_uid,
                part.closed,
                lit,
                burned,
                heat_bucket,
                part.state == DAMAGE_CUT,
            )
            screen.blit(chip, chip.get_rect(center=(int(view.x), int(view.y))))

            if self.tool == "cut" and uid == self.hover_uid and not part.damaged:
                pygame.draw.circle(
                    screen, (214, 66, 62), (int(view.x), int(view.y)), 40, 2
                )

            for terminal in (0, 1):
                tx, ty = self.terminal_pos(uid, terminal)
                highlight = self.hover_terminal == (uid, terminal)
                dragging_from = (
                    self.drag is not None
                    and self.drag.get("mode") == "wire"
                    and self.drag.get("start") == (uid, terminal)
                )
                radius = 6 if (highlight or dragging_from) else 4
                pygame.draw.circle(screen, (255, 255, 255), (int(tx), int(ty)), radius)
                pygame.draw.circle(
                    screen,
                    ACCENT if (highlight or dragging_from) else KIND_COLORS[part.kind],
                    (int(tx), int(ty)),
                    radius,
                    2,
                )

    def _chip_surface(
        self,
        kind: str,
        angle: int,
        selected: bool = False,
        hovered: bool = False,
        closed: bool = True,
        lit: int = 0,
        damaged: bool = False,
        heat: int = 0,
        cut: bool = False,
    ) -> pygame.Surface:
        key = (kind, angle, selected, hovered, closed, lit, damaged, heat, cut)
        cached = self._chip_cache.get(key)
        if cached is not None:
            return cached

        base = KIND_COLORS[kind]
        if damaged:
            body = (92, 84, 76)
            border = (58, 50, 44)
            symbol = (44, 39, 35)
        elif cut:
            body = KIND_SOFT[kind]
            border = (208, 104, 90)
            symbol = (138, 128, 120)
        else:
            body = KIND_SOFT[kind]
            border = base
            symbol = base
            if kind == "bulb" and lit:
                body = lerp_color((255, 255, 255), (255, 238, 190), lit / 8.0 * 0.95)
            if heat:
                border = lerp_color(border, (255, 86, 40), heat / 6.0 * 0.85)

        surface = pygame.Surface((CHIP_W, CHIP_H), pygame.SRCALPHA)
        pygame.draw.rect(surface, body, pygame.Rect(0, 0, CHIP_W, CHIP_H), border_radius=12)
        width = 3 if selected else 2
        border_color = SELECT_COLOR if selected else border
        pygame.draw.rect(
            surface,
            border_color,
            pygame.Rect(0, 0, CHIP_W, CHIP_H),
            width,
            border_radius=12,
        )
        self._draw_symbol(surface, kind, (CHIP_W // 2, CHIP_H // 2), closed, symbol, lit)

        if damaged:
            cracks = [
                [(CHIP_W // 2 - 26, 8), (CHIP_W // 2 - 14, 24), (CHIP_W // 2 - 22, 38),
                 (CHIP_W // 2 - 8, 52)],
                [(CHIP_W // 2 + 20, 14), (CHIP_W // 2 + 12, 28), (CHIP_W // 2 + 26, 40),
                 (CHIP_W // 2 + 16, 56)],
            ]
            for crack in cracks:
                pygame.draw.lines(surface, (36, 31, 28), False, crack, 2)
            for spot in ((CHIP_W // 2 - 18, 20), (CHIP_W // 2 + 8, 44), (CHIP_W // 2 + 22, 18)):
                pygame.draw.circle(surface, (206, 108, 52), spot, 2)

        if cut and not damaged:
            # 剪刀剪出来的断口：中间一小段擦掉导线，再用红色虚线标出来
            gap = pygame.Rect(CHIP_W // 2 - 8, 12, 16, CHIP_H - 24)
            pygame.draw.rect(surface, body, gap)
            pygame.draw.rect(surface, KIND_SOFT[kind], gap, border_radius=0)
            for y in range(14, CHIP_H - 13, 8):
                pygame.draw.line(
                    surface, (214, 74, 60), (CHIP_W // 2 - 9, y), (CHIP_W // 2 - 9, y + 4), 2
                )
                pygame.draw.line(
                    surface, (214, 74, 60), (CHIP_W // 2 + 9, y), (CHIP_W // 2 + 9, y + 4), 2
                )

        if angle % 360:
            surface = pygame.transform.rotate(surface, -angle)

        # 电池的 +/− 和仪表的 V/A 一直在屏幕上是正立的，否则旋转后读不出来
        marks: List[Tuple[str, Tuple[float, float], int]] = []
        if kind == "battery":
            marks = [
                ("+", (CHIP_W / 2 - 24, CHIP_H / 2 - 18), 11),
                ("−", (CHIP_W / 2 + 24, CHIP_H / 2 - 18), 11),
            ]
        elif kind in ("voltmeter", "ammeter"):
            label = "V" if kind == "voltmeter" else "A"
            marks = [(label, (CHIP_W / 2, CHIP_H / 2 - 1), 14)]
        for label, local_pos, size in marks:
            self._tiny_text(
                surface, label, self._chip_mark_position(angle, local_pos), symbol, size
            )
        self._chip_cache[key] = surface
        return surface

    def _chip_mark_position(self, angle: int, local_pos) -> Tuple[int, int]:
        """把元件本地坐标换算到旋转后芯片表面的坐标（只用到 0/90/180/270）。"""
        x, y = local_pos
        x -= CHIP_W / 2
        y -= CHIP_H / 2
        angle %= 360
        if angle == 90:
            x, y = -y, x
        elif angle == 180:
            x, y = -x, -y
        elif angle == 270:
            x, y = y, -x
        width, height = (CHIP_H, CHIP_W) if angle in (90, 270) else (CHIP_W, CHIP_H)
        return (int(width / 2 + x), int(height / 2 + y))

    def _tiny_text(self, surface, text, pos, color, size=11, bold=True) -> None:
        rendered = self.fonts.text(text, size, color, bold=bold)
        surface.blit(rendered, rendered.get_rect(center=pos))

    def _draw_symbol(self, surface, kind: str, center, closed: bool, color, lit: int) -> None:
        cx, cy = center
        width = 3

        def line(start, end, thickness=width):
            pygame.draw.line(surface, color, start, end, thickness)

        def leads(left_x, right_x):
            line((8, cy), (left_x, cy))
            line((right_x, cy), (CHIP_W - 8, cy))

        if kind == "battery":
            leads(cx - 10, cx + 10)
            line((cx - 10, cy - 14), (cx - 10, cy + 14), 4)
            line((cx + 10, cy - 7), (cx + 10, cy + 7), 4)
        elif kind == "resistor":
            leads(cx - 26, cx + 26)
            amplitude = 8
            points = [(cx - 26, cy)]
            for i in range(6):
                x = cx - 18 + i * 7.2
                points.append((x, cy - amplitude if i % 2 == 0 else cy + amplitude))
            points.append((cx + 26, cy))
            pygame.draw.lines(surface, color, False, points, 2)
        elif kind == "bulb":
            leads(cx - 17, cx + 17)
            radius = 15
            if lit:
                pygame.draw.circle(surface, _bulb_glass_color(lit), (cx, cy), radius)
            pygame.draw.circle(surface, color, (cx, cy), radius, 2)
            line((cx - 10, cy - 10), (cx + 10, cy + 10), 2)
            line((cx - 10, cy + 10), (cx + 10, cy - 10), 2)
        elif kind == "switch":
            leads(cx - 22, cx + 22)
            pygame.draw.circle(surface, color, (cx - 22, cy), 3)
            pygame.draw.circle(surface, color, (cx + 22, cy), 3)
            if closed:
                line((cx - 22, cy), (cx + 22, cy), 3)
            else:
                line((cx - 22, cy), (cx + 8, cy - 15), 3)
        elif kind == "rheostat":
            leads(cx - 26, cx + 26)
            pygame.draw.rect(surface, color, pygame.Rect(cx - 24, cy - 11, 48, 22), 2)
            line((cx - 32, cy + 16), (cx + 20, cy - 16), 2)
            line((cx + 20, cy - 16), (cx + 10, cy - 14), 2)
            line((cx + 20, cy - 16), (cx + 14, cy - 24), 2)
        elif kind in ("voltmeter", "ammeter"):
            leads(cx - 18, cx + 18)
            pygame.draw.circle(surface, color, (cx, cy), 16, 2)
        elif kind == "capacitor":
            leads(cx - 8, cx + 8)
            line((cx - 8, cy - 16), (cx - 8, cy + 16), 4)
            line((cx + 8, cy - 16), (cx + 8, cy + 16), 4)

    def _make_icon(self, kind: str) -> pygame.Surface:
        surface = pygame.Surface((84, 56), pygame.SRCALPHA)
        chip = self._chip_surface(kind, 0, False, False, True)
        small = pygame.transform.smoothscale(chip, (74, 47))
        surface.blit(small, (5, 4))
        return surface

    def _icon(self, kind: str) -> pygame.Surface:
        cached = self._icon_cache.get(kind)
        if cached is None:
            cached = self._make_icon(kind)
            self._icon_cache[kind] = cached
        return cached

    # -- 徽标 --------------------------------------------------------------
    def _badge_visible(self, uid: int) -> bool:
        if self.mode == "schematic":
            # 电路图里默认干净一些，只在悬浮或选中时标数据
            if self.display_mode == "always":
                return uid in (self.hover_uid, self.selected_uid)
        if self.display_mode == "always":
            return True
        if self.display_mode == "hover":
            return False
        return uid == self.selected_uid

    def _badge_text(self, part: Part) -> str:
        u = fmt_u_display(part.u)
        i = fmt_i_display(abs(part.i) if part.kind == "battery" else part.i)
        if part.kind == "capacitor":
            third = "C" + fmt_cap_display(part.value)
        else:
            third = "R=" + fmt_resistance(part.resistance)
        text = f"U{u}  I{i}  {third}"
        if part.state == DAMAGE_CUT:
            text += "  断路"
        elif part.damaged:
            text += "  爆炸" if part.state == DAMAGE_EXPLODED else "  烧毁"
        return text

    def _draw_badges(self) -> None:
        for uid, part in self.circuit.parts.items():
            view = self.views.get(uid)
            if view is None or not self._badge_visible(uid):
                continue
            text = self._badge_text(part)
            color = (255, 210, 200) if part.damaged else BADGE_TEXT
            text_surface = self.fonts.text(text, 12, color, bold=True)
            width = text_surface.get_width() + 14
            height = text_surface.get_height() + 8
            vertical = view.angle % 180 != 0
            half_height = CHIP_W / 2 if vertical else CHIP_H / 2
            terminal_extent = TERMINAL_X + 7 if vertical else 0
            top_gap = max(half_height + 14, terminal_extent + 4)
            center_x = int(clamp(view.x, CANVAS_RECT.left + width / 2 + 4,
                                 CANVAS_RECT.right - width / 2 - 4))
            center_y = int(clamp(view.y + top_gap + height / 2,
                                 CANVAS_RECT.top + height / 2 + 4,
                                 CANVAS_RECT.bottom - height / 2 - 4))
            rect = pygame.Rect(0, 0, width, height)
            rect.center = (center_x, center_y)
            background = BADGE_BG if not part.damaged else (96, 44, 40)
            pygame.draw.rect(self.screen, background, rect, border_radius=6)
            self.screen.blit(text_surface, text_surface.get_rect(center=rect.center))

    # -- 工具栏 ------------------------------------------------------------
    def _draw_toolbar(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, pygame.Rect(0, 0, WIDTH, TOOLBAR_H))
        pygame.draw.line(self.screen, BORDER, (0, TOOLBAR_H), (WIDTH, TOOLBAR_H))
        title = self.fonts.text("电路积木", 20, TEXT, bold=True)
        self.screen.blit(title, (16, 10))
        subtitle = self.fonts.text("Circuit Lab", 11, MUTED)
        self.screen.blit(subtitle, (18, 36))
        for item in self.toolbar_buttons():
            rect = item["rect"]
            if item["active"]:
                background = (232, 240, 255)
                border = ACCENT
                color = ACCENT
            else:
                background = (248, 249, 252)
                border = BORDER
                color = TEXT
            if item["id"] == "realistic" and self.realistic:
                background = (255, 238, 234)
                border = DANGER
                color = DANGER
            if item["id"] == "scissors" and self.tool == "cut":
                background = (255, 240, 236)
                border = WARN
                color = (198, 96, 52)
            pygame.draw.rect(self.screen, background, rect, border_radius=9)
            pygame.draw.rect(self.screen, border, rect, 1, border_radius=9)
            label = self.fonts.text(item["label"], 15, color, bold=True)
            self.screen.blit(label, label.get_rect(center=rect.center))

    # -- 零件栏 ------------------------------------------------------------
    def _draw_palette(self) -> None:
        pygame.draw.rect(self.screen, PALETTE_BG, PALETTE_RECT)
        pygame.draw.line(
            self.screen, BORDER, (PALETTE_RECT.right, PALETTE_RECT.top),
            (PALETTE_RECT.right, PALETTE_RECT.bottom),
        )
        title = self.fonts.text("零件", 16, TEXT, bold=True)
        self.screen.blit(title, (16, TOOLBAR_H + 14))
        hint = self.fonts.text("拖到画布上放置", 11, MUTED)
        self.screen.blit(hint, (58, TOOLBAR_H + 20))

        area = self.palette_content_rect()
        clipped = self.drag is not None and self.drag.get("mode") == "palette"
        for kind, rect in self.palette_slots():
            if rect.bottom <= area.top or rect.top >= area.bottom:
                continue
            hovered = (not clipped) and rect.collidepoint(self.mouse_pos)
            visible = pygame.Rect(rect)
            visible.top = max(visible.top, area.top)
            visible.bottom = min(visible.bottom, area.bottom)
            if visible.height <= 4:
                continue
            previous_clip = self.screen.get_clip()
            self.screen.set_clip(area)
            card = pygame.Rect(rect.x, max(rect.y, area.top), rect.w,
                               min(rect.bottom, area.bottom) - max(rect.y, area.top))
            pygame.draw.rect(
                self.screen, (255, 255, 255), pygame.Rect(rect.x, card.y, rect.w, card.h),
                border_radius=14,
            )
            pygame.draw.rect(
                self.screen,
                ACCENT if hovered else BORDER,
                pygame.Rect(rect.x, card.y, rect.w, card.h),
                2 if hovered else 1,
                border_radius=14,
            )
            if visible.height >= 90:
                self.screen.blit(self._icon(kind), self._icon(kind).get_rect(center=(rect.centerx, rect.y + 44)))
                label = self.fonts.text(PART_LABELS[kind], 13, TEXT, bold=True)
                self.screen.blit(label, label.get_rect(center=(rect.centerx, rect.bottom - 20)))
            self.screen.set_clip(previous_clip)

        # 删除区
        zone = self.delete_zone_rect()
        active = self.drag is not None and self.drag.get("mode") == "part" and zone.collidepoint(self.mouse_pos)
        if active:
            pygame.draw.rect(self.screen, (255, 236, 232), zone, border_radius=14)
            pygame.draw.rect(self.screen, DANGER, zone, 2, border_radius=14)
        else:
            pygame.draw.rect(self.screen, (255, 255, 255), zone, border_radius=14)
            pygame.draw.rect(self.screen, BORDER, zone, 1, border_radius=14)
        icon_rect = pygame.Rect(0, 0, 26, 26)
        icon_rect.center = (zone.centerx, zone.y + 34)
        pygame.draw.rect(self.screen, MUTED, icon_rect, 2, border_radius=5)
        pygame.draw.line(self.screen, MUTED, (icon_rect.centerx, icon_rect.top + 5),
                         (icon_rect.centerx, icon_rect.bottom - 5), 2)
        text = self.fonts.text("拖到这里删除", 12, DANGER if active else MUTED)
        self.screen.blit(text, text.get_rect(center=(zone.centerx, zone.y + 62)))
        text2 = self.fonts.text("或右键 / Delete 删除", 11, MUTED)
        self.screen.blit(text2, text2.get_rect(center=(zone.centerx, zone.y + 80)))

    # -- 右栏 --------------------------------------------------------------
    def _draw_panel(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, PANEL_RECT)
        pygame.draw.line(
            self.screen, BORDER, (PANEL_RECT.left, PANEL_RECT.top),
            (PANEL_RECT.left, PANEL_RECT.bottom),
        )
        part = self.selected_part()
        if part is not None:
            self._draw_panel_part(part)
        elif self.selected_wire is not None:
            self._draw_panel_wire(self.selected_wire)
        else:
            self._draw_panel_overview()

    def _panel_header(self, title: str, subtitle: str, badge: str = "") -> None:
        pygame.draw.rect(self.screen, ACCENT, (PANEL_RECT.x + 20, PANEL_RECT.top + 16, 5, 26),
                         border_radius=3)
        name = self.fonts.text(title, 18, TEXT, bold=True)
        self.screen.blit(name, (PANEL_RECT.x + 34, PANEL_RECT.top + 15))
        sub = self.fonts.text(subtitle, 11, MUTED)
        self.screen.blit(sub, (PANEL_RECT.x + 34, PANEL_RECT.top + 42))
        if badge:
            tag = self.fonts.text(badge, 12, MUTED)
            self.screen.blit(tag, tag.get_rect(topright=(PANEL_RECT.right - 22, PANEL_RECT.top + 20)))
        pygame.draw.line(
            self.screen, BORDER, (PANEL_RECT.x + 20, PANEL_RECT.top + 66),
            (PANEL_RECT.right - 20, PANEL_RECT.top + 66),
        )

    def _draw_readout(self, row: int, label: str, value: str, color) -> None:
        y = PANEL_READOUT_TOP + row * 26
        tag = self.fonts.text(label, 13, MUTED)
        self.screen.blit(tag, (PANEL_RECT.x + 24, y))
        text = self.fonts.text(value, 16, color, bold=True)
        self.screen.blit(text, text.get_rect(topright=(PANEL_RECT.right - 24, y - 2)))

    def _draw_panel_part(self, part: Part) -> None:
        self._panel_header(part.label, KIND_HINTS[part.kind], f"#{part.uid}")

        current = abs(part.i) if part.kind == "battery" else part.i
        rows = [
            ("电压 U", fmt_voltage(part.u)),
            ("电流 I", fmt_current(current)),
        ]
        if part.kind == "capacitor":
            rows.append(("容量 C", fmt_capacitance(part.value)))
        else:
            rows.append(("电阻 R", fmt_resistance(part.resistance)))
        rows.append(("功率 P", fmt_power(part.p)))
        colors = (ACCENT, (214, 126, 46), (60, 140, 100), (150, 100, 200))
        for row, (label, value) in enumerate(rows):
            self._draw_readout(row, label, value, colors[row])

        y = PANEL_READOUT_TOP + 4 * 26 + 6
        extra_lines: List[Tuple[str, tuple, bool]] = []
        if part.kind == "battery":
            extra_lines.append(
                (f"电动势 {fmt_voltage(part.value)} · 内阻 {fmt_resistance(part.r_internal)}", MUTED, False)
            )
        elif part.kind == "bulb":
            extra_lines.append(
                (f"额定 {part.rated_v:.0f}V / {fmt_power(part.rated_power)}", MUTED, False)
            )
            extra_lines.append(
                (
                    f"灯丝 {part.filament_k:.0f}K · 冷态 {fmt_resistance(part.cold_resistance)}",
                    MUTED,
                    False,
                )
            )
            extra_lines.append((f"亮度 {part.brightness * 100:.0f}%", (198, 128, 30), True))
        elif part.kind == "resistor":
            extra_lines.append((f"额定功率 {fmt_power(part.rated_power)}", MUTED, False))
        elif part.kind == "rheostat":
            extra_lines.append((f"可调范围 0–{RHEOSTAT_MAX:g}Ω · 额定 {fmt_power(part.rated_power)}", MUTED, False))
        elif part.kind == "switch":
            extra_lines.append(("状态：闭合" if part.closed else "状态：断开", MUTED, False))
        elif part.kind == "voltmeter":
            extra_lines.append(("内阻 1 MΩ · 并联测电压", MUTED, False))
        elif part.kind == "ammeter":
            extra_lines.append(("内阻 0.01 Ω · 串联测电流", MUTED, False))
        elif part.kind == "capacitor":
            energy = 0.5 * part.value * part.u * part.u
            extra_lines.append(
                (f"容量 {fmt_capacitance(part.value)} · 耐压 {part.rated_v:.0f}V", MUTED, False)
            )
            extra_lines.append((f"储能 {fmt_si(energy, 'J')}", MUTED, False))

        for text, color, bold in extra_lines:
            surface = self.fonts.text(text, 12, color, bold=bold)
            self.screen.blit(surface, (PANEL_RECT.x + 24, y))
            y += 20

        if part.damaged:
            if part.state == DAMAGE_EXPLODED:
                label = "已爆炸"
            elif part.state == DAMAGE_CUT:
                label = "被剪刀剪断"
            else:
                label = "已烧毁"
            text = self.fonts.text(f"⚠ {label}，电路已断开", 13, DANGER, bold=True)
            self.screen.blit(text, (PANEL_RECT.x + 24, PANEL_RECT.bottom - 198))
        elif self.realistic and part.heat > 0.01:
            label = self.fonts.text("热量", 12, MUTED)
            self.screen.blit(label, (PANEL_RECT.x + 24, PANEL_RECT.bottom - 200))
            track = pygame.Rect(PANEL_RECT.x + 70, PANEL_RECT.bottom - 194, PANEL_W - 96, 10)
            pygame.draw.rect(self.screen, (238, 240, 245), track, border_radius=5)
            fill = pygame.Rect(track.x, track.y, int(track.w * clamp(part.heat, 0, 1)), track.h)
            pygame.draw.rect(
                self.screen, lerp_color((240, 190, 90), (214, 60, 50), part.heat), fill, border_radius=5
            )

        for control in self.panel_controls():
            if control["type"] == "button":
                self._draw_button(control)
            elif control["type"] == "slider":
                self._draw_slider(control)
            elif control["type"] == "info":
                self._draw_info(control)

    def _draw_panel_wire(self, index: int) -> None:
        self._panel_header("导线", "连接两个端点的一段导线")
        current = 0.0
        if self.solution is not None and index < len(self.solution.wire_currents):
            current = self.solution.wire_currents[index]
        broken = self.circuit.is_wire_broken(index)
        pair = self.circuit.wires[index]
        self._draw_readout(0, "电流 I", fmt_current(current), (214, 126, 46))
        self._draw_readout(1, "状态", "已剪断（断路）" if broken else "正常", DANGER if broken else GOOD)
        info = self.fonts.text(
            f"端点 #{pair[0][0]}-{pair[0][1]}  →  #{pair[1][0]}-{pair[1][1]}", 11, MUTED
        )
        self.screen.blit(info, (PANEL_RECT.x + 24, PANEL_READOUT_TOP + 62))
        for control in self.panel_controls():
            self._draw_button(control)

    def _draw_panel_overview(self) -> None:
        self._panel_header("电路概览", "选中零件可查看 / 调节参数")
        battery_current = 0.0
        total_power = 0.0
        if self.solution is not None:
            battery_current = self.solution.battery_current
            total_power = self.solution.total_power
        damaged = sum(1 for part in self.circuit.parts.values() if part.damaged)
        broken = self.circuit.broken_count()
        self._draw_readout(0, "元件数量", f"{len(self.circuit.parts)} 个", TEXT)
        self._draw_readout(1, "导线数量", f"{len(self.circuit.wires)} 根", TEXT)
        self._draw_readout(2, "电源电流", fmt_i_display(battery_current).lstrip("="), (214, 126, 46))
        self._draw_readout(3, "总功率", fmt_power(total_power), (150, 100, 200))

        y = PANEL_READOUT_TOP + 4 * 26 + 2
        if damaged:
            text = self.fonts.text(
                f"⚠ {damaged} 个元件损坏/断路 · 点「检修」", 12, DANGER, bold=True
            )
            self.screen.blit(text, (PANEL_RECT.x + 24, y))
            y += 20
        if broken:
            text = self.fonts.text(f"✂ {broken} 根导线被剪断", 12, (196, 108, 92), bold=True)
            self.screen.blit(text, (PANEL_RECT.x + 24, y))
            y += 20

        y = max(y, PANEL_READOUT_TOP + 4 * 26 + 60)
        pygame.draw.line(self.screen, BORDER, (PANEL_RECT.x + 20, y), (PANEL_RECT.right - 20, y))
        y += 14
        title = self.fonts.text("小提示", 13, TEXT, bold=True)
        self.screen.blit(title, (PANEL_RECT.x + 24, y))
        y += 28
        tips = [
            "从左侧拖出零件",
            "从端点拖出导线",
            "单击零件选中",
            "右侧滑块调参数",
            "点开关可通断",
            "剪刀：剪断导线",
            "全真：元件会烧毁",
            "空格暂停仿真",
        ]
        for tip in tips:
            pygame.draw.circle(self.screen, MUTED, (PANEL_RECT.x + 30, y + 7), 2)
            surface = self.fonts.text(tip, 12, MUTED)
            self.screen.blit(surface, (PANEL_RECT.x + 40, y))
            y += 22

    def _draw_button(self, control: dict) -> None:
        rect = control["rect"]
        if control.get("danger"):
            background = (255, 243, 242)
            border = (234, 176, 172)
            color = DANGER
        elif control.get("accent"):
            background = (238, 244, 255)
            border = (183, 203, 245)
            color = ACCENT
        else:
            background = (247, 248, 251)
            border = BORDER
            color = TEXT
        pygame.draw.rect(self.screen, background, rect, border_radius=10)
        pygame.draw.rect(self.screen, border, rect, 1, border_radius=10)
        label = self.fonts.text(control["label"], 14, color, bold=True)
        self.screen.blit(label, label.get_rect(center=rect.center))

    def _draw_info(self, control: dict) -> None:
        rect = control["rect"]
        label = self.fonts.text(control["label"], 12, MUTED)
        self.screen.blit(label, (rect.x + 2, rect.y + 4))

    def _draw_slider(self, control: dict) -> None:
        rect = control["rect"]
        track = self.slider_track(control)
        label = self.fonts.text(control["label"], 12, MUTED)
        self.screen.blit(label, (rect.x + 2, rect.y + 2))
        value_text = fmt_si(control["value"], control["unit"])
        value = self.fonts.text(value_text, 13, ACCENT, bold=True)
        self.screen.blit(value, value.get_rect(topright=(rect.right - 2, rect.y)))

        pygame.draw.rect(self.screen, (236, 239, 246), track, border_radius=4)
        series = control["series"]
        ratio = 0.0
        if len(series) >= 2:
            low, high = series[0], series[-1]
            if high > low:
                ratio = clamp((control["value"] - low) / (high - low), 0.0, 1.0)
            index = min(range(len(series)), key=lambda k: abs(series[k] - control["value"]))
            ratio = index / (len(series) - 1)
        fill = pygame.Rect(track.x, track.y, int(track.w * ratio), track.h)
        pygame.draw.rect(self.screen, ACCENT, fill, border_radius=4)
        knob_x = track.x + int(track.w * ratio)
        pygame.draw.circle(self.screen, (255, 255, 255), (knob_x, track.centery), 9)
        pygame.draw.circle(self.screen, ACCENT, (knob_x, track.centery), 9, 2)
        low_label = self.fonts.text(fmt_si(series[0], control["unit"]), 10, MUTED)
        high_label = self.fonts.text(fmt_si(series[-1], control["unit"]), 10, MUTED)
        self.screen.blit(low_label, (track.x, track.bottom + 4))
        self.screen.blit(high_label, high_label.get_rect(topright=(track.right, track.bottom + 4)))

    # -- 状态栏 ------------------------------------------------------------
    def _draw_status(self) -> None:
        pygame.draw.rect(self.screen, PANEL_BG, STATUS_RECT)
        pygame.draw.line(self.screen, BORDER, (0, STATUS_RECT.top), (WIDTH, STATUS_RECT.top))
        if self.notice_text and self.time < self.notice_until:
            text = self.notice_text
            color = TEXT
        else:
            if self.solution is not None and self.solution.error:
                text = self.solution.error
                color = DANGER
            elif self.solution is not None and self.solution.warnings:
                text = self.solution.warnings[0]
                color = WARN
            else:
                if self.mode == "schematic":
                    text = (
                        "电路图模式：拖出零件、连导线 → 点「生成电路」应用到画板 · 可导出 SVG / 网表"
                    )
                elif self.touch_mode:
                    text = "单指拖动零件 / 端点连线 · 双击元件旋转 · 选中后在右栏删除或调参数"
                else:
                    text = "拖出零件 → 拖动端点连导线 → 单击零件调参数 · 右键删除 · R 旋转 · 空格暂停 · F1 帮助"
                color = MUTED
        surface = self.fonts.text(text, 12, color)
        self.screen.blit(surface, (16, STATUS_RECT.y + 7))

        right = f"仿真{'中' if self.sim_on else '暂停'} · U/I/R {DISPLAY_LABELS[self.display_mode]}"
        if self.mode == "schematic":
            right += " · 电路图"
        if self.realistic:
            right += " · 全真"
        if self.tool == "cut":
            right += " · 剪刀"
        if self.touch_mode:
            right += " · 触屏"
        right_surface = self.fonts.text(right, 12, ACCENT if self.realistic else MUTED)
        self.screen.blit(
            right_surface, right_surface.get_rect(topright=(WIDTH - 16, STATUS_RECT.y + 7))
        )

    # -- 拖拽覆盖层、提示、帮助 --------------------------------------------
    def _draw_drag_overlays(self) -> None:
        if self.drag is None:
            return
        mode = self.drag.get("mode")
        if mode == "palette":
            kind = self.drag["part_kind"]
            chip = self._chip_surface(kind, 0, False, False, True)
            ghost = chip.copy()
            ghost.set_alpha(190)
            self.screen.blit(ghost, ghost.get_rect(center=(int(self.mouse_pos[0]), int(self.mouse_pos[1]))))
            hint = self.fonts.text("松开放置", 12, TEXT, bold=True)
            hint_surface = pygame.Surface((hint.get_width() + 16, hint.get_height() + 8), pygame.SRCALPHA)
            pygame.draw.rect(hint_surface, (38, 44, 58, 220), hint_surface.get_rect(), border_radius=6)
            hint_surface.blit(hint, (8, 4))
            self.screen.blit(
                hint_surface, hint_surface.get_rect(center=(int(self.mouse_pos[0]), int(self.mouse_pos[1]) + 52))
            )
        elif mode == "wire":
            start = self.drag["start"]
            p0 = self.terminal_pos(*start)
            direction = self.terminal_dir(*start)
            target = self.hit_terminal(self.mouse_pos)
            end = self.mouse_pos
            if target is not None and target != start:
                end = self.terminal_pos(*target)
            distance = math.hypot(end[0] - p0[0], end[1] - p0[1])
            if self.mode == "schematic" or self.board_ortho:
                if target is not None:
                    points = schematic.wire_route(
                        p0, direction, end, self.terminal_dir(*target)
                    )
                else:
                    stub = (p0[0] + direction[0] * 24, p0[1] + direction[1] * 24)
                    if abs(direction[0]) > 0.5:
                        points = [p0, stub, (stub[0], end[1]), end]
                    else:
                        points = [p0, stub, (end[0], stub[1]), end]
            else:
                k = clamp(distance * 0.45, 36, 140)
                p1 = (p0[0] + direction[0] * k, p0[1] + direction[1] * k)
                p2 = (end[0], end[1])
                points = bezier_points(p0, p1, p2, end)
            for i in range(0, len(points) - 1, 2):
                pygame.draw.line(
                    self.screen, (96, 122, 214), points[i], points[i + 1],
                    4 if target is not None else 2,
                )
            pygame.draw.circle(self.screen, (255, 255, 255), (int(p0[0]), int(p0[1])), 7)
            pygame.draw.circle(self.screen, ACCENT, (int(p0[0]), int(p0[1])), 7, 2)

    def _tooltip_lines(self, part: Part) -> List[str]:
        lines = [f"{part.label} #{part.uid}"]
        lines.append(f"U = {fmt_voltage(part.u)}")
        current = abs(part.i) if part.kind == "battery" else part.i
        lines.append(f"I = {fmt_current(current)}")
        if part.kind == "capacitor":
            lines.append(f"C = {fmt_capacitance(part.value)}")
        else:
            lines.append(f"R = {fmt_resistance(part.resistance)}")
        lines.append(f"P = {fmt_power(part.p)}")
        if part.kind == "bulb":
            lines.append(f"额定 {part.rated_v:.0f}V / {fmt_power(part.rated_power)}")
            lines.append(f"灯丝 {part.filament_k:.0f}K · 冷态 {fmt_resistance(part.cold_resistance)}")
            lines.append(f"亮度 {part.brightness * 100:.0f}%")
        elif part.kind in ("resistor", "rheostat"):
            lines.append(f"额定功率 {fmt_power(part.rated_power)}")
        elif part.kind == "capacitor":
            energy = 0.5 * part.value * part.u * part.u
            lines.append(f"耐压 {part.rated_v:.0f}V · 储能 {fmt_si(energy, 'J')}")
        elif part.kind == "battery":
            lines.append(f"电动势 {fmt_voltage(part.value)} · 内阻 {fmt_resistance(part.r_internal)}")
        elif part.kind == "voltmeter":
            lines.append("并联在元件两端测电压")
        elif part.kind == "ammeter":
            lines.append("串联在电路里测电流")
        if part.damaged:
            if part.state == DAMAGE_CUT:
                lines.append("✖ 被剪刀剪断 · 电路断路")
            elif part.state == DAMAGE_EXPLODED:
                lines.append("✖ 已爆炸 · 选中后更换零件")
            else:
                lines.append("✖ 已烧毁 · 选中后更换零件")
        elif self.realistic and part.heat > 0.05:
            lines.append(f"热量 {part.heat * 100:.0f}%（满了会烧毁）")
        return lines

    def _draw_tooltip(self) -> None:
        if self.drag is not None or self.help_open:
            return
        target_part = None
        if self.hover_uid is not None:
            target_part = self.circuit.parts.get(self.hover_uid)
        lines: List[str] = []
        title_color = TEXT
        if target_part is not None:
            lines = self._tooltip_lines(target_part)
            if target_part.damaged:
                title_color = DANGER
        elif self.hover_wire is not None and self.hover_wire < len(self.circuit.wires):
            current = 0.0
            if self.solution is not None and self.hover_wire < len(self.solution.wire_currents):
                current = self.solution.wire_currents[self.hover_wire]
            lines = ["导线", f"I = {fmt_current(current)}"]
            if self.circuit.is_wire_broken(self.hover_wire):
                lines.append("已剪断（断路）")
            elif self.tool == "cut":
                lines.append("点击剪断这根导线")
        if not lines:
            return
        surfaces = []
        for index, line in enumerate(lines):
            color = title_color if index == 0 else MUTED
            bold = index == 0
            surfaces.append((self.fonts.text(line, 13 if index == 0 else 12, color, bold=bold), index == 0))
        width = max(surface.get_width() for surface, _ in surfaces) + 20
        height = sum(surface.get_height() + (6 if first else 3) for surface, first in surfaces) + 12
        position = (int(self.mouse_pos[0]) + 18, int(self.mouse_pos[1]) + 18)
        if position[0] + width > WIDTH - 8:
            position = (WIDTH - 8 - width, position[1])
        if position[1] + height > HEIGHT - 8:
            position = (position[0], HEIGHT - 8 - height)
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        pygame.draw.rect(panel, (255, 255, 255, 245), panel.get_rect(), border_radius=8)
        pygame.draw.rect(panel, (216, 222, 234, 255), panel.get_rect(), 1, border_radius=8)
        y = 8
        for surface, first in surfaces:
            panel.blit(surface, (10, y))
            y += surface.get_height() + (6 if first else 3)
        self.screen.blit(panel, position)

    def _draw_help(self) -> None:
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((22, 26, 36, 120))
        self.screen.blit(overlay, (0, 0))
        box = pygame.Rect(0, 0, 800, 664)
        box.center = (WIDTH // 2, HEIGHT // 2)
        pygame.draw.rect(self.screen, HELP_BG, box, border_radius=18)
        pygame.draw.rect(self.screen, (216, 222, 234), box, 1, border_radius=18)

        title = self.fonts.text("操作说明", 22, TEXT, bold=True)
        self.screen.blit(title, (box.x + 30, box.y + 22))
        close = self.fonts.text("F1 / Esc / 点击任意位置关闭", 12, MUTED)
        self.screen.blit(close, close.get_rect(topright=(box.right - 30, box.y + 30)))

        rows = [
            ("零件栏", "从左侧 8 种元件按住拖到画布上；拖回零件栏或删除区即删除"),
            ("移动", "拖动已放置的零件即可移动，导线会跟着走"),
            ("删除", "拖回左侧零件栏 / 右键 / 选中后按 Delete（手机上点右栏「删除零件」）"),
            ("连线", "从零件两端的圆点拖到另一个圆点，松手就连上导线"),
            ("调参", "单击零件选中，在右侧面板拖动滑块调电压、阻值、容量等"),
            ("开关", "单击开关即可闭合 / 断开，观察灯泡和仪表变化"),
            ("仪表", "电压表并联在元件两端测电压，电流表串联测电流"),
            ("电容", "电容有充放电过程（τ = RC），通电后电压慢慢升高"),
            ("剪刀", "点「剪刀」，再点导线或元件都能剪断，模拟断路故障"),
            ("全真", "打开「全真」后，过载的元件会发热、烧毁、爆炸，过流导线会烧断"),
            ("电路图", "点「电路图」进入电路图模式：自动排成标准电路图，可继续画和改"),
            ("生成电路", "在电路图模式点「生成电路」，把图里的连线变成可仿真的电路回到画板"),
            ("导出", "电路图模式里可「导出 SVG」（矢量图，浏览器能开）和「导出网表」"),
            ("U/I/R", "每个零件下方直接显示；工具栏「显示」切换 常显 / 悬浮 / 单击"),
            ("触屏", "单指拖动零件 / 从端点连线 · 双击元件旋转 90° · 选中后点右栏按钮调参或删除"),
            ("窗口", "自动等比缩放适配任意窗口大小 · F11 全屏 / 退出全屏"),
            ("快捷键", "空格 暂停/运行 · R 旋转 · Delete 删除 · 1-8 快速放置 · T 全真 · X 剪刀"),
            ("存档", "「保存」写入 circuit_save.json，「读取」恢复上次电路"),
        ]
        y = box.y + 74
        for label, text in rows:
            tag = self.fonts.text(label, 13, ACCENT, bold=True)
            self.screen.blit(tag, (box.x + 30, y))
            body = self.fonts.text(text, 13, TEXT)
            self.screen.blit(body, (box.x + 124, y))
            y += 30

        tip = self.fonts.text(
            "小目标：用变阻器调暗灯泡、看电容慢慢充电、打开全真把电阻烧掉试试", 12, MUTED
        )
        self.screen.blit(tip, (box.x + 30, box.bottom - 34))

    def _draw_tool_cursor(self) -> None:
        if self.tool != "cut" or self.help_open:
            return
        mx, my = int(self.mouse_pos[0]), int(self.mouse_pos[1])
        if mx < 0 or my < 0 or mx > WIDTH or my > HEIGHT:
            return
        color = (198, 96, 52)
        pygame.draw.circle(self.screen, color, (mx - 5, my + 7), 4, 2)
        pygame.draw.circle(self.screen, color, (mx + 6, my + 7), 4, 2)
        pygame.draw.line(self.screen, color, (mx - 5, my + 7), (mx + 4, my - 8), 2)
        pygame.draw.line(self.screen, color, (mx + 6, my + 7), (mx - 2, my - 10), 2)

    # -- 主循环 ------------------------------------------------------------
    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                self.handle_event(event)
            self.update(dt)
            self.draw()
        pygame.quit()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
