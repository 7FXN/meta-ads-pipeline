"""
Meta Ads Intelligence Pipeline — GUI
"""

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
_running = False


def ts():
    return datetime.now().strftime("%H:%M:%S")


def run_command(label, args, log, all_buttons):
    global _running
    if _running:
        return

    def set_buttons(state):
        for b in all_buttons:
            b.config(state=state)

    def target():
        global _running
        _running = True
        set_buttons("disabled")

        log.config(state="normal")
        log.insert(tk.END, f"\n[{ts()}] ▶ {label}\n", "header")
        log.insert(tk.END, f"$ python3 {' '.join(args)}\n", "cmd")
        log.insert(tk.END, "─" * 60 + "\n", "sep")
        log.see(tk.END)

        try:
            proc = subprocess.Popen(
                [sys.executable] + [str(SCRIPT_DIR / args[0])] + args[1:],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                tag = "error" if any(w in line.lower() for w in ["error", "traceback", "failed", "✗"]) \
                      else "success" if any(w in line.lower() for w in ["✓", "uploaded", "created", "done"]) \
                      else "normal"
                log.insert(tk.END, line, tag)
                log.see(tk.END)
                log.update_idletasks()
            proc.wait()
            result = f"[{ts()}] ✓ Finished\n" if proc.returncode == 0 else f"[{ts()}] ✗ Exit code {proc.returncode}\n"
            tag = "success" if proc.returncode == 0 else "error"
            log.insert(tk.END, "─" * 60 + "\n", "sep")
            log.insert(tk.END, result, tag)
        except Exception as e:
            log.insert(tk.END, f"[{ts()}] Error: {e}\n", "error")

        log.config(state="disabled")
        log.see(tk.END)
        _running = False
        log.after(0, lambda: set_buttons("normal"))

    threading.Thread(target=target, daemon=True).start()


def build_gui():
    root = tk.Tk()
    root.title("Meta Ads Intelligence Pipeline")
    root.geometry("860x720")
    root.configure(bg="#2b2b2b")

    all_buttons = []

    # ── Scraper settings ─────────────────────────────────────────────────────
    frm_top = tk.Frame(root, bg="#2b2b2b")
    frm_top.pack(fill="x", padx=12, pady=(10, 4))

    frm_left = tk.LabelFrame(frm_top, text=" Scraper Settings ", bg="#3c3f41",
                              fg="#bbbbbb", padx=10, pady=8)
    frm_left.pack(side="left", fill="both", expand=True)

    def lbl(parent, text):
        return tk.Label(parent, text=text, bg="#3c3f41", fg="#bbbbbb", anchor="w", width=13)

    def entry(parent, default, width=18):
        e = tk.Entry(parent, width=width, bg="#45494a", fg="#ffffff",
                     insertbackground="white", relief="flat", bd=4)
        e.insert(0, default)
        return e

    def combo(parent, values, default):
        c = ttk.Combobox(parent, values=values, state="readonly", width=16)
        c.set(default)
        return c

    style = ttk.Style()
    style.configure("Dark.TCombobox", fieldbackground="#45494a", background="#45494a", foreground="#ffffff")

    rows = [
        ("App / Keyword", entry(frm_left, "Duolingo")),
        ("Country",       entry(frm_left, "US", 8)),
        ("Limit",         entry(frm_left, "5", 8)),
        ("Rank By",       combo(frm_left, ["combined","age","order","impressions","copies"], "combined")),
        ("Filter",        combo(frm_left, ["static","video","combined"], "static")),
        ("Search By",     combo(frm_left, ["page","keyword"], "page")),
    ]
    for i, (lbl_text, widget) in enumerate(rows):
        lbl(frm_left, lbl_text).grid(row=i, column=0, sticky="w", pady=3)
        widget.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=3)
    frm_left.columnconfigure(1, weight=1)

    entry_app, entry_country, entry_limit, combo_rank, combo_filter, combo_search = \
        [w for _, w in rows]

    # ── Button panel ─────────────────────────────────────────────────────────
    frm_right = tk.LabelFrame(frm_top, text=" Commands ", bg="#3c3f41",
                               fg="#bbbbbb", padx=10, pady=8)
    frm_right.pack(side="left", fill="y", padx=(8, 0))

    def btn(parent, text, color, cmd):
        b = tk.Button(parent, text=text, bg=color, fg="white", relief="flat",
                      activebackground=color, activeforeground="white",
                      padx=8, pady=6, width=24, anchor="w", command=cmd)
        b.pack(fill="x", pady=3)
        all_buttons.append(b)
        return b

    # will be defined after log widget
    def get_scrape_args():
        apps = [a.strip() for a in entry_app.get().split(",") if a.strip()]
        return ["meta_ads_scraper.py",
                "--country",   entry_country.get().strip() or "US",
                "--limit",     entry_limit.get().strip() or "5",
                "--rank-by",   combo_rank.get(),
                "--filter",    combo_filter.get(),
                "--search-by", combo_search.get()] + (apps or ["Duolingo"])

    # placeholder lambdas — filled after log is created
    scrape_btn   = btn(frm_right, "▶  Scrape Ads",               "#0078d4", lambda: None)
    notion_btn   = btn(frm_right, "↑  Sync → Notion",             "#5c2d91", lambda: None)
    rename_btn   = btn(frm_right, "✎  Rename All Notion Pages",   "#5c2d91", lambda: None)
    creative_btn = btn(frm_right, "✦  Generate Creative Brief",   "#107c10", lambda: None)
    creative2_btn= btn(frm_right, "✦  Brief for App (field above)","#107c10", lambda: None)
    airtable_btn = btn(frm_right, "⟳  Airtable Updater",          "#c65c1a", lambda: None)
    dryryn_btn   = btn(frm_right, "⟳  Airtable Dry Run",          "#c65c1a", lambda: None)
    clear_btn    = tk.Button(frm_right, text="⊘  Clear Terminal",
                             bg="#555555", fg="white", relief="flat",
                             padx=8, pady=6, width=24, anchor="w")
    clear_btn.pack(fill="x", pady=(12, 3))

    # ── Terminal ─────────────────────────────────────────────────────────────
    frm_term = tk.LabelFrame(root, text=" Terminal ", bg="#2b2b2b",
                              fg="#bbbbbb", padx=6, pady=6)
    frm_term.pack(fill="both", expand=True, padx=12, pady=(4, 12))

    log = scrolledtext.ScrolledText(frm_term, state="disabled",
                                    font=("Courier New", 11),
                                    bg="#1e1e1e", fg="#d4d4d4",
                                    insertbackground="white",
                                    relief="flat", bd=0)
    log.pack(fill="both", expand=True)

    log.tag_config("header",  foreground="#569cd6", font=("Courier New", 11, "bold"))
    log.tag_config("cmd",     foreground="#808080")
    log.tag_config("sep",     foreground="#444444")
    log.tag_config("success", foreground="#4ec9b0")
    log.tag_config("error",   foreground="#f44747")
    log.tag_config("normal",  foreground="#d4d4d4")

    # ── Wire up buttons ───────────────────────────────────────────────────────
    def rc(label, args):
        run_command(label, args, log, all_buttons)

    scrape_btn.config(   command=lambda: rc("Scrape Ads", get_scrape_args()))
    notion_btn.config(   command=lambda: rc("Sync → Notion",
                             ["notion_publisher.py"] +
                             ([entry_app.get().split(",")[0].strip()]
                              if entry_app.get().strip() else [])))
    rename_btn.config(   command=lambda: rc("Rename All Notion Pages",
                             ["notion_publisher.py", "--rename"]))
    creative_btn.config( command=lambda: rc("Generate Creative Brief",
                             ["creative_generator.py", "--mix", "3"]))
    creative2_btn.config(command=lambda: rc("Generate Creative Brief for App",
                             ["creative_generator.py"] +
                             [a.strip() for a in entry_app.get().split(",") if a.strip()]))
    airtable_btn.config( command=lambda: rc("Airtable Updater",
                             ["airtable_updater.py"]))
    dryryn_btn.config(   command=lambda: rc("Airtable Updater (dry run)",
                             ["airtable_updater.py", "--dry-run"]))
    clear_btn.config(    command=lambda: (log.config(state="normal"),
                                          log.delete("1.0", tk.END),
                                          log.config(state="disabled")))

    log.config(state="normal")
    log.insert(tk.END, f"[{ts()}] Meta Ads Intelligence Pipeline ready.\n", "success")
    log.config(state="disabled")

    root.update()
    root.mainloop()


if __name__ == "__main__":
    build_gui()
