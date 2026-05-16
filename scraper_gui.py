"""
Meta Ads Intelligence Pipeline — GUI
"""

import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = str(Path(__file__).parent)
_running = False


def ts():
    return datetime.now().strftime("%H:%M:%S")


def run(label, args, log, buttons):
    global _running
    if _running:
        return

    def task():
        global _running
        _running = True
        for b in buttons:
            b.config(state="disabled")

        log.config(state="normal")
        log.insert(tk.END, f"\n[{ts()}]  {label}\n", "hdr")
        log.insert(tk.END, "─" * 55 + "\n", "sep")
        log.see(tk.END)

        try:
            cmd = [sys.executable, str(Path(SCRIPT_DIR) / args[0])] + args[1:]
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                stripped = line.rstrip()
                if not stripped:
                    continue
                tag = "err" if any(w in stripped.lower() for w in ["error","failed","traceback"]) \
                      else "ok" if any(w in stripped for w in ["✓","Uploaded","created","Done","Finished"]) \
                      else "txt"
                log.insert(tk.END, stripped + "\n", tag)
                log.see(tk.END)
                log.update_idletasks()
            proc.wait()
            log.insert(tk.END, "─" * 55 + "\n", "sep")
            if proc.returncode == 0:
                log.insert(tk.END, f"[{ts()}] ✓ Done\n", "ok")
            else:
                log.insert(tk.END, f"[{ts()}] ✗ Exit {proc.returncode}\n", "err")
        except Exception as e:
            log.insert(tk.END, f"[{ts()}] ERROR: {e}\n", "err")

        log.config(state="disabled")
        _running = False
        for b in buttons:
            log.after(0, lambda b=b: b.config(state="normal"))

    threading.Thread(target=task, daemon=True).start()


def main():
    root = tk.Tk()
    root.title("Meta Ads Intelligence Pipeline")
    root.geometry("820x700")

    buttons = []

    # ══ INPUT SECTION ════════════════════════════════════════════════════════
    box = tk.LabelFrame(root, text="  Scraper Inputs  ", padx=12, pady=10)
    box.pack(fill="x", padx=14, pady=(12, 4))

    # Row 1: App name + Country + Limit
    tk.Label(box, text="App / Keyword").grid(row=0, column=0, sticky="w", padx=(0,6), pady=5)
    app_var = tk.StringVar(value="Duolingo")
    tk.Entry(box, textvariable=app_var, width=28).grid(row=0, column=1, sticky="ew", pady=5)

    tk.Label(box, text="Country").grid(row=0, column=2, sticky="w", padx=(16,6), pady=5)
    country_var = tk.StringVar(value="US")
    tk.Entry(box, textvariable=country_var, width=6).grid(row=0, column=3, sticky="w", pady=5)

    tk.Label(box, text="Limit").grid(row=0, column=4, sticky="w", padx=(16,6), pady=5)
    limit_var = tk.StringVar(value="5")
    tk.Spinbox(box, textvariable=limit_var, from_=1, to=50, width=5).grid(row=0, column=5, sticky="w", pady=5)

    box.columnconfigure(1, weight=1)

    # Row 2: Rank by + Filter + Search by
    tk.Label(box, text="Rank By").grid(row=1, column=0, sticky="w", padx=(0,6), pady=5)
    rank_var = tk.StringVar(value="combined")
    ttk.Combobox(box, textvariable=rank_var, values=["combined","age","order","impressions","copies"],
                 state="readonly", width=14).grid(row=1, column=1, sticky="w", pady=5)

    tk.Label(box, text="Filter").grid(row=1, column=2, sticky="w", padx=(16,6), pady=5)
    filter_var = tk.StringVar(value="static")
    ttk.Combobox(box, textvariable=filter_var, values=["static","video","combined"],
                 state="readonly", width=10).grid(row=1, column=3, sticky="w", pady=5)

    tk.Label(box, text="Search By").grid(row=1, column=4, sticky="w", padx=(16,6), pady=5)
    search_var = tk.StringVar(value="page")
    ttk.Combobox(box, textvariable=search_var, values=["page","keyword"],
                 state="readonly", width=10).grid(row=1, column=5, sticky="w", pady=5)

    # ══ BUTTONS ══════════════════════════════════════════════════════════════
    def mkbtn(parent, text, color, cmd, col, row=0, colspan=1):
        b = tk.Button(parent, text=text, bg=color, fg="white",
                      activebackground=color, relief="flat",
                      padx=10, pady=8, command=cmd)
        b.grid(row=row, column=col, columnspan=colspan,
               sticky="ew", padx=5, pady=5)
        buttons.append(b)
        return b

    # Scraper buttons
    box2 = tk.LabelFrame(root, text="  Scraper  ", padx=8, pady=6)
    box2.pack(fill="x", padx=14, pady=4)
    for i in range(4): box2.columnconfigure(i, weight=1)

    def scrape_args():
        apps = [a.strip() for a in app_var.get().split(",") if a.strip()]
        return ["meta_ads_scraper.py",
                "--country", country_var.get() or "US",
                "--limit", limit_var.get() or "5",
                "--rank-by", rank_var.get(),
                "--filter", filter_var.get(),
                "--search-by", search_var.get()] + (apps or ["Duolingo"])

    mkbtn(box2, "▶  Scrape Ads", "#0078d4",
          lambda: run("Scrape Ads", scrape_args(), log, buttons), col=0, colspan=4)

    # Notion buttons
    box3 = tk.LabelFrame(root, text="  Notion  ", padx=8, pady=6)
    box3.pack(fill="x", padx=14, pady=4)
    for i in range(3): box3.columnconfigure(i, weight=1)

    def notion_args():
        app = app_var.get().split(",")[0].strip()
        return ["notion_publisher.py", app] if app else ["notion_publisher.py"]

    mkbtn(box3, "↑  Sync App → Notion", "#5c2d91",
          lambda: run("Sync → Notion", notion_args(), log, buttons), col=0)
    mkbtn(box3, "↑  Sync All → Notion", "#5c2d91",
          lambda: run("Sync All → Notion", ["notion_publisher.py"], log, buttons), col=1)
    mkbtn(box3, "✎  Rename All Pages", "#5c2d91",
          lambda: run("Rename All Pages", ["notion_publisher.py","--rename"], log, buttons), col=2)

    # Groq buttons
    box4 = tk.LabelFrame(root, text="  Creative Brief (Groq)  ", padx=8, pady=6)
    box4.pack(fill="x", padx=14, pady=4)
    for i in range(2): box4.columnconfigure(i, weight=1)

    def brief_args():
        apps = [a.strip() for a in app_var.get().split(",") if a.strip()]
        return ["creative_generator.py"] + apps if apps else ["creative_generator.py", "--mix", "3"]

    mkbtn(box4, "✦  Brief — All Competitors", "#107c10",
          lambda: run("Creative Brief", ["creative_generator.py","--mix","3"], log, buttons), col=0)
    mkbtn(box4, "✦  Brief — App in Field", "#107c10",
          lambda: run("Creative Brief for App", brief_args(), log, buttons), col=1)

    # Airtable buttons
    box5 = tk.LabelFrame(root, text="  Airtable  ", padx=8, pady=6)
    box5.pack(fill="x", padx=14, pady=4)
    for i in range(2): box5.columnconfigure(i, weight=1)

    mkbtn(box5, "⟳  Run Airtable Updater", "#c65c1a",
          lambda: run("Airtable Updater", ["airtable_updater.py"], log, buttons), col=0)
    mkbtn(box5, "⟳  Dry Run (preview only)", "#c65c1a",
          lambda: run("Airtable Dry Run", ["airtable_updater.py","--dry-run"], log, buttons), col=1)

    # ══ TERMINAL ═════════════════════════════════════════════════════════════
    term_frame = tk.LabelFrame(root, text="  Terminal  ", padx=6, pady=6)
    term_frame.pack(fill="both", expand=True, padx=14, pady=(4, 12))

    log = scrolledtext.ScrolledText(term_frame, state="disabled",
                                    font=("Courier New", 11),
                                    bg="#1e1e1e", fg="#d4d4d4",
                                    relief="flat", bd=0)
    log.pack(fill="both", expand=True)

    log.tag_config("hdr", foreground="#4fc1ff", font=("Courier New", 11, "bold"))
    log.tag_config("sep", foreground="#3a3a3a")
    log.tag_config("ok",  foreground="#4ec9b0")
    log.tag_config("err", foreground="#f44747")
    log.tag_config("txt", foreground="#d4d4d4")

    # clear button inside terminal frame
    tk.Button(term_frame, text="Clear", command=lambda: (
        log.config(state="normal"), log.delete("1.0", tk.END), log.config(state="disabled")
    ), relief="flat", bg="#3a3a3a", fg="white", padx=6, pady=2).pack(anchor="ne")

    log.config(state="normal")
    log.insert(tk.END, f"[{ts()}] Ready. Fill in the inputs above and press a button.\n", "ok")
    log.config(state="disabled")

    root.update()
    root.mainloop()


if __name__ == "__main__":
    main()
