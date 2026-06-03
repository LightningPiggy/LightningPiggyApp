"""Lightning Piggy Jump - an endless runner in the spirit of the offline
T-Rex game, starring the Lightning Piggy character.

Pure-Python LVGL game: a single lv.timer drives a fixed-timestep update loop
(see com.micropythonos.confetti for the same pattern). All art is moved around
as lv.image widgets; day/night is done with LVGL image recolor of the
obstacles/ground/clouds. The piggy keeps its full colour (it is excluded from
the recolour). Player sprites come from tools/gen_piggy.py; everything else
from tools/gen_sprites.py.

Controls
  - Tap anywhere   -> jump (and start / restart)
  - Hold DUCK      -> duck under flying bolts; tapping it midair fast-falls

NOTE: this file is ALSO embedded (as a copy) in the Lightning Piggy wallet as a
hidden easter egg. Keep both copies in sync when editing:
  - this one: com.micropythonos.dinojump/assets/dino.py (canonical; sprite
    generators live in this app's tools/)
  - the copy:  LightningPiggyApp/.../assets/dino.py
The resource path is derived from self.appFullName so the same file works in
both. See LightningPiggyApp/docs/dino-easter-egg.md for the full handover.
"""
import math
import time
import random

import lvgl as lv

from mpos import Activity, DisplayMetrics, SharedPreferences

# Native sprite sizes (px). Obstacles/ground from tools/gen_sprites.py; the
# player (Lightning Piggy) from tools/gen_piggy.py.
SIZ = {
    "piggy_run1": (37, 48), "piggy_run2": (37, 48), "piggy_stand": (37, 48),
    "piggy_dead": (37, 48), "piggy_duck1": (39, 31), "piggy_duck2": (39, 31),
    "poop_small": (32, 30), "poop_big": (49, 46),
    "bolt": (18, 36),
    "cloud": (46, 12), "moon": (30, 30), "ground": (480, 24), "restart": (42, 30),
}

# Player character sprites (the piggy stays full-colour: excluded from the
# day/night recolour applied to obstacles/ground/clouds).
CHAR_STAND = "piggy_stand"
CHAR_RUN = ("piggy_run1", "piggy_run2")
CHAR_DUCK = ("piggy_duck1", "piggy_duck2")
CHAR_DEAD = "piggy_dead"

DAY_BG = 0xF7F7F7
DAY_FG = 0x535353
NIGHT_BG = 0x2A2A2A
NIGHT_FG = 0xF7F7F7

# States
INTRO = 0
RUNNING = 1
GAMEOVER = 2


class DinoJump(Activity):

    def onCreate(self):
        self.prefs = SharedPreferences(self.appFullName)
        self.hi_score = self.prefs.get_int("hi_score", 0)
        # Resource path follows the host app, so this same activity works both
        # standalone and embedded (e.g. as the Lightning Piggy easter egg).
        self.res = "M:apps/" + self.appFullName + "/res/drawable-mdpi/"

        self.W = DisplayMetrics.width()
        self.H = DisplayMetrics.height()
        self.ground_y = self.H - max(24, int(self.H * 0.16))  # horizon line

        lv.lodepng_init()  # defensive PNG decoder init (MPOS_APP_DEV.md s6)

        self.screen = lv.obj()
        self.screen.set_style_bg_color(lv.color_hex(DAY_BG), 0)
        self.screen.set_style_bg_opa(lv.OPA.COVER, 0)
        self.screen.set_style_border_width(0, 0)
        self.screen.set_style_pad_all(0, 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        # Full-screen transparent jump button BEHIND the sprites. Sprite images
        # are not clickable, so taps fall through to this (LVGL hit-test only
        # considers CLICKABLE objects). The duck button sits on top of it.
        self.jump_btn = lv.button(self.screen)
        self.jump_btn.set_size(lv.pct(100), lv.pct(100))
        self.jump_btn.set_style_bg_opa(lv.OPA.TRANSP, 0)
        self.jump_btn.set_style_border_width(0, 0)
        self.jump_btn.set_style_shadow_width(0, 0)
        self.jump_btn.set_style_radius(0, 0)
        self.jump_btn.add_event_cb(self._on_press, lv.EVENT.PRESSED, None)

        # Full moon, high in the sky, drifting at 1/4 the cloud speed. Created
        # before the clouds so they pass in front of it. Full colour (not in
        # the day/night recolour group).
        self.moon = lv.image(self.screen)
        self.moon.set_src(self.res + "moon.png")
        self.moon_x = 0.0
        self.moon_y = int(self.H * 0.10)

        # Background clouds (slow parallax).
        self.clouds = []
        for _ in range(3):
            c = lv.image(self.screen)
            c.set_src(self.res + "cloud.png")
            c.add_flag(lv.obj.FLAG.HIDDEN)
            self.clouds.append({"img": c, "x": 0.0, "y": 0})

        # Two ground tiles scrolled left and wrapped.
        gw, gh = SIZ["ground"]
        self.ground_w = gw
        self.grounds = []
        for i in range(2):
            g = lv.image(self.screen)
            g.set_src(self.res + "ground.png")
            g.set_pos(i * gw, self.ground_y)
            self.grounds.append(g)

        # Obstacle pool (poop on the ground + flying lightning bolts).
        self.obstacles = []
        for _ in range(4):
            o = lv.image(self.screen)
            o.add_flag(lv.obj.FLAG.HIDDEN)
            self.obstacles.append({
                "img": o, "x": 0.0, "y": 0, "w": 0, "h": 0,
                "active": False, "kind": None, "frame": 0, "anim": 0.0,
            })

        # The dino.
        self.dino = lv.image(self.screen)
        self.dino.set_src(self.res + CHAR_STAND + ".png")
        self.dino_x = max(12, int(self.W * 0.06))
        self.dino.set_pos(self.dino_x, self.ground_y - SIZ[CHAR_STAND][1])

        # Score labels (top-right), monospace look via default font.
        self.hi_label = lv.label(self.screen)
        self.hi_label.set_style_text_color(lv.color_hex(DAY_FG), 0)
        self.score_label = lv.label(self.screen)
        self.score_label.set_style_text_color(lv.color_hex(DAY_FG), 0)

        # Center message (start / game over).
        self.msg = lv.label(self.screen)
        self.msg.set_style_text_color(lv.color_hex(DAY_FG), 0)
        self.msg.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self.msg.align(lv.ALIGN.CENTER, 0, -int(self.H * 0.12))

        # Restart icon (shown on game over).
        self.restart = lv.image(self.screen)
        self.restart.set_src(self.res + "restart.png")
        rw, rh = SIZ["restart"]
        self.restart.align(lv.ALIGN.CENTER, 0, int(self.H * 0.02))
        self.restart.add_flag(lv.obj.FLAG.HIDDEN)

        # Duck button (press-and-hold), bottom-right, on top of jump_btn.
        self.duck_btn = lv.button(self.screen)
        self.duck_btn.set_size(int(self.W * 0.26), max(34, int(self.H * 0.18)))
        self.duck_btn.align(lv.ALIGN.BOTTOM_RIGHT, -6, -6)
        self.duck_btn.set_style_bg_opa(lv.OPA._40, 0)
        dl = lv.label(self.duck_btn)
        dl.set_text(lv.SYMBOL.DOWN + " DUCK")
        dl.center()
        self.duck_btn.add_event_cb(self._on_duck_press, lv.EVENT.PRESSED, None)
        self.duck_btn.add_event_cb(self._on_duck_release, lv.EVENT.RELEASED, None)
        self.duck_btn.add_event_cb(self._on_duck_release, lv.EVENT.PRESS_LOST, None)

        # Exit button (top-left): leave the game and return to the host app.
        # Shown on the start / game-over screens, hidden while running so it
        # can't be hit by accident mid-jump.
        self.exit_btn = lv.button(self.screen)
        self.exit_btn.align(lv.ALIGN.TOP_LEFT, 4, 4)
        self.exit_btn.set_style_bg_opa(lv.OPA._40, 0)
        el = lv.label(self.exit_btn)
        el.set_text(lv.SYMBOL.LEFT + " Exit")
        el.center()
        self.exit_btn.add_event_cb(self._on_exit, lv.EVENT.CLICKED, None)

        # Recoloured for day/night. The piggy is intentionally NOT in this list
        # so it keeps its full colour on both light and dark backgrounds.
        self._all_images = ([self.restart] +
                            [g for g in self.grounds] +
                            [c["img"] for c in self.clouds] +
                            [o["img"] for o in self.obstacles])

        self.timer = None
        self.is_night = False
        self._reset_to_intro()
        self.setContentView(self.screen)

    # ----- lifecycle -----------------------------------------------------
    def onResume(self, screen):
        self.last_ms = time.ticks_ms()
        if self.timer is None:
            self.timer = lv.timer_create(self._tick, 20, None)  # ~50 fps

    def onPause(self, screen):
        if self.timer is not None:
            self.timer.delete()
            self.timer = None

    # ----- state setup ---------------------------------------------------
    def _reset_to_intro(self):
        self.state = INTRO
        self.speed = self.base_speed = self.W * 0.55     # px/s
        self.max_speed = self.W * 2.0
        self.score = 0.0
        self.distance = 0.0
        self.duck_held = False
        self.ducking = False
        self.on_ground = True
        self.dino_vy = 0.0
        self.dino_y = float(self.ground_y - SIZ[CHAR_STAND][1])
        self.run_anim = 0.0
        self.run_frame = 0
        self.bob_phase = 0.0
        self.spawn_dist = self._next_spawn_gap()
        self.dist_since_spawn = 0.0
        self.night_at = 0.0
        self.blink = 0.0
        for o in self.obstacles:
            o["active"] = False
            o["img"].add_flag(lv.obj.FLAG.HIDDEN)
        # place the moon (upper-right) and the clouds
        self.moon_x = float(self.W * 0.72)
        self.moon.set_pos(int(self.moon_x), self.moon_y)
        cw, ch = SIZ["cloud"]
        for i, c in enumerate(self.clouds):
            c["x"] = float(self.W * (0.3 + 0.45 * i))
            c["y"] = int(self.H * (0.12 + 0.10 * (i % 3)))
            c["img"].set_pos(int(c["x"]), c["y"])
            c["img"].remove_flag(lv.obj.FLAG.HIDDEN)
        self.dino.set_src(self.res + CHAR_STAND + ".png")
        self.dino.set_pos(self.dino_x, int(self.dino_y))
        self.restart.add_flag(lv.obj.FLAG.HIDDEN)
        self.msg.set_text("LIGHTNING PIGGY\nTap to start")
        self.msg.remove_flag(lv.obj.FLAG.HIDDEN)
        self.exit_btn.remove_flag(lv.obj.FLAG.HIDDEN)
        self._apply_palette(night=False)
        self._update_score_labels()

    def _start_game(self):
        self.state = RUNNING
        self.msg.add_flag(lv.obj.FLAG.HIDDEN)
        self.restart.add_flag(lv.obj.FLAG.HIDDEN)
        self.exit_btn.add_flag(lv.obj.FLAG.HIDDEN)
        self.score = 0.0
        self.distance = 0.0
        self.speed = self.base_speed
        self.dist_since_spawn = 0.0
        self.spawn_dist = self._next_spawn_gap()
        self.night_at = 700.0
        self._jump()

    def _game_over(self):
        self.state = GAMEOVER
        self.dino.set_src(self.res + CHAR_DEAD + ".png")
        self.dino.set_pos(self.dino_x, int(self.dino_y))
        sc = int(self.score)
        if sc > self.hi_score:
            self.hi_score = sc
            ed = self.prefs.edit()
            ed.put_int("hi_score", sc)
            ed.commit()
        self.msg.set_text("G A M E   O V E R")
        self.msg.remove_flag(lv.obj.FLAG.HIDDEN)
        self.restart.remove_flag(lv.obj.FLAG.HIDDEN)
        self.exit_btn.remove_flag(lv.obj.FLAG.HIDDEN)
        self._update_score_labels()

    # ----- input ---------------------------------------------------------
    def _on_press(self, event):
        if self.state == INTRO:
            self._start_game()
        elif self.state == RUNNING:
            self._jump()
        elif self.state == GAMEOVER:
            self._reset_to_intro()

    def _on_duck_press(self, event):
        self.duck_held = True
        if self.state == INTRO:
            self._start_game()
        elif self.state == GAMEOVER:
            self._reset_to_intro()

    def _on_duck_release(self, event):
        self.duck_held = False

    def _on_exit(self, event):
        # Leave the game and return to whatever launched it (the host app or
        # the launcher when running standalone).
        self.finish()

    def _jump(self):
        if self.on_ground:
            self.dino_vy = -(self.H * 2.75)  # px/s; ~95px peak with gravity below
            self.on_ground = False
            self.ducking = False

    # ----- main loop -----------------------------------------------------
    def _tick(self, timer):
        now = time.ticks_ms()
        dt = time.ticks_diff(now, self.last_ms) / 1000.0
        self.last_ms = now
        if dt <= 0:
            return
        if dt > 0.1:
            dt = 0.1  # clamp after stalls so physics stays sane

        self._scroll_world(dt, moving=(self.state == RUNNING))

        if self.state == RUNNING:
            self._update_running(dt)
        elif self.state == INTRO:
            self._animate_dino(dt, running=False)
            self._blink_msg(dt)

    def _scroll_world(self, dt, moving):
        spd = self.speed if moving else 0.0
        dx = spd * dt
        # ground
        for g in self.grounds:
            nx = g.get_x() - dx
            if nx <= -self.ground_w:
                nx += self.ground_w * 2
            g.set_x(int(nx))
        # clouds (parallax, always drift a little)
        cw, _ = SIZ["cloud"]
        cspd = (spd * 0.25) + self.base_speed * 0.08
        for c in self.clouds:
            c["x"] -= cspd * dt
            if c["x"] < -cw:
                c["x"] = self.W + random.randint(0, int(self.W * 0.5))
                c["y"] = int(self.H * (0.10 + 0.18 * random.random()))
            c["img"].set_pos(int(c["x"]), c["y"])
        # moon: drifts at 1/4 of the cloud speed, wraps from left to right
        mw = SIZ["moon"][0]
        self.moon_x -= (cspd * 0.25) * dt
        if self.moon_x < -mw:
            self.moon_x = float(self.W)
        self.moon.set_x(int(self.moon_x))

    def _update_running(self, dt):
        # advance distance / score / speed
        self.distance += self.speed * dt
        self.score = self.distance / (self.W * 0.10)
        if self.speed < self.max_speed:
            self.speed += (self.W * 0.04) * dt  # gentle ramp
        self._update_score_labels()

        # day/night toggle
        if self.score >= self.night_at:
            self.night_at += 700.0
            self._apply_palette(night=not self.is_night)

        # dino physics
        self.ducking = self.duck_held and self.on_ground
        g = self.H * 9.5
        if self.duck_held and not self.on_ground:
            g *= 2.2  # fast-fall
        self.dino_vy += g * dt
        self.dino_y += self.dino_vy * dt
        floor = self.ground_y - self._dino_h()
        if self.dino_y >= floor:
            self.dino_y = floor
            self.dino_vy = 0.0
            self.on_ground = True
        self._animate_dino(dt, running=True)

        # spawn obstacles
        self.dist_since_spawn += self.speed * dt
        if self.dist_since_spawn >= self.spawn_dist:
            self.dist_since_spawn = 0.0
            self.spawn_dist = self._next_spawn_gap()
            self._spawn_obstacle()

        # move + animate obstacles, check collision
        dino_box = self._dino_box()
        for o in self.obstacles:
            if not o["active"]:
                continue
            o["x"] -= self.speed * dt
            if o["kind"] == "bolt":
                o["x"] -= self.speed * 0.15 * dt  # bolts fly a touch faster
            if o["x"] + o["w"] < 0:
                o["active"] = False
                o["img"].add_flag(lv.obj.FLAG.HIDDEN)
                continue
            o["img"].set_x(int(o["x"]))
            if self._hit(dino_box, o):
                self._game_over()
                return

    # ----- dino rendering ------------------------------------------------
    def _dino_h(self):
        return SIZ[CHAR_DUCK[0]][1] if self.ducking else SIZ[CHAR_RUN[0]][1]

    def _animate_dino(self, dt, running):
        if not self.on_ground:
            self.dino.set_src(self.res + CHAR_STAND + ".png")
        elif self.ducking:
            self.run_anim += dt
            if self.run_anim >= 0.12:
                self.run_anim = 0.0
                self.run_frame ^= 1
            self.dino.set_src(self.res + (CHAR_DUCK[0] if self.run_frame else CHAR_DUCK[1]) + ".png")
        else:
            self.run_anim += dt
            if self.run_anim >= 0.10:
                self.run_anim = 0.0
                self.run_frame ^= 1
            if running:
                self.dino.set_src(self.res + (CHAR_RUN[0] if self.run_frame else CHAR_RUN[1]) + ".png")
            else:
                self.dino.set_src(self.res + CHAR_STAND + ".png")
        # keep the piggy's feet on the ground regardless of sprite height
        if self.on_ground and self.ducking:
            self.dino_y = float(self.ground_y - self._dino_h())
        # a small visual bob while running (does not affect the collision box)
        bob = 0
        if self.on_ground and not self.ducking:
            self.bob_phase += dt * 14.0
            bob = int(round(2.0 * math.sin(self.bob_phase)))
        self.dino.set_pos(self.dino_x, int(self.dino_y) + bob)

    def _dino_box(self):
        if self.ducking:
            w, h = SIZ[CHAR_DUCK[0]]
            # tighter box: ignore the tail on the left
            return (self.dino_x + 14, int(self.dino_y) + 4, w - 18, h - 6)
        w, h = SIZ[CHAR_RUN[0]]
        return (self.dino_x + 8, int(self.dino_y) + 4, w - 14, h - 6)

    # ----- obstacles -----------------------------------------------------
    def _next_spawn_gap(self):
        # world-distance until next spawn; floored to ~1s of travel so fast
        # play never produces an unclearable cluster.
        base = self.W * (0.85 + 0.7 * random.random())
        return max(base, self.speed * 0.95)

    def _free_obstacle(self):
        for o in self.obstacles:
            if not o["active"]:
                return o
        return None

    def _spawn_obstacle(self):
        o = self._free_obstacle()
        if o is None:
            return
        bolt_ok = self.score > 250
        roll = random.random()
        if bolt_ok and roll < 0.30:
            kind = "bolt"
            name = "bolt"
            w, h = SIZ[name]
            # three flight heights: jump over, duck under, or run under
            lvl = random.randint(0, 2)
            if lvl == 0:
                y = self.ground_y - h - int(self.H * 0.02)   # low (jump or stay)
            elif lvl == 1:
                y = self.ground_y - h - int(self.H * 0.22)   # mid (duck)
            else:
                y = self.ground_y - h - int(self.H * 0.42)   # high (run under)
        else:
            kind = "poop"
            if random.random() < 0.45:
                name = "poop_big"
            else:
                name = "poop_small"
            w, h = SIZ[name]
            y = self.ground_y - h
        o["img"].set_src(self.res + name + ".png")
        o["kind"] = kind
        o["w"] = w
        o["h"] = h
        o["x"] = float(self.W + 8)
        o["y"] = y
        o["img"].set_pos(int(o["x"]), y)
        o["img"].remove_flag(lv.obj.FLAG.HIDDEN)
        self._apply_obstacle_recolor(o)
        o["active"] = True

    def _hit(self, box, o):
        bx, by, bw, bh = box
        # shrink obstacle box a little for fairness
        pad = 4
        ox = o["x"] + pad
        oy = o["y"] + pad
        ow = o["w"] - 2 * pad
        oh = o["h"] - 2 * pad
        return (bx < ox + ow and bx + bw > ox and
                by < oy + oh and by + bh > oy)

    # ----- score / palette ----------------------------------------------
    def _update_score_labels(self):
        self.hi_label.set_text("HI %05d" % self.hi_score)
        self.score_label.set_text("%05d" % int(self.score))
        self.score_label.align(lv.ALIGN.TOP_RIGHT, -6, 6)
        self.hi_label.align_to(self.score_label, lv.ALIGN.OUT_LEFT_MID, -10, 0)

    def _apply_palette(self, night):
        self.is_night = night
        bg = NIGHT_BG if night else DAY_BG
        fg = NIGHT_FG if night else DAY_FG
        self.screen.set_style_bg_color(lv.color_hex(bg), 0)
        col = lv.color_hex(fg)
        for img in self._all_images:
            img.set_style_image_recolor(col, 0)
            img.set_style_image_recolor_opa(lv.OPA.COVER, 0)
        for lbl in (self.hi_label, self.score_label, self.msg):
            lbl.set_style_text_color(col, 0)
        for o in self.obstacles:
            if o["active"]:
                self._apply_obstacle_recolor(o)

    def _apply_obstacle_recolor(self, o):
        # Obstacles (shitcoin poop, lightning bolt) keep their full colour on
        # both day and night backgrounds, so recolour is disabled for them.
        o["img"].set_style_image_recolor_opa(lv.OPA.TRANSP, 0)

    def _blink_msg(self, dt):
        self.blink += dt
        if self.blink >= 0.5:
            self.blink = 0.0
            if self.msg.has_flag(lv.obj.FLAG.HIDDEN):
                self.msg.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                self.msg.add_flag(lv.obj.FLAG.HIDDEN)
