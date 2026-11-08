import pygame
import math
import sys
import random
from collections import deque
import os
from upload import LandingTab   # the Landing tab (upload.py)

# Initialize Pygame
pygame.init()
WIDTH, HEIGHT = 1250, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Self-Playing Terminal Network - High Spawn Rate & Time Tracker")
clock = pygame.time.Clock()

# Color Palette
BG_COLOR = (25, 25, 30)
TERMINAL_COLORS = {
    "A": (40, 50, 70),
    "B": (50, 40, 60),
    "C": (40, 60, 50),
    "D": (60, 50, 40)
}
NODE_COLOR = (0, 200, 255)
HIGHLIGHT_COLOR = (255, 255, 255)
BRIDGE_COLOR = (255, 200, 0)
AGENT_COLOR = (100, 220, 255)
SORTED_COLOR = (50, 150, 255)      # Blue for sorted bags/trails
UNSORTED_COLOR = (255, 100, 255)   # Magenta for unsorted bags/trails
CART_BG_COLOR = (35, 35, 45)
TEXT_COLOR = (220, 220, 220)

font = pygame.font.SysFont("Arial", 12, bold=True)
node_font = pygame.font.SysFont("Arial", 8)
title_font = pygame.font.SysFont("Arial", 15, bold=True)

# 1. TERMINAL ADJACENCY DICTIONARY
TERMINAL_PATHS = {
    "A": ["B"],
    "B": ["A", "C"],
    "C": ["B", "D"],
    "D": ["C"]
}

# 2. STRUCTURE & RECTANGULAR TERMINALS
terminals = {
    "A": pygame.Rect(60, 130, 230, 480),
    "B": pygame.Rect(350, 130, 230, 480),
    "C": pygame.Rect(640, 130, 230, 480),
    "D": pygame.Rect(930, 130, 230, 480),
}

# Dedicated crossing points (Bridges) placed cleanly between terminal gaps
bridges = {
    ("A", "B"): (320, 370),
    ("B", "C"): (610, 370),
    ("C", "D"): (900, 370)
}

# 3. GENERATE 30 EVENLY SPREAD NODES PER TERMINAL (Total = 120 nodes)
nodes = {}
NODES_PER_TERMINAL = 30

def generate_perimeter_nodes(rect, num_nodes):
    coords = []
    w = rect.width
    h = rect.height
    top_len = w
    right_len = h
    bottom_len = w
    left_len = h
    total_len = top_len + right_len + bottom_len + left_len
   
    for i in range(num_nodes):
        d = (i / num_nodes) * total_len
        if d < top_len:
            px = rect.x + d
            py = rect.y
        elif d < top_len + right_len:
            px = rect.x + w
            py = rect.y + (d - top_len)
        elif d < top_len + right_len + bottom_len:
            d_bottom = d - (top_len + right_len)
            px = rect.x + w - d_bottom
            py = rect.y + h
        else:
            d_left = d - (top_len + right_len + bottom_len)
            px = rect.x
            py = rect.y + h - d_left
        coords.append((int(px), int(py)))
    return coords

node_counter = 1
for t_name, rect in terminals.items():
    perimeter_positions = generate_perimeter_nodes(rect, NODES_PER_TERMINAL)
    for pos in perimeter_positions:
        nodes[f"N{node_counter}"] = {
            "terminal": t_name,
            "pos": pos,
            "id": node_counter
        }
        node_counter += 1

def get_bridge(t1, t2):
    pair = tuple(sorted([t1, t2]))
    return bridges.get(pair, None)

def get_terminal_at_pos(pos):
    for t_name, rect in terminals.items():
        if rect.collidepoint(pos):
            return t_name
    min_dist = float('inf')
    closest_t = "A"
    for t_name, rect in terminals.items():
        center_x = rect.x + rect.width / 2
        center_y = rect.y + rect.height / 2
        dist = math.hypot(pos[0] - center_x, pos[1] - center_y)
        if dist < min_dist:
            min_dist = dist
            closest_t = t_name
    return closest_t

def get_closest_node_in_terminal(pos, terminal_name):
    min_dist = float('inf')
    closest_key = "N1"
    for n_name, data in nodes.items():
        if data["terminal"] == terminal_name:
            dist = math.hypot(pos[0] - data["pos"][0], pos[1] - data["pos"][1])
            if dist < min_dist:
                min_dist = dist
                closest_key = n_name
    return closest_key

# 4. PATHFINDING LOGIC
def find_terminal_path(start, target):
    if start == target:
        return [start]
    queue = deque([[start]])
    visited = {start}
    while queue:
        path = queue.popleft()
        current = path[-1]
        if current == target:
            return path
        for neighbor in TERMINAL_PATHS.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])
    return []

def plan_path(start_node_key, target_node_key):
    start_info = nodes[start_node_key]
    target_info = nodes[target_node_key]
    t_start = start_info["terminal"]
    t_target = target_info["terminal"]
   
    if t_start == t_target:
        return [target_info["pos"]]
       
    terminal_path = find_terminal_path(t_start, t_target)
    if not terminal_path or len(terminal_path) < 2:
        return []
       
    waypoints = []
    for i in range(len(terminal_path) - 1):
        t1 = terminal_path[i]
        t2 = terminal_path[i+1]
        bridge_pos = get_bridge(t1, t2)
        if bridge_pos:
            waypoints.append(bridge_pos)
           
    waypoints.append(target_info["pos"])
    return waypoints

# 5. AUTONOMOUS AGENT CLASS
class Agent:
    def __init__(self, name, home_node_key):
        self.name = name
        self.home_node = home_node_key
        self.current_node = home_node_key
        self.target_node = home_node_key
        self.pos = list(nodes[home_node_key]["pos"])
        self.waypoints = []
        self.speed = 6
        self.cart = []  # Max capacity 16
        self.pickup_timer = 0    # 0.25-second loading timer (15 frames)
        self.unloading_timer = 0 # 1.0-second unloading timer (60 frames)
        self.is_delivering = False
        self.trail = []

    def navigate_to(self, target_node_key):
        current_t = get_terminal_at_pos(self.pos)
        self.current_node = get_closest_node_in_terminal(self.pos, current_t)
       
        path = plan_path(self.current_node, target_node_key)
        if path:
            self.waypoints = path
            self.target_node = target_node_key

    def update(self, active_baggages):
        if self.pickup_timer > 0:
            self.pickup_timer -= 1
            return
        if self.unloading_timer > 0:
            self.unloading_timer -= 1
            return

        # Autonomous AI Logic
        if not self.waypoints:
            if self.is_delivering:
                if not self.cart:
                    self.is_delivering = False
                    self.navigate_to(self.home_node)
                else:
                    self.navigate_to(self.cart[0]["target_node"])
            else:
                home_bags = [b for b in active_baggages if b["spawn_node"] == self.home_node]
               
                if home_bags and len(self.cart) < 16:
                    bag = home_bags[0]
                    self.cart.append(bag)
                    active_baggages.remove(bag)
                    self.pickup_timer = 15  # 0.25-second pickup delay
                   
                    if len(self.cart) >= 16 or not any(b["spawn_node"] == self.home_node for b in active_baggages):
                        self.is_delivering = True
                        self.cart.sort(key=lambda x: int(x["target_node"][1:]))
                        self.navigate_to(self.cart[0]["target_node"])
                elif self.cart:
                    self.is_delivering = True
                    self.cart.sort(key=lambda x: int(x["target_node"][1:]))
                    self.navigate_to(self.cart[0]["target_node"])
                else:
                    if self.current_node != self.home_node:
                        self.navigate_to(self.home_node)

        # Movement physics & Trail generation
        if not self.waypoints:
            return

        target_pos = self.waypoints[0]
        dx = target_pos[0] - self.pos[0]
        dy = target_pos[1] - self.pos[1]
        dist = math.hypot(dx, dy)

        if dist < self.speed:
            self.pos = list(target_pos)
            self.waypoints.pop(0)
            if not self.waypoints:
                self.current_node = self.target_node
        else:
            self.pos[0] += (dx / dist) * self.speed
            self.pos[1] += (dy / dist) * self.speed

        if self.cart:
            has_sorted = any(b["is_sorted"] for b in self.cart)
            trail_col = SORTED_COLOR if has_sorted else UNSORTED_COLOR
            self.trail.append((list(self.pos), trail_col))
            if len(self.trail) > 25:
                self.trail.pop(0)
        else:
            if self.trail:
                self.trail.pop(0)

    def draw(self, surface, is_selected):
        for p, col in self.trail:
            pygame.draw.circle(surface, col, (int(p[0]), int(p[1])), 3)

        if self.waypoints and self.pickup_timer == 0 and self.unloading_timer == 0:
            pygame.draw.line(surface, AGENT_COLOR, self.pos, self.waypoints[0], 1)
       
        if is_selected:
            pygame.draw.circle(surface, HIGHLIGHT_COLOR, (int(self.pos[0]), int(self.pos[1])), 12, 2)
           
        pygame.draw.circle(surface, AGENT_COLOR, (int(self.pos[0]), int(self.pos[1])), 6)

# Instantiate 120 Agents with home node set to their own node (N1 to N120)
agents = [Agent(f"Agent {i}", f"N{i}") for i in range(1, 121)]
selected_agent = agents[0]

packages_delivered = 0
simulation_frames = 0

# Baggage System State (18x spawn rate increase -> interval 10 frames)
active_baggages = []  
spawn_timer = 0
SPAWN_INTERVAL = 10  

# ----------------------------------------------------------------------
# TABS + LANDING TAB
# ----------------------------------------------------------------------
current_tab = "sim"                      # "sim" or "landing"  (F1 / F2 or click the tab buttons)
TAB_SIM = pygame.Rect(900, 8, 150, 30)
TAB_LAND = pygame.Rect(1060, 8, 150, 30)

# Flight data: baggage_zipf.csv (Zipf-shaped flights) if it sits next to this file, else baggage.csv
_here = os.path.dirname(os.path.abspath(__file__))
_zipf_csv = os.path.join(_here, "baggage_zipf.csv")
FLIGHT_CSV = _zipf_csv if os.path.exists(_zipf_csv) else None
CONTENT_RECT = pygame.Rect(0, 60, WIDTH, HEIGHT - 60)

# Background traffic: random 16-bag batches every SPAWN_INTERVAL frames (the busy, cluttered look).
# Press R on the Simulation tab to switch it on/off. False = bags only come from landed planes.
RANDOM_SPAWN = True

# Each gate letter (A-T) is one node: 5 gates per terminal, evenly spaced
LETTERS = list("ABCDEFGHIJKLMNOPQRST")
GATE_NODES = {g: f"N{(i // 5) * NODES_PER_TERMINAL + (i % 5) * 6 + 4}" for i, g in enumerate(LETTERS)}
COMMON_LOAD_NODES = ["N1", "N2", "N3", "N5", "N6"]            # where common carts appear on the map
UNCOMMON_LOAD_NODES = ["N61", "N62", "N63", "N65", "N66"]     # where uncommon carts appear


def handle_cart_depart(info):
    """Called by the Landing tab when a cart leaves: put its bags on the map for the agents."""
    is_common = info["kind"] == "common"
    spawn = random.choice(COMMON_LOAD_NODES if is_common else UNCOMMON_LOAD_NODES)
    for gate in info["bags"]:
        active_baggages.append({
            "spawn_node": spawn,
            "target_node": GATE_NODES[gate],
            "is_sorted": is_common,
            "color": SORTED_COLOR if is_common else UNSORTED_COLOR
        })


landing = LandingTab(CONTENT_RECT, csv_path=FLIGHT_CSV, on_cart_depart=handle_cart_depart)
landing.land_plane()                      # first plane lands at startup

# WARM_START: the first cart normally takes ~30 seconds to fill, which made the Simulation tab look
# frozen. This fast-forwards the first plane until its first cart leaves, so agents move immediately.
WARM_START = True
if WARM_START:
    for _ in range(5000):
        if landing.stats["carts"] > 0:
            break
        landing.update()

# Main Loop
running = True
while running:
    clock.tick(60)
    simulation_frames += 1
   
    # Calculate Time Elapsed: 1 minute every 4 seconds (240 frames)
    total_minutes = simulation_frames // 240
    hours = total_minutes // 60
    minutes = total_minutes % 60
    time_str = f"{hours:02d}:{minutes:02d}"

    mouse_pos = pygame.mouse.get_pos()
   
    # Baggage Batch Spawning Logic (18x faster spawn rate)
    spawn_timer += 1
    if RANDOM_SPAWN and spawn_timer >= SPAWN_INTERVAL:
        spawn_timer = 0
        spawn_node_key = f"N{random.randint(1, 120)}"
        is_sorted_batch = random.random() < 0.5
       
        if is_sorted_batch:
            common_target = f"N{random.randint(1, 120)}"
            while common_target == spawn_node_key:
                common_target = f"N{random.randint(1, 120)}"
               
            for _ in range(16):
                active_baggages.append({
                    "spawn_node": spawn_node_key,
                    "target_node": common_target,
                    "is_sorted": True,
                    "color": SORTED_COLOR
                })
        else:
            for _ in range(16):
                target_node_key = f"N{random.randint(1, 120)}"
                while target_node_key == spawn_node_key:
                    target_node_key = f"N{random.randint(1, 120)}"
               
                active_baggages.append({
                    "spawn_node": spawn_node_key,
                    "target_node": target_node_key,
                    "is_sorted": False,
                    "color": UNSORTED_COLOR
                })

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
           
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
            current_tab = "sim"
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_F2:
            current_tab = "landing"

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if TAB_SIM.collidepoint(event.pos):
                current_tab = "sim"
            elif TAB_LAND.collidepoint(event.pos):
                current_tab = "landing"
            elif current_tab == "sim":
                for ag in agents:
                    if math.hypot(mouse_pos[0] - ag.pos[0], mouse_pos[1] - ag.pos[1]) <= 12:
                        selected_agent = ag
                        break
            else:
                landing.handle_event(event)

        elif event.type == pygame.KEYDOWN and event.key == pygame.K_n and current_tab == "sim":
            landing.land_plane()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_r and current_tab == "sim":
            RANDOM_SPAWN = not RANDOM_SPAWN

        elif current_tab == "landing":
            landing.handle_event(event)

    # --- DROP-OFF CHECK WITH 1-SECOND UNLOADING DELAY ---
    for ag in agents:
        if not ag.waypoints and ag.pickup_timer == 0 and ag.unloading_timer == 0:
            delivered_bags = []
            for bag in ag.cart:
                if ag.current_node == bag["target_node"]:
                    delivered_bags.append(bag)
                    packages_delivered += 1
            if delivered_bags:
                for bag in delivered_bags:
                    ag.cart.remove(bag)
                ag.unloading_timer = 60  # 1-second flat unloading delay (60 frames)

    # Update all 120 autonomous agents
    for ag in agents:
        ag.update(active_baggages)

    landing.update()   # runs even when the Simulation tab is showing

    # --- RENDERING ---
    screen.fill(BG_COLOR)

    # 1. Draw Terminals
    for t_name, rect in terminals.items():
        pygame.draw.rect(screen, TERMINAL_COLORS[t_name], rect, border_radius=8)
        label = title_font.render(f"Terminal {t_name}", True, TEXT_COLOR)
        screen.blit(label, (rect.x + 10, rect.y + 10))

    # 2. Draw Bridges
    for (t1, t2), b_pos in bridges.items():
        pygame.draw.circle(screen, BRIDGE_COLOR, b_pos, 8)
        bridge_lbl = font.render(f"Bridge ({t1}-{t2})", True, BRIDGE_COLOR)
        screen.blit(bridge_lbl, (b_pos[0] - 45, b_pos[1] - 25))

    # 3. Draw Perimeter Nodes & Numbers
    for n_name, data in nodes.items():
        pos = data["pos"]
        n_id = data["id"]
        pygame.draw.circle(screen, NODE_COLOR, pos, 4)
        num_lbl = node_font.render(str(n_id), True, TEXT_COLOR)
        screen.blit(num_lbl, (pos[0] + 5, pos[1] - 4))

    # 4. Group and Draw Uncollected Baggages with Stack Counts & Colors
    node_bag_groups = {}
    for bag in active_baggages:
        s_node = bag["spawn_node"]
        if s_node not in node_bag_groups:
            node_bag_groups[s_node] = {"count": 0, "color": bag["color"]}
        node_bag_groups[s_node]["count"] += 1

    for s_node, info in node_bag_groups.items():
        b_pos = nodes[s_node]["pos"]
        bx, by = b_pos[0], b_pos[1]
        pygame.draw.rect(screen, info["color"], (bx - 8, by - 18, 18, 14), border_radius=3)
        count_lbl = font.render(str(info["count"]), True, (255, 255, 255))
        screen.blit(count_lbl, (bx - 5, by - 33))

    # 5. Draw All 120 Agents & Trails
    for ag in agents:
        ag.draw(screen, is_selected=(ag == selected_agent))

    # 6. UI Header & Scoreboard
    info_txt = font.render(f"Time Elapsed: {time_str} | Inspecting: {selected_agent.name} (Home: {selected_agent.home_node})", True, TEXT_COLOR)
    screen.blit(info_txt, (20, 10))
   
    score_txt = title_font.render(f"Packages Delivered: {packages_delivered}", True, (100, 255, 100))
    screen.blit(score_txt, (20, 30))

    traffic_txt = font.render(f"Background traffic: {'ON' if RANDOM_SPAWN else 'OFF'} (R)  |  N = land plane", True, (150, 150, 150))
    screen.blit(traffic_txt, (560, 10))

    # 7. Draw Cart Inventory Bar at the Bottom for the Inspected Character
    cart_rect = pygame.Rect(60, 638, WIDTH - 120, 48)
    pygame.draw.rect(screen, CART_BG_COLOR, cart_rect, border_radius=6)
    pygame.draw.rect(screen, BRIDGE_COLOR, cart_rect, 2, border_radius=6)
   
    cart_title = font.render(f"{selected_agent.name} Cart ({len(selected_agent.cart)}/16):", True, AGENT_COLOR)
    screen.blit(cart_title, (cart_rect.x + 12, cart_rect.y + 15))
   
    if not selected_agent.cart:
        empty_lbl = font.render("Cart is empty (Home node / waiting)", True, (150, 150, 150))
        screen.blit(empty_lbl, (cart_rect.x + 210, cart_rect.y + 15))
    else:
        bag_str = ", ".join([f"-> {bag['target_node']}" for bag in selected_agent.cart])
        if len(bag_str) > 95:
            bag_str = bag_str[:92] + "..."
        items_lbl = font.render(bag_str, True, UNSORTED_COLOR)
        screen.blit(items_lbl, (cart_rect.x + 210, cart_rect.y + 15))

    # Hint when the map is idle (nothing waiting, nothing in carts)
    if current_tab == "sim" and not active_baggages and not any(ag.cart for ag in agents):
        wait_txt = font.render("Waiting for the next cart from the Landing tab - press N to land a plane, F2 to watch it", True, BRIDGE_COLOR)
        screen.blit(wait_txt, (20, 48))

    # 8. Tabs: the Landing tab is drawn over the simulation area
    if current_tab == "landing":
        pygame.draw.rect(screen, BG_COLOR, CONTENT_RECT)
        landing.draw(screen)

    for rect, label, tab in ((TAB_SIM, "Simulation (F1)", "sim"), (TAB_LAND, "Landing (F2)", "landing")):
        active = (current_tab == tab)
        pygame.draw.rect(screen, (60, 60, 80) if active else CART_BG_COLOR, rect, border_radius=6)
        pygame.draw.rect(screen, BRIDGE_COLOR if active else (90, 90, 100), rect, 2, border_radius=6)
        tab_lbl = font.render(label, True, TEXT_COLOR if active else (150, 150, 150))
        screen.blit(tab_lbl, (rect.centerx - tab_lbl.get_width() // 2, rect.centery - tab_lbl.get_height() // 2))

    pygame.display.flip()

pygame.quit()
sys.exit()