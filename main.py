import pygame
import random
import sys
import socket
import json
import math
import threading
import urllib.parse
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# ======================================================================
# PATH HELPERS — PyInstaller compatibility
#
# When the game is bundled into a .exe, PyInstaller extracts everything
# to a temp folder stored in sys._MEIPASS. Any path that worked as a
# plain relative string at dev time breaks inside the exe unless we
# re-root it to that temp folder.
#
# Two separate helpers because assets and save files need different roots:
#   resource_path()  — read-only assets bundled inside the exe
#   save_path()      — writable save files (profiles.json) that must
#                      live next to the exe so they persist between runs.
# ======================================================================
def resource_path(relative_path):
    """Resolve a path to a bundled read-only asset.
    Works both when running as a plain .py script and as a PyInstaller exe."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative_path)

def save_path(filename):
    """Resolve a path for a writable save file.
    Always placed next to the exe (or next to t.py during development)
    so the file survives between sessions and isn't lost when the
    PyInstaller temp folder is cleaned up."""
    if hasattr(sys, "_MEIPASS"):
        # Running as bundled exe — write next to the exe itself.
        return os.path.join(os.path.dirname(sys.executable), filename)
    # Running as plain script — write in the current working directory.
    return filename


# Initialize Pygame
pygame.init()

# Constants
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 600
FPS = 60
SPRITE_WIDTH = 30
SPRITE_HEIGHT = 30
NUM_STARS = 100
NETWORK_PORT = 5050
NETWORK_BUFFER = 4096
PHONE_CONTROLLER_PORT = 8080

# ======================================================================
# FULLSCREEN SCALING SYSTEM
#
# The game always renders to an 800x600 internal canvas (_canvas).
# _flip() stretches that canvas to fill the real OS window (_window)
# every frame — so fullscreen works at any resolution with no black bars.
# ======================================================================
_canvas = None   # 800x600 Surface — all drawing goes here
_window = None   # real OS window — any resolution
_fullscreen = False

def _set_mode(fullscreen):
    """Create or resize the OS window. Call this whenever fullscreen
    is toggled. Safe to call before _canvas exists."""
    global _window, _fullscreen
    _fullscreen = fullscreen
    if fullscreen:
        _window = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    else:
        _window = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

def _flip():
    """Scale _canvas to fit _window keeping 4:3 ratio.
    Fills the letterbox/pillarbox bars with a dark starfield colour
    so they look intentional rather than like a broken border."""
    if _canvas is not None and _window is not None:
        win_w, win_h = _window.get_size()
        if (win_w, win_h) == (SCREEN_WIDTH, SCREEN_HEIGHT):
            # Windowed native size — direct copy, zero overhead.
            _window.blit(_canvas, (0, 0))
        else:
            # Scale to the largest 4:3 rect that fits inside the window.
            scale = min(win_w / SCREEN_WIDTH, win_h / SCREEN_HEIGHT)
            scaled_w = int(SCREEN_WIDTH  * scale)
            scaled_h = int(SCREEN_HEIGHT * scale)
            off_x = (win_w - scaled_w) // 2
            off_y = (win_h - scaled_h) // 2
            # Dark bar colour — matches the game's space background.
            _window.fill((5, 5, 15))
            scaled = pygame.transform.scale(_canvas, (scaled_w, scaled_h))
            _window.blit(scaled, (off_x, off_y))
    pygame.display.flip()


def blit_scaled(source, target):
    """Scale source surface to fill target while preserving 4:3 aspect ratio.
    Like _flip() but works on arbitrary surfaces (not just _canvas/_window)."""
    if source.get_size() == target.get_size():
        target.blit(source, (0, 0))
    else:
        scale = min(target.get_width() / source.get_width(),
                    target.get_height() / source.get_height())
        scaled_w = int(source.get_width() * scale)
        scaled_h = int(source.get_height() * scale)
        off_x = (target.get_width() - scaled_w) // 2
        off_y = (target.get_height() - scaled_h) // 2
        scaled = pygame.transform.scale(source, (scaled_w, scaled_h))
        target.blit(scaled, (off_x, off_y))

def get_display_surface(fullscreen):
    """Toggle fullscreen/windowed. Returns the canvas (not the window)
    so existing code that does screen = get_display_surface(...) keeps
    pointing at the right 800x600 drawing surface."""
    _set_mode(fullscreen)
    return _canvas


# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
PINK = (255, 105, 180)
SKY_BLUE = (91, 135, 255)
GROUND_GREEN = (61, 184, 58)
GROUND_BROWN = (143, 75, 30)
BRICK_ORANGE = (210, 95, 36)

# Menu UI colors
MENU_ACCENT = (255, 196, 60)      # selected button fill / title glow
MENU_PANEL = (12, 16, 40, 170)    # unselected button background (semi-transparent)
MENU_BORDER = (95, 105, 150)      # unselected button border
MENU_SUBTEXT = (170, 180, 210)    # hints / footer text

# Big "arcade lobby" button colors (fill, drop-shadow) - one flat, saturated
# color per main menu option, each with a darker shade for the pressed-in
# shadow beneath it. This is what gives the menu its chunky, friendly look
# instead of flat system text.
BTN_RED = (196, 44, 54)
BTN_RED_SHADOW = (120, 24, 30)
BTN_BLUE = (43, 92, 191)
BTN_BLUE_SHADOW = (24, 52, 110)
BTN_GREEN = (43, 158, 79)
BTN_GREEN_SHADOW = (22, 96, 46)
BTN_YELLOW = (223, 178, 42)
BTN_YELLOW_SHADOW = (150, 114, 18)
BTN_PURPLE = (130, 79, 191)
BTN_PURPLE_SHADOW = (76, 44, 118)
BTN_GREY = (90, 98, 130)
BTN_GREY_SHADOW = (50, 56, 80)

# One (fill, shadow, text_color) triple per big button, in on-screen order.
MENU_BUTTON_COLORS = [
    (BTN_RED, BTN_RED_SHADOW, WHITE),
    (BTN_BLUE, BTN_BLUE_SHADOW, WHITE),
    (BTN_YELLOW, BTN_YELLOW_SHADOW, BLACK),
    (BTN_GREEN, BTN_GREEN_SHADOW, WHITE),
    (BTN_PURPLE, BTN_PURPLE_SHADOW, WHITE),
]

# Profile storage — replaces the old single highscore.txt with a proper
# named-profile system. Each profile is {name, high_score}. The file is
# a plain JSON list so it's easy to inspect or reset manually.
PROFILES_FILE = "profiles.json"

class ProfileManager:
    """Loads, saves and manages all player profiles.
    Also remembers the last used profile name and control method so the
    game can skip straight to playing on the next launch."""

    def __init__(self):
        self.profiles = []
        self.last_profile_name = None   # name of last selected profile
        self.last_control = "keyboard"  # "keyboard" or "phone"
        self._load()

    def _load(self):
        try:
            with open(save_path(PROFILES_FILE), "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    # New format: {profiles: [...], last_profile: ..., last_control: ...}
                    self.profiles = [
                        p for p in data.get("profiles", [])
                        if isinstance(p, dict) and "name" in p and "high_score" in p
                    ]
                    self.last_profile_name = data.get("last_profile")
                    self.last_control = data.get("last_control", "keyboard")
                elif isinstance(data, list):
                    # Old format: plain list of profiles — migrate silently.
                    self.profiles = [
                        p for p in data
                        if isinstance(p, dict) and "name" in p and "high_score" in p
                    ]
        except (FileNotFoundError, json.JSONDecodeError):
            self.profiles = []

    def _save(self):
        with open(save_path(PROFILES_FILE), "w") as f:
            json.dump({
                "profiles":     self.profiles,
                "last_profile": self.last_profile_name,
                "last_control": self.last_control,
            }, f, indent=2)

    def remember(self, profile_name, control):
        """Save the last used profile + control so next launch can skip pickers."""
        self.last_profile_name = profile_name
        self.last_control = control
        self._save()

    def last_profile(self):
        """Return the last used profile dict, or None if not found."""
        if self.last_profile_name:
            return self.get(self.last_profile_name)
        return None

    def add_profile(self, name):
        """Create a new profile and return it. No-op if name already exists."""
        name = name.strip()
        if not name:
            return None
        if any(p["name"].lower() == name.lower() for p in self.profiles):
            return self.get(name)
        profile = {"name": name, "high_score": 0}
        self.profiles.append(profile)
        self._save()
        return profile

    def get(self, name):
        """Return the profile dict for name, or None."""
        for p in self.profiles:
            if p["name"].lower() == name.lower():
                return p
        return None

    def update_high_score(self, name, score):
        """Update a profile's high score if score beats the existing one."""
        for p in self.profiles:
            if p["name"].lower() == name.lower():
                if score > p["high_score"]:
                    p["high_score"] = score
                    self._save()
                return p["high_score"]
        return 0

    def top(self, n=5):
        """Return up to n profiles sorted by high_score descending."""
        return sorted(self.profiles, key=lambda p: p["high_score"], reverse=True)[:n]

# Single global instance — created once, shared everywhere so the file
# is only read from disk once per session.
profile_manager = ProfileManager()

def show_profile_select_screen(screen, title="SELECT PLAYER"):
    """Profile-picker popup shown before a game starts.
    Lists existing profiles as selectable buttons. A 'NEW PLAYER' button
    opens an inline text input. Returns the chosen profile dict, or None
    if the player cancels with Escape."""
    stars = create_stars()
    clock = pygame.time.Clock()

    # UI state — pre-select the last used profile if one exists.
    selected = 0
    last = profile_manager.last_profile()
    if last and last in profile_manager.profiles:
        try:
            selected = profile_manager.profiles.index(last)
        except ValueError:
            selected = 0

    typing = False
    new_name = ""
    error_msg = ""
    error_timer = 0

    PROFILES_PER_PAGE = 5
    scroll_offset = 0

    BUTTON_W = 340
    BUTTON_H = 46
    BUTTON_GAP = 10
    LIST_X = SCREEN_WIDTH // 2 - BUTTON_W // 2
    LIST_FIRST_Y = 180

    while True:
        profiles = profile_manager.profiles   # always fresh after adds
        # Build the option list: existing profiles + "NEW PLAYER" at the end.
        page = profiles[scroll_offset: scroll_offset + PROFILES_PER_PAGE]
        visible_options = [p["name"] for p in page] + ["+ NEW PLAYER"]
        # Clamp selection to visible options.
        selected = max(0, min(selected, len(visible_options) - 1))

        # ---- events ----
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            if event.type == pygame.KEYDOWN:
                if typing:
                    if event.key == pygame.K_ESCAPE:
                        typing = False
                        new_name = ""
                        error_msg = ""
                    elif event.key == pygame.K_RETURN:
                        name = new_name.strip()
                        if not name:
                            error_msg = "Name cannot be empty."
                            error_timer = 90
                        elif any(p["name"].lower() == name.lower()
                                 for p in profile_manager.profiles):
                            error_msg = "That name already exists — select it from the list."
                            error_timer = 120
                        else:
                            profile = profile_manager.add_profile(name)
                            return profile
                    elif event.key == pygame.K_BACKSPACE:
                        new_name = new_name[:-1]
                    elif len(new_name) < 16 and event.unicode.isprintable():
                        new_name += event.unicode
                else:
                    if event.key == pygame.K_ESCAPE:
                        return None
                    elif event.key == pygame.K_UP:
                        if selected == 0 and scroll_offset > 0:
                            scroll_offset -= 1
                        else:
                            selected = max(0, selected - 1)
                    elif event.key == pygame.K_DOWN:
                        if selected == len(visible_options) - 1:
                            if scroll_offset + PROFILES_PER_PAGE < len(profiles):
                                scroll_offset += 1
                        else:
                            selected = min(len(visible_options) - 1, selected + 1)
                    elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        choice = visible_options[selected]
                        if choice == "+ NEW PLAYER":
                            typing = True
                            new_name = ""
                        else:
                            return profile_manager.get(choice)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not typing:
                for idx in range(len(visible_options)):
                    y = LIST_FIRST_Y + idx * (BUTTON_H + BUTTON_GAP)
                    rect = pygame.Rect(LIST_X, y, BUTTON_W, BUTTON_H)
                    if rect.collidepoint(event.pos):
                        selected = idx
                        choice = visible_options[idx]
                        if choice == "+ NEW PLAYER":
                            typing = True
                            new_name = ""
                        else:
                            return profile_manager.get(choice)

        # ---- draw ----
        draw_star_background(screen, stars, speed=0.5)
        draw_title_with_glow(screen, title, 46, SCREEN_WIDTH // 2, 80, WHITE, MENU_ACCENT)
        draw_text(screen, "Choose your profile or create a new one",
                  22, SCREEN_WIDTH // 2, 132, MENU_SUBTEXT)

        for idx, option in enumerate(visible_options):
            y = LIST_FIRST_Y + idx * (BUTTON_H + BUTTON_GAP)
            rect = pygame.Rect(LIST_X, y, BUTTON_W, BUTTON_H)
            is_new = (option == "+ NEW PLAYER")
            fill = BTN_GREEN if is_new else BTN_BLUE
            shadow = BTN_GREEN_SHADOW if is_new else BTN_BLUE_SHADOW
            # Show personal high score on each existing profile button.
            if not is_new:
                profile = profile_manager.get(option)
                label = f"{option}   HS: {profile['high_score']}"
            else:
                label = option
            draw_shadow_button(screen, rect, fill, shadow, label,
                               selected=idx == selected, font_size=26)

        # Scroll hints
        if scroll_offset > 0:
            draw_text(screen, "▲ more", 18,
                      SCREEN_WIDTH // 2, LIST_FIRST_Y - 22, MENU_SUBTEXT)
        if scroll_offset + PROFILES_PER_PAGE < len(profiles):
            draw_text(screen, "▼ more", 18,
                      SCREEN_WIDTH // 2,
                      LIST_FIRST_Y + len(visible_options) * (BUTTON_H + BUTTON_GAP) + 4,
                      MENU_SUBTEXT)

        # Name-input box (shown over the list when typing)
        if typing:
            box_rect = pygame.Rect(SCREEN_WIDTH // 2 - 200, SCREEN_HEIGHT // 2 - 60, 400, 120)
            bg = pygame.Surface((box_rect.width, box_rect.height), pygame.SRCALPHA)
            bg.fill((10, 14, 36, 220))
            screen.blit(bg, box_rect)
            pygame.draw.rect(screen, MENU_ACCENT, box_rect, width=2, border_radius=10)
            draw_text(screen, "Enter your name:", 26,
                      SCREEN_WIDTH // 2, box_rect.y + 14, WHITE)
            # Blinking cursor appended to the typed text.
            cursor = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else " "
            draw_text(screen, new_name + cursor, 32,
                      SCREEN_WIDTH // 2, box_rect.y + 48, MENU_ACCENT)
            draw_text(screen, "ENTER to confirm  •  ESC to cancel", 18,
                      SCREEN_WIDTH // 2, box_rect.y + 88, MENU_SUBTEXT)

        # Error message
        if error_timer > 0:
            error_timer -= 1
            draw_text(screen, error_msg, 20,
                      SCREEN_WIDTH // 2, SCREEN_HEIGHT - 90, RED)

        draw_text(screen, "ESC to cancel", 18,
                  SCREEN_WIDTH // 2, SCREEN_HEIGHT - 50, MENU_SUBTEXT)
        _flip()
        clock.tick(FPS)

# specific to mechanics a new player might not have noticed yet.
GAME_OVER_TIPS = [
    "Tip: Shields block one hit but wear off after 5 seconds.",
    "Tip: Enemies with a red dot need 2 hits to destroy.",
    "Tip: Health pickups only appear when you're low on lives.",
    "Tip: Staying mobile makes swarms easier to dodge.",
    "Tip: Difficulty ramps up with your score - stay sharp late game.",
    "Tip: You can hold Space, but bullets are capped at 5 on screen.",
]

# Phone controller port — separate from the LAN co-op port so both can
# run simultaneously without conflict.
PHONE_CONTROLLER_PORT = 8080

# ======================================================================
# PHONE CONTROLLER
#
# Starts a tiny HTTP server in a background thread. The phone opens
# http://<PC-IP>:8080 in its browser and gets a full-screen touch pad.
# Touch events POST to /input and update a thread-safe dict that the
# game loop reads every frame — same pattern as keyboard input_state.
# ======================================================================
class PhoneController:
    """Runs an HTTP server in a daemon thread so the game loop is never
    blocked waiting for network I/O. Call start() before the round,
    stop() after. Read .input_state for the latest phone input."""

    # The HTML page served to the phone. Designed for landscape orientation
    # with big thumb-friendly buttons. Uses touch events (not click) so
    # there's no 300ms mobile tap delay. Sends a POST to /input with the
    # current full button state on every press/release so the PC always
    # knows which buttons are held, not just which were tapped.
    _HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="screen-orientation" content="landscape">
<title>Air Assault Controller</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box;
      user-select:none; -webkit-user-select:none; }

  html, body {
    width: 100vw;
    height: 100vh;
    transform: none;
  }

  body {
    background:#000008;
    font-family:'Courier New', monospace;
    height:100dvh; width:100dvw;
    overflow:hidden; touch-action:none;
  }

  /* Main controller layout */
  #controller {
    display:flex;
    flex-direction:column;
    height:100dvh; width:100dvw;
  }

  /* Auto-rotate controller when phone is held vertically (portrait) */
  @media (orientation: portrait) {
    #controller, #start-overlay {
      transform: rotate(90deg);
      transform-origin: 50% 50%;
      width: 100vh !important;
      height: 100vw !important;
      position: fixed !important;
      top: 50% !important;
      left: 50% !important;
      margin-top: -50vw !important;
      margin-left: -50vh !important;
    }
  }

  /* Game start overlay - shown when first connecting */
  #start-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 8, 0.96);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 20px;
    z-index: 1000;
  }

  #start-btn {
    background: linear-gradient(160deg,#3a0a08 0%,#1a0404 100%);
    border: 2px solid #c42c36;
    color: #ff4a56;
    padding: 20px 40px;
    border-radius: 16px;
    font-size: 28px;
    font-weight: bold;
    letter-spacing: 4px;
    cursor: pointer;
    transition: transform 0.1s, box-shadow 0.1s;
    box-shadow: 0 0 24px #c42c3666, inset 0 1px 0 #ff4a5622;
    text-align: center;
    min-width: 200px;
  }

  #start-btn:active {
    transform: scale(0.95);
    box-shadow: 0 0 40px #ff4a56cc;
    background: linear-gradient(160deg,#6a1010 0%,#3a0808 100%);
  }

  #start-instruction {
    color: #ffba00;
    font-size: 20px;
    text-align: center;
    max-width: 80%;
  }

  /* Header bar — matches game HUD style */
  #header {
    display:flex; align-items:center; justify-content:space-between;
    padding:6px 20px;
    background:linear-gradient(180deg,#0d0f2a 0%,#07091a 100%);
    border-bottom:1px solid #1e2248;
  }
  #game-title {
    color:#ffba00; font-size:20px; letter-spacing:4px; font-weight:bold;
    text-shadow:0 0 12px #ffba0088;
  }
  #status-dot {
    display:flex; align-items:center; gap:6px;
    color:#4fff80; font-size:13px; letter-spacing:1px;
  }
  #dot {
    width:9px; height:9px; border-radius:50%;
    background:#4fff80; box-shadow:0 0 8px #4fff80;
    animation:pulse 1.4s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { opacity:1; } 50% { opacity:0.3; }
  }

  /* Stars background on the pad area */
  #pad {
    flex:1; display:flex; align-items:stretch;
    gap:10px; padding:10px 16px;
    background:radial-gradient(ellipse at center,#080b20 0%,#000008 100%);
    position:relative;
  }

  /* Decorative star dots */
  #pad::before {
    content:'· · ·   · ·     ·   · · ·     · ·   ·';
    position:absolute; inset:0; padding:8px 12px;
    color:#ffffff18; font-size:10px; letter-spacing:6px;
    pointer-events:none; overflow:hidden;
  }

  /* Buttons */
  .btn {
    flex:1; border-radius:16px; display:flex;
    flex-direction:column; align-items:center; justify-content:center;
    gap:6px; border:2px solid; cursor:pointer;
    transition:filter 0.04s, transform 0.04s;
    position:relative; overflow:hidden;
  }
  .btn-label { font-size:13px; letter-spacing:2px; opacity:0.7; }
  .btn-icon  { font-size:42px; line-height:1; }

  /* Left / Right — blue space theme */
  #btn-left, #btn-right {
    background:linear-gradient(160deg,#0e1e48 0%,#060e28 100%);
    border-color:#2b5cbf;
    color:#5b8cff;
    box-shadow:0 0 18px #2b5cbf44, inset 0 1px 0 #3a6adf22;
  }
  /* Fire — red/orange like the ship's engine glow */
  #btn-shoot {
    flex:1.4;
    background:linear-gradient(160deg,#3a0a08 0%,#1a0404 100%);
    border-color:#c42c36;
    color:#ff4a56;
    box-shadow:0 0 24px #c42c3666, inset 0 1px 0 #ff4a5622;
    font-size:15px; letter-spacing:3px;
  }
  #btn-shoot .btn-icon { font-size:38px; }

  /* Pressed state — bright flash */
  .btn.pressed {
    filter:brightness(2.4);
    transform:scale(0.95);
    transition:none;
  }
  #btn-left.pressed, #btn-right.pressed {
    box-shadow:0 0 32px #5b8cffaa;
    background:linear-gradient(160deg,#1a3a80 0%,#0e1e48 100%);
  }
  #btn-shoot.pressed {
    box-shadow:0 0 40px #ff4a56cc;
    background:linear-gradient(160deg,#6a1010 0%,#3a0808 100%);
  }

  /* Role label footer */
  #footer {
    text-align:center; padding:4px;
    color:#ffffff28; font-size:10px; letter-spacing:2px;
    background:#000008;
  }

  /* ── Game-over overlay ── */
  #gameover-overlay {
    display: none;           /* shown by JS when /status says game_over */
    position: fixed; inset: 0;
    background: rgba(0, 0, 8, 0.96);
    flex-direction: column;
    align-items: center; justify-content: center;
    gap: 24px; z-index: 2000;
  }
  #gameover-title {
    color: #ff4a56; font-size: 36px;
    font-weight: bold; letter-spacing: 6px;
    text-shadow: 0 0 20px #ff4a5688;
  }
  #gameover-sub {
    color: #ffba00; font-size: 18px;
    letter-spacing: 2px;
  }
  .action-btn {
    padding: 18px 36px; border-radius: 16px;
    font-size: 26px; font-weight: bold;
    letter-spacing: 4px; cursor: pointer;
    transition: transform 0.1s, box-shadow 0.1s;
    text-align: center; min-width: 180px;
    border: 2px solid;
  }
  .action-btn:active { transform: scale(0.95); }
  #btn-restart {
    background: linear-gradient(160deg,#0e3a1a 0%,#051008 100%);
    border-color: #43c867; color: #43c867;
    box-shadow: 0 0 24px #43c86744;
  }
  #btn-restart:active { box-shadow: 0 0 40px #43c867cc; }
  #btn-quit {
    background: linear-gradient(160deg,#3a0a08 0%,#1a0404 100%);
    border-color: #c42c36; color: #ff4a56;
    box-shadow: 0 0 24px #c42c3644;
  }
  #btn-quit:active { box-shadow: 0 0 40px #ff4a56cc; }
</style>
</head>
<body>

<!-- Game start overlay -->
<div id="start-overlay">
  <div style="color:#ffba00;font-size:28px;letter-spacing:6px;font-weight:bold;text-shadow:0 0 12px #ffba0088;">AIR ASSAULT</div>
  <div id="start-instruction">Tap START when ready to play</div>
  <div id="start-btn" class="action-btn" style="border-color:#c42c36;color:#ff4a56;background:linear-gradient(160deg,#3a0a08 0%,#1a0404 100%);box-shadow:0 0 24px #c42c3666;">START &#128970;</div>
</div>

<!-- Game-over overlay (hidden until game ends) -->
<div id="gameover-overlay">
  <div id="gameover-title">GAME OVER</div>
  <div id="gameover-sub">What do you want to do?</div>
  <div id="btn-restart" class="action-btn">&#9654; RESTART</div>
  <div id="btn-quit" class="action-btn">&#10005; QUIT</div>
</div>

<!-- Controller (always visible, auto-rotated) -->
<div id="controller">
  <div id="header">
    <div id="game-title">AIR ASSAULT</div>
    <div id="status-dot">
      <div id="dot"></div>
      <span>CONNECTED</span>
    </div>
  </div>

  <div id="pad">
    <div class="btn" id="btn-left">
      <div class="btn-icon">&#9664;</div>
      <div class="btn-label">LEFT</div>
    </div>
    <div class="btn" id="btn-shoot">
      <div class="btn-icon">&#128970;</div>
      <div class="btn-label">FIRE</div>
    </div>
    <div class="btn" id="btn-right">
      <div class="btn-icon">&#9654;</div>
      <div class="btn-label">RIGHT</div>
    </div>
  </div>

  <div id="footer">PILOT MODE &nbsp;·&nbsp; TAP AND HOLD TO MOVE</div>
</div>

<script>
const state = {left:false, right:false, shoot:false};
const map = {'btn-left':'left','btn-shoot':'shoot','btn-right':'right'};
let gameStarted = false;

function send() {
  fetch('/input', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(state)
  }).catch(()=>{});
}

// Start button handler
const startBtn = document.getElementById('start-btn');
if (startBtn) {
  startBtn.addEventListener('touchstart', e => {
    e.preventDefault();
    gameStarted = true;
    document.getElementById('start-overlay').style.display = 'none';

    // Request fullscreen and lock orientation
    if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
    if (screen.orientation && screen.orientation.lock) screen.orientation.lock('landscape');

    // Send start signal to PC game
    fetch('/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ started: true })
    }).catch(() => {});

    send();
  });
}

// Attach touch events to every button
Object.keys(map).forEach(id => {
  const el = document.getElementById(id);
  const key = map[id];
  el.addEventListener('touchstart', e => {
    e.preventDefault();
    // Wait for start before allowing input
    if (!gameStarted) return;
    state[key] = true;
    el.classList.add('pressed');
    send();
  }, {passive:false});
  el.addEventListener('touchend', e => {
    e.preventDefault();
    state[key] = false;
    el.classList.remove('pressed');
    send();
  }, {passive:false});
  // Safety: release if touch leaves the button mid-swipe
  el.addEventListener('touchcancel', e => {
    state[key] = false;
    el.classList.remove('pressed');
    send();
  });
});

// Heartbeat — keeps the PC's "connected" flag alive
setInterval(() => fetch('/ping').catch(()=>{}), 1000);

// Game over overlay handlers
const gameoverOverlay = document.getElementById('gameover-overlay');
const btnRestart = document.getElementById('btn-restart');
const btnQuit = document.getElementById('btn-quit');

function sendAction(action) {
  fetch('/action', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action })
  }).catch(() => {});
}

// Game over buttons
if (btnRestart) {
  btnRestart.addEventListener('touchstart', e => {
    e.preventDefault();
    sendAction('restart');
  });
}
if (btnQuit) {
  btnQuit.addEventListener('touchstart', e => {
    e.preventDefault();
    sendAction('quit');
  });
}

// Periodically check game status and show overlay if game over
setInterval(() => {
  fetch('/status')
    .then(res => res.json())
    .then(data => {
      if (data.game_over) {
        // Game is over - show game-over overlay
        if (gameoverOverlay) gameoverOverlay.style.display = 'flex';
        // Freeze all controller buttons
        Object.keys(map).forEach(id => {
          const el = document.getElementById(id);
          if (el) el.style.opacity = '0.3';
        });
        // Hide start button if visible
        const startOverlay = document.getElementById('start-overlay');
        if (startOverlay) startOverlay.style.display = 'none';
      } else if (data.round_started) {
        // New round has started on PC - reset phone state
        gameStarted = false;
        // Show start overlay
        const startOverlay = document.getElementById('start-overlay');
        if (startOverlay) startOverlay.style.display = 'flex';
        // Hide game-over overlay
        if (gameoverOverlay) gameoverOverlay.style.display = 'none';
        // Re-enable controller buttons
        Object.keys(map).forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            el.style.opacity = '1';
            el.classList.remove('pressed');
          }
        });
      } else {
        // Game is active - hide game-over overlay
        if (gameoverOverlay) gameoverOverlay.style.display = 'none';
        // Re-enable controller buttons
        Object.keys(map).forEach(id => {
          const el = document.getElementById(id);
          if (el) {
            el.style.opacity = '1';
            el.classList.remove('pressed');
          }
        });
        // Only show start overlay if game hasn't started yet
        const startOverlay = document.getElementById('start-overlay');
        if (startOverlay && !gameStarted) {
          startOverlay.style.display = 'flex';
        }
      }
    })
    .catch(() => {});
}, 500); // Check every 0.5 seconds
</script>
</body>
</html>"""

    def __init__(self):
        self.input_state = {"left": False, "right": False, "shoot": False}
        self.connected = False      # True once phone has loaded the page
        self.game_over = False       # Set True by game loop when round ends
        self.round_started = False   # Set True when a new round begins
        self.action = None           # "restart" or "quit" — set by phone
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    def start(self):
        """Start the HTTP server on PHONE_CONTROLLER_PORT."""
        controller = self         # captured by the handler class below

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass              # suppress per-request console noise

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    with controller._lock:
                        controller.connected = True
                    body = controller._HTML.encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/ping":
                    self.send_response(204)
                    self.end_headers()
                elif self.path == "/status":
                    with controller._lock:
                        status = {
                            "game_over": controller.game_over,
                            "round_started": controller.round_started
                        }
                    body = json.dumps(status).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                if self.path == "/input":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    try:
                        data = json.loads(body)
                        with controller._lock:
                            controller.input_state = {
                                "left":  bool(data.get("left")),
                                "right": bool(data.get("right")),
                                "shoot": bool(data.get("shoot")),
                            }
                            controller.connected = True
                            # Reset round_started after phone sends input (acknowledgment)
                            controller.round_started = False
                    except (json.JSONDecodeError, Exception):
                        pass
                    self.send_response(204)
                    self.end_headers()
                elif self.path == "/action":
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    try:
                        data = json.loads(body)
                        act = data.get("action")
                        if act in ("restart", "quit"):
                            with controller._lock:
                                controller.action = act
                    except (json.JSONDecodeError, Exception):
                        pass
                    self.send_response(204)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

        try:
            self._server = HTTPServer(("", PHONE_CONTROLLER_PORT), Handler)
            self._thread = threading.Thread(
                target=self._server.serve_forever, daemon=True
            )
            self._thread.start()
            return True
        except OSError:
            # Port already in use — caller should show an error.
            return False

    def get_input(self):
        """Thread-safe snapshot of the latest phone input."""
        with self._lock:
            return dict(self.input_state)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server = None


# Star class for moving background effect
class Star:
    def __init__(self):
        self.x = random.randint(0, SCREEN_WIDTH)
        self.y = random.randint(0, SCREEN_HEIGHT)
        self.speed = random.uniform(1, 3)
        self.size = random.randint(3, 6)

    def update(self):
        self.y += self.speed
        if self.y > SCREEN_HEIGHT:
            self.y = 0
            self.x = random.randint(0, SCREEN_WIDTH)

    def draw(self, screen):
        pygame.draw.circle(screen, WHITE, (self.x, int(self.y)), self.size)

# ======================================================================
# VISUAL JUICE CLASSES
# ======================================================================
class ScreenShake:
    """Offsets every blit by a decaying random amount for a frame or two.
    Call trigger() on a hit/death event. Call offset() each frame to get
    the (dx, dy) to pass into the camera draw offset."""
    def __init__(self):
        self.duration = 0
        self.intensity = 0

    def trigger(self, intensity=8, duration=10):
        # Only upgrade an existing shake, never downgrade mid-shake.
        if intensity >= self.intensity:
            self.intensity = intensity
            self.duration = duration

    def update(self):
        if self.duration > 0:
            self.duration -= 1
            # Intensity decays linearly so the shake smooths out.
            current = self.intensity * (self.duration / 10)
            return (
                random.randint(-int(current), int(current)),
                random.randint(-int(current), int(current)),
            )
        return (0, 0)


class ScorePopup:
    """A small '+1' label that floats upward from a killed enemy and
    fades out over ~40 frames. Stored in GameLogic.popups and drawn
    in GameLogic.draw — no sprite group needed since it has no collision."""
    def __init__(self, x, y, text="+1"):
        self.x = x
        self.y = y
        self.text = text
        self.lifetime = 40      # frames to live
        self.age = 0

    def update(self):
        self.y -= 1.2           # float upward
        self.age += 1

    def draw(self, surface):
        if self.age >= self.lifetime:
            return
        alpha = max(0, 255 - int(255 * self.age / self.lifetime))
        font = pygame.font.Font(None, 28)
        text_surf = font.render(self.text, True, MENU_ACCENT)
        text_surf.set_alpha(alpha)
        rect = text_surf.get_rect(center=(int(self.x), int(self.y)))
        surface.blit(text_surf, rect)

    @property
    def dead(self):
        return self.age >= self.lifetime


def draw_text(surface, text, size, x, y, color):
    """Display text on screen."""
    font = pygame.font.Font(None, size)
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect()
    text_rect.midtop = (x, y)
    surface.blit(text_surface, text_rect)

def draw_left_text(surface, text, size, x, y, color):
    """Display left-aligned text on screen."""
    font = pygame.font.Font(None, size)
    text_surface = font.render(text, True, color)
    surface.blit(text_surface, (x, y))

def draw_title_with_glow(surface, text, size, x, y, base_color, glow_color):
    font = pygame.font.Font(None, size)
    glow_surface = font.render(text, True, glow_color)
    for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)]:
        glow_rect = glow_surface.get_rect(midtop=(x + dx, y + dy))
        surface.blit(glow_surface, glow_rect)

    main_surface = font.render(text, True, base_color)
    main_rect = main_surface.get_rect(midtop=(x, y))
    surface.blit(main_surface, main_rect)

def draw_menu_button(surface, label, x, y, width, height, selected):
    rect = pygame.Rect(x, y, width, height)

    if selected:
        pygame.draw.rect(surface, MENU_ACCENT, rect, border_radius=8)
        pygame.draw.rect(surface, WHITE, rect, width=3, border_radius=8)
        text_color = BLACK
    else:
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill(MENU_PANEL)
        surface.blit(panel, (x, y))
        pygame.draw.rect(surface, MENU_BORDER, rect, width=2, border_radius=8)
        text_color = WHITE

    font = pygame.font.Font(None, 34)
    text_surface = font.render(label, True, text_color)
    text_rect = text_surface.get_rect(center=rect.center)
    surface.blit(text_surface, text_rect)
    return rect

def draw_shadow_button(surface, rect, fill_color, shadow_color, label, selected, text_color=WHITE, font_size=30):
    draw_rect = rect.inflate(10, 10) if selected else rect
    shadow_rect = draw_rect.move(0, 7)

    pygame.draw.rect(surface, shadow_color, shadow_rect, border_radius=16)
    pygame.draw.rect(surface, fill_color, draw_rect, border_radius=16)
    border_color = WHITE if selected else BLACK
    border_width = 4 if selected else 3
    pygame.draw.rect(surface, border_color, draw_rect, width=border_width, border_radius=16)

    font = pygame.font.Font(None, font_size)
    text_surface = font.render(label, True, text_color)
    text_rect = text_surface.get_rect(center=draw_rect.center)
    surface.blit(text_surface, text_rect)
    return rect

def draw_icon_button(surface, center, radius, fill_color, shadow_color, selected, icon="fullscreen"):
    draw_radius = radius + 4 if selected else radius
    shadow_center = (center[0], center[1] + 5)

    pygame.draw.circle(surface, shadow_color, shadow_center, draw_radius)
    pygame.draw.circle(surface, fill_color, center, draw_radius)
    pygame.draw.circle(surface, WHITE if selected else BLACK, center, draw_radius, 3)

    cx, cy = center
    if icon == "fullscreen":
        span = draw_radius * 0.55
        for sx, sy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            corner = (cx + sx * span, cy + sy * span)
            pygame.draw.line(surface, WHITE, corner, (corner[0] - sx * 9, corner[1]), 3)
            pygame.draw.line(surface, WHITE, corner, (corner[0], corner[1] - sy * 9), 3)
    elif icon == "quit":
        span = draw_radius * 0.45
        pygame.draw.line(surface, WHITE, (cx - span, cy - span), (cx + span, cy + span), 4)
        pygame.draw.line(surface, WHITE, (cx - span, cy + span), (cx + span, cy - span), 4)

    return pygame.Rect(center[0] - radius, center[1] - radius, radius * 2, radius * 2)

def draw_menu_mascot(surface, x, y):
    ship = load_asset("assets/Player.png", (150, 150))
    bob_offset = math.sin(pygame.time.get_ticks() / 400) * 10

    shadow_rect = pygame.Rect(0, 0, 110, 26)
    shadow_rect.center = (x, y + 95)
    shadow_surface = pygame.Surface((shadow_rect.width, shadow_rect.height), pygame.SRCALPHA)
    pygame.draw.ellipse(shadow_surface, (0, 0, 0, 110), shadow_surface.get_rect())
    surface.blit(shadow_surface, shadow_rect)

    ship_rect = ship.get_rect(center=(x, y + bob_offset))
    surface.blit(ship, ship_rect)

def draw_retro_menu_background(screen):
    screen.fill(SKY_BLUE)

    ground_top = SCREEN_HEIGHT - 70
    pygame.draw.rect(screen, GROUND_GREEN, (0, ground_top - 26, SCREEN_WIDTH, 26))
    pygame.draw.rect(screen, GROUND_BROWN, (0, ground_top, SCREEN_WIDTH, 70))

    for x in range(0, SCREEN_WIDTH, 32):
        pygame.draw.rect(screen, BRICK_ORANGE, (x, ground_top, 30, 20))
        pygame.draw.rect(screen, BLACK, (x, ground_top, 30, 20), 2)
        pygame.draw.line(screen, BLACK, (x + 15, ground_top), (x + 15, ground_top + 20), 2)

    pygame.draw.circle(screen, GROUND_GREEN, (70, ground_top - 18), 55)
    pygame.draw.circle(screen, GROUND_GREEN, (150, ground_top - 10), 45)
    pygame.draw.circle(screen, GROUND_GREEN, (675, ground_top - 18), 58)
    pygame.draw.circle(screen, GROUND_GREEN, (755, ground_top - 8), 42)

def create_stars():
    return [[random.randint(0, SCREEN_WIDTH), random.randint(0, SCREEN_HEIGHT)] for _ in range(NUM_STARS)]

def draw_star_background(screen, stars, speed=1):
    screen.fill(BLACK)
    for star in stars:
        star[1] += speed
        if star[1] > SCREEN_HEIGHT:
            star[0] = random.randint(0, SCREEN_WIDTH)
            star[1] = 0
        screen.set_at((int(star[0]), int(star[1])), WHITE)

def fade_out(screen, speed=5):
    fade_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    fade_surface.fill(BLACK)
    for alpha in range(0, 255, speed):
        fade_surface.set_alpha(alpha)
        screen.blit(fade_surface, (0, 0))
        _flip()
        pygame.time.delay(20)

def show_leaderboard(screen):
    stars = create_stars()
    clock = pygame.time.Clock()

    while True:
        draw_star_background(screen, stars, speed=0.25)
        draw_title_with_glow(screen, "LEADERBOARD", 58,
                             SCREEN_WIDTH // 2, 60, WHITE, MENU_ACCENT)

        top = profile_manager.top(5)
        if top:
            for rank, profile in enumerate(top, start=1):
                y = 160 + (rank - 1) * 60
                # Rank medal colours: gold / silver / bronze / plain
                color = {1: (255, 215, 0), 2: (192, 192, 192),
                         3: (205, 127, 50)}.get(rank, MENU_SUBTEXT)
                draw_text(screen,
                          f"#{rank}  {profile['name']}  —  {profile['high_score']}",
                          34, SCREEN_WIDTH // 2, y, color)
        else:
            draw_text(screen, "No scores yet — play a round!", 28,
                      SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, MENU_SUBTEXT)

        draw_text(screen, "Press M or Escape to return to Menu", 18,
                  SCREEN_WIDTH // 2, SCREEN_HEIGHT - 50, MENU_SUBTEXT)
        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_m, pygame.K_ESCAPE):
                return
        clock.tick(FPS)

def show_credits_screen(screen):
    stars = create_stars()

    screen.fill(BLACK)
    running = True
    while running:
        draw_star_background(screen, stars, speed=0.25)

        draw_text(screen, "Credits", 64, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 6, WHITE)
        draw_text(screen, "Developed by: Geet Prajapati", 36, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3, WHITE)
        draw_text(screen, "Powered by: Pygame", 36, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 3 + 40, WHITE)
        draw_text(screen, "Press M to return to Menu", 18, SCREEN_WIDTH // 2, SCREEN_HEIGHT * 3 // 4, WHITE)

        _flip()

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_m, pygame.K_ESCAPE):
                    return

def draw_qr_code(surface, url, x, y, size=180):
    """Draw a scannable QR code for url using pygame rectangles.
    Uses the qrcode library if available, falls back to a placeholder
    that shows the URL as text so the player can type it manually."""
    try:
        import qrcode
        qr = qrcode.QRCode(box_size=1, border=1)
        qr.add_data(url)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        n = len(matrix)
        cell = size // n
        # White background
        pygame.draw.rect(surface, WHITE, (x, y, cell * n + 4, cell * n + 4))
        for row in range(n):
            for col in range(n):
                if matrix[row][col]:
                    pygame.draw.rect(surface, BLACK,
                                     (x + 2 + col * cell,
                                      y + 2 + row * cell,
                                      cell, cell))
        return True
    except ImportError:
        # qrcode not installed — draw a placeholder box and show the URL.
        pygame.draw.rect(surface, WHITE, (x, y, size, size))
        pygame.draw.rect(surface, BLACK, (x, y, size, size), 3)
        font = pygame.font.Font(None, 18)
        lines = ["Type this URL", "in your phone"] + url.replace("http://","").split("/")
        for i, line in enumerate(lines):
            surf = font.render(line, True, BLACK)
            surface.blit(surf, (x + size//2 - surf.get_width()//2,
                                y + 20 + i * 22))
        return False

def show_controls_screen(screen):
    """Controls screen with three tabs: Keyboard, Co-op/Tandem, Phone."""
    stars = create_stars()
    clock = pygame.time.Clock()
    tab = 0   # 0 = Keyboard, 1 = Co-op Tandem, 2 = Phone Controller
    local_ip = get_local_ip()
    url = f"http://{local_ip}:{PHONE_CONTROLLER_PORT}"
    TAB_LABELS = ["⌨  KEYBOARD", "🚀  CO-OP", "📱  PHONE"]

    while True:
        draw_star_background(screen, stars, speed=0.25)
        draw_title_with_glow(screen, "CONTROLS", 58,
                             SCREEN_WIDTH // 2, 36, WHITE, MENU_ACCENT)

        # Tab bar — 3 tabs
        tab_w = 170
        total_w = tab_w * 3
        start_x = SCREEN_WIDTH // 2 - total_w // 2
        for i, label in enumerate(TAB_LABELS):
            rect = pygame.Rect(start_x + i * tab_w + 4, 96, tab_w - 8, 38)
            color = MENU_ACCENT if i == tab else MENU_BORDER
            pygame.draw.rect(screen, color, rect, border_radius=8)
            if i != tab:
                pygame.draw.rect(screen, color, rect, width=2, border_radius=8)
            font = pygame.font.Font(None, 24)
            ts = font.render(label, True, BLACK if i == tab else WHITE)
            screen.blit(ts, ts.get_rect(center=rect.center))

        if tab == 0:
            # ---- Keyboard controls ----
            rows = [
                ("Move Left",     "← Arrow Key"),
                ("Move Right",    "→ Arrow Key"),
                ("Shoot",         "Space"),
                ("Pause",         "P"),
                ("Fullscreen",    "F"),
                ("Quit (paused)", "Q"),
            ]
            for i, (action, key) in enumerate(rows):
                y = 164 + i * 46
                draw_left_text(screen, action, 28,
                               SCREEN_WIDTH // 2 - 220, y, MENU_SUBTEXT)
                draw_left_text(screen, key, 28,
                               SCREEN_WIDTH // 2 + 20, y, WHITE)

        elif tab == 1:
            # ---- Co-op / Tandem Mode explanation ----
            draw_title_with_glow(screen, "TANDEM CO-OP MODE", 36,
                                 SCREEN_WIDTH // 2, 152, MENU_ACCENT, MENU_ACCENT)
            draw_text(screen,
                      "One ship. Two players. Each controls half.",
                      22, SCREEN_WIDTH // 2, 192, MENU_SUBTEXT)

            # Divider line
            pygame.draw.line(screen, MENU_BORDER,
                             (80, 220), (SCREEN_WIDTH - 80, 220), 1)

            # Step-by-step how to start
            steps = [
                ("Step 1", "Both players on same Wi-Fi network"),
                ("Step 2", "Host clicks CO-OP MULTIPLAYER → HOST CO-OP"),
                ("Step 3", "Host shares their IP address with Player 2"),
                ("Step 4", "Player 2 clicks JOIN CO-OP and types the IP"),
                ("Step 5", "Both players pick a role and press ENTER"),
            ]
            for i, (step, desc) in enumerate(steps):
                y = 234 + i * 38
                draw_left_text(screen, step, 22,
                               SCREEN_WIDTH // 2 - 280, y, MENU_ACCENT)
                draw_left_text(screen, desc, 22,
                               SCREEN_WIDTH // 2 - 170, y, WHITE)

            # Divider
            pygame.draw.line(screen, MENU_BORDER,
                             (80, 430), (SCREEN_WIDTH - 80, 430), 1)

            # Role breakdown side by side
            draw_text(screen, "ROLES", 24,
                      SCREEN_WIDTH // 2, 440, MENU_SUBTEXT)

            # Pilot box
            pilot_x = SCREEN_WIDTH // 2 - 190
            pygame.draw.rect(screen, (24, 52, 110),
                             (pilot_x, 462, 170, 88), border_radius=10)
            pygame.draw.rect(screen, BTN_BLUE,
                             (pilot_x, 462, 170, 88), width=2, border_radius=10)
            draw_text(screen, "PILOT", 26, pilot_x + 85, 470, WHITE)
            draw_text(screen, "← → Move ship", 19, pilot_x + 85, 496, MENU_SUBTEXT)
            draw_text(screen, "Normal screen", 19, pilot_x + 85, 518, MENU_SUBTEXT)

            # Gunner box
            gunner_x = SCREEN_WIDTH // 2 + 20
            pygame.draw.rect(screen, (76, 44, 118),
                             (gunner_x, 462, 170, 88), border_radius=10)
            pygame.draw.rect(screen, BTN_PURPLE,
                             (gunner_x, 462, 170, 88), width=2, border_radius=10)
            draw_text(screen, "GUNNER", 26, gunner_x + 85, 470, WHITE)
            draw_text(screen, "Space — Shoot", 19, gunner_x + 85, 496, MENU_SUBTEXT)
            draw_text(screen, "⚠ MIRRORED screen!", 19, gunner_x + 85, 518, RED)

        else:
            # ---- Phone Controller tab ----
            draw_text(screen, "Scan with your phone's camera", 24,
                      SCREEN_WIDTH // 2, 150, MENU_SUBTEXT)
            draw_text(screen, url, 26,
                      SCREEN_WIDTH // 2, 180, MENU_ACCENT)

            qr_x = SCREEN_WIDTH // 2 - 90
            qr_y = 215
            draw_qr_code(screen, url, qr_x, qr_y, size=180)

            draw_text(screen, "Both devices must be on the same Wi-Fi", 20,
                      SCREEN_WIDTH // 2, 420, MENU_SUBTEXT)
            draw_text(screen, "Phone controller works in Single Player mode", 20,
                      SCREEN_WIDTH // 2, 446, MENU_SUBTEXT)

        draw_text(screen, "← → to switch tabs  •  M / Escape to go back", 18,
                  SCREEN_WIDTH // 2, SCREEN_HEIGHT - 40, MENU_SUBTEXT)
        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_m, pygame.K_ESCAPE):
                    return
                if event.key == pygame.K_LEFT:
                    tab = (tab - 1) % len(TAB_LABELS)
                elif event.key == pygame.K_RIGHT:
                    tab = (tab + 1) % len(TAB_LABELS)
        clock.tick(FPS)

def get_local_ip():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except OSError:
        return "127.0.0.1"

def draw_menu_stars(screen, stars):
    draw_star_background(screen, stars, speed=1)

def show_network_message(screen, title, lines):
    stars = create_stars()
    clock = pygame.time.Clock()
    while True:
        draw_menu_stars(screen, stars)
        draw_text(screen, title, 58, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 5, WHITE)
        for index, line in enumerate(lines):
            draw_text(screen, line, 28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + index * 34, WHITE)
        draw_text(screen, "Press M or Escape", 22, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 80, WHITE)
        _flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_m, pygame.K_ESCAPE):
                return
        clock.tick(FPS)

def prompt_for_host_ip(screen):
    stars = create_stars()
    clock = pygame.time.Clock()
    ip_text = ""
    while True:
        draw_menu_stars(screen, stars)
        draw_text(screen, "JOIN LAN GAME", 58, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 5, WHITE)
        draw_text(screen, "Type host IP address", 30, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 45, WHITE)
        draw_text(screen, ip_text or "...", 38, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, WHITE)
        draw_text(screen, "Enter joins - Escape returns", 22, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 80, WHITE)
        _flip()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key == pygame.K_RETURN and ip_text:
                    return ip_text
                if event.key == pygame.K_BACKSPACE:
                    ip_text = ip_text[:-1]
                elif event.unicode and event.unicode in "0123456789.":
                    ip_text += event.unicode
        clock.tick(FPS)

def wait_for_lan_client(screen):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("", NETWORK_PORT))
    server.listen(1)
    server.setblocking(False)

    stars = create_stars()
    clock = pygame.time.Clock()
    local_ip = get_local_ip()
    while True:
        draw_menu_stars(screen, stars)
        draw_text(screen, "HOST LAN GAME", 58, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 5, WHITE)
        draw_text(screen, f"Your IP: {local_ip}", 32, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 35, WHITE)
        draw_text(screen, f"Port: {NETWORK_PORT}", 28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 5, WHITE)
        draw_text(screen, "Waiting for player 2...", 28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 45, WHITE)
        draw_text(screen, "Escape returns", 22, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 80, WHITE)
        _flip()

        try:
            conn, addr = server.accept()
            conn.setblocking(False)
            server.close()
            return conn
        except BlockingIOError:
            pass

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                server.close()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                server.close()
                return None
        clock.tick(FPS)

def connect_to_lan_host(screen):
    host_ip = prompt_for_host_ip(screen)
    if not host_ip:
        return None
    try:
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(5)
        conn.connect((host_ip, NETWORK_PORT))
        conn.setblocking(False)
        return conn
    except OSError as error:
        show_network_message(screen, "CONNECTION FAILED", [str(error)])
        return None

def send_json_message(conn, data):
    try:
        conn.sendall((json.dumps(data) + "\n").encode("utf-8"))
        return True
    except OSError:
        return False

def receive_json_messages(conn, buffer):
    messages = []
    try:
        while True:
            chunk = conn.recv(NETWORK_BUFFER)
            if not chunk:
                return messages, buffer, False
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.strip():
                    messages.append(json.loads(line))
    except BlockingIOError:
        return messages, buffer, True
    except (OSError, json.JSONDecodeError):
        return messages, buffer, False

def prompt_tandem_role_selection(screen, conn, is_host):
    stars = create_stars()
    clock = pygame.time.Clock()
    conn_buffer = ""

    my_role = "pilot" if is_host else "gunner"
    my_ready = False
    partner_role = None
    partner_ready = False

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                conn.close()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return None
                if event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN) and not my_ready:
                    my_role = "gunner" if my_role == "pilot" else "pilot"
                if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if my_ready:
                        my_ready = False
                    elif partner_role != my_role:
                        my_ready = True

        if not send_json_message(conn, {"type": "tandem_pick", "role": my_role, "ready": my_ready}):
            show_network_message(screen, "CONNECTION LOST", ["The other player disconnected."])
            return None

        messages, conn_buffer, connected = receive_json_messages(conn, conn_buffer)
        if not connected:
            show_network_message(screen, "CONNECTION LOST", ["The other player disconnected."])
            return None
        for message in messages:
            if message.get("type") == "tandem_pick":
                partner_role = message.get("role")
                partner_ready = message.get("ready", False)

        if my_ready and partner_ready and partner_role is not None and partner_role != my_role:
            return my_role

        if my_ready and partner_role == my_role:
            my_ready = False

        draw_menu_stars(screen, stars)
        draw_text(screen, "TANDEM MODE", 54, SCREEN_WIDTH // 2, 60, WHITE)
        draw_text(screen, "One ship. One pilot. One gunner.", 22, SCREEN_WIDTH // 2, 110, MENU_SUBTEXT)

        # Role descriptions — shown while the player is choosing so they
        # know what they're signing up for before they ready up.
        if my_role == "pilot":
            draw_text(screen, "PILOT: Arrow keys move the ship. Normal view.", 20, SCREEN_WIDTH // 2, 148, MENU_SUBTEXT)
        else:
            draw_text(screen, "GUNNER: Space bar shoots. YOUR SCREEN IS MIRRORED!", 20, SCREEN_WIDTH // 2, 148, RED)

        my_label = "PILOT (Move)" if my_role == "pilot" else "GUNNER (Fire — Mirrored!)"
        draw_text(screen, f"You: {my_label}", 34, SCREEN_WIDTH // 2, 220, GREEN if my_ready else WHITE)

        if partner_role:
            partner_label = "PILOT (Move)" if partner_role == "pilot" else "GUNNER (Fire — Mirrored!)"
            draw_text(screen, f"Partner: {partner_label}", 30, SCREEN_WIDTH // 2, 278, GREEN if partner_ready else WHITE)
        else:
            draw_text(screen, "Partner: choosing...", 30, SCREEN_WIDTH // 2, 270, MENU_SUBTEXT)

        if partner_role == my_role and partner_role is not None:
            draw_text(screen, "You both picked the same role - press an arrow key to switch", 20, SCREEN_WIDTH // 2, 330, RED)
        elif my_ready:
            draw_text(screen, "Waiting for partner to ready up...", 22, SCREEN_WIDTH // 2, 330, MENU_SUBTEXT)
        else:
            draw_text(screen, "Arrow keys to switch role - ENTER to ready up", 22, SCREEN_WIDTH // 2, 330, MENU_SUBTEXT)

        draw_text(screen, "Escape to cancel", 18, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 40, MENU_SUBTEXT)
        _flip()
        clock.tick(FPS)


# ======================================================================
# SOUND MANAGER
# ======================================================================
class SoundManager:
    def __init__(self):
        pygame.mixer.init()
        self.sounds = {}
        # Simple procedural sound generation:
        # If files aren't ready, we hold off, but the code is ready.
        try:
            # We look for assets/sfx/ folder.
            self.sounds["shoot"] = pygame.mixer.Sound(resource_path("assets/sfx/shoot.wav"))
            self.sounds["explosion"] = pygame.mixer.Sound(resource_path("assets/sfx/explosion.wav"))
        except:
            print("SFX not found, skipping SoundManager initialization.")

    def play(self, name):
        if name in self.sounds:
            self.sounds[name].play()

sound_manager = SoundManager()


# Cache of loaded/transformed assets so the same image is never loaded twice.
ASSET_CACHE = {}


def load_asset(path, size=None):
    key = (path, size)
    if key not in ASSET_CACHE:
        image = pygame.image.load(resource_path(path)).convert_alpha()
        if size:
            image = pygame.transform.scale(image, size)
        ASSET_CACHE[key] = image
    return ASSET_CACHE[key]


# ======================================================================
# SPRITE CLASSES
# ======================================================================
class Player(pygame.sprite.Sprite):
    def __init__(self, player_index=0, controls=None):
        super().__init__()
        self.image = load_asset("assets/Player.png", (60, 60))
        self.rect = self.image.get_rect()
        start_x = SCREEN_WIDTH // 2 if player_index == 0 else SCREEN_WIDTH // 2 + 120
        self.rect.center = (start_x, SCREEN_HEIGHT - 50)
        self.speed = 5
        self.lives = 3
        self.shield_active = False
        self.shield_timer = 0
        self.player_index = player_index
        self.controls = controls or {"left": pygame.K_LEFT, "right": pygame.K_RIGHT}
        # Hit flash: briefly tints the ship white when struck.
        self.hit_flash = 0          # frames remaining for flash
        self._base_image = self.image   # original surface kept for restore

    def activate_shield(self):
        self.shield_active = True
        self.shield_timer = pygame.time.get_ticks()

    def trigger_hit_flash(self, duration=12):
        """Call this when the player takes a hit to start the white flash."""
        self.hit_flash = duration

    def apply_input(self, input_state):
        if input_state.get("left") and self.rect.left > 0:
            self.rect.x -= self.speed
        if input_state.get("right") and self.rect.right < SCREEN_WIDTH:
            self.rect.x += self.speed

        if self.shield_active and pygame.time.get_ticks() - self.shield_timer > 5000:
            self.shield_active = False

        # Hit flash: strobe white then normal every 3 frames while active.
        if self.hit_flash > 0:
            self.hit_flash -= 1
            if (self.hit_flash // 3) % 2 == 0:
                white = pygame.Surface(self._base_image.get_size(), pygame.SRCALPHA)
                white.fill((255, 255, 255, 180))
                flashed = self._base_image.copy()
                flashed.blit(white, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
                self.image = flashed
            else:
                self.image = self._base_image
        else:
            self.image = self._base_image

    def update(self):
        keys = pygame.key.get_pressed()
        self.apply_input({
            "left": keys[self.controls["left"]],
            "right": keys[self.controls["right"]],
        })

class Bullet(pygame.sprite.Sprite):
    def __init__(self, x, y, owner=0):
        super().__init__()
        self.image = load_asset("assets/Missile.png", (20, 30))
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.speed = -6
        self.owner = owner

    def update(self):
        self.rect.y += self.speed
        if self.rect.bottom < 0:
            self.kill()

class Explosion(pygame.sprite.Sprite):
    def __init__(self, x, y):
        super().__init__()
        self.images = [
            load_asset(f"assets/Explosion/Explosion{i + 1}.png", (50, 50))
            for i in range(9)
        ]
        self.index = 0
        self.image = self.images[self.index]
        self.rect = self.image.get_rect()
        self.rect.center = (x, y)
        self.counter = 0

    def update(self):
        explosion_speed = 3
        self.counter += 1
        if self.counter >= explosion_speed and self.index < 8:
            self.counter = 0
            self.index += 1
            self.image = self.images[self.index]
        if self.index >= 8:
            self.kill()

class Enemy(pygame.sprite.Sprite):
    def __init__(self, speed, health=1):
        super().__init__()
        size = (60, 60) if health > 1 else (40, 40)
        self.image = load_asset(f"assets/Meteor/Meteor{random.randint(1, 9)}.png", size)
        self.rect = self.image.get_rect()
        self.rect.x = random.randint(0, SCREEN_WIDTH - SPRITE_WIDTH)
        self.rect.y = random.randint(-100, -40)
        self.speed = speed
        self.health = health

    def update(self):
        self.rect.y += self.speed
        if self.rect.top > SCREEN_HEIGHT:
            self.kill()

class Shield(pygame.sprite.Sprite):
    def __init__(self, speed=3, lifespan=None):
        super().__init__()
        self.image = load_asset("assets/Powerup/Shield.png", (35, 35))
        self.rect = self.image.get_rect()
        self.rect.x = random.randint(0, SCREEN_WIDTH - SPRITE_WIDTH)
        self.rect.y = random.randint(-100, -40)
        self.speed = speed
        self.lifespan = lifespan if lifespan is not None else random.randint(300, 600)

    def update(self):
        self.rect.y += self.speed
        self.lifespan -= 1
        if self.lifespan <= 0 or self.rect.top > SCREEN_HEIGHT:
            self.kill()

class Life(pygame.sprite.Sprite):
    def __init__(self, speed, lifespan=None):
        super().__init__()
        self.image = load_asset("assets/Powerup/Health.png", (35, 35))
        self.rect = self.image.get_rect()
        self.rect.x = random.randint(0, SCREEN_WIDTH - SPRITE_WIDTH)
        self.rect.y = random.randint(-100, -40)
        self.speed = speed
        self.lifespan = lifespan if lifespan is not None else random.randint(300, 600)

    def update(self):
        self.rect.y += self.speed
        self.lifespan -= 1
        if self.lifespan <= 0 or self.rect.top > SCREEN_HEIGHT:
            self.kill()

def spawn_swarm(all_sprites, enemies, speed):
    start_x = random.randint(50, SCREEN_WIDTH - 150)

    for i in range(3):
        enemy = Enemy(speed)
        enemy.rect.x = start_x + (i * 50)
        enemy.rect.y = -50
        all_sprites.add(enemy)
        enemies.add(enemy)

def draw_lives(surface, x, y, lives, heart_image):
    for i in range(lives):
        surface.blit(heart_image, (x + 35 * i, y))


# ======================================================================
# GAME CONFIG — centralized magic numbers for the current codebase
# ======================================================================
class GameConfig:
    MAX_BULLETS = 8


# ======================================================================
# GAMELOGIC
# ======================================================================
class GameLogic:
    def __init__(self, num_players=1):
        self.num_players = num_players
        self.all_sprites = pygame.sprite.Group()
        self.bullets = pygame.sprite.Group()
        self.enemies = pygame.sprite.Group()
        self.lives_group = pygame.sprite.Group()
        self.shields_group = pygame.sprite.Group()
        self.explosions = pygame.sprite.Group()

        controls_p1 = {"left": pygame.K_LEFT, "right": pygame.K_RIGHT}
        controls_p2 = {"left": pygame.K_a, "right": pygame.K_d}
        self.players = []
        for index in range(num_players):
            controls = controls_p1 if index == 0 else controls_p2
            player = Player(player_index=index, controls=controls)
            self.players.append(player)
            self.all_sprites.add(player)

        self.score = 0
        self.enemies_destroyed = 0   # tracked separately from score so future
                                      # scoring changes (combos, bonuses) never
                                      # silently corrupt this end-screen stat
        self.game_over = False
        self.shoot_cooldowns = [0] * num_players
        self.popups = []          # ScorePopup instances
        # shake_events: list of (intensity, duration) tuples waiting to be
        # consumed by the game loop's ScreenShake instance. GameLogic itself
        # has no reference to the renderer, so it queues events here and the
        # loop drains them each frame.
        self.shake_events = []

        # Combo System
        self.combo = 0            # current combo streak
        self.combo_timer = 0      # frames remaining to continue combo (3 seconds)
        self.combo_expire_frames = 180  # 3 seconds at 60 FPS
        self.max_combo = 0        # highest combo reached this run

        now = pygame.time.get_ticks()
        self.last_life_spawn = now
        self.last_shield_spawn = now

    def handle_input(self, inputs):
        for index, player in enumerate(self.players):
            if player.lives <= 0:
                continue
            player_input = inputs[index] if index < len(inputs) else {}
            player.apply_input(player_input)

            self.shoot_cooldowns[index] = max(0, self.shoot_cooldowns[index] - 1)
            player_bullets = [b for b in self.bullets if b.owner == index]
            if player_input.get("shoot") and self.shoot_cooldowns[index] == 0 and len(player_bullets) < GameConfig.MAX_BULLETS:
                bullet = Bullet(player.rect.centerx, player.rect.top, owner=index)
                self.all_sprites.add(bullet)
                self.bullets.add(bullet)
                self.shoot_cooldowns[index] = 12
                sound_manager.play("shoot")

    def spawn_enemies(self):
        spawn_rate = 0.02 + self.score * 0.0005
        if random.random() >= spawn_rate:
            return

        if self.score < 20:
            enemy = Enemy(random.randint(3, 5))
        elif self.score < 50:
            enemy = Enemy(random.randint(5, 7))
        elif self.score < 100:
            enemy_speed = random.randint(6, 8)
            if random.random() < 0.25:
                spawn_swarm(self.all_sprites, self.enemies, enemy_speed)
                return
            enemy = Enemy(enemy_speed)
        else:
            enemy_speed = random.randint(7, 10)
            health = 2 if random.random() < 0.20 else 1
            enemy = Enemy(enemy_speed, health=health)

        self.all_sprites.add(enemy)
        self.enemies.add(enemy)

    def spawn_powerups(self):
        current_time = pygame.time.get_ticks()
        living_players = [p for p in self.players if p.lives > 0]

        weakest_lives = min((p.lives for p in living_players), default=3)
        life_delay = 25000
        if weakest_lives == 1:
            life_delay = 10000
        elif weakest_lives == 2:
            life_delay = 18000
        if self.score > 50:
            life_delay += 5000
        if self.score > 100:
            life_delay += 5000

        if len(self.lives_group) == 0 and current_time - self.last_life_spawn > life_delay:
            life = Life(speed=random.randint(3, 5))
            self.all_sprites.add(life)
            self.lives_group.add(life)
            self.last_life_spawn = current_time

        any_shield_inactive = any(not p.shield_active for p in living_players) if living_players else True
        shield_delay = 20000 if any_shield_inactive else 30000
        if self.score > 50:
            shield_delay += 5000
        if self.score > 100:
            shield_delay += 10000

        if len(self.shields_group) == 0 and current_time - self.last_shield_spawn > shield_delay:
            shield = Shield(speed=random.randint(3, 5))
            self.all_sprites.add(shield)
            self.shields_group.add(shield)
            self.last_shield_spawn = current_time

    def handle_collisions(self):
        # Combo System: increment on enemy kill
        self.combo_timer -= 1
        if self.combo_timer <= 0 and self.combo > 0:
            # Combo expired - reset to 1 (next kill starts fresh)
            self.combo = 0

        for bullet in list(self.bullets):
            hits = pygame.sprite.spritecollide(bullet, self.enemies, False, pygame.sprite.collide_rect)
            if not hits:
                continue
            bullet.kill()
            enemy = hits[0]
            enemy.health -= 1
            if enemy.health <= 0:
                explosion = Explosion(enemy.rect.centerx, enemy.rect.centery)
                self.all_sprites.add(explosion)
                self.explosions.add(explosion)
                enemy.kill()
                sound_manager.play("explosion")

                # Combo scoring: base 1 point + bonus for combo streak
                self.combo += 1
                self.combo_timer = self.combo_expire_frames  # reset combo timer
                self.max_combo = max(self.max_combo, self.combo)

                # Score = 1 base + combo bonus (1 point per combo level beyond first)
                score_gain = 1 + (self.combo - 1)
                self.score += score_gain
                self.enemies_destroyed += 1

                # Show combo in popup
                if self.combo >= 2:
                    self.popups.append(
                        ScorePopup(enemy.rect.centerx, enemy.rect.centery, f"+{score_gain} (x{self.combo})")
                    )
                else:
                    self.popups.append(ScorePopup(enemy.rect.centerx, enemy.rect.centery))
                self.shake_events.append((4, 6))
            else:
                # Hit but not dead — tiny shake so the hit feels registered.
                self.shake_events.append((2, 4))

        for player in self.players:
            if player.lives <= 0:
                continue

            enemy_hits = pygame.sprite.spritecollide(player, self.enemies, True)
            for hit in enemy_hits:
                if not player.shield_active:
                    explosion = Explosion(hit.rect.centerx, hit.rect.centery)
                    self.all_sprites.add(explosion)
                    self.explosions.add(explosion)
                    player.lives -= 1
                    player.trigger_hit_flash()
                    intensity = 14 if player.lives == 0 else 10
                    self.shake_events.append((intensity, 14))
                    # Combo breaker! Taking damage resets combo to 0
                    if self.combo > 0:
                        self.popups.append(
                            ScorePopup(player.rect.centerx, player.rect.top - 20, "COMBO LOST!")
                        )
                    self.combo = 0

            for _ in pygame.sprite.spritecollide(player, self.lives_group, True):
                player.lives = min(player.lives + 1, 5)
                self.shake_events.append((3, 5))

            for shield in list(self.shields_group):
                if pygame.sprite.collide_rect(player, shield):
                    shield.kill()
                    player.activate_shield()
                    self.shake_events.append((3, 5))

        self.game_over = all(player.lives <= 0 for player in self.players)

    def update(self, inputs):
        if self.game_over:
            return
        self.handle_input(inputs)
        self.all_sprites.update()
        self.spawn_enemies()
        self.spawn_powerups()
        self.handle_collisions()
        # Advance popups and prune dead ones.
        for popup in self.popups:
            popup.update()
        self.popups = [p for p in self.popups if not p.dead]

    def draw(self, screen, stars):
        screen.fill(BLACK)
        for star in stars:
            star[1] += 1
            if star[1] > SCREEN_HEIGHT:
                star[0] = random.randint(0, SCREEN_WIDTH)
                star[1] = random.randint(-20, -1)
            screen.set_at(star, WHITE)

        self.all_sprites.draw(screen)

        for enemy in self.enemies:
            if enemy.health > 1:
                pygame.draw.circle(screen, RED, enemy.rect.center, 5)
        for player in self.players:
            if player.shield_active:
                pygame.draw.circle(screen, (0, 255, 255), player.rect.center, 30, 3)

        # Combo display — big combo number above score
        if self.combo >= 2:
            combo_color = (255, 196, 60)  # MENU_ACCENT
            pulse = (math.sin(pygame.time.get_ticks() / 100) + 1) / 2
            combo_size = int(48 + 10 * pulse)  # pulsing effect
            combo_font = pygame.font.Font(None, combo_size)
            combo_surf = combo_font.render(f"x{self.combo}", True, combo_color)
            combo_rect = combo_surf.get_rect(center=(SCREEN_WIDTH - 70, 85))
            screen.blit(combo_surf, combo_rect)

        # Pickup glow — a pulsing coloured ring around life/shield pickups
        # so they're impossible to miss in a busy field of enemies.
        t = pygame.time.get_ticks()
        for life in self.lives_group:
            radius = int(22 + 5 * math.sin(t / 180))
            glow = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (80, 220, 80, 90), (radius + 2, radius + 2), radius)
            screen.blit(glow, (life.rect.centerx - radius - 2, life.rect.centery - radius - 2))
        for shield in self.shields_group:
            radius = int(22 + 5 * math.sin(t / 180 + 1))
            glow = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(glow, (80, 180, 255, 90), (radius + 2, radius + 2), radius)
            screen.blit(glow, (shield.rect.centerx - radius - 2, shield.rect.centery - radius - 2))

        # Score popups float above killed enemies.
        for popup in self.popups:
            popup.draw(screen)

    def to_sync_dict(self):
        return {
            "players": [
                {"x": p.rect.centerx, "y": p.rect.centery, "lives": p.lives, "shield": p.shield_active}
                for p in self.players
            ],
            "bullets": [{"x": b.rect.centerx, "y": b.rect.centery} for b in self.bullets],
            "enemies": [
                {"x": e.rect.centerx, "y": e.rect.centery, "health": e.health}
                for e in self.enemies
            ],
            "lives_pickups": [{"x": l.rect.centerx, "y": l.rect.centery} for l in self.lives_group],
            "shield_pickups": [{"x": s.rect.centerx, "y": s.rect.centery} for s in self.shields_group],
            "score": self.score,
            "game_over": self.game_over,
            "combo": self.combo,
        }


# ======================================================================
# LAN MULTIPLAYER
# ======================================================================
def load_lan_assets():
    return {
        "player": load_asset("assets/Player.png", (60, 60)),
        "bullet": load_asset("assets/Missile.png", (20, 30)),
        "enemy": load_asset("assets/Meteor/Meteor1.png", (40, 40)),
        "life_pickup": load_asset("assets/Powerup/Health.png", (35, 35)),
        "shield_pickup": load_asset("assets/Powerup/Shield.png", (35, 35)),
    }

def draw_tandem_state(screen, state, stars, assets, my_role):
    screen.fill(BLACK)
    for star in stars:
        star[1] += 1
        if star[1] > SCREEN_HEIGHT:
            star[0] = random.randint(0, SCREEN_WIDTH)
            star[1] = random.randint(-20, -1)
        screen.set_at(star, WHITE)

    for enemy in state["enemies"]:
        rect = assets["enemy"].get_rect(center=(enemy["x"], enemy["y"]))
        screen.blit(assets["enemy"], rect)
        if enemy.get("health", 1) > 1:
            pygame.draw.circle(screen, RED, rect.center, 5)
    for bullet in state["bullets"]:
        rect = assets["bullet"].get_rect(center=(bullet["x"], bullet["y"]))
        screen.blit(assets["bullet"], rect)
    for pickup in state.get("lives_pickups", []):
        rect = assets["life_pickup"].get_rect(center=(pickup["x"], pickup["y"]))
        t = pygame.time.get_ticks()
        radius = int(22 + 5 * math.sin(t / 180))
        glow = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (80, 220, 80, 90), (radius + 2, radius + 2), radius)
        screen.blit(glow, (pickup["x"] - radius - 2, pickup["y"] - radius - 2))
        screen.blit(assets["life_pickup"], rect)
    for pickup in state.get("shield_pickups", []):
        rect = assets["shield_pickup"].get_rect(center=(pickup["x"], pickup["y"]))
        t = pygame.time.get_ticks()
        radius = int(22 + 5 * math.sin(t / 180 + 1))
        glow = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (80, 180, 255, 90), (radius + 2, radius + 2), radius)
        screen.blit(glow, (pickup["x"] - radius - 2, pickup["y"] - radius - 2))
        screen.blit(assets["shield_pickup"], rect)

    ship_state = state["players"][0]
    if ship_state["lives"] > 0:
        rect = assets["player"].get_rect(center=(ship_state["x"], ship_state["y"]))
        screen.blit(assets["player"], rect)
        if ship_state.get("shield"):
            pygame.draw.circle(screen, (0, 255, 255), rect.center, 30, 3)

    draw_text(screen, "TANDEM MODE", 24, SCREEN_WIDTH // 2, 8, WHITE)
    draw_text(screen, f"Score: {state['score']}", 32, 80, 8, WHITE)
    draw_text(screen, f"Lives: {ship_state['lives']}", 24, 85, 42, WHITE)
    role_label = "YOU: PILOT (Move)" if my_role == "pilot" else "YOU: GUNNER (Fire)"
    draw_left_text(screen, role_label, 22, SCREEN_WIDTH - 220, 10, MENU_ACCENT)

def run_tandem_multiplayer(screen, role, conn, my_role):
    clock = pygame.time.Clock()
    conn_buffer = ""
    stars = create_stars()
    assets = load_lan_assets()
    connected = True
    synced_state = None

    logic = GameLogic(num_players=1) if role == "host" else None
    shake = ScreenShake()

    while connected:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                conn.close()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                connected = False

        keys = pygame.key.get_pressed()
        if my_role == "pilot":
            my_partial_input = {
                "left": keys[pygame.K_LEFT] or keys[pygame.K_a],
                "right": keys[pygame.K_RIGHT] or keys[pygame.K_d],
            }
        else:
            my_partial_input = {"shoot": keys[pygame.K_SPACE]}

        if role == "host":
            messages, conn_buffer, connected = receive_json_messages(conn, conn_buffer)
            partner_partial_input = {}
            for message in messages:
                if message.get("type") == "tandem_input":
                    partner_partial_input = message.get("input", partner_partial_input)

            combined_input = {"left": False, "right": False, "shoot": False}
            combined_input.update(my_partial_input)
            combined_input.update(partner_partial_input)

            logic.update([combined_input])
            synced_state = logic.to_sync_dict()
            for intensity, duration in logic.shake_events:
                shake.trigger(intensity, duration)
            logic.shake_events.clear()
            connected = connected and send_json_message(conn, {"type": "state", "state": synced_state})
        else:
            connected = send_json_message(conn, {"type": "tandem_input", "input": my_partial_input})
            messages, conn_buffer, connected = receive_json_messages(conn, conn_buffer)
            for message in messages:
                if message.get("type") == "state":
                    synced_state = message["state"]

        if synced_state:
            ox, oy = shake.update()
            canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
            draw_tandem_state(canvas, synced_state, stars, assets, my_role)
            if synced_state.get("game_over"):
                draw_text(canvas, "GAME OVER", 58, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40, WHITE)
                draw_text(canvas, "Press Escape", 28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 20, WHITE)

            # Gunner sees a mirrored world — same logic, same controls,
            # but left and right are swapped on screen. This is the chaos.
            # The HUD text was already drawn on canvas so it flips too,
            # which is intentional: everything the gunner sees is reversed.
            if my_role == "gunner":
                canvas = pygame.transform.flip(canvas, True, False)

            # Apply screen shake and blit to the global _canvas so _flip() displays it
            _canvas.fill(BLACK)
            _canvas.blit(canvas, (ox, oy))

        _flip()
        clock.tick(FPS)

        if (
            role == "host"
            and synced_state
            and synced_state.get("game_over")
        ):
            # Co-op profile saving will be wired in when co-op gets its
            # own profile picker. For now just keep the global top score
            # updated so the leaderboard reflects tandem runs too.
            top = profile_manager.top(1)
            top_score = top[0]["high_score"] if top else 0
            if synced_state["score"] > top_score and top:
                profile_manager.update_high_score(top[0]["name"], synced_state["score"])

    conn.close()

def show_multiplayer_screen(screen):
    stars = create_stars()
    menu_options = [("HOST CO-OP", "host"), ("JOIN CO-OP", "join"), ("BACK", "back")]
    selected_option = 0
    clock = pygame.time.Clock()

    def run_action(action):
        if action == "back":
            return True
        if action == "host":
            conn = wait_for_lan_client(screen)
            if conn:
                my_role = prompt_tandem_role_selection(screen, conn, is_host=True)
                if my_role:
                    run_tandem_multiplayer(screen, "host", conn, my_role)
                else:
                    conn.close()
        elif action == "join":
            conn = connect_to_lan_host(screen)
            if conn:
                my_role = prompt_tandem_role_selection(screen, conn, is_host=False)
                if my_role:
                    run_tandem_multiplayer(screen, "client", conn, my_role)
                else:
                    conn.close()
        return False

    button_width = 280
    button_height = 42
    button_gap = 12
    first_y = SCREEN_HEIGHT // 2 - 30

    while True:
        draw_menu_stars(screen, stars)
        draw_title_with_glow(screen, "LAN MULTIPLAYER", 50, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 6, WHITE, MENU_ACCENT)

        mouse_pos = pygame.mouse.get_pos()
        menu_x = SCREEN_WIDTH // 2 - button_width // 2
        button_rects = []
        for index, (label, action) in enumerate(menu_options):
            y = first_y + index * (button_height + button_gap)
            hover_rect = pygame.Rect(menu_x, y, button_width, button_height)
            if hover_rect.collidepoint(mouse_pos):
                selected_option = index
            rect = draw_menu_button(screen, label, menu_x, y, button_width, button_height, index == selected_option)
            button_rects.append(rect)

        draw_text(screen, "Same Wi-Fi - Host shares IP", 22, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 90, MENU_SUBTEXT)
        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    selected_option = (selected_option - 1) % len(menu_options)
                elif event.key == pygame.K_DOWN:
                    selected_option = (selected_option + 1) % len(menu_options)
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if run_action(menu_options[selected_option][1]):
                        return
                elif event.key in (pygame.K_ESCAPE, pygame.K_m):
                    return
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, rect in enumerate(button_rects):
                    if rect.collidepoint(event.pos):
                        selected_option = index
                        if run_action(menu_options[index][1]):
                            return
                        break
        clock.tick(FPS)


# ======================================================================
# GAME SETUP / MENUS
# ======================================================================
def show_intro_animation(screen):
    logo_font = pygame.font.Font(None, 120)
    text = logo_font.render("Air Assault", True, WHITE)
    text_rect = text.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
    clock = pygame.time.Clock()
    alpha_surface = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    alpha_surface.fill(BLACK)

    fade_in_speed = 5
    alpha = 255

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                running = False

        screen.fill(BLACK)

        if alpha > 0:
            alpha -= fade_in_speed
            if alpha < 0:
                alpha = 0
            alpha_surface.set_alpha(alpha)
        else:
            pygame.time.delay(1000)
            running = False

        screen.blit(text, text_rect)
        screen.blit(alpha_surface, (0, 0))
        _flip()
        clock.tick(FPS)

def show_start_screen(screen, fullscreen=False):
    stars = create_stars()
    menu_options = [
        ("SINGLE PLAYER", "single"),
        ("CO-OP MULTIPLAYER", "multi"),
        ("LEADERBOARD", "leaderboard"),
        ("CONTROLS", "controls"),
        ("CREDITS", "credits"),
        ("FULLSCREEN", "fullscreen"),
        ("QUIT", "quit"),
    ]
    selected_option = 0

    big_button_width = 340
    big_button_height = 62
    big_button_gap = 18
    big_button_x = SCREEN_WIDTH - big_button_width - 60
    big_button_first_y = 150

    icon_radius = 28
    fullscreen_icon_center = (SCREEN_WIDTH - 50, 50)
    quit_icon_center = (SCREEN_WIDTH - 50, SCREEN_HEIGHT - 50)

    def run_action(action):
        nonlocal screen, fullscreen
        if action == "single":
            return True         # caller shows profile popup then starts round
        if action == "multi":
            show_multiplayer_screen(screen)
        elif action == "leaderboard":
            show_leaderboard(screen)
        elif action == "credits":
            show_credits_screen(screen)
        elif action == "controls":
            show_controls_screen(screen)
        elif action == "fullscreen":
            fullscreen = not fullscreen
            screen = get_display_surface(fullscreen)
        elif action == "quit":
            pygame.quit()
            sys.exit()
        return False

    while True:
        draw_star_background(screen, stars, speed=1)

        draw_title_with_glow(screen, "AIR ASSAULT", 50, 220, 36, WHITE, MENU_ACCENT)
        draw_text(screen, "Endless Arcade Dogfights", 22, 220, 90, MENU_SUBTEXT)
        draw_menu_mascot(screen, 210, 360)
        draw_left_text(screen, "v1.0", 18, 20, SCREEN_HEIGHT - 30, MENU_SUBTEXT)

        mouse_pos = pygame.mouse.get_pos()
        button_rects = []
        for index in range(5):
            label, _action = menu_options[index]
            y = big_button_first_y + index * (big_button_height + big_button_gap)
            rect = pygame.Rect(big_button_x, y, big_button_width, big_button_height)
            if rect.collidepoint(mouse_pos):
                selected_option = index
            fill_color, shadow_color, text_color = MENU_BUTTON_COLORS[index]
            draw_shadow_button(screen, rect, fill_color, shadow_color, label, index == selected_option, text_color)
            button_rects.append(rect)

        fullscreen_rect = draw_icon_button(
            screen, fullscreen_icon_center, icon_radius, BTN_GREY, BTN_GREY_SHADOW,
            selected_option == 5, icon="fullscreen",
        )
        if fullscreen_rect.collidepoint(mouse_pos):
            selected_option = 5
        quit_rect = draw_icon_button(
            screen, quit_icon_center, icon_radius, BTN_RED, BTN_RED_SHADOW,
            selected_option == 6, icon="quit",
        )
        if quit_rect.collidepoint(mouse_pos):
            selected_option = 6
        button_rects.append(fullscreen_rect)
        button_rects.append(quit_rect)

        draw_text(screen, "FULLSCREEN", 16, fullscreen_icon_center[0], fullscreen_icon_center[1] + icon_radius + 6, MENU_SUBTEXT)
        draw_text(screen, "QUIT", 16, quit_icon_center[0], quit_icon_center[1] - icon_radius - 24, MENU_SUBTEXT)

        draw_text(screen, "ARROWS OR MOUSE - ENTER OR CLICK", 20, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 26, MENU_SUBTEXT)

        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP:
                    selected_option = (selected_option - 1) % len(menu_options)
                elif event.key == pygame.K_DOWN:
                    selected_option = (selected_option + 1) % len(menu_options)
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if run_action(menu_options[selected_option][1]):
                        return screen, fullscreen
                elif event.key == pygame.K_s:
                    return screen, fullscreen
                elif event.key == pygame.K_m:
                    show_multiplayer_screen(screen)
                elif event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    screen = get_display_surface(fullscreen)
                elif event.key == pygame.K_l:
                    show_leaderboard(screen)
                elif event.key == pygame.K_c:
                    show_credits_screen(screen)
                elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                    pygame.quit()
                    sys.exit()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for index, rect in enumerate(button_rects):
                    if rect.collidepoint(event.pos):
                        selected_option = index
                        if run_action(menu_options[index][1]):
                            return screen, fullscreen
                        break

def show_control_method_screen(screen):
    """Shown after profile selection, before the round starts.
    Returns 'keyboard' or 'phone'. If phone is chosen, starts the
    PhoneController server and shows a QR+URL waiting screen until
    the phone connects (or the player cancels)."""
    stars = create_stars()
    clock = pygame.time.Clock()
    # Pre-select whichever control method was used last session.
    options = [
        ("⌨   KEYBOARD",  "keyboard",
         "Arrow keys + Space   •   Works always"),
        ("📱   PHONE CONTROLLER", "phone",
         "Touch buttons on your phone   •   Same Wi-Fi needed"),
    ]
    keys = [o[1] for o in options]
    selected = keys.index(profile_manager.last_control) if profile_manager.last_control in keys else 0
    BTN_W, BTN_H = 420, 72
    BTN_X = SCREEN_WIDTH // 2 - BTN_W // 2
    COLORS = [(BTN_BLUE, BTN_BLUE_SHADOW, WHITE),
              (BTN_GREEN, BTN_GREEN_SHADOW, WHITE)]

    while True:
        draw_star_background(screen, stars, speed=0.5)
        draw_title_with_glow(screen, "CHOOSE CONTROLS", 46,
                             SCREEN_WIDTH // 2, 80, WHITE, MENU_ACCENT)

        mouse_pos = pygame.mouse.get_pos()
        rects = []
        for i, (label, key, hint) in enumerate(options):
            y = 200 + i * (BTN_H + 24)
            rect = pygame.Rect(BTN_X, y, BTN_W, BTN_H)
            if rect.collidepoint(mouse_pos):
                selected = i
            fill, shadow, tc = COLORS[i]
            draw_shadow_button(screen, rect, fill, shadow, label,
                               selected == i, tc, font_size=28)
            draw_text(screen, hint, 18,
                      SCREEN_WIDTH // 2, y + BTN_H + 4, MENU_SUBTEXT)
            rects.append(rect)

        draw_text(screen, "↑ ↓ to choose   •   Enter to confirm   •   Escape to cancel",
                  18, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 40, MENU_SUBTEXT)
        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return "keyboard"   # safe default on cancel
                if event.key == pygame.K_UP:
                    selected = (selected - 1) % len(options)
                elif event.key == pygame.K_DOWN:
                    selected = (selected + 1) % len(options)
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    return options[selected][1]
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, rect in enumerate(rects):
                    if rect.collidepoint(event.pos):
                        return options[i][1]
        clock.tick(FPS)


def show_phone_waiting_screen(screen, controller):
    """Shown after the user picks Phone Controller.
    Displays the QR code and URL, waits for the phone to connect.
    Returns True when connected, False if the player cancels."""
    stars = create_stars()
    clock = pygame.time.Clock()
    local_ip = get_local_ip()
    url = f"http://{local_ip}:{PHONE_CONTROLLER_PORT}"

    while True:
        draw_star_background(screen, stars, speed=0.3)
        draw_title_with_glow(screen, "CONNECT YOUR PHONE", 44,
                             SCREEN_WIDTH // 2, 36, WHITE, MENU_ACCENT)

        draw_text(screen, "1. Connect your phone to the same Wi-Fi as this PC",
                  22, SCREEN_WIDTH // 2, 100, MENU_SUBTEXT)
        draw_text(screen, "2. Open your camera and scan the QR code below",
                  22, SCREEN_WIDTH // 2, 126, MENU_SUBTEXT)

        # QR code centred on screen
        qr_size = 200
        qr_x = SCREEN_WIDTH // 2 - qr_size // 2
        qr_y = 158
        draw_qr_code(screen, url, qr_x, qr_y, size=qr_size)

        draw_text(screen, "Or type this address in your phone's browser:",
                  20, SCREEN_WIDTH // 2, qr_y + qr_size + 14, MENU_SUBTEXT)
        draw_text(screen, url, 28, SCREEN_WIDTH // 2,
                  qr_y + qr_size + 38, MENU_ACCENT)

        if controller.connected:
            draw_text(screen, "✓ Phone connected!", 28,
                      SCREEN_WIDTH // 2, qr_y + qr_size + 70, GREEN)
            draw_text(screen, "Press START on your phone, or SHOOT/MOVE to begin!", 22,
                      SCREEN_WIDTH // 2, qr_y + qr_size + 105, MENU_ACCENT)
            _flip()

            # Check if player pressed a button on the phone to start
            ph = controller.get_input()
            if ph.get("left") or ph.get("right") or ph.get("shoot"):
                return True

            # Allow keyboard input as well to start
            keys = pygame.key.get_pressed()
            if keys[pygame.K_SPACE] or keys[pygame.K_LEFT] or keys[pygame.K_RIGHT] or keys[pygame.K_RETURN]:
                return True
        else:
            # Blinking "waiting" text
            if (pygame.time.get_ticks() // 600) % 2 == 0:
                draw_text(screen, "Waiting for phone to connect...", 24,
                          SCREEN_WIDTH // 2, qr_y + qr_size + 82, MENU_SUBTEXT)

        draw_text(screen, "Escape to go back to keyboard instead",
                  18, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 40, MENU_SUBTEXT)
        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                controller.stop()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                controller.stop()
                return False
        clock.tick(FPS)

def show_game_over_screen(screen, score, high_score, is_new_high_score=False,
                          enemies_destroyed=0, survival_seconds=0, player_name="", max_combo=0,
                          phone_controller=None):
    """End-of-run screen. Shows the run's stats and, if this run beat the
    previous high score, a pulsing 'NEW HIGH SCORE!' flash - the goal is to
    make the player feel something about the run instead of just reading
    a number and hitting restart."""
    stars = create_stars()
    tip = random.choice(GAME_OVER_TIPS)
    minutes, seconds = divmod(survival_seconds, 60)
    survival_text = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"

    # Notify phone that the game is over (so the game-over overlay shows)
    if phone_controller:
        phone_controller.game_over = True

    screen.fill(BLACK)
    running = True
    while running:
        draw_star_background(screen, stars, speed=1)

        t = pygame.time.get_ticks()

        if is_new_high_score:
            # Pulse the glow between gold and white for a genuine "flash"
            # feel instead of a static title.
            pulse = (math.sin(t / 150) + 1) / 2  # oscillates 0..1
            glow_color = (
                int(MENU_ACCENT[0] + (255 - MENU_ACCENT[0]) * pulse),
                int(MENU_ACCENT[1] + (255 - MENU_ACCENT[1]) * pulse),
                int(MENU_ACCENT[2] + (255 - MENU_ACCENT[2]) * pulse),
            )
            draw_title_with_glow(
                screen, "NEW HIGH SCORE!", 54, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 6,
                MENU_ACCENT, glow_color,
            )
            draw_text(screen, "Game Over", 34, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 6 + 60, MENU_SUBTEXT)
        else:
            draw_text(screen, "Game Over", 60, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 6, WHITE)

        # ---- Stats panel ----
        stats_y = SCREEN_HEIGHT // 2 - 60
        stat_color = MENU_ACCENT if is_new_high_score else WHITE
        if player_name:
            draw_text(screen, player_name, 26, SCREEN_WIDTH // 2, stats_y - 34, MENU_SUBTEXT)
        draw_text(screen, f"Score: {score}", 40, SCREEN_WIDTH // 2, stats_y, stat_color)
        draw_text(screen, f"High Score: {high_score}", 28, SCREEN_WIDTH // 2, stats_y + 46, MENU_SUBTEXT)
        draw_text(screen, f"Enemies Destroyed: {enemies_destroyed}", 26, SCREEN_WIDTH // 2, stats_y + 86, WHITE)
        draw_text(screen, f"Max Combo: x{max_combo}", 26, SCREEN_WIDTH // 2, stats_y + 114, MENU_ACCENT if max_combo >= 5 else WHITE)
        draw_text(screen, f"Survived: {survival_text}", 26, SCREEN_WIDTH // 2, stats_y + 142, WHITE)

        draw_text(screen, tip, 20, SCREEN_WIDTH // 2, stats_y + 182, MENU_SUBTEXT)

        # Check phone controller action
        phone_action = None
        if phone_controller and phone_controller.action:
            phone_action = phone_controller.action
            phone_controller.action = None

        if phone_action:
            if phone_action == "restart":
                return True
            elif phone_action == "quit":
                return "menu"

        draw_text(screen, "Press R to Restart, Q to Quit, or M to return to Menu", 18, SCREEN_WIDTH // 2, SCREEN_HEIGHT - 60, WHITE)

        _flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    return True
                if event.key == pygame.K_q:
                    pygame.quit()
                    sys.exit()
                if event.key == pygame.K_m:
                    return "menu"


# ======================================================================
# SINGLE PLAYER
# ======================================================================
def run_single_player_round(screen, fullscreen, heart_icon, profile=None, phone_controller=None):
    """profile is a dict {name, high_score} from ProfileManager, or None
    for a guest run. phone_controller is a started PhoneController instance
    or None when using keyboard only."""
    clock = pygame.time.Clock()
    high_score = profile["high_score"] if profile else 0
    player_name = profile["name"] if profile else "Guest"
    stars = create_stars()
    logic = GameLogic(num_players=1)
    player = logic.players[0]
    shake = ScreenShake()
    round_start_ticks = pygame.time.get_ticks()

    running = True
    paused = False
    started = False  # Freeze gameplay until player gives first input

    # Notify phone that a new round has started (so it resets)
    if phone_controller:
        phone_controller.round_started = True
        phone_controller.game_over = False

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if not started:
                    started = True
                if event.key == pygame.K_p:
                    paused = not paused
                if event.key == pygame.K_q and paused:
                    pygame.quit()
                    sys.exit()
                if event.key == pygame.K_f:
                    fullscreen = not fullscreen
                    screen = get_display_surface(fullscreen)
            if event.type == pygame.WINDOWMINIMIZED:
                paused = True

        keys = pygame.key.get_pressed()
        # Keyboard input — always active so the player can switch back
        # mid-game if the phone disconnects or lags.
        kb = {
            "left":  keys[pygame.K_LEFT],
            "right": keys[pygame.K_RIGHT],
            "shoot": keys[pygame.K_SPACE],
        }
        # Phone input — OR'd with keyboard so either device works.
        ph = phone_controller.get_input() if phone_controller else {}
        input_state = {
            "left":  kb["left"]  or ph.get("left",  False),
            "right": kb["right"] or ph.get("right", False),
            "shoot": kb["shoot"] or ph.get("shoot", False),
        }

        # Check if phone initiated start
        if not started and (input_state["left"] or input_state["right"] or input_state["shoot"]):
            started = True

        if not paused and started:
            logic.update([input_state])
            if logic.game_over:
                running = False

            for intensity, duration in logic.shake_events:
                shake.trigger(intensity, duration)
            logic.shake_events.clear()

        ox, oy = shake.update() if (not paused and started) else (0, 0)
        canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
        logic.draw(canvas, stars)
        draw_left_text(canvas, player_name, 24, 12, 44, MENU_SUBTEXT)
        draw_left_text(canvas, f"Score: {logic.score}", 36, SCREEN_WIDTH - 220, 50, WHITE)
        draw_lives(canvas, 10, 10, player.lives, heart_icon)
        draw_left_text(canvas, f"Best: {high_score}", 36, SCREEN_WIDTH - 220, 10, WHITE)
        # Small phone icon in HUD when using phone controller.
        if phone_controller:
            draw_left_text(canvas, "📱", 22, 12, 64, MENU_SUBTEXT)
        if paused:
            draw_text(canvas, "Paused. Press P to continue or Q to quit.",
                      36, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2, WHITE)
        elif not started:
            # Prompt player to start
            draw_title_with_glow(canvas, "READY TO PLAY", 42,
                                 SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 40, WHITE, MENU_ACCENT)
            if (pygame.time.get_ticks() // 500) % 2 == 0:
                draw_text(canvas, "PRESS MOVE OR SHOOT TO START!",
                          28, SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 15, MENU_ACCENT)

        # Blit shake-offset canvas onto the main screen canvas.
        screen.fill(BLACK)
        screen.blit(canvas, (ox, oy))
        _flip()
        clock.tick(FPS)

    # Mark game over on phone controller so the game-over overlay appears
    if phone_controller:
        phone_controller.game_over = True

    is_new_hs = logic.score > high_score
    if profile and is_new_hs:
        profile_manager.update_high_score(profile["name"], logic.score)
        high_score = logic.score

    survival_seconds = (pygame.time.get_ticks() - round_start_ticks) // 1000
    fade_out(screen)
    result = show_game_over_screen(
        screen,
        score=logic.score,
        high_score=high_score,
        is_new_high_score=is_new_hs,
        enemies_destroyed=logic.enemies_destroyed,
        survival_seconds=survival_seconds,
        player_name=player_name,
        max_combo=logic.max_combo,
        phone_controller=phone_controller,
    )
    next_action = "restart" if result is True else result
    return screen, fullscreen, next_action

def main():
    global _canvas
    pygame.display.set_caption("Air Assault")

    # Start windowed. _canvas is the permanent 800x600 drawing surface.
    _set_mode(False)
    _canvas = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))

    # Set window icon.
    try:
        icon = pygame.image.load(resource_path("icon.ico"))
        pygame.display.set_icon(icon)
    except Exception:
        pass

    # screen always points to _canvas.
    screen = _canvas
    show_intro_animation(screen)

    heart_icon = load_asset("assets/Powerup/Health.png", (30, 30))
    fullscreen = False
    active_profile = None
    active_control = "keyboard"
    phone_ctrl = None

    screen, fullscreen = show_start_screen(screen, fullscreen)

    # Ask profile + controls once before the first round.
    active_profile = show_profile_select_screen(screen, "SELECT PLAYER")
    active_control = show_control_method_screen(screen)
    if active_control == "phone":
        phone_ctrl = PhoneController()
        if not phone_ctrl.start():
            phone_ctrl = None
            active_control = "keyboard"
        else:
            if not show_phone_waiting_screen(screen, phone_ctrl):
                phone_ctrl = None
                active_control = "keyboard"

    # Save choices so next launch pre-selects them automatically.
    profile_manager.remember(
        active_profile["name"] if active_profile else None,
        active_control,
    )

    next_action = "restart"
    while next_action:
        if next_action == "menu":
            # Back to menu — ask profile + controls again for the new session.
            screen, fullscreen = show_start_screen(screen, fullscreen)
            active_profile = show_profile_select_screen(screen, "SELECT PLAYER")
            active_control = show_control_method_screen(screen)
            # If going to menu from phone quit, stop the server
            if phone_ctrl:
                phone_ctrl.stop()
                phone_ctrl = None
            active_control = None
            if active_control == "phone":
                phone_ctrl = PhoneController()
                if not phone_ctrl.start():
                    phone_ctrl = None
                    active_control = "keyboard"
                else:
                    if not show_phone_waiting_screen(screen, phone_ctrl):
                        phone_ctrl = None
                        active_control = "keyboard"

            # Save updated choices.
            profile_manager.remember(
                active_profile["name"] if active_profile else None,
                active_control,
            )

        # Restart — reuse same profile and control, no screens shown.
        screen, fullscreen, next_action = run_single_player_round(
            screen, fullscreen, heart_icon,
            profile=active_profile,
            phone_controller=phone_ctrl,
        )

    pygame.quit()

if __name__ == "__main__":
    main()