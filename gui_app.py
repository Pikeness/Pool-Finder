#!/usr/bin/env python3
"""
Pool Lead Finder - GUI

A simple point-and-click front end for the free pool-finding pipeline.
Type in a town, click "Find Pools", wait for it to finish, then click
through the results list on the left to preview each candidate's
thumbnail on the right. Check "Confirmed pool" for the ones you
visually verify, then export just those to a clean mailing-list CSV.

Run with:
    python gui_app.py

To turn this into a double-clickable app that doesn't need a terminal
at all, see "Building an executable" in README.md.
"""
import csv
import json
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

from pool_finder.pipeline import run_pipeline


class _NullWriter:
    """
    A safe stand-in for stdout/stderr.

    PyInstaller's --windowed build mode (no console window) sets
    sys.stdout and sys.stderr to None. If any code -- including
    Tkinter's own built-in error reporting, or a library like rasterio
    that occasionally prints warnings -- tries to write to them, it
    raises 'AttributeError: NoneType object has no attribute write'.
    That secondary crash can happen *inside* the error-reporting path
    itself, which means the ORIGINAL error silently vanishes and the
    app just looks frozen with zero clues. Installing this prevents
    that entire failure mode.
    """
    def write(self, *args, **kwargs):
        pass

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()


def resource_path(relative_path):
    """
    Resolves a path to a bundled resource (like the logo image) so it
    works both when running as a plain Python script AND when frozen
    into a PyInstaller --onefile executable, which unpacks bundled
    data files into a temporary folder at sys._MEIPASS at runtime.
    """
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


# Brand palette, sampled directly from the Immaculate Pools logo.
NAVY = "#005589"
SKY = "#25AAE7"
BG = "#EAF6FB"
WHITE = "#FFFFFF"


class PoolFinderApp:
    def __init__(self, root):
        self.root = root
        root.title("Immaculate Pool Lead Finder")
        root.geometry("1250x830")
        root.minsize(1000, 680)
        root.configure(bg=BG)

        try:
            icon_img = Image.open(resource_path("assets/logo.png")).resize((64, 64))
            self._icon_photo = ImageTk.PhotoImage(icon_img)
            root.iconphoto(False, self._icon_photo)
        except Exception:
            pass  # icon is a nice-to-have, never worth crashing over

        self._setup_style()

        self.results = []          # candidates from the last completed run
        self.confirmed = {}        # candidate id -> bool checkbox state
        self.addresses = {}        # candidate id -> address you typed in
        self.current_id = None
        self.current_out_dir = None
        self.log_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.photo_cache = None    # keep a reference so Tkinter won't garbage-collect it
        self.logo_placeholder = None

        self._build_layout()
        self.root.after(100, self._poll_queues)

    # ---------- Styling ----------

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass  # fall back to whatever default theme is available

        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=NAVY)
        style.configure("Header.TLabel", background=BG, foreground=NAVY,
                         font=("Georgia", 22, "bold"))
        style.configure("Sub.TLabel", background=BG, foreground=SKY,
                         font=("Segoe UI", 10, "italic"))
        style.configure("TButton", background=NAVY, foreground=WHITE,
                         font=("Segoe UI", 10, "bold"), padding=6, borderwidth=0)
        style.map("TButton",
                  background=[("active", SKY), ("disabled", "#A9C7D6")],
                  foreground=[("disabled", "#EEEEEE")])
        style.configure("TCheckbutton", background=BG, foreground=NAVY,
                         font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", BG)])
        style.configure("TEntry", fieldbackground=WHITE)

    # ---------- UI construction ----------

    def _build_layout(self):
        header = ttk.Frame(self.root, padding=(15, 12))
        header.pack(fill="x")

        try:
            logo_img = Image.open(resource_path("assets/logo.png")).resize((56, 56))
            self._header_logo = ImageTk.PhotoImage(logo_img)
            ttk.Label(header, image=self._header_logo, background=BG).pack(side="left", padx=(0, 12))
        except Exception:
            pass

        title_frame = ttk.Frame(header)
        title_frame.pack(side="left")
        ttk.Label(title_frame, text="Immaculate Pool Lead Finder", style="Header.TLabel").pack(anchor="w")
        ttk.Label(title_frame, text="Find backyard pools from free aerial imagery",
                  style="Sub.TLabel").pack(anchor="w")

        search = ttk.Frame(self.root, padding=(15, 0, 15, 10))
        search.pack(fill="x")

        ttk.Label(search, text="Town:").pack(side="left")
        self.town_entry = ttk.Entry(search, width=32)
        self.town_entry.pack(side="left", padx=5)
        self.town_entry.insert(0, "Wyckoff, NJ")

        self.run_button = ttk.Button(search, text="Find Pools", command=self._on_run)
        self.run_button.pack(side="left", padx=5)

        self.status_label = ttk.Label(search, text="Ready.")
        self.status_label.pack(side="left", padx=10)

        main = ttk.Frame(self.root, padding=(15, 0, 15, 10))
        main.pack(fill="both", expand=True)

        # Left: results list
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Candidates (click to preview)").pack(anchor="w")
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="y", expand=True)

        self.listbox = tk.Listbox(
            list_frame, width=45, height=32, exportselection=False,
            bg=WHITE, fg=NAVY, selectbackground=SKY, selectforeground=WHITE,
            highlightthickness=1, highlightbackground="#B9DCEC", relief="flat",
        )
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        scrollbar = ttk.Scrollbar(list_frame, command=self.listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        # Right: preview pane
        right = ttk.Frame(main, padding=(25, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        self.image_label = ttk.Label(right)
        self.image_label.pack(anchor="n", pady=10)
        self._show_placeholder_logo()

        self.confidence_label = ttk.Label(right, font=("Segoe UI", 10, "bold"))
        self.confidence_label.pack(anchor="n", pady=(5, 0))

        self.maps_button = ttk.Button(
            right, text="Open in Google Maps", command=self._on_open_maps
        )
        self.maps_button.pack(anchor="n", pady=8)

        address_frame = ttk.Frame(right)
        address_frame.pack(anchor="n", fill="x", pady=(0, 5))
        ttk.Label(address_frame, text="Street address (type it in after checking Maps):").pack(anchor="w")
        self.address_entry = ttk.Entry(address_frame, width=45)
        self.address_entry.pack(anchor="w", pady=(2, 0))
        self.address_entry.bind("<FocusOut>", lambda e: self._save_current_address())
        self.address_entry.bind("<Return>", lambda e: self._save_current_address())

        self.confirmed_var = tk.BooleanVar()
        self.confirmed_check = ttk.Checkbutton(
            right, text="Confirmed pool (include in mailing list)",
            variable=self.confirmed_var, command=self._on_confirm_toggle
        )
        self.confirmed_check.pack(anchor="n", pady=10)

        bottom = ttk.Frame(self.root, padding=(15, 0, 15, 10))
        bottom.pack(fill="x")
        self.export_button = ttk.Button(
            bottom, text="Export confirmed list to CSV",
            command=self._on_export, state="disabled"
        )
        self.export_button.pack(side="left")
        self.confirmed_count_label = ttk.Label(bottom, text="")
        self.confirmed_count_label.pack(side="left", padx=15)
        self.export_status = ttk.Label(bottom, text="")
        self.export_status.pack(side="left", padx=10)

        ttk.Label(self.root, text="Log:", padding=(15, 0)).pack(anchor="w")
        log_frame = ttk.Frame(self.root, padding=(15, 0, 15, 12))
        log_frame.pack(fill="both")
        self.log_text = tk.Text(log_frame, height=11, state="disabled",
                                 bg=WHITE, fg=NAVY, relief="flat",
                                 highlightthickness=1, highlightbackground="#B9DCEC")
        self.log_text.pack(fill="both", expand=True)

    def _load_scaled_photo(self, path, box_size):
        """
        Loads an image and scales it to fill a box_size x box_size
        square (preserving aspect ratio), scaling UP as well as down.

        This matters specifically for the detection thumbnails: each
        one is a tight crop around a small detected shape, often just
        a few dozen pixels across. PIL's plain thumbnail() only ever
        shrinks an image, so a tiny crop stayed tiny no matter how
        large the display box was. This scales in both directions so
        small crops are actually visible.
        """
        img = Image.open(path)
        scale = box_size / max(img.width, img.height)
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _show_placeholder_logo(self):
        try:
            if self.logo_placeholder is None:
                img = Image.open(resource_path("assets/logo.png"))
                img.thumbnail((320, 320))
                self.logo_placeholder = ImageTk.PhotoImage(img)
            self.image_label.config(image=self.logo_placeholder, text="")
        except Exception:
            self.image_label.config(image="", text="Select a candidate to preview it here.")

    # ---------- Actions ----------

    def _on_run(self):
        try:
            self._start_run()
        except Exception:
            messagebox.showerror("Error starting search", traceback.format_exc())
            self.run_button.config(state="normal")

    def _start_run(self):
        town = self.town_entry.get().strip()
        if not town:
            messagebox.showwarning("Missing town", "Please enter a town name.")
            return

        self.run_button.config(state="disabled")
        self.export_button.config(state="disabled")
        self.listbox.delete(0, tk.END)
        self.results = []
        self.confirmed = {}
        self.current_id = None
        self._show_placeholder_logo()
        self.addresses = {}
        self.address_entry.delete(0, tk.END)
        self.confirmed_var.set(False)
        self.confidence_label.config(text="")
        self.confirmed_count_label.config(text="")
        self.status_label.config(text="Running... this can take several minutes.")
        self._log_clear()

        safe_name = "".join(c if c.isalnum() else "_" for c in town)
        out_dir = f"pool_leads_{safe_name}"
        self.current_out_dir = out_dir

        thread = threading.Thread(target=self._run_pipeline_thread, args=(town, out_dir), daemon=True)
        thread.start()

    def _run_pipeline_thread(self, town, out_dir):
        try:
            results = run_pipeline(
                town, out_dir=out_dir,
                progress=lambda msg: self.log_queue.put(msg),
            )
            self.result_queue.put(("done", results))
        except Exception as e:
            self.result_queue.put(("error", str(e)))

    def _poll_queues(self):
        while not self.log_queue.empty():
            self._log_append(self.log_queue.get())

        while not self.result_queue.empty():
            kind, payload = self.result_queue.get()
            if kind == "done":
                # Most-confident candidates first -- when you're
                # working through a big list, this puts the ones most
                # likely to be real pools at the top instead of in
                # arbitrary scan order.
                self.results = sorted(payload, key=lambda r: r["confidence"], reverse=True)
                self.confirmed = {r["id"]: False for r in self.results}
                self._load_progress()
                self._populate_list()
                self._update_confirmed_count()
                self.status_label.config(text=f"Found {len(self.results)} candidate(s).")
                self.run_button.config(state="normal")
                self.export_button.config(state="normal" if self.results else "disabled")
            elif kind == "error":
                messagebox.showerror("Error", payload)
                self.status_label.config(text="Error - see message.")
                self.run_button.config(state="normal")

        self.root.after(100, self._poll_queues)

    def _row_label(self, r):
        mark = "\u2713 " if self.confirmed.get(r["id"]) else "   "
        return f"{mark}[{r['confidence']:.2f}]  {r['lat']:.5f}, {r['lon']:.5f}"

    def _populate_list(self):
        self.listbox.delete(0, tk.END)
        for r in self.results:
            self.listbox.insert(tk.END, self._row_label(r))

    def _refresh_current_listbox_row(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        r = self.results[idx]
        self.listbox.delete(idx)
        self.listbox.insert(idx, self._row_label(r))
        self.listbox.select_set(idx)

    def _update_confirmed_count(self):
        total = len(self.results)
        confirmed_n = sum(1 for v in self.confirmed.values() if v)
        self.confirmed_count_label.config(
            text=f"{confirmed_n} of {total} confirmed" if total else ""
        )

    def _progress_key(self, r):
        return f"{round(r['lat'], 6)},{round(r['lon'], 6)}"

    def _progress_path(self):
        if not self.current_out_dir:
            return None
        return os.path.join(self.current_out_dir, "review_progress.json")

    def _save_progress(self):
        path = self._progress_path()
        if not path:
            return
        data = {}
        for r in self.results:
            confirmed = self.confirmed.get(r["id"], False)
            address = self.addresses.get(r["id"], "")
            if confirmed or address:
                data[self._progress_key(r)] = {"confirmed": confirmed, "address": address}
        try:
            os.makedirs(self.current_out_dir, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f)
        except Exception:
            pass  # autosave is best-effort; never let it interrupt review

    def _load_progress(self):
        path = self._progress_path()
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            return
        for r in self.results:
            entry = data.get(self._progress_key(r))
            if entry:
                self.confirmed[r["id"]] = entry.get("confirmed", False)
                addr = entry.get("address", "")
                if addr:
                    self.addresses[r["id"]] = addr

    def _save_current_address(self):
        # Commit whatever's typed in the box before switching candidates
        # or exporting, so nothing typed gets lost.
        if self.current_id is not None:
            new_val = self.address_entry.get().strip()
            if self.addresses.get(self.current_id, "") != new_val:
                self.addresses[self.current_id] = new_val
                self._save_progress()

    def _on_select(self, event):
        selection = self.listbox.curselection()
        if not selection:
            return

        self._save_current_address()

        idx = selection[0]
        r = self.results[idx]
        self.current_id = r["id"]
        self.current_maps_url = r["maps_url"]

        self.confidence_label.config(text=f"Detector confidence: {r['confidence']:.2f}")
        self.confirmed_var.set(self.confirmed.get(r["id"], False))

        self.address_entry.delete(0, tk.END)
        self.address_entry.insert(0, self.addresses.get(r["id"], ""))

        if os.path.exists(r["thumbnail_path"]):
            self.photo_cache = self._load_scaled_photo(r["thumbnail_path"], 480)
            self.image_label.config(image=self.photo_cache, text="")
        else:
            self.image_label.config(image="", text="Thumbnail not found.")

    def _on_open_maps(self):
        if getattr(self, "current_maps_url", None):
            webbrowser.open(self.current_maps_url)
        else:
            messagebox.showinfo("No selection", "Select a candidate from the list first.")

    def _on_confirm_toggle(self):
        if self.current_id is not None:
            self.confirmed[self.current_id] = self.confirmed_var.get()
            self._save_progress()
            self._refresh_current_listbox_row()
            self._update_confirmed_count()

    def _on_export(self):
        self._save_current_address()

        confirmed_results = [r for r in self.results if self.confirmed.get(r["id"])]
        if not confirmed_results:
            messagebox.showinfo("Nothing to export", "No candidates are checked as confirmed yet.")
            return

        out_path = "confirmed_mailing_list.csv"
        with open(out_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["address", "lat", "lon", "confidence", "google_maps_link"])
            for r in confirmed_results:
                address = self.addresses.get(r["id"], "")
                writer.writerow([address, r["lat"], r["lon"], r["confidence"], r["maps_url"]])

        self.export_status.config(text=f"Saved {len(confirmed_results)} candidate(s) to {out_path}")

    # ---------- Logging ----------

    def _log_clear(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

    def _log_append(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")


def main():
    root = tk.Tk()

    def show_uncaught_error(exc, val, tb):
        # Without this override, Tkinter's default handler tries to
        # print the traceback to stderr -- which is None in a
        # --windowed build, silently swallowing the real error. This
        # makes any unexpected crash visible as a popup instead.
        err_text = "".join(traceback.format_exception(exc, val, tb))
        messagebox.showerror("Unexpected error", err_text)

    root.report_callback_exception = show_uncaught_error

    PoolFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
