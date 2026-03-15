#!/usr/bin/env python3
import sys, os, time, tempfile, selectors

os.environ['XDG_RUNTIME_DIR'] = f'/run/user/{os.getenv("SUDO_UID", "1000")}'
os.environ['WAYLAND_DISPLAY'] = 'wayland-1'

import evdev
from evdev import InputDevice, ecodes as e
from pywayland.client import Display
from wayland_protocols.wayland import WlSeat
from wayland_protocols.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1
from wayland_protocols.zwp_virtual_keyboard_unstable_v1 import ZwpVirtualKeyboardManagerV1

# ── 连接 cage ──────────────────────────────────────────────────────
display = Display()
display.connect()
registry = display.get_registry()

vp_manager = None
vk_manager = None
seat = None

def on_global(registry, name, interface, version):
    global vp_manager, vk_manager, seat
    if interface == 'zwlr_virtual_pointer_manager_v1':
        vp_manager = registry.bind(name, ZwlrVirtualPointerManagerV1, version)
    elif interface == 'zwp_virtual_keyboard_manager_v1':
        vk_manager = registry.bind(name, ZwpVirtualKeyboardManagerV1, version)
    elif interface == 'wl_seat':
        seat = registry.bind(name, WlSeat, version)

registry.dispatcher['global'] = on_global
display.roundtrip()

if not vp_manager: print("ERROR: no virtual pointer"); sys.exit(1)
if not vk_manager: print("ERROR: no virtual keyboard"); sys.exit(1)

vpointer  = vp_manager.create_virtual_pointer(seat)
vkeyboard = vk_manager.create_virtual_keyboard(seat)
display.roundtrip()

# ── 上传 keymap ────────────────────────────────────────────────────
KEYMAP = b"xkb_keymap {\n  xkb_keycodes { include \"evdev+aliases(qwerty)\" };\n  xkb_types    { include \"complete\" };\n  xkb_compat   { include \"complete\" };\n  xkb_symbols  { include \"pc+us+inet(evdev)\" };\n  xkb_geometry { include \"pc(pc105)\" };\n};\n\x00"

with tempfile.NamedTemporaryFile(delete=False) as f:
    f.write(KEYMAP)
    keymap_path = f.name

fd = os.open(keymap_path, os.O_RDONLY)
vkeyboard.keymap(1, fd, len(KEYMAP))
os.close(fd)
display.roundtrip()
print("Keymap 上传成功")

# ── XKB modifier 位掩码（标准 pc+us 布局）─────────────────────────
MOD_SHIFT   = 0x01
MOD_LOCK    = 0x02
MOD_CTRL    = 0x04
MOD_ALT     = 0x08
MOD_MOD4    = 0x40  # Super/Win

MODIFIER_KEYS = {
    e.KEY_LEFTSHIFT:  MOD_SHIFT,
    e.KEY_RIGHTSHIFT: MOD_SHIFT,
    e.KEY_LEFTCTRL:   MOD_CTRL,
    e.KEY_RIGHTCTRL:  MOD_CTRL,
    e.KEY_LEFTALT:    MOD_ALT,
    e.KEY_RIGHTALT:   MOD_ALT,
    e.KEY_LEFTMETA:   MOD_MOD4,
    e.KEY_RIGHTMETA:  MOD_MOD4,
}

mods_depressed = 0

def update_modifiers(keycode, value):
    global mods_depressed
    if keycode not in MODIFIER_KEYS:
        return
    bit = MODIFIER_KEYS[keycode]
    if value == 1:    # press
        mods_depressed |= bit
    elif value == 0:  # release
        mods_depressed &= ~bit
    vkeyboard.modifiers(mods_depressed, 0, 0, 0)

# ── 打开三个设备 ───────────────────────────────────────────────────
mouse_rel = InputDevice('/dev/input/event22') # TODO: autodetect
mouse_abs = InputDevice('/dev/input/event23') # config HERE!
keyboard  = InputDevice('/dev/input/event24')

mouse_rel.grab()
mouse_abs.grab()
keyboard.grab()

print(f"REL 鼠标:  {mouse_rel.name}")
print(f"ABS 鼠标:  {mouse_abs.name}")
print(f"键盘:      {keyboard.name}")

# ── 把指针初始化到屏幕中央 ─────────────────────────────────────────
def ms(): return int(time.monotonic() * 1000)

vpointer.motion_absolute(int(time.time()), 960, 540, 1920, 1080)
vpointer.frame()
display.flush()
print("指针已初始化到屏幕中央")

# ── 事件循环 ───────────────────────────────────────────────────────
sel = selectors.DefaultSelector()
sel.register(mouse_rel, selectors.EVENT_READ, 'rel')
sel.register(mouse_abs, selectors.EVENT_READ, 'abs')
sel.register(keyboard,  selectors.EVENT_READ, 'kbd')

pending_dx = 0
pending_dy = 0

print("桥接运行中...")
# 在设备初始化后获取 abs 范围
abs_info_x = mouse_abs.absinfo(e.ABS_X)
abs_info_y = mouse_abs.absinfo(e.ABS_Y)
print(f"ABS 范围: X={abs_info_x.min}~{abs_info_x.max} Y={abs_info_y.min}~{abs_info_y.max}")

pending_ax = None
pending_ay = None

last_ax = 0
last_ay = 0

while True:
    for key, _ in sel.select():
        tag = key.data
        dev = key.fileobj

        for event in dev.read():
            t = ms()

            if tag == 'rel':
                if event.type == e.EV_REL:
                    if event.code == e.REL_X:
                        pending_dx += event.value
                    elif event.code == e.REL_Y:
                        pending_dy += event.value
                    elif event.code == e.REL_WHEEL:
                        vpointer.axis(t, 0, event.value * 15)
                        # 不要在这里调用 axis_stop
                    elif event.code == e.REL_WHEEL_HI_RES:
                        # 高精度滚轮，值是普通的 1/120
                        vpointer.axis(t, 0, event.value * 15 // 120)
                    elif event.code == e.REL_HWHEEL:
                        vpointer.axis(t, 1, event.value * 15)  # 1 = 水平轴
                    elif event.code == e.REL_HWHEEL_HI_RES:
                        vpointer.axis(t, 1, event.value * 15 // 120)
                elif event.type == e.EV_KEY:  # ← 点击在这里
                    if event.code in (e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE,
                                    e.BTN_SIDE, e.BTN_EXTRA):
                        vpointer.button(t, event.code, event.value)
                elif event.type == e.EV_SYN:
                    if pending_dx != 0 or pending_dy != 0:
                        vpointer.motion(t, float(pending_dx), float(pending_dy))
                        pending_dx = 0
                        pending_dy = 0
                    vpointer.frame()
                    display.flush()




            elif tag == 'abs':
                if event.type == e.EV_ABS:
                    if event.code == e.ABS_X:
                        last_ax = event.value
                    elif event.code == e.ABS_Y:
                        last_ay = event.value
                elif event.type == e.EV_KEY:
                    if event.code in (e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE,
                                    e.BTN_SIDE, e.BTN_EXTRA):
                        vpointer.button(t, event.code, event.value)
                elif event.type == e.EV_SYN:
                    vpointer.motion_absolute(
                        t,
                        last_ax, last_ay,
                        abs_info_x.max,
                        abs_info_y.max
                    )
                    vpointer.frame()
                    display.flush()

            elif tag == 'kbd':
                if event.type == e.EV_KEY and event.value in (0, 1, 2):
                    update_modifiers(event.code, event.value)
                    vkeyboard.key(t, event.code, event.value)
                    display.flush()
