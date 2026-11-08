"""
upload.py - the "Landing" tab and the "Loading" tab for main_1.py

LANDING (plane -> worker -> sorted carts)
  1. A plane lands and its bags come out of the cargo hold along the arrow to the scanner.
  2. A worker scans each bag's tag -> the tag says which gate it goes to.
  3. ZIPF'S LAW: a few gates get most of the bags. Rank the gates on this flight by bag count:
       - ranks 1, 2, 3, 4  -> COMMON loading area: four bins, one cart per ranked gate.
                              A common cart waits until it holds 16 bags (one gate, full cart).
       - every other gate  -> UNCOMMON loading area: one mixed cart that goes gate to gate.
                              It leaves near capacity (14 bags) because we optimize for speed.
  4. When the plane is empty the leftover common bags are aggregated into fewer, fuller carts
     (see AGGREGATION below); the uncommon cart just leaves with what it has.

AGGREGATION: when the plane is empty, the partly filled common carts are NOT sent one by one.
  Their leftover bags are merged into as few carts as possible (16 per cart, sorted by gate),
  so most carts leave full. At most 4 leave (one per common container) - the worst case.

main_1.py only needs: create the tab, call update() every frame, draw() when it is open,
and pass it events. LandingTab calls on_cart_depart(info) whenever a cart leaves so the
simulation tab can receive those bags.

Uses only pygame + the standard library (no pandas needed). Reads baggage.csv if it sits
next to this file; otherwise it makes up random flights.
"""
import colorsys
import csv
import math
import os
import random
import pygame

GATES = list("ABCDEFGHIJKLMNOPQRST")

# ---- TUNE THESE ------------------------------------------------------------
ZIPF_TOP = 4               # the top-N ranked gates each get their own common cart
CART_CAP = 16              # cells drawn per cart (physical capacity)
COMMON_DISPATCH_AT = 16    # common carts leave only when completely full
UNCOMMON_DISPATCH_AT = 14  # the uncommon cart leaves near capacity ("almost 16")
# -----------------------------------------------------------------------------
KINDS = ("common", "uncommon")
DISPATCH_AT = {"common": COMMON_DISPATCH_AT, "uncommon": UNCOMMON_DISPATCH_AT}
BIN_COUNT = {"common": ZIPF_TOP, "uncommon": 1}
GRID = {"common": (22, 3), "uncommon": (38, 4)}    # (cell size, gap) of the 4 x 4 cart grids
BIN_PITCH = 125                                     # distance between the four common bins

# Colors (match main_1.py: blue = common/sorted, magenta = uncommon/unsorted)
PANEL = (35, 35, 45)
TEXT = (220, 220, 220)
DIM = (150, 150, 150)
GOLD = (255, 200, 0)
GREEN = (100, 255, 100)
COMMON_COLOR = (50, 150, 255)
UNCOMMON_COLOR = (255, 100, 255)
UNREAD = (110, 110, 120)

BELT_Y = 385           # y of the main flow line
BELT_X0 = 240          # where bags start on the arrow (landing tab)
BELT_SPEED = 3
BAG_SPACING = 30


def gate_color(g):
    r, gr, b = colorsys.hsv_to_rgb(GATES.index(g) / len(GATES), 0.65, 1.0)
    return (int(r * 255), int(gr * 255), int(b * 255))


def load_flights(path):
    flights = []
    try:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                counts = {g: int(row[g]) for g in GATES if row.get(g) and int(row[g]) > 0}
                if counts:
                    flights.append({"flight": int(row["flight"]), "counts": counts})
    except (OSError, KeyError, ValueError):
        pass
    return flights


def random_flight():
    total = random.randint(10, 70)
    k = random.randint(1, 5)
    gates = sorted(random.sample(GATES, k))
    cuts = sorted(random.sample(range(1, total), k - 1)) if k > 1 else []
    parts = [b - a for a, b in zip([0] + cuts, cuts + [total])]
    return {"flight": random.randint(100, 999), "counts": dict(zip(gates, parts))}


class _BaseTab:
    """Shared screen furniture: layout, buttons, histogram, scanner, carts, legend."""
    mode = "land"
    next_label = "Land Plane (N)"

    def __init__(self, rect, csv_path=None, mirrored=False):
        self.rect = rect
        self.mirrored = mirrored
        base = os.path.dirname(os.path.abspath(__file__))
        self.flights = load_flights(csv_path or os.path.join(base, "baggage.csv"))
        self.flight_idx = 0

        self.f_big = pygame.font.SysFont("Arial", 16, bold=True)
        self.f_mid = pygame.font.SysFont("Arial", 13, bold=True)
        self.f_small = pygame.font.SysFont("Arial", 11, bold=True)
        self.f_tiny = pygame.font.SysFont("Arial", 9, bold=True)

        self.btn_next = pygame.Rect(760, 70, 140, 32)
        self.btn_auto = pygame.Rect(910, 70, 140, 32)
        self.btn_scan = pygame.Rect(1060, 70, 160, 32)
        self.btn_speed = pygame.Rect(760, 110, 140, 26)

        if mirrored:   # loading tab: carts on the left, plane on the right
            self.area_rects = {"common": (30, 168, 520, 225), "uncommon": (30, 405, 520, 225)}
            self.scan_x = 730
            self.plane_x = 1030
            self.tag_box = (735, BELT_Y + 40)
            self.worker_pos = (self.scan_x - 60, BELT_Y + 40)
        else:          # landing tab: plane on the left, carts on the right
            self.area_rects = {"common": (700, 168, 520, 225), "uncommon": (700, 405, 520, 225)}
            self.scan_x = 520
            self.plane_x = 30
            self.tag_box = (300, BELT_Y + 40)
            self.worker_pos = (self.scan_x + 60, BELT_Y + 40)

        self.auto = True
        self.speed = 1
        self.frame = 0
        self.flight = None
        self.common_gate = None
        self.rank_gates = []
        self.bin_of = {}
        self.active = False
        self.remaining = {}
        self.scan_state = "idle"     # idle -> waiting (manual) -> scanning -> result -> idle
        self.scan_timer = 0
        self.tweens = []
        self.departing = []
        self.areas = {k: self._new_area(BIN_COUNT[k]) for k in KINDS}
        self.stats = {"scanned": 0, "common": 0, "uncommon": 0, "carts": 0}
        self.message = ""

    # ------------------------------------------------------------------ state
    @staticmethod
    def _new_area(n_bins):
        return {"bins": [{"slots": [], "reserved": 0, "carts": [], "refill": 0} for _ in range(n_bins)],
                "last": 0, "sent": 0, "routed": 0}

    def _setup_flight(self, f):
        """Pick the flight, rank its gates (Zipf), reset the shared state."""
        counts = dict(f["counts"])
        ranked = sorted(counts, key=lambda g: (-counts[g], GATES.index(g)))
        self.rank_gates = ranked[:ZIPF_TOP]
        self.bin_of = {g: i for i, g in enumerate(self.rank_gates)}
        self.common_gate = self.rank_gates[0]
        total = sum(counts.values())
        share = round(100 * sum(counts[g] for g in self.rank_gates) / total)
        self.flight = {"flight": f["flight"], "counts": counts, "total": total}
        self.remaining = dict(counts)
        self.tweens, self.departing = [], []
        self.areas = {k: self._new_area(BIN_COUNT[k]) for k in KINDS}
        self.stats = {"scanned": 0, "common": 0, "uncommon": 0, "carts": 0}
        self.scan_state, self.scan_timer = "idle", 0
        self.active = True
        return share

    def _next_flight(self):
        if self.flights:
            f = self.flights[self.flight_idx % len(self.flights)]
            self.flight_idx += 1
            return f
        return random_flight()

    def start_flight(self):
        raise NotImplementedError

    def toggle_auto(self):
        self.auto = not self.auto
        if self.auto and self.scan_state == "waiting":
            self._start_scan()

    def scan_next(self):
        if self.scan_state == "waiting":
            self._start_scan()

    def cycle_speed(self):
        self.speed = {1: 2, 2: 4, 4: 1}[self.speed]

    def _start_scan(self):
        self.scan_state = "scanning"
        self.scan_timer = 25

    # ----------------------------------------------------------------- events
    def handle_event(self, event):
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_n:
                self.start_flight()
            elif event.key == pygame.K_a:
                self.toggle_auto()
            elif event.key == pygame.K_SPACE:
                self.scan_next()
            elif event.key == pygame.K_s:
                self.cycle_speed()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.btn_next.collidepoint(event.pos):
                self.start_flight()
            elif self.btn_auto.collidepoint(event.pos):
                self.toggle_auto()
            elif self.btn_scan.collidepoint(event.pos):
                self.scan_next()
            elif self.btn_speed.collidepoint(event.pos):
                self.cycle_speed()

    def update(self):
        for _ in range(self.speed):
            self._step()

    def _step(self):
        raise NotImplementedError

    # --------------------------------------------------------------- geometry
    def _grid_origin(self, kind, b):
        x, y, _, _ = self.area_rects[kind]
        if kind == "common":
            return x + 15 + b * BIN_PITCH, y + 50
        return x + 20, y + 44

    def _slot_center(self, kind, b, idx):
        cell, gap = GRID[kind]
        gx, gy = self._grid_origin(kind, b)
        pitch = cell + gap
        return gx + (idx % 4) * pitch + cell // 2, gy + (idx // 4) * pitch + cell // 2

    # ------------------------------------------------------------------- draw
    def _text(self, surf, s, pos, font, color=TEXT, center=False):
        img = font.render(s, True, color)
        if center:
            pos = (pos[0] - img.get_width() // 2, pos[1] - img.get_height() // 2)
        surf.blit(img, pos)

    def _button(self, surf, rect, label, color=TEXT):
        pygame.draw.rect(surf, (45, 45, 60), rect, border_radius=6)
        pygame.draw.rect(surf, color, rect, 2, border_radius=6)
        self._text(surf, label, rect.center, self.f_mid, color, center=True)

    @staticmethod
    def _arrow(surf, p0, p1, color, width=2, head=9):
        pygame.draw.line(surf, color, p0, p1, width)
        ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
        left = (p1[0] - head * math.cos(ang - 0.45), p1[1] - head * math.sin(ang - 0.45))
        right = (p1[0] - head * math.cos(ang + 0.45), p1[1] - head * math.sin(ang + 0.45))
        pygame.draw.polygon(surf, color, [p1, left, right])

    def _progress_text(self):          # "Scanned 3/56" / "Loaded 3/56"
        raise NotImplementedError

    def _title_text(self):
        raise NotImplementedError

    def _hint_text(self):
        raise NotImplementedError

    def draw(self, surf):
        self._text(surf, self._title_text(), (30, 64), self.f_big, GOLD)
        self._text(surf, self.message, (30, 84), self.f_small, DIM)
        self._draw_histogram(surf)

        self._button(surf, self.btn_next, self.next_label, GREEN if not self.active else DIM)
        self._button(surf, self.btn_auto, f"Auto: {'ON' if self.auto else 'OFF'} (A)",
                     GREEN if self.auto else GOLD)
        self._button(surf, self.btn_scan, "Scan Next (SPACE)",
                     GOLD if self.scan_state == "waiting" else DIM)
        self._button(surf, self.btn_speed, f"Speed: {self.speed}x (S)")
        total = self.flight["total"] if self.flight else 0
        self._text(surf, f"{self._progress_text()}/{total}", (910, 110), self.f_small)
        self._text(surf, f"Common {self.stats['common']}  |  Uncommon {self.stats['uncommon']}  |  "
                         f"Carts {self.stats['carts']}", (910, 125), self.f_small)
        self._text(surf, self._hint_text(), (760, 144), self.f_tiny, DIM)

        self._draw_flow(surf)
        self._draw_plane_block(surf)
        self._draw_scanner(surf)
        for kind in KINDS:
            self._draw_area(surf, kind)
        self._draw_extra(surf)
        self._draw_flying_bags(surf)
        self._draw_legend(surf)

    def _draw_extra(self, surf):
        pass

    def _draw_plane_block(self, surf):
        raise NotImplementedError

    def _draw_histogram(self, surf):
        x0, base, width, max_h = 30, 150, 670, 30
        pygame.draw.line(surf, (70, 70, 85), (x0, base), (x0 + width, base), 1)
        counts = self.flight["counts"] if self.flight else {}
        biggest = max(counts.values()) if counts else 1
        bar_w = width / len(GATES)
        for i, g in enumerate(GATES):
            bx = int(x0 + i * bar_w)
            n = counts.get(g, 0)
            ranked = g in self.bin_of
            if n:
                full_h = max(3, int(max_h * n / biggest))
                color = COMMON_COLOR if ranked else UNCOMMON_COLOR
                pygame.draw.rect(surf, (60, 60, 75), (bx + 4, base - full_h, int(bar_w) - 8, full_h), 1)
                left = self.remaining.get(g, n)
                h = int(full_h * left / n)
                if h > 0:
                    pygame.draw.rect(surf, color, (bx + 4, base - h, int(bar_w) - 8, h))
                self._text(surf, str(n), (bx + bar_w / 2, base - full_h - 7), self.f_tiny, TEXT, center=True)
                if ranked:
                    self._text(surf, f"#{self.bin_of[g] + 1}", (bx + bar_w / 2, base - full_h - 17),
                               self.f_tiny, GOLD, center=True)
            self._text(surf, g, (bx + bar_w / 2, base + 8), self.f_tiny,
                       COMMON_COLOR if ranked else DIM, center=True)

    def _draw_plane(self, surf, caption, frac, grow):
        ox = self.plane_x
        flip = self.mirrored

        def X(xl):
            return ox + (190 - xl if flip else xl)

        body, wing = (200, 200, 215), (165, 165, 185)
        pygame.draw.polygon(surf, wing, [(X(65), 362), (X(110), 362), (X(82), 322), (X(60), 322)])
        pygame.draw.polygon(surf, wing, [(X(65), 408), (X(110), 408), (X(82), 448), (X(60), 448)])
        pygame.draw.polygon(surf, wing, [(X(22), 368), (X(22), 402), (X(0), 385)])
        x1, x2 = sorted((X(15), X(185)))
        pygame.draw.rect(surf, body, (x1, 360, x2 - x1, 50), border_radius=24)
        label = f"FLIGHT {self.flight['flight']}" if self.flight else "NO PLANE"
        self._text(surf, label, (X(100), 385), self.f_mid, (40, 40, 50), center=True)
        self._text(surf, caption, (ox, 462), self.f_small)
        pygame.draw.rect(surf, (60, 60, 75), (ox, 480, 190, 8), border_radius=4)
        w = int(190 * frac)
        if w > 0:
            pygame.draw.rect(surf, GREEN if grow else GOLD, (ox, 480, w, 8), border_radius=4)

    def _draw_flow(self, surf):
        """Arrows (no conveyor): plane <-> scanner <-> loading areas."""
        sx = self.scan_x
        if not self.mirrored:
            self._arrow(surf, (225, BELT_Y), (sx - 34, BELT_Y), DIM, 3)            # plane -> scanner
            pygame.draw.line(surf, DIM, (sx + 34, BELT_Y), (640, BELT_Y), 2)
            pygame.draw.line(surf, COMMON_COLOR, (640, BELT_Y), (694, 280), 2)
            pygame.draw.line(surf, UNCOMMON_COLOR, (640, BELT_Y), (694, 518), 2)
            self._arrow(surf, (688, 290), (698, 278), COMMON_COLOR, 2, 10)
            self._arrow(surf, (688, 508), (698, 520), UNCOMMON_COLOR, 2, 10)
            self._text(surf, "common", (655, 318), self.f_tiny, COMMON_COLOR)
            self._text(surf, "other gates", (645, 440), self.f_tiny, UNCOMMON_COLOR)
        else:
            fx = 620
            pygame.draw.line(surf, COMMON_COLOR, (556, 280), (fx, BELT_Y), 2)
            pygame.draw.line(surf, UNCOMMON_COLOR, (556, 518), (fx, BELT_Y), 2)
            self._arrow(surf, (560, 285), (fx, BELT_Y), COMMON_COLOR, 2, 10)
            self._arrow(surf, (560, 513), (fx, BELT_Y), UNCOMMON_COLOR, 2, 10)
            self._arrow(surf, (fx, BELT_Y), (sx - 34, BELT_Y), DIM, 3)             # carts -> scanner
            self._arrow(surf, (sx + 34, BELT_Y), (self.plane_x - 8, BELT_Y), GREEN, 3)   # scanner -> plane
            self._text(surf, "common", (562, 318), self.f_tiny, COMMON_COLOR)
            self._text(surf, "other gates", (562, 440), self.f_tiny, UNCOMMON_COLOR)

    def _scanner_gate(self):
        raise NotImplementedError

    def _result_text(self, gate):
        raise NotImplementedError

    def _draw_scanner(self, surf):
        sx = self.scan_x
        pygame.draw.line(surf, DIM, (sx - 28, BELT_Y - 13), (sx - 28, BELT_Y - 48), 3)
        pygame.draw.line(surf, DIM, (sx + 28, BELT_Y - 13), (sx + 28, BELT_Y - 48), 3)
        pygame.draw.line(surf, DIM, (sx - 28, BELT_Y - 48), (sx + 28, BELT_Y - 48), 3)
        self._text(surf, "SCANNER", (sx, BELT_Y - 60), self.f_small, DIM, center=True)
        if self.scan_state == "scanning" and (self.frame // 3) % 2 == 0:
            pygame.draw.line(surf, (255, 60, 60), (sx, BELT_Y - 46), (sx, BELT_Y + 14), 2)

        wx, wy = self.worker_pos
        pygame.draw.circle(surf, (230, 190, 150), (wx, wy - 14), 9)
        pygame.draw.rect(surf, (230, 130, 40), (wx - 10, wy - 4, 20, 26), border_radius=4)
        self._text(surf, "Worker", (wx, wy + 34), self.f_tiny, DIM, center=True)

        bx, by = self.tag_box
        box = pygame.Rect(bx, by, 215, 62)
        pygame.draw.rect(surf, PANEL, box, border_radius=6)
        pygame.draw.rect(surf, (70, 70, 85), box, 1, border_radius=6)
        gate = self._scanner_gate()
        if self.scan_state == "waiting":
            self._text(surf, "Bag at scanner", (box.x + 10, box.y + 10), self.f_mid, GOLD)
            self._text(surf, "Press SPACE to scan the tag", (box.x + 10, box.y + 32), self.f_small)
        elif self.scan_state == "scanning":
            self._text(surf, "Reading tag...", (box.x + 10, box.y + 10), self.f_mid, (255, 100, 100))
        elif self.scan_state == "result" and gate:
            text, color = self._result_text(gate)
            self._text(surf, f"Tag: Gate {gate}", (box.x + 10, box.y + 8), self.f_mid, gate_color(gate))
            self._text(surf, text, (box.x + 10, box.y + 32), self.f_mid, color)
        else:
            self._text(surf, "Scanner idle", (box.x + 10, box.y + 10), self.f_mid, DIM)

    def _area_lines(self, kind):
        """(line1, line2, ...) of extra text under/next to the carts; set by the subclass."""
        raise NotImplementedError

    def _draw_area(self, surf, kind):
        x, y, w, h = self.area_rects[kind]
        color = COMMON_COLOR if kind == "common" else UNCOMMON_COLOR
        area = self.areas[kind]
        pygame.draw.rect(surf, PANEL, (x, y, w, h), border_radius=8)
        pygame.draw.rect(surf, color, (x, y, w, h), 2, border_radius=8)
        loading = (self.mode == "load")

        if kind == "common":
            self._text(surf, "COMMON LOADING AREA - Ranks 1-4", (x + 20, y + 10), self.f_big, color)
            for bi, b in enumerate(area["bins"]):
                gate = self.rank_gates[bi] if bi < len(self.rank_gates) else None
                gx, gy = self._grid_origin(kind, bi)
                is_last = bool(self.active and gate and bi == area["last"])
                label = f"#{bi + 1} Gate {gate}" if gate else f"#{bi + 1} (no gate)"
                self._text(surf, label, (gx, y + 32), self.f_small, GOLD if is_last else DIM)
                self._draw_cart(surf, kind, bi, b["slots"], 0, GOLD if is_last else (40, 90, 150))
                if loading:
                    count = f"{len(b['slots'])} left, +{len(b['carts'])} carts"
                else:
                    count = f"{len(b['slots'])}/{COMMON_DISPATCH_AT}"
                self._text(surf, count, (gx, gy + 100), self.f_small)
            l1, l2 = self._area_lines(kind)
            self._text(surf, l1, (x + 20, y + 178), self.f_small)
            self._text(surf, l2, (x + 20, y + 198), self.f_small, DIM)
        else:
            self._text(surf, "UNCOMMON LOADING AREA - all other gates", (x + 20, y + 10), self.f_big, color)
            b = area["bins"][0]
            slots = b["slots"]
            tx = x + 230
            gates = ", ".join(sorted(set(slots))) if slots else "-"
            self._text(surf, f"Gates ranked {ZIPF_TOP + 1} and below", (tx, y + 50), self.f_mid)
            self._text(surf, f"Gates in cart: {gates}", (tx, y + 72), self.f_small, DIM)
            if loading:
                self._text(surf, f"Cart: {len(slots)} left, +{len(b['carts'])} carts", (tx, y + 104), self.f_mid, GOLD)
            else:
                self._text(surf, f"Cart load: {len(slots)}/{UNCOMMON_DISPATCH_AT}", (tx, y + 104), self.f_mid, GOLD)
            l1, l2 = self._area_lines(kind)
            self._text(surf, l1, (tx, y + 128), self.f_small)
            self._text(surf, l2, (tx, y + 146), self.f_small, DIM)
            self._draw_cart(surf, kind, 0, slots, 0, GOLD if self.active else (120, 70, 120))

        for d in self.departing:
            if d["kind"] == kind:
                self._draw_cart(surf, kind, d["bin"], d["slots"], d["x"], GREEN)

    def _draw_cart(self, surf, kind, bi, slots, dx, frame_color):
        cell, gap = GRID[kind]
        gx, gy = self._grid_origin(kind, bi)
        gx += int(dx)
        pitch = cell + gap
        size = 4 * pitch - gap + 10
        pygame.draw.rect(surf, (20, 20, 26), (gx - 5, gy - 5, size, size), border_radius=6)
        pygame.draw.rect(surf, frame_color, (gx - 5, gy - 5, size, size), 1, border_radius=6)
        font = self.f_mid if cell >= 30 else self.f_tiny
        limit = DISPATCH_AT[kind]
        for i in range(CART_CAP):
            c = pygame.Rect(gx + (i % 4) * pitch, gy + (i // 4) * pitch, cell, cell)
            if i < len(slots):
                pygame.draw.rect(surf, gate_color(slots[i]), c, border_radius=4)
                self._text(surf, slots[i], c.center, font, (20, 20, 25), center=True)
            else:
                # cells past the dispatch point are dimmer: the cart leaves before they fill
                outline = (45, 45, 58) if i < limit else (32, 32, 40)
                pygame.draw.rect(surf, outline, c, 1, border_radius=4)

    def _draw_flying_bags(self, surf):
        for tw in self.tweens:
            p = tw["t"] / tw["dur"]
            p = p * p * (3 - 2 * p)   # smooth start and stop
            x = tw["sx"] + (tw["ex"] - tw["sx"]) * p
            y = tw["sy"] + (tw["ey"] - tw["sy"]) * p
            pygame.draw.rect(surf, gate_color(tw["gate"]), (int(x) - 11, int(y) - 8, 22, 16), border_radius=3)

    def _draw_legend(self, surf):
        y = 650
        self._text(surf, "Gate colors:", (30, y + 2), self.f_small, DIM)
        for i, g in enumerate(GATES):
            x = 115 + i * 33
            pygame.draw.rect(surf, gate_color(g), (x, y, 28, 18), border_radius=3)
            self._text(surf, g, (x + 14, y + 9), self.f_small, (20, 20, 25), center=True)
        pygame.draw.rect(surf, COMMON_COLOR, (800, y + 2, 14, 14), border_radius=3)
        self._text(surf, "common (Zipf ranks 1-4)", (820, y + 2), self.f_small)
        pygame.draw.rect(surf, UNCOMMON_COLOR, (985, y + 2, 14, 14), border_radius=3)
        self._text(surf, "uncommon (all other gates)", (1005, y + 2), self.f_small)


# ======================================================================================
class LandingTab(_BaseTab):
    mode = "land"
    next_label = "Land Plane (N)"

    def __init__(self, rect, csv_path=None, on_cart_depart=None):
        super().__init__(rect, csv_path, mirrored=False)
        self.on_cart_depart = on_cart_depart
        self.queue = []
        self.belt = []
        self.release_timer = 0
        self.message = "Press N (or click Land Plane) to land the first plane."

    def land_plane(self):
        if self.active:
            self.message = "The previous plane is still unloading."
            return False
        f = self._next_flight()
        share = self._setup_flight(f)
        bags = [g for g, n in self.flight["counts"].items() for _ in range(n)]
        random.shuffle(bags)
        self.queue = bags
        self.belt = []
        self.release_timer = 0
        top = ", ".join(self.rank_gates)
        self.message = (f"Flight {f['flight']} landed with {len(bags)} bags. Top {len(self.rank_gates)} gates "
                        f"({top}) hold {share}% of them (Zipf).")
        return True

    def start_flight(self):
        return self.land_plane()

    # ----------------------------------------------------------------- update
    def _step(self):
        self.frame += 1

        for d in self.departing:          # departing carts slide off to the right
            d["x"] += 6
        self.departing = [d for d in self.departing if d["x"] < 760]

        for tw in self.tweens[:]:         # bags flying from the scanner into a cart slot
            tw["t"] += 1
            if tw["t"] >= tw["dur"]:
                self.tweens.remove(tw)
                b = self.areas[tw["kind"]]["bins"][tw["bin"]]
                b["slots"].append(tw["gate"])
                if len(b["slots"]) >= DISPATCH_AT[tw["kind"]]:
                    self._depart(tw["kind"], tw["bin"])

        if not self.active:
            return

        # 1. bags leave the cargo hold and travel along the arrow
        if self.queue:
            self.release_timer -= 1
            if self.release_timer <= 0 and (not self.belt or self.belt[-1]["x"] > BELT_X0 + BAG_SPACING):
                self.belt.append({"gate": self.queue.pop(), "x": float(BELT_X0)})
                self.release_timer = 8

        # 2. the front bag stops at the scanner, the rest queue behind it
        for i, b in enumerate(self.belt):
            limit = self.scan_x if i == 0 else self.belt[i - 1]["x"] - BAG_SPACING
            b["x"] = min(b["x"] + BELT_SPEED, limit)

        # 3. scanner / worker
        if self.scan_state == "idle":
            if self.belt and self.belt[0]["x"] >= self.scan_x - 0.5:
                if self.auto:
                    self._start_scan()
                else:
                    self.scan_state = "waiting"
        elif self.scan_state == "scanning":
            self.scan_timer -= 1
            if self.scan_timer <= 0:
                self.scan_state, self.scan_timer = "result", 18
        elif self.scan_state == "result":
            self.scan_timer -= 1
            if self.scan_timer <= 0 and self._route_front_bag():
                self.scan_state = "idle"

        # 4. plane empty -> the last partial carts depart
        if (not self.queue and not self.belt and self.scan_state == "idle" and not self.tweens):
            before, after = self._aggregate_common()
            for bi, b in enumerate(self.areas["uncommon"]["bins"]):
                if b["slots"]:
                    self._depart("uncommon", bi)
            self.active = False
            note = f" Aggregated {before} partial common carts into {after}." if before > after else ""
            self.message = f"Flight {self.flight['flight']} fully unloaded - last carts departed.{note}"

    def _route_front_bag(self):
        gate = self.belt[0]["gate"]
        if gate in self.bin_of:                  # Zipf rank 1-4 -> its own common cart
            kind, bi = "common", self.bin_of[gate]
        else:                                    # every other gate -> the mixed uncommon cart
            kind, bi = "uncommon", 0
        area = self.areas[kind]
        b = area["bins"][bi]
        if b["reserved"] >= DISPATCH_AT[kind]:   # that cart is leaving right now: wait a moment
            return False
        self.belt.pop(0)
        idx = b["reserved"]
        b["reserved"] += 1
        area["last"] = bi
        area["routed"] += 1
        self.remaining[gate] -= 1
        self.stats["scanned"] += 1
        self.stats[kind] += 1
        ex, ey = self._slot_center(kind, bi, idx)
        self.tweens.append({"gate": gate, "kind": kind, "bin": bi, "sx": self.scan_x, "sy": BELT_Y,
                            "ex": ex, "ey": ey, "t": 0, "dur": 22})
        return True

    def _depart(self, kind, bi):
        b = self.areas[kind]["bins"][bi]
        slots = b["slots"]
        b["slots"], b["reserved"] = [], 0
        self._send_cart(kind, bi, slots)

    def _send_cart(self, kind, bi, slots):
        """Send one cart off (bi = which container position it leaves from)."""
        if not slots:
            return
        self.areas[kind]["sent"] += 1
        self.stats["carts"] += 1
        self.departing.append({"slots": slots, "kind": kind, "bin": bi, "x": 0.0})
        gates = sorted(set(slots))
        where = f"gate {gates[0]}" if len(gates) == 1 else "gates " + ", ".join(gates)
        name = f"Common cart #{bi + 1}" if kind == "common" else "Uncommon cart"
        self.message = f"{name} departed with {len(slots)} bags -> {where}."
        if self.on_cart_depart:
            self.on_cart_depart({"kind": kind, "bin": bi, "bags": list(slots),
                                 "flight": self.flight["flight"],
                                 "common_gate": self.common_gate})

    def _aggregate_common(self):
        """Merge the partly filled common containers into as few carts as possible.
        Returns (partial carts before, carts sent after). Never more than ZIPF_TOP (4)."""
        bins = self.areas["common"]["bins"]
        leftovers, before = [], 0
        for b in bins:
            if b["slots"]:
                before += 1
                leftovers.extend(b["slots"])
                b["slots"], b["reserved"] = [], 0
        if not leftovers:
            return 0, 0
        leftovers.sort(key=GATES.index)                 # sorted by gate so the route is tidy
        chunks = [leftovers[i:i + COMMON_DISPATCH_AT]
                  for i in range(0, len(leftovers), COMMON_DISPATCH_AT)]
        for ci, chunk in enumerate(chunks):
            self._send_cart("common", ci, chunk)
        return before, len(chunks)

    # ------------------------------------------------------------------- draw
    def _title_text(self):
        if not self.flight:
            return "No plane has landed yet"
        n = self.flight["counts"][self.common_gate]
        return (f"Flight {self.flight['flight']} | {self.flight['total']} bags | "
                f"#1 gate: {self.common_gate} ({n} bags)")

    def _progress_text(self):
        return f"Scanned {self.stats['scanned']}"

    def _hint_text(self):
        return (f"Common carts leave at {COMMON_DISPATCH_AT} (leftovers merged at the end), "
                f"uncommon at {UNCOMMON_DISPATCH_AT}")

    def _draw_plane_block(self, surf):
        left = len(self.queue)
        frac = (left / self.flight["total"]) if self.flight and self.flight["total"] else 0
        self._draw_plane(surf, f"Cargo hold: {left} bags left", frac, grow=False)

    def _scanner_gate(self):
        return self.belt[0]["gate"] if self.belt else None

    def _result_text(self, gate):
        if gate in self.bin_of:
            return f"-> COMMON cart #{self.bin_of[gate] + 1}", COMMON_COLOR
        return "-> UNCOMMON cart", UNCOMMON_COLOR

    def _area_lines(self, kind):
        area = self.areas[kind]
        if kind == "common":
            return ("Each ranked gate fills its own cart; leftovers get merged at the end",
                    f"Carts sent: {area['sent']}   |   Bags routed here: {area['routed']}")
        return (f"Carts sent: {area['sent']}", f"Bags routed here: {area['routed']}")

    def _draw_extra(self, surf):
        # bags travelling along the arrow (gray until the tag has been read)
        for i, b in enumerate(self.belt):
            color = UNREAD
            if i == 0 and self.scan_state == "result":
                color = gate_color(b["gate"])
            pygame.draw.rect(surf, color, (int(b["x"]) - 12, BELT_Y - 8, 24, 16), border_radius=3)
