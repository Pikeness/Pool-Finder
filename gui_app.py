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
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

from pool_finder.pipeline import run_pipeline


class PoolFinderApp:
    def __init__(self, root):
        self.root = root
        root.title("Pool Lead Finder")
        root.geometry("950x650")
        root.minsize(750, 500)

        self.results = []       # candidates from the last completed run
        self.confirmed = {}     # candidate id -> bool checkbox state
        self.addresses = {}     # candidate id -> address you typed in
        self.current_id = None
        self.log_queue = queue.Queue()
        self.result_queue = queue.Queue()
        self.photo_cache = None  # keep a reference so Tkinter won't garbage-collect it

        self._build_layout()
        self.root.after(100, self._poll_queues)

    # ---------- UI construction ----------

    def _build_layout(self):
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="Town:").pack(side="left")
        self.town_entry = ttk.Entry(top, width=32)
        self.town_entry.pack(side="left", padx=5)
        self.town_entry.insert(0, "Wyckoff, NJ")

        self.run_button = ttk.Button(top, text="Find Pools", command=self._on_run)
        self.run_button.pack(side="left", padx=5)

        self.status_label = ttk.Label(top, text="Ready.")
        self.status_label.pack(side="left", padx=10)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # Left: results list
        left = ttk.Frame(main)
        left.pack(side="left", fill="y")

        ttk.Label(left, text="Candidates (click to preview)").pack(anchor="w")
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="y", expand=True)

        self.listbox = tk.Listbox(list_frame, width=45, height=28, exportselection=False)
        self.listbox.pack(side="left", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_select)

        scrollbar = ttk.Scrollbar(list_frame, command=self.listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        # Right: preview pane
        right = ttk.Frame(main, padding=(20, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        self.image_label = ttk.Label(right, text="Select a candidate to preview it here.")
        self.image_label.pack(anchor="n", pady=10)

        self.confidence_label = ttk.Label(right, text="")
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

        self.confirmed_var = tk.BooleanVar()
        self.confirmed_check = ttk.Checkbutton(
            right, text="Confirmed pool (include in mailing list)",
            variable=self.confirmed_var, command=self._on_confirm_toggle
        )
        self.confirmed_check.pack(anchor="n", pady=10)

        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(fill="x")
        self.export_button = ttk.Button(
            bottom, text="Export confirmed list to CSV",
            command=self._on_export, state="disabled"
        )
        self.export_button.pack(side="left")
        self.export_status = ttk.Label(bottom, text="")
        self.export_status.pack(side="left", padx=10)

        ttk.Label(self.root, text="Log:").pack(anchor="w", padx=10)
        self.log_text = tk.Text(self.root, height=7, state="disabled")
        self.log_text.pack(fill="x", padx=10, pady=(0, 10))

    # ---------- Actions ----------

    def _on_run(self):
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
        self.image_label.config(image="", text="Select a candidate to preview it here.")
        self.address_label.config(text="")
        self.confidence_label.config(text="")
        self.status_label.config(text="Running... this can take several minutes.")
        self._log_clear()

        safe_name = "".join(c if c.isalnum() else "_" for c in town)
        out_dir = f"pool_leads_{safe_name}"

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
                self.results = payload
                self.confirmed = {r["id"]: False for r in self.results}
                self._populate_list()
                self.status_label.config(text=f"Found {len(self.results)} candidate(s).")
                self.run_button.config(state="normal")
                self.export_button.config(state="normal" if self.results else "disabled")
            elif kind == "error":
                messagebox.showerror("Error", payload)
                self.status_label.config(text="Error - see message.")
                self.run_button.config(state="normal")

        self.root.after(100, self._poll_queues)

    def _populate_list(self):
        self.listbox.delete(0, tk.END)
        for r in self.results:
            label = f"[{r['confidence']:.2f}]  {r['lat']:.5f}, {r['lon']:.5f}"
            self.listbox.insert(tk.END, label)

    def _save_current_address(self):
        # Commit whatever's typed in the box before switching candidates
        # or exporting, so nothing typed gets lost.
        if self.current_id is not None:
            self.addresses[self.current_id] = self.address_entry.get().strip()

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
            img = Image.open(r["thumbnail_path"])
            img.thumbnail((420, 420))
            self.photo_cache = ImageTk.PhotoImage(img)
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
    PoolFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
