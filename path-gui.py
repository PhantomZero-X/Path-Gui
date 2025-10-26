#!/usr/bin/env python3
"""
Path Scanner - Modern GUI version
Author: (refactor oleh ChatGPT untuk pengguna)
Catatan penting: Gunakan tool ini hanya pada target yang Anda miliki atau
yang Anda memiliki izin eksplisit untuk menguji.
"""

import requests
import concurrent.futures
import threading
import time
import queue
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ----------------------
# Config & Globals
# ----------------------
STOP_EVENT = threading.Event()
RESULT_QUEUE = queue.Queue()

# ----------------------
# Worker (network) logic
# ----------------------
def probe_path(session, base_url, path, headers, timeout):
    """
    Mengirim GET ke base_url/path. Mengembalikan tuple:
    (path, full_url, status_code, reason, elapsed_seconds, ok_bool, error_str)
    """
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    t0 = time.time()
    try:
        r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        elapsed = time.time() - t0
        return (path, url, r.status_code, r.reason, round(elapsed, 3), True, "")
    except requests.RequestException as e:
        elapsed = time.time() - t0
        return (path, url, None, None, round(elapsed, 3), False, str(e))

# ----------------------
# Scanning controller
# ----------------------
def scan_controller(target, wordlist_path, scheme, user_agent, concurrency, delay, timeout, filters):
    STOP_EVENT.clear()
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent})
    base_url = f"{scheme}://{target}"

    # read wordlist
    try:
        with open(wordlist_path, "r", encoding="utf-8", errors="ignore") as f:
            words = [w.strip() for w in f if w.strip()]
    except Exception as e:
        RESULT_QUEUE.put(("__error__", f"Gagal membaca wordlist: {e}"))
        return

    total = len(words)
    RESULT_QUEUE.put(("__meta__", {"total": total, "target": base_url}))

    # thread pool
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as exe:
        futures = []
        for i, w in enumerate(words, start=1):
            if STOP_EVENT.is_set():
                break
            futures.append(exe.submit(probe_path, session, base_url, w, session.headers, timeout))
            # rate limiting (small sleep between scheduling to reduce burst)
            time.sleep(delay)
        # collect results as they complete
        for fut in concurrent.futures.as_completed(futures):
            if STOP_EVENT.is_set():
                break
            res = fut.result()
            # apply simple filters (list of strings like "2xx", "3xx", "200,301" or "all")
            if res[5]:  # ok performed request -> check status
                code = res[2]
                if should_show_status(code, filters):
                    RESULT_QUEUE.put(("result", res))
            else:
                # network error
                RESULT_QUEUE.put(("result_err", res))
    RESULT_QUEUE.put(("__done__", "Scan selesai"))

def should_show_status(code, filters):
    if filters is None:
        return True
    if code is None:
        return True
    # filters can be set to "all" or a comma separated list or ranges like 2xx
    f = filters.strip().lower()
    if f in ("", "all", "any"):
        return True
    parts = [p.strip() for p in f.split(",") if p.strip()]
    for p in parts:
        if p.endswith("xx") and len(p) == 3:  # e.g. 2xx
            prefix = int(p[0])
            if code // 100 == prefix:
                return True
        else:
            try:
                if int(p) == code:
                    return True
            except ValueError:
                continue
    return False

# ----------------------
# GUI Logic
# ----------------------
class App(ttk.Frame):
    def __init__(self, root):
        super().__init__(root, padding=(12,12,12,12))
        self.root = root
        self.root.title("Path Scanner — Modern UI")
        self.pack(fill="both", expand=True)
        self.create_widgets()
        self.scan_thread = None
        self.poll_queue()

    def create_widgets(self):
        # top frame - inputs
        top = ttk.LabelFrame(self, text="Target & Wordlist", padding=8)
        top.pack(fill="x", pady=(0,8))

        ttk.Label(top, text="Target (domain or IP):").grid(row=0, column=0, sticky="w")
        self.entry_target = ttk.Entry(top, width=40)
        self.entry_target.grid(row=0, column=1, sticky="w", padx=6)

        ttk.Label(top, text="Skema:").grid(row=0, column=2, sticky="e")
        self.scheme_var = tk.StringVar(value="https")
        scheme_cb = ttk.Combobox(top, width=6, textvariable=self.scheme_var, values=("https","http"), state="readonly")
        scheme_cb.grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(top, text="Wordlist:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.entry_wordlist = ttk.Entry(top, width=50)
        self.entry_wordlist.grid(row=1, column=1, columnspan=2, sticky="w", padx=6, pady=(6,0))
        ttk.Button(top, text="Browse", command=self.browse_wordlist).grid(row=1, column=3, padx=6, pady=(6,0))

        # options frame
        opts = ttk.LabelFrame(self, text="Options", padding=8)
        opts.pack(fill="x", pady=(0,8))

        ttk.Label(opts, text="User-Agent:").grid(row=0, column=0, sticky="w")
        self.entry_ua = ttk.Entry(opts, width=50)
        self.entry_ua.insert(0, "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        self.entry_ua.grid(row=0, column=1, columnspan=3, sticky="w", padx=6)

        ttk.Label(opts, text="Concurrency:").grid(row=1, column=0, sticky="w", pady=(6,0))
        self.spin_conc = ttk.Spinbox(opts, from_=1, to=50, width=6)
        self.spin_conc.set(10)
        self.spin_conc.grid(row=1, column=1, sticky="w", pady=(6,0), padx=6)

        ttk.Label(opts, text="Delay (s):").grid(row=1, column=2, sticky="e", pady=(6,0))
        self.spin_delay = ttk.Spinbox(opts, from_=0.0, to=5.0, increment=0.05, width=6)
        self.spin_delay.set(0.02)
        self.spin_delay.grid(row=1, column=3, sticky="w", pady=(6,0), padx=6)

        ttk.Label(opts, text="Timeout (s):").grid(row=2, column=0, sticky="w", pady=(6,0))
        self.spin_timeout = ttk.Spinbox(opts, from_=1, to=30, increment=1, width=6)
        self.spin_timeout.set(5)
        self.spin_timeout.grid(row=2, column=1, sticky="w", pady=(6,0), padx=6)

        ttk.Label(opts, text="Filter Status (e.g. 200,2xx or 'all'):", foreground="gray").grid(row=2, column=2, sticky="e", pady=(6,0))
        self.entry_filter = ttk.Entry(opts, width=12)
        self.entry_filter.insert(0, "200,301,302")
        self.entry_filter.grid(row=2, column=3, sticky="w", pady=(6,0), padx=6)

        # action buttons
        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(0,8))

        self.btn_start = ttk.Button(actions, text="Start Scan", command=self.on_start)
        self.btn_start.pack(side="left", padx=6)
        self.btn_stop = ttk.Button(actions, text="Stop", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(actions, text="Clear Output", command=self.on_clear).pack(side="left", padx=6)
        ttk.Button(actions, text="Save Results", command=self.on_save).pack(side="left", padx=6)

        # progress & stats
        prog_frame = ttk.Frame(self)
        prog_frame.pack(fill="x", pady=(0,8))
        self.progress = ttk.Progressbar(prog_frame, value=0, maximum=100)
        self.progress.pack(fill="x", side="left", expand=True, padx=(0,10))
        self.label_status = ttk.Label(prog_frame, text="Idle")
        self.label_status.pack(side="right")

        # output box
        out_frame = ttk.LabelFrame(self, text="Output", padding=6)
        out_frame.pack(fill="both", expand=True)

        self.txt_output = scrolledtext.ScrolledText(out_frame, height=18, wrap="none", font=("Consolas", 10))
        self.txt_output.pack(fill="both", expand=True)
        # simple tags
        self.txt_output.tag_config("ok", foreground="#45d17f")
        self.txt_output.tag_config("redir", foreground="#f3c623")
        self.txt_output.tag_config("err", foreground="#ff6b6b")
        self.txt_output.tag_config("meta", foreground="#9ad0ff")

        # internal
        self.results = []  # list of result tuples
        self.total_jobs = 0
        self.completed = 0

    # UI helpers
    def browse_wordlist(self):
        p = filedialog.askopenfilename(title="Pilih wordlist", filetypes=[("Text files","*.txt"),("All files","*.*")])
        if p:
            self.entry_wordlist.delete(0, tk.END)
            self.entry_wordlist.insert(0, p)

    def on_start(self):
        target = self.entry_target.get().strip()
        wordlist = self.entry_wordlist.get().strip()
        ua = self.entry_ua.get().strip()
        scheme = self.scheme_var.get()
        try:
            concurrency = int(self.spin_conc.get())
            delay = float(self.spin_delay.get())
            timeout = float(self.spin_timeout.get())
        except Exception:
            messagebox.showerror("Error", "Periksa nilai concurrency/delay/timeout.")
            return
        filters = self.entry_filter.get().strip()

        if not target or not wordlist:
            messagebox.showwarning("Input kurang", "Masukkan target dan pilih wordlist terlebih dahulu.")
            return
        if not os.path.isfile(wordlist):
            messagebox.showerror("Wordlist", "File wordlist tidak ditemukan.")
            return

        # prepare UI state
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.label_status.configure(text="Starting...")
        self.progress.configure(value=0)
        self.results.clear()
        self.completed = 0
        self.total_jobs = 0

        # start scan thread
        args = (target, wordlist, scheme, ua, concurrency, delay, timeout, filters)
        self.scan_thread = threading.Thread(target=scan_controller, args=args, daemon=True)
        self.scan_thread.start()
        # note: results come via RESULT_QUEUE polled by GUI thread

    def on_stop(self):
        STOP_EVENT.set()
        self.label_status.configure(text="Stopping...")
        self.btn_stop.configure(state="disabled")

    def on_clear(self):
        self.txt_output.delete("1.0", tk.END)
        self.results.clear()
        self.progress.configure(value=0)
        self.label_status.configure(text="Idle")

    def on_save(self):
        if not self.results:
            messagebox.showinfo("Simpan", "Belum ada hasil untuk disimpan.")
            return
        fn = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files","*.txt")])
        if not fn:
            return
        try:
            with open(fn, "w", encoding="utf-8") as f:
                for r in self.results:
                    # r is tuple produced by probe_path
                    line = f"{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}\n"
                    f.write(line)
            messagebox.showinfo("Simpan", f"Hasil disimpan ke {fn}")
        except Exception as e:
            messagebox.showerror("Simpan", f"Gagal menyimpan: {e}")

    # polling GUI queue for results
    def poll_queue(self):
        try:
            while True:
                item = RESULT_QUEUE.get_nowait()
                self.handle_queue_item(item)
        except queue.Empty:
            pass
        # poll again
        self.after(150, self.poll_queue)

    def handle_queue_item(self, item):
        tag = item[0]
        payload = item[1]
        if tag == "__error__":
            self.txt_output.insert(tk.END, f"[ERROR] {payload}\n", "err")
            self.label_status.configure(text="Error")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
        elif tag == "__meta__":
            # payload is dict
            self.total_jobs = payload.get("total", 0)
            target = payload.get("target", "")
            self.txt_output.insert(tk.END, f"[*] Start scan {target} | total paths: {self.total_jobs}\n", "meta")
            self.label_status.configure(text="Running")
        elif tag == "result":
            # payload is result tuple
            self.completed += 1
            self.results.append(payload)
            _, url, code, reason, elapsed, ok, err = payload
            color_tag = "ok" if (code and code < 300) else ("redir" if (code and 300 <= code < 400) else "err")
            self.txt_output.insert(tk.END, f"[{code}] {url} ({elapsed}s) {reason}\n", color_tag)
            pct = int((self.completed / self.total_jobs) * 100) if self.total_jobs else 0
            self.progress.configure(value=pct)
            self.label_status.configure(text=f"Running — {self.completed}/{self.total_jobs}")
            self.txt_output.see(tk.END)
        elif tag == "result_err":
            self.completed += 1
            payload = payload
            _, url, code, reason, elapsed, ok, err = payload
            self.results.append(payload)
            self.txt_output.insert(tk.END, f"[ERR] {url} — {err}\n", "err")
            pct = int((self.completed / self.total_jobs) * 100) if self.total_jobs else 0
            self.progress.configure(value=pct)
            self.label_status.configure(text=f"Running — {self.completed}/{self.total_jobs}")
            self.txt_output.see(tk.END)
        elif tag == "__done__":
            self.txt_output.insert(tk.END, f"[*] {payload}\n", "meta")
            self.label_status.configure(text="Selesai")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")

# ----------------------
# Run app
# ----------------------
def main():
    root = tk.Tk()
    # ttk style for basic dark-ish look (simple)
    style = ttk.Style(root)
    try:
        # prefer available theme
        style.theme_use("clam")
    except Exception:
        pass
    App(root)
    root.geometry("900x640")
    root.mainloop()

if __name__ == "__main__":
    main()
