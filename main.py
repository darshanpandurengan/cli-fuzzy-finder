"""
main.py - CLI Fuzzy Finder Desktop GUI & Command-Line Interface
===============================================================
Dual-mode application entry point:
1. Interactive Tkinter Desktop GUI (Zero external dependencies).
   - Developer terminal dark theme.
   - Live per-keystroke fuzzy search.
   - Matched character visual highlighting.
   - Live Algorithmic Telemetry panel (nodes visited, subtrees pruned, latency).
   - Keyboard navigation (Up/Down/Enter/Escape).
   - In-memory search history.
   - Built-in dataset & local directory scanner.
2. CLI Tool (Headless pipe/stdin/argument interface).

Run GUI:
    python main.py
Run CLI:
    python main.py app -k 5
"""

import argparse
import os
import subprocess
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional

from fuzzy_search import DEFAULT_DATASET, FuzzyEngine, Match, Scorer


# =====================================================================
# 1. HEADLESS CLI INTERFACE (For Terminal Pipes & Scripts)
# =====================================================================

def has_stdin_data() -> bool:
    """Non-blocking check to determine if data is actively piped into stdin."""
    if sys.stdin.isatty():
        return False
    try:
        if sys.platform == "win32":
            import ctypes, msvcrt
            handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            avail = ctypes.c_ulong(0)
            res = ctypes.windll.kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(avail), None)
            return bool(res != 0 and avail.value > 0)
        else:
            import select
            return bool(select.select([sys.stdin], [], [], 0)[0])
    except Exception:
        return False


def run_cli(args: argparse.Namespace) -> None:
    """Executes the fuzzy finder in headless terminal CLI mode."""
    engine = FuzzyEngine()

    # Determine input paths
    if args.file:
        if not os.path.exists(args.file):
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f if line.strip()]
        engine.load_dataset(lines, label=f"File: {args.file}")
    elif args.scan:
        count = engine.load_directory(args.scan)
        print(f"Indexed {count} paths from {args.scan}", file=sys.stderr)
    elif has_stdin_data():
        lines = [line.strip() for line in sys.stdin if line.strip()]
        engine.load_dataset(lines, label="Standard Input")
    else:
        engine.load_default_dataset()

    matches, telemetry = engine.search(args.query, k=args.k)

    print(f"\nCLI Fuzzy Finder (Trie + MinHeap)")
    print(f"Query: '{args.query}' | Dataset: {engine.source_label} ({telemetry['total_paths']} paths)")
    print(f"Latency: {telemetry['latency_us']} µs | Pruned: {telemetry['subtrees_pruned']} subtrees\n")
    print("-" * 65)

    if not matches:
        print("No matches found.")
    else:
        for idx, m in enumerate(matches, 1):
            print(f"{idx:2d}. [Score: {m.score:3d}]  {m.path:<38}")

    print("-" * 65 + "\n")


# =====================================================================
# 1b. OPEN / REVEAL HELPERS (cross-platform file explorer integration)
# =====================================================================

def reveal_in_file_explorer(full_path: str) -> None:
    """Opens the OS file explorer with the file selected (folder opened on Linux)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(full_path)}"])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", full_path])
    else:
        # Linux file managers have no universal "select file" flag: open the parent folder
        folder = full_path if os.path.isdir(full_path) else os.path.dirname(full_path)
        subprocess.Popen(["xdg-open", folder])


def open_with_default_app(full_path: str) -> None:
    """Opens the file with the OS default application."""
    if sys.platform == "win32":
        os.startfile(full_path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", full_path])
    else:
        subprocess.Popen(["xdg-open", full_path])


# =====================================================================
# 1c. INTRO SPLASH SCREEN (~3 seconds, click or press any key to skip)
# =====================================================================

def _blend(c1: str, c2: str, t: float) -> str:
    """Linear blend between two #rrggbb colors (t=0 -> c1, t=1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(a, b))


class SplashScreen:
    """
    Borderless animated intro: fades in, types the title, then runs a live
    demo query ('app') through the real Scorer and highlights the matched letters.
    """

    W, H = 560, 316
    TITLE = "CLI FUZZY FINDER"
    TAGLINE = "Search anything. Instantly."
    QUERY = "app"
    DEMO_PATH = "src/App.java"

    def __init__(self, root: tk.Tk, on_done, duration_ms: int = 3200) -> None:
        self.root = root
        self.on_done = on_done
        self.duration = duration_ms
        self.finished = False
        self.result_built = False

        G = FuzzyFinderGUI  # reuse the app's colour palette
        self.G = G

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.configure(bg=G.BG_DARK)
        x = (root.winfo_screenwidth() - self.W) // 2
        y = (root.winfo_screenheight() - self.H) // 2
        self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
        try:
            self.win.attributes("-topmost", True)
            self.win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass  # transparency unsupported: animation still works without fade

        self.canvas = tk.Canvas(
            self.win, width=self.W, height=self.H, bg=G.BG_DARK,
            highlightthickness=2, highlightbackground=G.ACCENT_BLUE,
        )
        self.canvas.pack()
        c = self.canvas

        # Logo + typed title (fixed start x so letters don't jitter while typing)
        c.create_text(self.W // 2, 56, text="⚡", font=("Segoe UI", 30), fill=G.ACCENT_YELLOW)
        self.title_font = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        title_x = (self.W - self.title_font.measure(self.TITLE)) // 2
        self.title_id = c.create_text(title_x, 110, text="", anchor="w", font=self.title_font, fill=G.ACCENT_BLUE)
        self.tag_id = c.create_text(self.W // 2, 148, text=self.TAGLINE, font=("Segoe UI", 10), fill=G.BG_DARK)

        # Mini search bar
        c.create_rectangle(80, 176, 480, 214, fill=G.BG_SURFACE, outline=G.BG_HIGHLIGHT)
        c.create_text(98, 195, text="🔍", font=("Segoe UI", 11), fill=G.ACCENT_BLUE)
        self.query_id = c.create_text(125, 195, text="", anchor="w", font=("Consolas", 13), fill=G.FG_TEXT)

        # Skip hint + progress bar
        c.create_text(self.W // 2, 280, text="click or press any key to skip", font=("Segoe UI", 8), fill=G.FG_DIM)
        c.create_rectangle(80, 296, 480, 300, fill=G.BG_HIGHLIGHT, outline="")
        self.bar_id = c.create_rectangle(80, 296, 80, 300, fill=G.ACCENT_GREEN, outline="")

        self.win.bind("<Button-1>", lambda _: self._finish())
        self.win.bind("<Key>", lambda _: self._finish())
        self.win.focus_force()

        self.t0 = time.perf_counter()
        self._tick()

    def _build_result(self) -> None:
        """Draws the demo result using the real Scorer, with matched letters highlighted."""
        G, c = self.G, self.canvas
        score, positions = Scorer.score(self.DEMO_PATH, self.QUERY)
        normal = tkfont.Font(family="Consolas", size=12)
        bold = tkfont.Font(family="Consolas", size=12, weight="bold")
        x, y = 100, 244
        c.create_text(84, y, text="▶", anchor="w", font=("Consolas", 11), fill=G.ACCENT_PEACH)
        for i, ch in enumerate(self.DEMO_PATH):
            hit = i in positions
            f = bold if hit else normal
            c.create_text(x, y, text=ch, anchor="w", font=f, fill=G.ACCENT_GREEN if hit else G.FG_TEXT)
            x += f.measure(ch)
        c.create_text(476, y, text=str(score), anchor="e", font=("Consolas", 11, "bold"), fill=G.ACCENT_YELLOW)
        self.result_built = True

    def _tick(self) -> None:
        if self.finished:
            return
        G, c = self.G, self.canvas
        t = (time.perf_counter() - self.t0) * 1000
        d = self.duration

        if t >= d:
            self._finish()
            return

        # Fade in / out
        alpha = min(1.0, t / 300) if t < d - 300 else max(0.0, (d - t) / 300)
        try:
            self.win.attributes("-alpha", alpha)
        except tk.TclError:
            pass

        # Title typing
        n = max(0, min(len(self.TITLE), int((t - 250) / 55)))
        c.itemconfigure(self.title_id, text=self.TITLE[:n])

        # Tagline fade-in
        k = max(0.0, min(1.0, (t - 1000) / 400))
        c.itemconfigure(self.tag_id, fill=_blend(G.BG_DARK, G.FG_DIM, k))

        # Demo query typing with blinking cursor
        typed = 0 if t < 1500 else min(len(self.QUERY), int((t - 1500) / 180) + 1)
        cursor = "▌" if int(t / 400) % 2 == 0 and t >= 1400 else ""
        c.itemconfigure(self.query_id, text=self.QUERY[:typed] + cursor)

        if t >= 2200 and not self.result_built:
            self._build_result()

        # Progress bar
        c.coords(self.bar_id, 80, 296, 80 + 400 * min(1.0, t / d), 300)

        self.win.after(16, self._tick)

    def _finish(self) -> None:
        if self.finished:
            return
        self.finished = True
        self.win.destroy()
        self.on_done()


# =====================================================================
# 2. TKINTER DESKTOP APPLICATION (Developer Terminal Dark Aesthetic)
# =====================================================================

class FuzzyFinderGUI:
    """
    Tkinter/ttk desktop GUI providing a terminal-inspired fuzzy search experience.
    """

    # Modern Catppuccin Mocha Dark Palette
    BG_DARK = "#181825"
    BG_SURFACE = "#1e1e2e"
    BG_CARD = "#24273a"
    BG_HIGHLIGHT = "#313244"
    FG_TEXT = "#cdd6f4"
    FG_DIM = "#9399b2"
    ACCENT_GREEN = "#a6e3a1"
    ACCENT_BLUE = "#89b4fa"
    ACCENT_YELLOW = "#f9e2af"
    ACCENT_PEACH = "#fab387"
    ACCENT_RED = "#f38ba8"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CLI Fuzzy Finder — Trie & MinHeap Subsequence Engine")
        self.root.geometry("1060x720")
        self.root.minsize(880, 580)
        self.root.configure(bg=self.BG_DARK)

        # Search Engine Instance
        self.engine = FuzzyEngine()
        self.engine.load_default_dataset()

        # In-memory search history & navigation state
        self.history: List[str] = []
        self.history_index: int = -1
        self.current_matches: List[Match] = []
        self.selected_result_idx: int = 0
        self.last_telemetry: dict = {}
        self.show_telemetry_var = tk.BooleanVar(value=False)
        self._telemetry_visible: bool = False  # tracks real pane state

        self._configure_styles()
        self._build_ui()
        self._bind_shortcuts()

        # Initial trigger to show sample dataset
        self.search_entry.focus_set()
        self.on_query_change()

    def _configure_styles(self) -> None:
        """Applies dark theme styling to standard ttk widgets."""
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=self.BG_DARK, foreground=self.FG_TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=self.BG_DARK)
        style.configure("Card.TFrame", background=self.BG_CARD, relief="flat")
        style.configure("TLabel", background=self.BG_DARK, foreground=self.FG_TEXT)
        style.configure("Card.TLabel", background=self.BG_CARD, foreground=self.FG_TEXT)
        style.configure("Header.TLabel", background=self.BG_DARK, foreground=self.ACCENT_BLUE, font=("Segoe UI", 12, "bold"))
        style.configure("TelemetryVal.TLabel", background=self.BG_CARD, foreground=self.ACCENT_GREEN, font=("Consolas", 11, "bold"))
        style.configure("TelemetryKey.TLabel", background=self.BG_CARD, foreground=self.FG_DIM, font=("Segoe UI", 9))

        style.configure(
            "TButton",
            background=self.BG_HIGHLIGHT,
            foreground=self.FG_TEXT,
            borderwidth=0,
            focusthickness=0,
            padding=5,
            font=("Segoe UI", 9, "bold"),
        )
        style.map("TButton", background=[("active", self.ACCENT_BLUE)], foreground=[("active", self.BG_DARK)])

        style.configure(
            "TCombobox",
            fieldbackground=self.BG_SURFACE,
            background=self.BG_HIGHLIGHT,
            foreground=self.FG_TEXT,
            bordercolor=self.BG_HIGHLIGHT,
            arrowcolor=self.ACCENT_BLUE,
        )

    def _build_ui(self) -> None:
        """Constructs the comprehensive terminal-inspired GUI layout."""
        self._build_menubar()

        # Top Container: Header, Search Bar, Dataset Controls
        top_container = tk.Frame(self.root, bg=self.BG_DARK, padx=16, pady=12)
        top_container.pack(fill=tk.X)

        # Header Title Banner
        banner_frame = tk.Frame(top_container, bg=self.BG_DARK)
        banner_frame.pack(fill=tk.X, pady=(0, 10))

        title_lbl = tk.Label(
            banner_frame,
            text="⚡ CLI FUZZY FINDER",
            font=("Segoe UI", 14, "bold"),
            fg=self.ACCENT_BLUE,
            bg=self.BG_DARK,
        )
        title_lbl.pack(side=tk.LEFT)

        subtitle_lbl = tk.Label(
            banner_frame,
            text="— Subtree Character Bitmask Trie & Array-Based MinHeap Engine",
            font=("Segoe UI", 10),
            fg=self.FG_DIM,
            bg=self.BG_DARK,
        )
        subtitle_lbl.pack(side=tk.LEFT, padx=10, pady=(3, 0))

        # Dataset Source Bar
        src_bar = tk.Frame(top_container, bg=self.BG_DARK)
        src_bar.pack(fill=tk.X, pady=(0, 8))

        self.source_var = tk.StringVar(value="builtin")
        demo_radio = tk.Radiobutton(
            src_bar,
            text="Built-in Developer Dataset (50 Paths)",
            variable=self.source_var,
            value="builtin",
            command=self._on_source_switch,
            bg=self.BG_DARK,
            fg=self.FG_TEXT,
            selectcolor=self.BG_SURFACE,
            activebackground=self.BG_DARK,
            activeforeground=self.ACCENT_GREEN,
            font=("Segoe UI", 9),
        )
        demo_radio.pack(side=tk.LEFT)

        folder_radio = tk.Radiobutton(
            src_bar,
            text="Scan Local Folder...",
            variable=self.source_var,
            value="folder",
            command=self._browse_directory,
            bg=self.BG_DARK,
            fg=self.FG_TEXT,
            selectcolor=self.BG_SURFACE,
            activebackground=self.BG_DARK,
            activeforeground=self.ACCENT_GREEN,
            font=("Segoe UI", 9),
        )
        folder_radio.pack(side=tk.LEFT, padx=16)

        self.dataset_info_lbl = tk.Label(
            src_bar,
            text=f"Active Source: {self.engine.source_label} ({self.engine.trie.size} paths)",
            font=("Segoe UI", 9, "italic"),
            fg=self.ACCENT_YELLOW,
            bg=self.BG_DARK,
        )
        self.dataset_info_lbl.pack(side=tk.RIGHT)

        # Search Bar + Top-K Selector Frame
        search_frame = tk.Frame(top_container, bg=self.BG_SURFACE, padx=10, pady=8, highlightbackground=self.BG_HIGHLIGHT, highlightthickness=1)
        search_frame.pack(fill=tk.X)

        search_icon = tk.Label(search_frame, text="🔍", font=("Segoe UI", 12), bg=self.BG_SURFACE, fg=self.ACCENT_BLUE)
        search_icon.pack(side=tk.LEFT, padx=(4, 8))

        self.query_var = tk.StringVar()
        self.query_var.trace_add("write", lambda *_: self.on_query_change())

        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.query_var,
            font=("Consolas", 13),
            bg=self.BG_SURFACE,
            fg=self.FG_TEXT,
            insertbackground=self.ACCENT_GREEN,
            relief="flat",
            borderwidth=0,
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        clear_btn = tk.Button(
            search_frame,
            text="✕",
            command=self._clear_search,
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_SURFACE,
            fg=self.FG_DIM,
            activebackground=self.BG_SURFACE,
            activeforeground=self.ACCENT_RED,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
        )
        clear_btn.pack(side=tk.LEFT, padx=6)

        k_label = tk.Label(search_frame, text="Top-K:", bg=self.BG_SURFACE, fg=self.FG_DIM, font=("Segoe UI", 9, "bold"))
        k_label.pack(side=tk.LEFT, padx=(12, 4))

        self.k_var = tk.IntVar(value=10)
        self.k_combo = ttk.Combobox(search_frame, textvariable=self.k_var, values=[5, 10, 20, 50], width=4, state="readonly")
        self.k_combo.pack(side=tk.LEFT, padx=(0, 4))
        self.k_combo.bind("<<ComboboxSelected>>", lambda _: self.on_query_change())

        # Main Body: Split Panes (Left: Results, Right: Telemetry & Explanations)
        self.body_paned = body_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=self.BG_DARK, bd=0, sashwidth=4, sashrelief="flat")
        body_paned.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        # =============================================================
        # Left Panel: Results & Match Highlighting View
        # =============================================================
        left_frame = tk.Frame(body_paned, bg=self.BG_SURFACE, padx=12, pady=10)
        body_paned.add(left_frame, minsize=480, stretch="always")

        # Status text above results
        self.status_lbl = tk.Label(
            left_frame,
            text="Ready. Enter a search query to test fuzzy matching.",
            font=("Consolas", 10),
            fg=self.ACCENT_GREEN,
            bg=self.BG_SURFACE,
            anchor="w",
        )
        self.status_lbl.pack(fill=tk.X, pady=(0, 6))

        # Text Widget for Terminal-style Results with Rich Highlighting
        res_container = tk.Frame(left_frame, bg=self.BG_SURFACE)
        res_container.pack(fill=tk.BOTH, expand=True)

        self.results_text = tk.Text(
            res_container,
            bg=self.BG_DARK,
            fg=self.FG_TEXT,
            font=("Consolas", 11),
            relief="flat",
            wrap="none",
            cursor="arrow",
            padx=10,
            pady=8,
        )
        scrollbar_y = ttk.Scrollbar(res_container, orient=tk.VERTICAL, command=self.results_text.yview)
        scrollbar_x = ttk.Scrollbar(res_container, orient=tk.HORIZONTAL, command=self.results_text.xview)
        self.results_text.configure(xscrollcommand=scrollbar_x.set, yscrollcommand=scrollbar_y.set)

        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)
        scrollbar_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Configure Highlighting Tags
        self.results_text.tag_configure("rank", foreground=self.ACCENT_PEACH, font=("Consolas", 11, "bold"))
        self.results_text.tag_configure("score", foreground=self.ACCENT_YELLOW, font=("Consolas", 10, "bold"))
        self.results_text.tag_configure("normal", foreground=self.FG_TEXT, font=("Consolas", 11))
        self.results_text.tag_configure("match_char", foreground=self.ACCENT_GREEN, font=("Consolas", 11, "bold"), background=self.BG_HIGHLIGHT)
        self.results_text.tag_configure("dim", foreground=self.FG_DIM, font=("Consolas", 10))
        self.results_text.tag_configure("selected", background=self.BG_CARD)
        self.results_text.tag_configure("header", foreground=self.ACCENT_BLUE, font=("Consolas", 11, "bold"))
        self.results_text.configure(state="disabled")

        # Mouse interaction: click selects, double-click opens, right-click shows menu
        self.context_menu = tk.Menu(
            self.root, tearoff=0, bg=self.BG_CARD, fg=self.FG_TEXT,
            activebackground=self.ACCENT_BLUE, activeforeground=self.BG_DARK,
        )
        self.context_menu.add_command(label="📂  Show in File Explorer   (Ctrl+E)", command=self._reveal_selected)
        self.context_menu.add_command(label="📄  Open File   (Ctrl+Enter)", command=self._open_selected)
        self.context_menu.add_command(label="📋  Copy Path   (Enter)", command=self._copy_selected)
        self.results_text.bind("<Button-1>", self._on_result_click)
        self.results_text.bind("<Double-Button-1>", self._on_result_double_click)
        self.results_text.bind("<Button-3>", self._on_result_right_click)
        self.results_text.bind("<Button-2>", self._on_result_right_click)  # macOS right-click

        # =============================================================
        # Right Panel: Live Algorithmic Telemetry & Viva Guide
        # =============================================================
        # Panel is created here but only shown when toggled from View > Algorithmic Telemetry
        self.right_frame = right_frame = tk.Frame(body_paned, bg=self.BG_CARD, padx=14, pady=12)

        telemetry_header = tk.Frame(right_frame, bg=self.BG_CARD)
        telemetry_header.pack(fill=tk.X, pady=(0, 8))

        telemetry_title = tk.Label(
            telemetry_header,
            text="📊 ALGORITHMIC TELEMETRY",
            font=("Segoe UI", 11, "bold"),
            fg=self.ACCENT_BLUE,
            bg=self.BG_CARD,
        )
        telemetry_title.pack(side=tk.LEFT)

        telemetry_close_btn = tk.Button(
            telemetry_header,
            text="✕",
            command=self._close_telemetry,
            font=("Segoe UI", 10, "bold"),
            bg=self.BG_CARD,
            fg=self.FG_DIM,
            activebackground=self.BG_CARD,
            activeforeground=self.ACCENT_RED,
            relief="flat",
            borderwidth=0,
            cursor="hand2",
        )
        telemetry_close_btn.pack(side=tk.RIGHT)

        # Metrics Grid
        metrics_frame = tk.Frame(right_frame, bg=self.BG_CARD)
        metrics_frame.pack(fill=tk.X, pady=(0, 10))

        self.telemetry_labels: dict[str, tk.Label] = {}
        metric_items = [
            ("Stored Paths:", "total_paths", "0"),
            ("Total Trie Nodes:", "total_nodes", "0"),
            ("Nodes Visited (DFS):", "nodes_visited", "0"),
            ("Subtrees Pruned (Mask):", "subtrees_pruned", "0"),
            ("Pruning Efficiency:", "pruning_ratio", "0.0%"),
            ("Candidates Evaluated:", "candidates_found", "0"),
            ("MinHeap Top-K Evictions:", "heap_evictions", "0"),
            ("Search Latency:", "latency_us", "0.0 µs"),
        ]

        for r, (label_text, key, initial_val) in enumerate(metric_items):
            lbl_k = tk.Label(metrics_frame, text=label_text, font=("Segoe UI", 9), fg=self.FG_DIM, bg=self.BG_CARD)
            lbl_k.grid(row=r, column=0, sticky="w", pady=2)
            lbl_v = tk.Label(metrics_frame, text=initial_val, font=("Consolas", 10, "bold"), fg=self.ACCENT_GREEN, bg=self.BG_CARD)
            lbl_v.grid(row=r, column=1, sticky="e", pady=2, padx=(12, 0))
            metrics_frame.grid_columnconfigure(0, weight=1)
            self.telemetry_labels[key] = lbl_v

        # Viva / DSA Explanation Card
        dsa_info_frame = tk.Frame(right_frame, bg=self.BG_SURFACE, padx=10, pady=8, highlightbackground=self.BG_HIGHLIGHT, highlightthickness=1)
        dsa_info_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 8))

        dsa_title = tk.Label(
            dsa_info_frame,
            text="🔬 DATA STRUCTURE IN ACTION",
            font=("Segoe UI", 10, "bold"),
            fg=self.ACCENT_PEACH,
            bg=self.BG_SURFACE,
        )
        dsa_title.pack(anchor="w", pady=(0, 4))

        self.dsa_explanation = tk.Text(
            dsa_info_frame,
            bg=self.BG_SURFACE,
            fg=self.FG_TEXT,
            font=("Segoe UI", 9),
            relief="flat",
            wrap="word",
            height=10,
        )
        self.dsa_explanation.pack(fill=tk.BOTH, expand=True)
        self._update_dsa_explanation("Type a query to see subtree bitmask pruning in action.")

        # Bottom Bar: Keyboard Shortcuts Legend
        bottom_bar = tk.Frame(self.root, bg=self.BG_DARK, padx=16, pady=6)
        bottom_bar.pack(fill=tk.X)

        legend_text = ("[↑/↓] Navigate  |  [Enter] Copy Path  |  [Ctrl+E] Show in Explorer  |  "
                       "[Ctrl+Enter / Double-click] Open File  |  [Right-click] Menu  |  [Esc] Clear  |  [Ctrl+O] Folder  |  [Ctrl+T] Telemetry")
        legend_lbl = tk.Label(bottom_bar, text=legend_text, font=("Segoe UI", 9), fg=self.FG_DIM, bg=self.BG_DARK)
        legend_lbl.pack(side=tk.LEFT)

    def _build_menubar(self) -> None:
        """Top menu bar with a View menu to show/hide the telemetry panel."""
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Choose Folder...", accelerator="Ctrl+O", command=self._browse_directory)
        file_menu.add_command(label="Use Built-in Dataset", command=self._use_builtin)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_checkbutton(
            label="Algorithmic Telemetry",
            accelerator="Ctrl+T",
            variable=self.show_telemetry_var,
            command=self._apply_telemetry_visibility,
        )
        menubar.add_cascade(label="View", menu=view_menu)

        self.root.config(menu=menubar)

    def _apply_telemetry_visibility(self) -> None:
        """Shows or hides the right-hand telemetry panel to match the menu checkbox."""
        want_visible = bool(self.show_telemetry_var.get())
        if want_visible and not self._telemetry_visible:
            self.body_paned.add(self.right_frame, minsize=320, stretch="never")
            self._telemetry_visible = True
        elif not want_visible and self._telemetry_visible:
            self.body_paned.forget(self.right_frame)
            self._telemetry_visible = False

    def _close_telemetry(self) -> None:
        """Hides the telemetry panel (✕ button in its header)."""
        self.show_telemetry_var.set(False)
        self._apply_telemetry_visibility()

    def _toggle_telemetry_shortcut(self) -> None:
        self.show_telemetry_var.set(not self.show_telemetry_var.get())
        self._apply_telemetry_visibility()

    def _use_builtin(self) -> None:
        self.source_var.set("builtin")
        self._on_source_switch()

    def _bind_shortcuts(self) -> None:
        """Configures keyboard shortcuts."""
        self.root.bind("<Down>", self._on_arrow_down)
        self.root.bind("<Up>", self._on_arrow_up)
        self.root.bind("<Return>", self._on_enter_pressed)
        self.root.bind("<Escape>", lambda _: self._clear_search())
        self.root.bind("<Control-o>", lambda _: self._browse_directory())
        self.root.bind("<Control-e>", lambda _: self._reveal_selected())
        self.root.bind("<Control-t>", lambda _: self._toggle_telemetry_shortcut())
        self.root.bind("<Control-Return>", lambda _: self._open_selected())

    # =============================================================
    # Real-Time Search & Event Handling
    # =============================================================

    def on_query_change(self) -> None:
        """Executes the search algorithm on every keystroke."""
        query = self.query_var.get().strip()
        k = self.k_var.get()

        matches, telemetry = self.engine.search(query, k=k)
        self.current_matches = matches
        self.last_telemetry = telemetry
        self.selected_result_idx = 0

        # Update telemetry labels
        self.telemetry_labels["total_paths"].configure(text=str(telemetry["total_paths"]))
        self.telemetry_labels["total_nodes"].configure(text=str(telemetry["total_nodes"]))
        self.telemetry_labels["nodes_visited"].configure(text=str(telemetry["nodes_visited"]))
        self.telemetry_labels["subtrees_pruned"].configure(text=str(telemetry["subtrees_pruned"]))
        self.telemetry_labels["pruning_ratio"].configure(text=f"{telemetry['pruning_ratio']}%")
        self.telemetry_labels["candidates_found"].configure(text=str(telemetry["candidates_found"]))
        self.telemetry_labels["heap_evictions"].configure(text=str(telemetry["heap_evictions"]))
        self.telemetry_labels["latency_us"].configure(text=f"{telemetry['latency_us']} µs")

        # Render results with character highlights
        self._render_results(query, matches, telemetry)

    def _render_results(self, query: str, matches: List[Match], telemetry: dict) -> None:
        """Renders ranked candidates with visual character highlighting in Text widget."""
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", tk.END)

        if not query:
            self.status_lbl.configure(text=f"Loaded {self.engine.trie.size} paths. Type to begin fuzzy search...")
            self.results_text.insert(tk.END, "Sample Available Paths in Search Index:\n\n", "header")
            for i, p in enumerate(list(self.engine.trie.traverse())[:15], 1):
                self.results_text.insert(tk.END, f"  {i:2d}. {p}\n", "dim")
            if self.engine.trie.size > 15:
                self.results_text.insert(tk.END, f"\n  ... and {self.engine.trie.size - 15} more paths.", "dim")
            self._update_dsa_explanation(
                "Trie initialized with 64-bit character masks.\n\n"
                f"• Stored Paths: {self.engine.trie.size}\n"
                f"• Allocated Nodes: {self.engine.trie.total_nodes}\n\n"
                "Type query 'app' or 'src' to observe bitmask pruning in action."
            )
            self.results_text.configure(state="disabled")
            return

        if not matches:
            self.status_lbl.configure(
                text=f"0 matches found in {telemetry['latency_us']} µs | {telemetry['subtrees_pruned']} subtrees pruned"
            )
            self.results_text.insert(tk.END, f"No matches found for '{query}'.\n\n", "header")
            self.results_text.insert(
                tk.END,
                "The 64-bit subtree character mask pruned all non-matching branches\n"
                "in O(1) time without visiting unnecessary descendant nodes.\n",
                "dim",
            )
            self._update_dsa_explanation(
                f"Query '{query}' pruned {telemetry['subtrees_pruned']} subtrees.\n\n"
                "Pruning condition:\n"
                "(node.mask & rem_mask) != rem_mask\n\n"
                "Because required characters were absent in candidate branches, "
                "the Trie immediately skipped those subtrees in O(1)."
            )
            self.results_text.configure(state="disabled")
            return

        self.status_lbl.configure(
            text=f"Found {len(matches)} matches in {telemetry['latency_us']} µs (from {telemetry['candidates_found']} candidates)"
        )

        # Print each ranked match with highlighted indices
        for rank, m in enumerate(matches, 1):
            is_selected = (rank - 1 == self.selected_result_idx)
            prefix = "▶ " if is_selected else "  "

            self.results_text.insert(tk.END, f"{prefix}{rank:2d}. ", "rank")
            self.results_text.insert(tk.END, f"[Score: {m.score:3d}]  ", "score")

            # Print path with character-by-character highlighting
            pos_set = set(m.positions)
            for idx, ch in enumerate(m.path):
                if idx in pos_set:
                    self.results_text.insert(tk.END, ch, "match_char")
                else:
                    self.results_text.insert(tk.END, ch, "normal")

            self.results_text.insert(tk.END, f"  (len: {len(m.path)})\n", "dim")

        self.results_text.configure(state="disabled")
        self.results_text.see(f"{self.selected_result_idx + 1}.0")

        # Update viva explanation
        best_match = matches[0]
        self._update_dsa_explanation(
            f"Top Match: '{best_match.path}' (Score: {best_match.score}/100)\n\n"
            f"1. Trie Bitmask Pruning:\n"
            f"   • Pruned {telemetry['subtrees_pruned']} subtrees without traversal.\n"
            f"   • Pruning Efficiency: {telemetry['pruning_ratio']}%\n\n"
            f"2. MinHeap Top-K Filter:\n"
            f"   • Evicted {telemetry['heap_evictions']} lower-scoring candidates.\n"
            f"   • Complexity: O(C log K) instead of O(C log C) full sort."
        )

    def _update_dsa_explanation(self, text: str) -> None:
        """Updates the text content in the viva explanation panel."""
        self.dsa_explanation.configure(state="normal")
        self.dsa_explanation.delete("1.0", tk.END)
        self.dsa_explanation.insert(tk.END, text)
        self.dsa_explanation.configure(state="disabled")

    # =============================================================
    # Dataset Loading and Controls
    # =============================================================

    def _on_source_switch(self) -> None:
        """Switches back to the built-in dataset."""
        self.engine.load_default_dataset()
        self.dataset_info_lbl.configure(text=f"Active Source: {self.engine.source_label} ({self.engine.trie.size} paths)")
        self.on_query_change()

    def _browse_directory(self) -> None:
        """Prompts user to select a folder for dynamic indexing."""
        folder = filedialog.askdirectory(title="Select Project Directory to Index")
        if not folder:
            # Cancelled: keep radio button in sync with the dataset actually loaded
            self.source_var.set("folder" if self.engine.root_dir else "builtin")
            return
        if folder:
            try:
                count = self.engine.load_directory(folder)
                self.source_var.set("folder")
                self.dataset_info_lbl.configure(text=f"Active Source: {self.engine.source_label} ({count} paths)")
                self.on_query_change()
                messagebox.showinfo("Directory Indexed", f"Successfully indexed {count} file paths from:\n{folder}")
            except Exception as e:
                self.source_var.set("folder" if self.engine.root_dir else "builtin")
                messagebox.showerror("Error", f"Failed to index directory:\n{e}")

    def _clear_search(self) -> None:
        """Clears the query box."""
        self.query_var.set("")
        self.search_entry.focus_set()

    # =============================================================
    # Keyboard Navigation
    # =============================================================

    def _on_arrow_down(self, event: Optional[tk.Event] = None) -> None:
        """Navigates down in the search results."""
        if self.current_matches and self.selected_result_idx < len(self.current_matches) - 1:
            self.selected_result_idx += 1
            query = self.query_var.get().strip()
            _, telemetry = self.engine.search(query, k=self.k_var.get())
            self._render_results(query, self.current_matches, telemetry)

    def _on_arrow_up(self, event: Optional[tk.Event] = None) -> None:
        """Navigates up in the search results."""
        if self.current_matches and self.selected_result_idx > 0:
            self.selected_result_idx -= 1
            query = self.query_var.get().strip()
            _, telemetry = self.engine.search(query, k=self.k_var.get())
            self._render_results(query, self.current_matches, telemetry)

    def _on_enter_pressed(self, event: Optional[tk.Event] = None) -> None:
        """Copies selected path to clipboard and logs query to history."""
        q = self.query_var.get().strip()
        if q and (not self.history or self.history[-1] != q):
            self.history.append(q)

        if self.current_matches and 0 <= self.selected_result_idx < len(self.current_matches):
            selected_path = self.current_matches[self.selected_result_idx].path
            self.root.clipboard_clear()
            self.root.clipboard_append(selected_path)
            self.status_lbl.configure(text=f"Copied to clipboard: '{selected_path}'")

    # =============================================================
    # Open / Reveal Selected Result
    # =============================================================

    def _selected_match(self) -> Optional[Match]:
        if self.current_matches and 0 <= self.selected_result_idx < len(self.current_matches):
            return self.current_matches[self.selected_result_idx]
        return None

    def _resolve_selected(self) -> Optional[str]:
        """Returns the real on-disk path of the selected result, or reports why it can't."""
        m = self._selected_match()
        if m is None:
            self.status_lbl.configure(text="No result selected.")
            return None
        full = self.engine.resolve_path(m.path)
        if full is None:
            self.status_lbl.configure(
                text="Can't open: this path isn't a real file. Use 'Scan Local Directory' to index a real folder."
            )
        return full

    def _reveal_selected(self) -> None:
        full = self._resolve_selected()
        if full:
            try:
                reveal_in_file_explorer(full)
                self.status_lbl.configure(text=f"Revealed in file explorer: '{full}'")
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file explorer:\n{e}")

    def _open_selected(self) -> None:
        full = self._resolve_selected()
        if full:
            try:
                open_with_default_app(full)
                self.status_lbl.configure(text=f"Opened: '{full}'")
            except Exception as e:
                messagebox.showerror("Error", f"Could not open file:\n{e}")

    def _copy_selected(self) -> None:
        self._on_enter_pressed()

    def _select_from_event(self, event: tk.Event) -> bool:
        """Maps a mouse click to a result row (each result occupies one line)."""
        if not self.current_matches:
            return False
        line = int(self.results_text.index(f"@{event.x},{event.y}").split(".")[0])
        idx = line - 1
        if not (0 <= idx < len(self.current_matches)):
            return False
        if idx != self.selected_result_idx:
            self.selected_result_idx = idx
            self._render_results(self.query_var.get().strip(), self.current_matches, self.last_telemetry)
        return True

    def _on_result_click(self, event: tk.Event) -> str:
        self._select_from_event(event)
        return "break"

    def _on_result_double_click(self, event: tk.Event) -> str:
        if self._select_from_event(event):
            self._open_selected()
        return "break"

    def _on_result_right_click(self, event: tk.Event) -> str:
        if self._select_from_event(event):
            self.context_menu.tk_popup(event.x_root, event.y_root)
        return "break"


# =====================================================================
# 3. ENTRY POINT ROUTING
# =====================================================================

def main() -> None:
    """Parses arguments to route between CLI mode and Desktop GUI mode."""
    parser = argparse.ArgumentParser(description="CLI Fuzzy Finder (Trie + MinHeap)", add_help=False)
    parser.add_argument("query", nargs="?", default=None, help="Search query string")
    parser.add_argument("-k", type=int, default=10, help="Maximum number of results to display")
    parser.add_argument("-f", "--file", help="Path to text file containing paths (one per line)")
    parser.add_argument("--scan", help="Local directory path to scan and index")
    parser.add_argument("--no-splash", action="store_true", help="Skip the intro animation in GUI mode")
    parser.add_argument("-h", "--help", action="store_true", help="Show help message and exit")

    args, _ = parser.parse_known_args()

    # If help requested or CLI query provided, execute CLI mode
    if args.help:
        parser.print_help()
        sys.exit(0)

    if args.query is not None or has_stdin_data():
        if args.query is None:
            args.query = ""
        run_cli(args)
    else:
        # Launch Desktop Tkinter GUI
        root = tk.Tk()
        if args.no_splash:
            app = FuzzyFinderGUI(root)
        else:
            root.withdraw()  # build the UI hidden, reveal it when the intro ends
            app = FuzzyFinderGUI(root)

            def show_main() -> None:
                root.deiconify()
                app.search_entry.focus_force()

            SplashScreen(root, show_main)
        root.mainloop()


if __name__ == "__main__":
    main()
