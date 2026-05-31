#!/usr/bin/env python3
"""
VATSIM Discord Rich Presence — with GUI
"""

import re
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import requests
from pypresence import Presence

# ── Config ────────────────────────────────────────────────────────────────────
POLL_SECONDS = 30
VATSIM_URL   = "https://data.vatsim.net/v3/vatsim-data.json"

# you need an actual discord client ID
CLIENT_ID = ""


# ── VATSIM ────────────────────────────────────────────────────────────────────
def fetch_pilot_by_cid(cid: str) -> dict | None:
    resp = requests.get(VATSIM_URL, timeout=10)
    resp.raise_for_status()
    pilots = resp.json().get("pilots", [])
    return next((p for p in pilots if str(p["cid"]) == str(cid)), None)


def clean_aircraft(raw: str) -> str:
    raw = re.sub(r"^[A-Z]/", "", raw)
    raw = raw.split("/")[0]
    return raw.strip()


def parse_registration(remarks: str) -> str | None:
    match = re.search(r"\b(?:REG|RG)/([A-Z0-9-]+)\b", remarks, re.IGNORECASE)
    return match.group(1).upper() if match else None


def parse_flight(pilot: dict) -> dict:
    fp = pilot.get("flight_plan") or {}
    remarks = fp.get("remarks", "")
    return {
        "callsign":     pilot["callsign"],
        "departure":    fp.get("departure") or "????",
        "arrival":      fp.get("arrival")   or "????",
        "aircraft":     clean_aircraft(fp.get("aircraft_faa") or fp.get("aircraft") or "Unknown"),
        "registration": parse_registration(remarks),
        "altitude":     pilot.get("altitude", 0),
        "groundspeed":  pilot.get("groundspeed", 0),
        "flight_rules": fp.get("flight_rules", "IFR"),
    }


def flight_phase(gs: int, alt: int) -> str:
    if gs < 40:                 return "On the ground"
    if alt < 1500 and gs < 180: return "Departing"
    if alt < 1500:              return "Arriving"
    if alt < 10000:             return "Climbing"
    if gs > 250:                return "En route"
    return                             "Descending"


# ── App ───────────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root):
        self.root  = root
        self.rpc   = None
        self.running   = False
        self.poll_thread = None

        root.title("VATSIM Rich Presence")
        root.resizable(False, False)
        root.configure(padx=20, pady=20)

        # ── CID row ──
        tk.Label(root, text="VATSIM CID", font=("Segoe UI", 10)).grid(row=0, column=0, sticky="w")
        self.cid_var = tk.StringVar()
        self.cid_entry = tk.Entry(root, textvariable=self.cid_var, width=20, font=("Segoe UI", 11))
        self.cid_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))

        # ── Buttons ──
        self.start_btn = tk.Button(root, text="Start", width=10, command=self.start)
        self.start_btn.grid(row=2, column=0, sticky="w")
        self.stop_btn  = tk.Button(root, text="Stop",  width=10, command=self.stop, state="disabled")
        self.stop_btn.grid(row=2, column=1, sticky="e")

        # ── Status box ──
        tk.Label(root, text="Status", font=("Segoe UI", 9), fg="gray").grid(row=3, column=0, sticky="w", pady=(16, 2))
        self.status_text = tk.Text(root, width=45, height=8, state="disabled",
                                   font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
                                   relief="flat", padx=8, pady=6)
        self.status_text.grid(row=4, column=0, columnspan=2)

    def log(self, msg: str):
        self.status_text.configure(state="normal")
        self.status_text.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.status_text.see("end")
        self.status_text.configure(state="disabled")

    def start(self):
        cid = self.cid_var.get().strip()
        if not cid.isdigit():
            messagebox.showerror("Invalid CID", "CID must be a number.")
            return
        if CLIENT_ID == "YOUR_APP_CLIENT_ID_HERE":
            messagebox.showerror("No Client ID", "Set CLIENT_ID at the top of the script first.")
            return

        try:
            self.rpc = Presence(CLIENT_ID)
            self.rpc.connect()
        except Exception as e:
            messagebox.showerror("Discord error", f"Couldn't connect to Discord:\n{e}")
            return

        self.running = True
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.cid_entry.configure(state="disabled")
        self.log(f"Connected to Discord. Tracking CID {cid}…")

        self.poll_thread = threading.Thread(target=self.poll_loop, args=(cid,), daemon=True)
        self.poll_thread.start()

    def stop(self):
        self.running = False
        if self.rpc:
            try:
                self.rpc.clear()
                self.rpc.close()
            except Exception:
                pass
            self.rpc = None
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.cid_entry.configure(state="normal")
        self.log("Stopped.")

    def poll_loop(self, cid: str):
        while self.running:
            try:
                pilot = fetch_pilot_by_cid(cid)

                if pilot is None:
                    self.log(f"CID {cid} not found on network")
                    self.rpc.update(
                        details=f"CID {cid} — Offline",
                        state="Not connected to VATSIM",
                        large_image="vatsim",
                        large_text="VATSIM",
                    )
                else:
                    f      = parse_flight(pilot)
                    phase  = flight_phase(f["groundspeed"], f["altitude"])
                    reg    = f" · {f['registration']}" if f["registration"] else ""
                    alt_ft = f"{f['altitude']:,}"

                    details    = f"{f['callsign']}  ✈  {f['departure']} → {f['arrival']}"
                    state      = f"{f['aircraft']}{reg}  ·  {f['groundspeed']} kt  ·  {alt_ft} ft"
                    large_text = f"VATSIM · {f['flight_rules']} · {phase}"

                    self.rpc.update(
                        details=details,
                        state=state,
                        large_image="vatsim",
                        large_text=large_text,
                        small_image=phase.lower().replace(" ", "_"),
                        small_text=phase,
                        start=int(time.time()),
                        buttons=[{"label": "View on VATSIM",
                                  "url": f"https://map.vatsim.net/?callsign={f['callsign']}"}],
                    )
                    self.log(f"{details}")
                    self.log(f"  {state}")

            except requests.RequestException as e:
                self.log(f"Network error: {e}")
            except Exception as e:
                self.log(f"Error: {e}")

            for _ in range(POLL_SECONDS * 10):
                if not self.running:
                    break
                time.sleep(0.1)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
