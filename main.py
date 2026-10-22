"""LumaIR — Kivy remote for IR LED controllers."""

__version__ = "1.0.0"

import colorsys
import json
import math
import os
import re
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform
from kivy.core.window import Window

from ir_backend import IrError, IrTransmitter, build_nec_pattern, parse_key_pattern


BG = (0.035, 0.047, 0.071, 1)
PANEL = (0.075, 0.09, 0.125, 1)
PANEL_2 = (0.10, 0.12, 0.16, 1)
TEXT = (0.94, 0.96, 1.0, 1)
MUTED = (0.53, 0.60, 0.70, 1)
ACCENT = (0.45, 0.93, 0.76, 1)
ORANGE = (1.0, 0.67, 0.34, 1)
FONT = "Roboto"


def rgba(hex_color, alpha=1):
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return (1, 1, 1, alpha)
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


def rgb_hex(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb)


def make_label(text="", size=14, color=TEXT, bold=False, **kwargs):
    halign = kwargs.pop("halign", "left")
    valign = kwargs.pop("valign", "middle")
    return Label(
        text=text, font_name=FONT, font_size=sp(size), color=color,
        bold=bold, halign=halign, valign=valign, **kwargs
    )


class RoundedPanel(BoxLayout):
    def __init__(self, color=PANEL, radius=dp(22), **kwargs):
        super().__init__(**kwargs)
        self._panel_color = color
        self._radius = radius
        with self.canvas.before:
            self._bg_color = Color(*color)
            self._bg_shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])
        self.bind(pos=self._redraw, size=self._redraw)

    def _redraw(self, *_):
        self._bg_shape.pos = self.pos
        self._bg_shape.size = self.size


class PillButton(Button):
    def __init__(self, text, fill=PANEL_2, text_color=TEXT, radius=dp(14), **kwargs):
        super().__init__(text=text, **kwargs)
        self.font_name = FONT
        self.font_size = sp(kwargs.pop("font_size", 13)) if "font_size" in kwargs else sp(13)
        self.color = text_color
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self._fill = fill
        self._down_fill = tuple(max(0, c * 0.82) if i < 3 else c for i, c in enumerate(fill))
        self._radius = radius
        with self.canvas.before:
            self._shape_color = Color(*fill)
            self._shape = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])
        self.bind(pos=self._sync_shape, size=self._sync_shape, state=self._sync_state)

    def _sync_shape(self, *_):
        self._shape.pos = self.pos
        self._shape.size = self.size

    def _sync_state(self, *_):
        self._shape_color.rgba = self._down_fill if self.state == "down" else self._fill


class ColorWheel(Widget):
    """Saturation/hue disc. Brightness is controlled by the dedicated slider."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hue = 0.05
        self.saturation = 0.86
        self.value = 1.0
        self._texture = None
        with self.canvas:
            self._image_color = Color(1, 1, 1, 1)
            self._image = Rectangle(pos=self.pos, size=self.size)
            self._ring_color = Color(1, 1, 1, 0.22)
            self._ring = Line(circle=(0, 0, 1), width=dp(1.0))
            self._marker_color = Color(1, 1, 1, 1)
            self._marker_shadow = Ellipse(pos=(0, 0), size=(dp(24), dp(24)))
            self._marker_inner_color = Color(0.04, 0.06, 0.09, 0.92)
            self._marker_inner = Ellipse(pos=(0, 0), size=(dp(18), dp(18)))
        self.bind(pos=self._redraw, size=self._redraw)
        Clock.schedule_once(lambda _dt: self._make_texture(), 0)

    def set_hsv(self, hue, saturation, value=None):
        self.hue = hue % 1.0
        self.saturation = max(0.0, min(1.0, saturation))
        if value is not None:
            next_value = max(0.0, min(1.0, value))
            if self._texture is None or abs(next_value - self.value) > 0.005:
                self.value = next_value
                self._make_texture()
        self._redraw()

    def _make_texture(self):
        size = 192
        buf = bytearray(size * size * 4)
        center = (size - 1) / 2
        radius = center - 1
        for y in range(size):
            dy = center - y
            for x in range(size):
                dx = x - center
                distance = (dx * dx + dy * dy) ** 0.5
                i = (y * size + x) * 4
                if distance <= radius:
                    h = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
                    s = min(1.0, distance / radius)
                    r, g, b = colorsys.hsv_to_rgb(h, s, self.value)
                    buf[i:i + 4] = bytes((int(r * 255), int(g * 255), int(b * 255), 255))
                else:
                    buf[i:i + 4] = b"\x00\x00\x00\x00"
        texture = Texture.create(size=(size, size), colorfmt="rgba")
        texture.blit_buffer(bytes(buf), colorfmt="rgba", bufferfmt="ubyte")
        texture.flip_vertical()
        self._texture = texture
        self._redraw()

    def _redraw(self, *_):
        if not self.width or not self.height:
            return
        side = min(self.width, self.height)
        x = self.x + (self.width - side) / 2
        y = self.y + (self.height - side) / 2
        self._image.pos = (x, y)
        self._image.size = (side, side)
        self._image.texture = self._texture
        center = (x + side / 2, y + side / 2)
        radius = side * 0.46
        self._ring.circle = (*center, radius)
        angle = self.hue * 2 * math.pi
        marker_radius = radius * self.saturation
        mx = center[0] + math.cos(angle) * marker_radius
        my = center[1] + math.sin(angle) * marker_radius
        self._marker_shadow.pos = (mx - dp(12), my - dp(12))
        self._marker_inner.pos = (mx - dp(9), my - dp(9))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return super().on_touch_down(touch)
        touch.grab(self)
        return self._pick(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self._pick(touch)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    def _pick(self, touch):
        side = min(self.width, self.height)
        center_x = self.x + self.width / 2
        center_y = self.y + self.height / 2
        dx, dy = touch.x - center_x, touch.y - center_y
        radius = max(1, side * 0.46)
        distance = min((dx * dx + dy * dy) ** 0.5, radius)
        self.hue = (math.atan2(dy, dx) / (2 * math.pi)) % 1.0
        self.saturation = distance / radius
        self._redraw()
        App.get_running_app().set_color_from_wheel(self.hue, self.saturation)
        return True


class LumaIRApp(App):
    title = "LumaIR"

    def build(self):
        Window.clearcolor = BG
        Window.softinput_mode = "below_target"
        self.transmitter = IrTransmitter()
        self.settings = self._load_settings()
        self.favorites = self._load_favorites()
        self.hue, self.saturation, self.value = 0.05, 0.86, 0.95
        self.rgb = tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(self.hue, self.saturation, self.value))
        self.wheel = None
        self.status_label = None
        self.hex_input = None
        self.rgb_inputs = []
        self.brightness_label = None
        self.protocol_label = None
        self.favorites_box = None
        self._syncing = False
        self._build_ui()
        self._refresh_device_status()
        return self.root

    def _load_settings(self):
        defaults = {"protocol": "rgb", "carrier_hz": 38000, "address": "00", "key_codes": {}}
        try:
            path = os.path.join(self.user_data_dir, "settings.json")
            with open(path, "r", encoding="utf-8") as file:
                loaded = json.load(file)
            defaults.update(loaded if isinstance(loaded, dict) else {})
        except (OSError, ValueError, TypeError):
            pass
        if defaults.get("protocol") not in ("rgb", "keys"):
            defaults["protocol"] = "rgb"
        if not isinstance(defaults.get("key_codes"), dict):
            defaults["key_codes"] = {}
        try:
            defaults["carrier_hz"] = int(defaults["carrier_hz"])
        except (ValueError, TypeError):
            defaults["carrier_hz"] = 38000
        address = str(defaults.get("address", "00")).upper().removeprefix("0X")
        defaults["address"] = address.zfill(2) if re.fullmatch(r"[0-9A-F]{1,2}", address) else "00"
        return defaults

    def _load_favorites(self):
        try:
            with open(os.path.join(self.user_data_dir, "favorites.json"), "r", encoding="utf-8") as file:
                data = json.load(file)
            return [v for v in data if re.fullmatch(r"#[0-9A-Fa-f]{6}", v)][:12]
        except (OSError, ValueError, TypeError):
            return []

    def _save_json(self, filename, data):
        os.makedirs(self.user_data_dir, exist_ok=True)
        path = os.path.join(self.user_data_dir, filename)
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def _build_ui(self):
        self.root = BoxLayout(orientation="vertical", padding=(dp(18), dp(8), dp(18), dp(10)), spacing=dp(8))
        with self.root.canvas.before:
            Color(*BG)
            self._root_rect = Rectangle(pos=self.root.pos, size=self.root.size)
        self.root.bind(pos=lambda *_: setattr(self._root_rect, "pos", self.root.pos), size=lambda *_: setattr(self._root_rect, "size", self.root.size))

        header = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        logo = RoundedPanel(orientation="vertical", size_hint=(None, None), size=(dp(42), dp(42)), radius=dp(14), color=(0.12, 0.27, 0.25, 1))
        logo.add_widget(make_label("IR", size=16, color=ACCENT, bold=True, halign="center"))
        header.add_widget(logo)
        brand = BoxLayout(orientation="vertical", spacing=dp(0))
        brand.add_widget(make_label("LUMAIR", size=16, bold=True))
        brand.add_widget(make_label("УПРАВЛЕНИЕ СВЕТОМ", size=9, color=MUTED, bold=True))
        header.add_widget(brand)
        header.add_widget(Widget())
        protocol_name = "RGB · 32 БИТ" if self.settings["protocol"] == "rgb" else "КНОПКИ · RAW"
        self.protocol_label = PillButton(protocol_name, fill=(0.10, 0.22, 0.20, 1), text_color=ACCENT, size_hint=(None, None), size=(dp(124), dp(34)))
        self.protocol_label.bind(on_release=lambda *_: self.open_settings())
        header.add_widget(self.protocol_label)
        self.root.add_widget(header)

        status = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(8))
        with status.canvas.before:
            self._status_dot_color_instruction = Color(0.16, 0.72, 0.53, 1)
            self._status_dot = Ellipse(pos=(0, 0), size=(dp(7), dp(7)))
        status.bind(pos=self._place_status_dot, size=self._place_status_dot)
        self.status_label = make_label("Проверяем ИК-передатчик…", size=11, color=MUTED)
        status.add_widget(self.status_label)
        self.root.add_widget(status)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(2), scroll_type=["bars", "content"])
        content = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12), padding=(0, dp(4), 0, dp(12)))
        content.bind(minimum_height=content.setter("height"))
        title = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(58), spacing=dp(0))
        title.add_widget(make_label("Цвет вашей ленты", size=25, bold=True))
        title.add_widget(make_label("Выберите оттенок или введите значения вручную", size=12, color=MUTED))
        content.add_widget(title)

        wheel_card = RoundedPanel(orientation="vertical", size_hint_y=None, height=dp(276), padding=(dp(8), dp(8)), spacing=dp(2), color=PANEL)
        self.wheel = ColorWheel(size_hint=(1, 1))
        wheel_card.add_widget(self.wheel)
        content.add_widget(wheel_card)

        entry_card = RoundedPanel(orientation="vertical", size_hint_y=None, height=dp(105), padding=(dp(14), dp(9)), spacing=dp(7), color=PANEL)
        entry_card.add_widget(make_label("ТОЧНЫЙ ЦВЕТ", size=9, color=MUTED, bold=True, size_hint_y=None, height=dp(13)))
        entry_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(7))
        self.hex_input = self._field("#F4A66A", 15, True)
        self.hex_input.size_hint_x = 1.35
        self.hex_input.bind(text=self._on_hex_text, on_text_validate=lambda *_: self._commit_fields())
        entry_row.add_widget(self.hex_input)
        self.rgb_inputs = []
        for value, name in zip(self.rgb, ("R", "G", "B")):
            field = self._field(str(value), 13, False, hint=name)
            field.size_hint_x = 0.68
            field.input_filter = "int"
            field.bind(text=self._on_rgb_text, on_text_validate=lambda *_: self._commit_fields())
            self.rgb_inputs.append(field)
            entry_row.add_widget(field)
        entry_card.add_widget(entry_row)
        content.add_widget(entry_card)

        brightness = RoundedPanel(orientation="vertical", size_hint_y=None, height=dp(78), padding=(dp(14), dp(8)), spacing=dp(3), color=PANEL)
        bright_head = BoxLayout(size_hint_y=None, height=dp(20))
        bright_head.add_widget(make_label("Яркость", size=12, bold=True))
        bright_head.add_widget(Widget())
        self.brightness_label = make_label("95%", size=11, color=ACCENT, bold=True, halign="right", size_hint_x=None, width=dp(45))
        bright_head.add_widget(self.brightness_label)
        brightness.add_widget(bright_head)
        self.brightness_slider = Slider(min=0, max=100, value=self.value * 100, step=1, cursor_size=(dp(20), dp(20)))
        self._style_slider(self.brightness_slider)
        self.brightness_slider.bind(value=self._on_brightness)
        brightness.add_widget(self.brightness_slider)
        content.add_widget(brightness)

        presets_card = RoundedPanel(orientation="vertical", size_hint_y=None, height=dp(114), padding=(dp(14), dp(10)), spacing=dp(7), color=PANEL)
        preset_head = BoxLayout(size_hint_y=None, height=dp(16))
        preset_head.add_widget(make_label("БЫСТРЫЕ ЦВЕТА", size=9, color=MUTED, bold=True))
        preset_head.add_widget(Widget())
        star = PillButton("☆  Сохранить", fill=(0.10, 0.13, 0.17, 1), text_color=ACCENT, size_hint=(None, None), size=(dp(110), dp(28)), font_size=11)
        star.bind(on_release=lambda *_: self.toggle_favorite())
        preset_head.add_widget(star)
        presets_card.add_widget(preset_head)
        preset_row = BoxLayout(spacing=dp(9), size_hint_y=None, height=dp(36))
        self.preset_buttons = []
        for name, color in [("Красный", "#FF3048"), ("Янтарь", "#FF9D38"), ("Лайм", "#B9F542"), ("Мята", "#34D9A2"), ("Лёд", "#55C8FF"), ("Фиолет", "#A881FF")]:
            chip = Button(text="", size_hint=(1, 1), background_normal="", background_color=(0, 0, 0, 0))
            chip._hex = color
            with chip.canvas.before:
                chip._chip_color = Color(*rgba(color))
                chip._chip = RoundedRectangle(pos=chip.pos, size=chip.size, radius=[dp(12)])
                Color(1, 1, 1, 0.26)
                chip._shine = Line(rounded_rectangle=(0, 0, 1, 1, dp(12)), width=dp(1))
            chip.bind(pos=lambda instance, *_: self._sync_chip(instance), size=lambda instance, *_: self._sync_chip(instance), on_release=lambda instance: self.set_color_hex(instance._hex))
            chip._preset_name = name
            self.preset_buttons.append(chip)
            preset_row.add_widget(chip)
        presets_card.add_widget(preset_row)
        self.favorites_box = BoxLayout(spacing=dp(7), size_hint_y=None, height=dp(24))
        presets_card.add_widget(self.favorites_box)
        content.add_widget(presets_card)

        send_row = BoxLayout(size_hint_y=None, height=dp(58), spacing=dp(9))
        send = PillButton("➤   ПЕРЕДАТЬ ЦВЕТ", fill=ACCENT, text_color=(0.035, 0.07, 0.07, 1), radius=dp(18), font_size=14)
        send.bind(on_release=lambda *_: self.send_current_color())
        send_row.add_widget(send)
        settings_button = PillButton("⚙", fill=PANEL_2, text_color=TEXT, radius=dp(18), size_hint_x=None, width=dp(58), font_size=21)
        settings_button.bind(on_release=lambda *_: self.open_settings())
        power_on = PillButton("ON", fill=(0.10, 0.22, 0.20, 1), text_color=ACCENT, radius=dp(16), size_hint_x=None, width=dp(45), font_size=10)
        power_on.bind(on_release=lambda *_: self.send_key_action("POWER_ON"))
        power_on.disabled = self.settings.get("protocol") != "keys"
        power_off = PillButton("OFF", fill=PANEL_2, text_color=MUTED, radius=dp(16), size_hint_x=None, width=dp(45), font_size=10)
        power_off.bind(on_release=lambda *_: self.send_key_action("POWER_OFF"))
        power_off.disabled = self.settings.get("protocol") != "keys"
        self._power_buttons = (power_on, power_off)
        send_row.add_widget(power_on)
        send_row.add_widget(power_off)
        send_row.add_widget(settings_button)
        content.add_widget(send_row)
        footer = make_label("Совместимость зависит от протокола контроллера ленты", size=10, color=MUTED, halign="center", size_hint_y=None, height=dp(20))
        content.add_widget(footer)
        scroll.add_widget(content)
        self.root.add_widget(scroll)
        self._sync_fields()
        self._render_favorites()

    def _field(self, text, font_size, bold, hint=""):
        field = TextInput(text=text, hint_text=hint, multiline=False, font_name=FONT, font_size=sp(font_size),
                          foreground_color=TEXT, hint_text_color=MUTED, cursor_color=ACCENT,
                          background_normal="", background_active="", background_color=PANEL_2,
                          padding=(dp(10), dp(8)), halign="center", write_tab=False)
        return field

    def _style_slider(self, slider):
        slider.cursor_size = (dp(18), dp(18))
        slider.value_track = True
        slider.value_track_color = ACCENT
        slider.min = 0
        slider.max = 100

    def _place_status_dot(self, widget, *_):
        self._status_dot.pos = (widget.x, widget.center_y - dp(3.5))

    def _sync_chip(self, chip):
        chip._chip.pos, chip._chip.size = chip.pos, chip.size
        chip._shine.rounded_rectangle = (*chip.pos, *chip.size, dp(12))

    def _refresh_device_status(self):
        info = self.transmitter.inspect()
        if info.available:
            self.status_label.text = "ИК-передатчик готов · %s" % info.label
            self.status_label.color = ACCENT
            self._status_dot_color((0.16, 0.82, 0.58, 1))
        elif platform != "android":
            self.status_label.text = "Предпросмотр · сборка и проверка ИК доступны на Android"
            self.status_label.color = MUTED
            self._status_dot_color((0.98, 0.67, 0.28, 1))
        else:
            self.status_label.text = info.label
            self.status_label.color = ORANGE
            self._status_dot_color((1.0, 0.54, 0.30, 1))

    def _status_dot_color(self, color):
        self._status_dot_color_instruction.rgba = color

    def _set_status(self, message, color=MUTED):
        self.status_label.text = message
        self.status_label.color = color

    def set_color_from_wheel(self, hue, saturation):
        self.hue, self.saturation = hue, saturation
        self._set_rgb_from_hsv()

    def _set_rgb_from_hsv(self):
        self.rgb = tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(self.hue, self.saturation, self.value))
        self._sync_fields()

    def _set_rgb(self, rgb, source=None):
        self.rgb = tuple(max(0, min(255, int(v))) for v in rgb)
        h, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in self.rgb))
        if max(self.rgb) > 0:
            self.hue, self.saturation = h, s
        self.value = v
        self._syncing = True
        self.brightness_slider.value = round(v * 100)
        self._syncing = False
        if self.wheel:
            self.wheel.set_hsv(self.hue, self.saturation, self.value)
        self._sync_fields(skip=source)

    def _sync_fields(self, skip=None):
        self._syncing = True
        if self.hex_input and skip != "hex":
            self.hex_input.text = rgb_hex(self.rgb)
        for index, field in enumerate(self.rgb_inputs):
            if skip != index:
                field.text = str(self.rgb[index])
        if self.brightness_label:
            self.brightness_label.text = "%d%%" % round(self.value * 100)
        if self.wheel:
            self.wheel.set_hsv(self.hue, self.saturation, self.value)
        self._syncing = False

    def _on_hex_text(self, field, text):
        if self._syncing:
            return
        value = text.strip().upper().lstrip("#")
        if re.fullmatch(r"[0-9A-F]{6}", value):
            rgb = tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
            self._set_rgb(rgb, source="hex")

    def _on_rgb_text(self, field, _text):
        if self._syncing:
            return
        try:
            rgb = [int(item.text or "0") for item in self.rgb_inputs]
        except ValueError:
            return
        if all(0 <= value <= 255 for value in rgb):
            source = self.rgb_inputs.index(field)
            self._set_rgb(rgb, source=source)

    def _commit_fields(self):
        if self.hex_input and re.fullmatch(r"#?[0-9A-Fa-f]{6}", self.hex_input.text.strip()):
            self.set_color_hex(self.hex_input.text)
            return
        try:
            rgb = [int(item.text) for item in self.rgb_inputs]
            if all(0 <= v <= 255 for v in rgb):
                self._set_rgb(rgb)
        except ValueError:
            self._sync_fields()

    def _on_brightness(self, _slider, value):
        if self._syncing:
            return
        self.value = max(0, min(1, value / 100))
        self._set_rgb_from_hsv()

    def set_color_hex(self, hex_color):
        value = hex_color.strip().lstrip("#")
        if re.fullmatch(r"[0-9A-Fa-f]{6}", value):
            self._set_rgb(tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)))

    def toggle_favorite(self):
        current = rgb_hex(self.rgb)
        if current in self.favorites:
            self.favorites.remove(current)
            self._set_status("Цвет удалён из избранного", MUTED)
        elif len(self.favorites) < 12:
            self.favorites.insert(0, current)
            self._set_status("Цвет сохранён в избранное", ACCENT)
        else:
            self.favorites.pop()
            self.favorites.insert(0, current)
            self._set_status("Избранное обновлено · максимум 12 цветов", ACCENT)
        self._save_json("favorites.json", self.favorites)
        self._render_favorites()

    def _render_favorites(self):
        if not self.favorites_box:
            return
        self.favorites_box.clear_widgets()
        if not self.favorites:
            self.favorites_box.add_widget(make_label("☆ Сохраняйте любимые оттенки", size=10, color=MUTED))
            return
        for color in self.favorites[:12]:
            chip = PillButton("", fill=rgba(color), radius=dp(7), size_hint=(None, 1), width=dp(27))
            chip.bind(on_release=lambda _button, value=color: self.set_color_hex(value))
            self.favorites_box.add_widget(chip)

    def open_settings(self):
        modal = ModalView(size_hint=(0.94, 0.88), background_color=(0, 0, 0, 0.55), auto_dismiss=True)
        panel = RoundedPanel(orientation="vertical", padding=(dp(18), dp(15)), spacing=dp(10), color=(0.055, 0.07, 0.10, 1), radius=dp(24))
        heading = BoxLayout(size_hint_y=None, height=dp(35))
        heading.add_widget(make_label("Настройки ИК", size=19, bold=True))
        heading.add_widget(Widget())
        close = PillButton("×", fill=PANEL_2, size_hint=(None, None), size=(dp(36), dp(34)), font_size=20)
        close.bind(on_release=lambda *_: modal.dismiss())
        heading.add_widget(close)
        panel.add_widget(heading)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(2))
        form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(9), padding=(0, 0, 0, dp(8)))
        form.bind(minimum_height=form.setter("height"))
        form.add_widget(make_label("ПРОТОКОЛ ПЕРЕДАЧИ", size=9, color=MUTED, bold=True, size_hint_y=None, height=dp(17)))
        mode_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        rgb_mode = PillButton("RGB-пакет · произвольный цвет", fill=PANEL_2, text_color=ACCENT if self.settings["protocol"] == "rgb" else MUTED, font_size=11)
        keys_mode = PillButton("Коды кнопок / RAW", fill=PANEL_2, text_color=ACCENT if self.settings["protocol"] == "keys" else MUTED, font_size=11)
        chosen_mode = {"value": self.settings["protocol"]}
        mode_row.add_widget(rgb_mode)
        mode_row.add_widget(keys_mode)
        form.add_widget(mode_row)

        form.add_widget(make_label("Несущая частота (Гц)", size=12, bold=True, size_hint_y=None, height=dp(19)))
        freq = self._field(str(self.settings.get("carrier_hz", 38000)), 14, False)
        freq.input_filter = "int"
        freq.size_hint_y = None
        freq.height = dp(40)
        form.add_widget(freq)
        form.add_widget(make_label("Адрес пакета (HEX, 00–FF)", size=12, bold=True, size_hint_y=None, height=dp(19)))
        address = self._field(str(self.settings.get("address", "00")), 14, False)
        address.size_hint_y = None
        address.height = dp(40)
        form.add_widget(address)

        form.add_widget(make_label("Команды · NEC-коды или RAW-тайминги", size=12, bold=True, size_hint_y=None, height=dp(19)))
        form.add_widget(make_label("Ключи #RRGGBB, POWER_OFF, POWER_ON или WHITE. Значение: 8 HEX-цифр NEC либо RAW:интервалы в мкс.", size=10, color=MUTED, size_hint_y=None, height=dp(34)))
        codes = TextInput(text=json.dumps(self.settings.get("key_codes", {}), ensure_ascii=False, indent=2), multiline=True,
                          font_name=FONT, font_size=sp(12), foreground_color=TEXT, cursor_color=ACCENT,
                          background_normal="", background_active="", background_color=PANEL_2,
                          padding=(dp(10), dp(9)), size_hint_y=None, height=dp(130))
        form.add_widget(codes)
        note = RoundedPanel(orientation="vertical", size_hint_y=None, height=dp(86), padding=(dp(11), dp(8)), color=(0.13, 0.10, 0.07, 1), radius=dp(14))
        note.add_widget(make_label("Важно про совместимость", size=11, color=ORANGE, bold=True, size_hint_y=None, height=dp(19)))
        note.add_widget(make_label("RGB-пакет — настраиваемый формат, который поддерживают не все ленты. Кнопочные пульты обычно умеют только заранее записанные цвета.", size=10, color=(0.87, 0.79, 0.67, 1)))
        form.add_widget(note)
        form.add_widget(make_label("Проверяйте частоту в характеристиках контроллера. Android сообщит поддерживаемый диапазон телефона.", size=10, color=MUTED, size_hint_y=None, height=dp(34)))
        scroll.add_widget(form)
        panel.add_widget(scroll)
        save_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        message = make_label("", size=10, color=ORANGE)
        save = PillButton("Сохранить профиль", fill=ACCENT, text_color=(0.035, 0.07, 0.07, 1), radius=dp(16), font_size=13)
        save_row.add_widget(save)
        panel.add_widget(save_row)

        def choose(mode):
            chosen_mode["value"] = mode
            for button, selected in ((rgb_mode, mode == "rgb"), (keys_mode, mode == "keys")):
                button.color = ACCENT if selected else MUTED
                button._fill = (0.10, 0.22, 0.20, 1) if selected else PANEL_2
                button._down_fill = tuple(max(0, c * 0.82) if i < 3 else c for i, c in enumerate(button._fill))
                button._shape_color.rgba = button._fill
        rgb_mode.bind(on_release=lambda *_: choose("rgb"))
        keys_mode.bind(on_release=lambda *_: choose("keys"))

        def save_profile(*_):
            try:
                hz = int(freq.text)
                addr = address.text.strip().upper().removeprefix("0X")
                mapping = json.loads(codes.text or "{}")
                if not 30000 <= hz <= 60000:
                    raise ValueError("Частота должна быть от 30000 до 60000 Гц")
                if not re.fullmatch(r"[0-9A-F]{1,2}", addr):
                    raise ValueError("Адрес должен быть HEX-числом 00–FF")
                if not isinstance(mapping, dict):
                    raise ValueError("Таблица кодов должна быть JSON-объектом")
                clean = {}
                for key, code in mapping.items():
                    color = str(key).upper()
                    value = str(code).strip().upper()
                    if not (re.fullmatch(r"#[0-9A-F]{6}", color) or color in ("POWER_ON", "POWER_OFF", "WHITE")):
                        raise ValueError("Ключ должен быть цветом #RRGGBB или действием POWER_ON/POWER_OFF/WHITE")
                    parse_key_pattern(value)
                    clean[color] = value
                self.settings.update({"protocol": chosen_mode["value"], "carrier_hz": hz, "address": addr.zfill(2), "key_codes": clean})
                self._save_json("settings.json", self.settings)
                self.protocol_label.text = "RGB · 32 БИТ" if self.settings["protocol"] == "rgb" else "КНОПКИ · RAW"
                for button in self._power_buttons:
                    button.disabled = self.settings["protocol"] != "keys"
                self._set_status("Профиль сохранён · %d Гц" % hz, ACCENT)
                modal.dismiss()
            except (ValueError, json.JSONDecodeError) as exc:
                message.text = str(exc)
                if not message.parent:
                    save_row.add_widget(message)

        save.bind(on_release=save_profile)
        modal.add_widget(panel)
        modal.open()

    def send_current_color(self):
        self._commit_fields()
        selected = rgb_hex(self.rgb)
        settings = self.settings
        try:
            if settings["protocol"] == "rgb":
                address = int(settings.get("address", "00"), 16)
                # Custom 32-bit NEC-timed frame: [address byte, R, G, B].
                code = (address << 24) | (self.rgb[0] << 16) | (self.rgb[1] << 8) | self.rgb[2]
                pattern = build_nec_pattern(code)
            else:
                code_hex = settings.get("key_codes", {}).get(selected)
                if not code_hex:
                    self._set_status("Для %s нет команды в профиле" % selected, ORANGE)
                    return
                pattern = parse_key_pattern(code_hex, repeats=1)
            self.transmitter.send(int(settings.get("carrier_hz", 38000)), pattern)
            self._set_status("Передан %s · %s" % (selected, datetime.now().strftime("%H:%M:%S")), ACCENT)
        except IrError as exc:
            self._set_status(str(exc), ORANGE)
        except (ValueError, TypeError) as exc:
            self._set_status("Проверьте настройки профиля: %s" % exc, ORANGE)

    def send_key_action(self, action):
        if self.settings.get("protocol") != "keys":
            self._set_status("Команды питания доступны в профиле кнопок", ORANGE)
            return
        code_hex = self.settings.get("key_codes", {}).get(action)
        if not code_hex:
            self._set_status("Добавьте команду %s в профиль" % action, ORANGE)
            return
        try:
            pattern = parse_key_pattern(code_hex, repeats=1)
            self.transmitter.send(int(self.settings.get("carrier_hz", 38000)), pattern)
            label = "включить" if action == "POWER_ON" else "выключить"
            self._set_status("Команда «%s» передана" % label, ACCENT)
        except (IrError, ValueError, TypeError) as exc:
            self._set_status(str(exc), ORANGE)


if __name__ == "__main__":
    LumaIRApp().run()
