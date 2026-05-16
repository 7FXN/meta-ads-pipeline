"""
Meta Ads Intelligence Pipeline — GUI
Run this file in PyCharm to get a graphical interface for the scraper.
"""

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def run_command(args: list, log: scrolledtext.ScrolledText, on_done=None):
    """Run a subprocess and stream output to the log widget."""
    def target():
        log.config(state="normal")
        log.insert(tk.END, f"\n$ {' '.join(args)}\n", "cmd")
        log.see(tk.END)
        try:
            proc = subprocess.Popen(
                [sys.executable] + args,
                cwd=SCRIPT_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in proc.stdout:
                log.insert(tk.END, line)
                log.see(tk.END)
                log.update_idletasks()
            proc.wait()
            status = "✓ Done" if proc.returncode == 0 else f"✗ Exit code {proc.returncode}"
            log.insert(tk.END, f"{status}\n", "status")
        except Exception as e:
            log.insert(tk.END, f"Error: {e}\n", "error")
        log.config(state="disabled")
        if on_done:
            on_done()

    threading.Thread(target=target, daemon=True).start()


def build_gui():
    root = tk.Tk()
    root.title("Meta Ads Intelligence Pipeline")
    root.resizable(True, True)

    # ── Inputs ──────────────────────────────────────────────────────────────
    frame_inputs = ttk.LabelFrame(root, text="Scraper Settings", padding=10)
    frame_inputs.grid(row=0, column=0, padx=12, pady=8, sticky="ew")
    root.columnconfigure(0, weight=1)

    labels = ["App / Keyword", "Country", "Limit", "Rank By", "Filter", "Search By"]
    for i, lbl in enumerate(labels):
        ttk.Label(frame_inputs, text=lbl).grid(row=i, column=0, sticky="w", pady=3)

    entry_app     = ttk.Entry(frame_inputs, width=30)
    entry_country = ttk.Entry(frame_inputs, width=10)
    spin_limit    = ttk.Spinbox(frame_inputs, from_=1, to=50, width=8)
    combo_rank    = ttk.Combobox(frame_inputs, values=["combined","age","order","impressions","copies"], width=14, state="readonly")
    combo_filter  = ttk.Combobox(frame_inputs, values=["static","video","combined"], width=14, state="readonly")
    combo_search  = ttk.Combobox(frame_inputs, values=["page","keyword"], width=14, state="readonly")

    entry_app.insert(0, "Duolingo")
    entry_country.insert(0, "US")
    spin_limit.set(5)
    combo_rank.set("combined")
    combo_filter.set("static")
    combo_search.set("page")

    widgets = [entry_app, entry_country, spin_limit, combo_rank, combo_filter, combo_search]
    for i, w in enumerate(widgets):
        w.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=3)
    frame_inputs.columnconfigure(1, weight=1)

    # ── Buttons ─────────────────────────────────────────────────────────────
    frame_btns = ttk.Frame(root, padding=(12, 0, 12, 8))
    frame_btns.grid(row=1, column=0, sticky="ew")

    btn_scrape   = ttk.Button(frame_btns, text="▶  Scrape Ads")
    btn_creative = ttk.Button(frame_btns, text="✦  Generate Creative Brief")
    btn_notion   = ttk.Button(frame_btns, text="↑  Sync to Notion")
    btn_clear    = ttk.Button(frame_btns, text="Clear Log")

    btn_scrape.grid(row=0, column=0, padx=4, pady=4)
    btn_creative.grid(row=0, column=1, padx=4, pady=4)
    btn_notion.grid(row=0, column=2, padx=4, pady=4)
    btn_clear.grid(row=0, column=3, padx=4, pady=4)

    # ── Log ─────────────────────────────────────────────────────────────────
    log = scrolledtext.ScrolledText(root, height=24, width=80, state="disabled",
                                    font=("Courier New", 11), bg="#1e1e1e", fg="#d4d4d4",
                                    insertbackground="white")
    log.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")
    root.rowconfigure(2, weight=1)

    log.tag_config("cmd",    foreground="#569cd6")
    log.tag_config("status", foreground="#4ec9b0")
    log.tag_config("error",  foreground="#f44747")

    # ── Actions ─────────────────────────────────────────────────────────────
    def set_buttons(state):
        for b in [btn_scrape, btn_creative, btn_notion]:
            b.config(state=state)

    def on_scrape():
        apps = [a.strip() for a in entry_app.get().split(",") if a.strip()]
        if not apps:
            return
        set_buttons("disabled")
        args = ["meta_ads_scraper.py",
                "--country", entry_country.get().strip() or "US",
                "--limit",   str(int(spin_limit.get())),
                "--rank-by", combo_rank.get(),
                "--filter",  combo_filter.get(),
                "--search-by", combo_search.get()] + apps
        run_command(args, log, on_done=lambda: root.after(0, lambda: set_buttons("normal")))

    def on_creative():
        set_buttons("disabled")
        run_command(["creative_generator.py", "--mix", "3"], log,
                    on_done=lambda: root.after(0, lambda: set_buttons("normal")))

    def on_notion():
        set_buttons("disabled")
        app = entry_app.get().split(",")[0].strip()
        args = ["notion_publisher.py", app] if app else ["notion_publisher.py"]
        run_command(args, log, on_done=lambda: root.after(0, lambda: set_buttons("normal")))

    def on_clear():
        log.config(state="normal")
        log.delete("1.0", tk.END)
        log.config(state="disabled")

    btn_scrape.config(command=on_scrape)
    btn_creative.config(command=on_creative)
    btn_notion.config(command=on_notion)
    btn_clear.config(command=on_clear)

    root.mainloop()


if __name__ == "__main__":
    build_gui()
