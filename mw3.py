import ee as ee
import mw as mw
import zlib
import xxhash
import struct
import sys
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk
from pathlib import Path

# ─────────────────────────────────────────────
# OFFSETS
# ─────────────────────────────────────────────

offset_crc_np = [
    0x0000, 0x17EC-4, 0xA294-4, 0xD264-4, 0x10BC4-4, 0x13B94-4,
    0x1669C-4, 0x18CD8, 0x1C638, 0x1F608, 0x26D90, 0x29D60,
    0x2A228, 0x319B0, 0x344BC-4, 0x3CA98, 0x3F5A0, 0x48048,
    0x4AB50, 0x54918, 0x5AD80, 0x611E8,
]

offset_crc_mp = [
    0x0000, 0x17E8, 0xA290, 0xD260, 0x10BC0, 0x13B90, 0x16698,
    0x191A0, 0x1CB00, 0x1FAD0, 0x27258, 0x2A228, 0x319B0, 0x344B8,
    0x3CF60, 0x3FA68, 0x48EA0, 0x4B9A8, 0x4F308, 0x55770, 0x5BBD8,
    0x62040,
]

offset_xx_np = [
    (0x15, 0x11DC), (0x17FD, 0x8078), (0xA2A5, 0x247B), (0xD275, 0x247B),
    (0x10BD5, 0x23FF), (0x13BA5, 0x263B), (0x166AD, 0x247B), (0x18CED, 0x3891),
    (0x1C64D, 0x247B), (0x1F61D, 0x6312), (0x26DA5, 0x263B), (0x29D75, 0x02C3),
    None, None,
    (0x344CD, 0x80BA), (0x3CAAD, 0x25D7), (0x3F5B5, 0x81BA),
    (0x4805D, 0x247B), (0x4AB65, 0x247B), None, (0x5AD95, 0x1420),
]

offset_xx_mp = [
    (0x0015, 0x1287), (0x17FD, 0x888C), (0xA2A5, 0x2791), (0xD275, 0x2791),
    (0x10BD5, 0x2715), (0x13BA5, 0x2951), (0x166AD, 0x2791), (0x191B5, 0x3919),
    (0x1CB15, 0x2791), (0x1FAE5, 0x6B2B), (0x2726D, 0x2951),
    None, None,
    (0x344CD, 0x88CE), (0x3CF75, 0x28ED), (0x3FA7D, 0x8FEB),
    (0x48EB5, 0x2791), (0x4B9BD, 0x2791), (0x4F31D, 0x0DD4),
    None, (0x5BBED, 0x1A60),
]

# ─────────────────────────────────────────────
# CHECKSUM HELPERS
# ─────────────────────────────────────────────

def update_crc32(data, offset_crc):
    for i in range(len(offset_crc) - 1):
        crc_offset = offset_crc[i]
        start = crc_offset + 4
        end   = offset_crc[i + 1]
        crc   = zlib.crc32(data[start:end]) & 0xFFFFFFFF
        struct.pack_into('<I', data, crc_offset, crc)
    return data

def update_xxhash(data, offset_xx, offset_crc):
    for i, entry in enumerate(offset_xx):
        if entry is None:
            continue
        hash_offset, rel_end = entry
        start  = hash_offset + 5
        end    = offset_crc[i] + rel_end
        digest = xxhash.xxh32(data[start:end], seed=0).intdigest()
        struct.pack_into('<I', data, hash_offset, digest)
    return data

# ─────────────────────────────────────────────
# FILE HELPERS
# ─────────────────────────────────────────────

def read_file(path):
    if path is None or not Path(path).is_file():
        return None
    with open(path, 'rb') as f:
        return f.read()

def write_file(data, path):
    if data is None or path is None:
        return
    with open(path, 'wb') as f:
        f.write(data)
    return True

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).parent

# ─────────────────────────────────────────────
# LOGIC
# ─────────────────────────────────────────────

def do_unpack(log):
    packed_path = filedialog.askopenfilename(
        title='Select your memory.dat',
        initialfile='memory.dat',
        filetypes=[("DAT files", "*.dat"), ("All files", "*.*")]
    )
    if not packed_path:
        return

    output_dir = get_base_dir() / "unpacked"
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        log("Unpacking memory.dat …")
        ee.unpack(packed_path, out_dir=str(output_dir))

        for name, label in [("npdata", "NP"), ("mpdata", "MP")]:
            p = output_dir / name
            if p.exists():
                log(f"Decompressing {label} data …")
                data = read_file(p)
                decompressed, _ = mw.decompress_file(data)
                write_file(decompressed, output_dir / f"{name}_decompressed.bin")
                log(f"  → {name}_decompressed.bin saved.")

        log(f"Done! Files saved to:\n  {output_dir}")
        messagebox.showinfo("Unpack Complete", f"Files saved to:\n{output_dir}")

    except Exception as e:
        log(f"ERROR: {e}")
        messagebox.showerror("Error", f"An error occurred:\n{e}")


def do_repack(log):
    packed_path = filedialog.askopenfilename(
        title='Select original memory.dat',
        initialfile='memory.dat',
        filetypes=[("DAT files", "*.dat")]
    )
    if not packed_path:
        return

    output_dir = get_base_dir() / "unpacked"
    edited = []

    pairs = [
        ("npdata", offset_crc_np, offset_xx_np),
        ("mpdata", offset_crc_mp, offset_xx_mp),
    ]

    try:
        for name, crc_offsets, xx_offsets in pairs:
            orig  = output_dir / name
            decomp = output_dir / f"{name}_decompressed.bin"
            if not (orig.exists() and decomp.exists()):
                continue

            log(f"Fixing checksums for {name} …")
            data_original = read_file(orig)
            mutable = bytearray(read_file(decomp))
            mutable = update_crc32(mutable, crc_offsets)
            mutable = update_xxhash(mutable, xx_offsets, crc_offsets)

            log(f"Compressing {name} …")
            recompressed = mw.compress_file(mutable, data_original)
            tmp = output_dir / f"{name}_repacked.tmp"
            write_file(recompressed, tmp)
            edited.append(str(tmp))
            log(f"  → {tmp.name} ready.")

        if edited:
            log("Injecting and repacking memory.dat …")
            ee.repack(packed_path, *edited)
            log("Done! Created memory_repacked.dat")
            messagebox.showinfo("Repack Complete", "Repack successful!\nCreated memory_repacked.dat")
        else:
            log("No decompressed files found to repack.")
            messagebox.showwarning("Nothing to Repack",
                "No decompressed files were found.\nRun Unpack first.")

    except Exception as e:
        log(f"ERROR: {e}")
        messagebox.showerror("Repack Error", f"Failed to repack:\n{e}")


# ─────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────

DARK_BG   = "#1a1a2e"
PANEL_BG  = "#16213e"
CARD_BG   = "#0f3460"
ACCENT    = "#e94560"
ACCENT2   = "#4a9eff"
TEXT      = "#e0e0e0"
TEXT_DIM  = "#8899aa"
BTN_FG    = "#ffffff"
MONO      = ("Consolas", 9)
SANS      = ("Segoe UI", 10)
SANS_SM   = ("Segoe UI", 9)
HEADER    = ("Segoe UI Semibold", 11)


def build_gui():
    root = tk.Tk()
    root.title("MW3 Memory Tool")
    root.configure(bg=DARK_BG)
    root.resizable(False, False)

    # ── title bar ──────────────────────────────
    title_frame = tk.Frame(root, bg=ACCENT, height=4)
    title_frame.pack(fill="x")

    header = tk.Frame(root, bg=DARK_BG, pady=14, padx=24)
    header.pack(fill="x")
    tk.Label(header, text="MW3 Memory Tool",
             font=("Segoe UI Semibold", 16), fg=TEXT, bg=DARK_BG).pack(side="left")
    tk.Label(header, text="v1.0",
             font=SANS_SM, fg=TEXT_DIM, bg=DARK_BG).pack(side="left", padx=(8, 0), pady=(4, 0))

    # ── main body ──────────────────────────────
    body = tk.Frame(root, bg=DARK_BG, padx=20, pady=0)
    body.pack(fill="both", expand=True)

    # ── two side-by-side cards ─────────────────
    cards = tk.Frame(body, bg=DARK_BG)
    cards.pack(fill="x")

    def make_card(parent, title, color, steps, btn_text, btn_color, cmd):
        card = tk.Frame(parent, bg=PANEL_BG, padx=18, pady=16,
                        highlightbackground=color, highlightthickness=1,
                        relief="flat")
        card.pack(side="left", fill="both", expand=True, padx=(0, 8) if btn_text == "Unpack" else (8, 0))

        # card header
        hdr = tk.Frame(card, bg=PANEL_BG)
        hdr.pack(fill="x", pady=(0, 10))
        indicator = tk.Frame(hdr, bg=color, width=3, height=18)
        indicator.pack(side="left", padx=(0, 8))
        tk.Label(hdr, text=title, font=HEADER, fg=TEXT, bg=PANEL_BG).pack(side="left")

        # instructions
        inst_frame = tk.Frame(card, bg=CARD_BG, padx=10, pady=10)
        inst_frame.pack(fill="x", pady=(0, 14))
        tk.Label(inst_frame, text="Instructions", font=("Segoe UI Semibold", 9),
                 fg=color, bg=CARD_BG).pack(anchor="w")
        for step in steps:
            row = tk.Frame(inst_frame, bg=CARD_BG)
            row.pack(fill="x", pady=1)
            num, text = step
            tk.Label(row, text=num, font=("Segoe UI Semibold", 9),
                     fg=color, bg=CARD_BG, width=2).pack(side="left", anchor="nw")
            tk.Label(row, text=text, font=SANS_SM, fg=TEXT_DIM, bg=CARD_BG,
                     wraplength=210, justify="left").pack(side="left", anchor="nw")

        # button
        btn = tk.Button(card, text=btn_text, font=("Segoe UI Semibold", 10),
                        bg=btn_color, fg=BTN_FG, activebackground=color,
                        activeforeground=BTN_FG, relief="flat", cursor="hand2",
                        padx=14, pady=8, bd=0, command=cmd)
        btn.pack(fill="x")
        return card

    unpack_steps = [
        ("1.", "Click Unpack and select your original memory.dat file."),
        ("2.", "The tool will extract and decompress npdata and mpdata."),
        ("3.", "Decompressed .bin files appear in the unpacked/ folder next to this tool."),
        ("4.", "Edit the .bin files with your preferred hex editor."),
    ]

    repack_steps = [
        ("1.", "Make sure you ran Unpack first and have edited the .bin files."),
        ("2.", "Click Repack and select the original (unmodified) memory.dat."),
        ("3.", "Make sure the .bin files are in the unpacked/ folder."),
        ("4.", "A new memory_repacked.dat is created — use it on your console."),
    ]

    def unpack_cmd():
        do_unpack(log)

    def repack_cmd():
        do_repack(log)

    make_card(cards, "Unpack", ACCENT2, unpack_steps, "Unpack", "#1a6fb5", unpack_cmd)
    make_card(cards, "Repack", ACCENT,  repack_steps, "Repack", "#b52a3a", repack_cmd)

    # ── log area ───────────────────────────────
    log_label = tk.Frame(body, bg=DARK_BG, pady=(8))
    log_label.pack(fill="x", pady=(14, 4))
    indicator2 = tk.Frame(log_label, bg=TEXT_DIM, width=3, height=14)
    indicator2.pack(side="left", padx=(0, 8))
    tk.Label(log_label, text="Log", font=HEADER, fg=TEXT_DIM, bg=DARK_BG).pack(side="left")

    log_box = tk.Text(body, height=8, bg="#0d0d1a", fg="#5dfc8d",
                      font=MONO, relief="flat", bd=0, padx=10, pady=8,
                      state="disabled", wrap="word",
                      insertbackground=TEXT, selectbackground=CARD_BG)
    log_box.pack(fill="x", pady=(0, 6))

    # scrollbar
    sb = ttk.Scrollbar(body, orient="vertical", command=log_box.yview)
    log_box.configure(yscrollcommand=sb.set)

    def log(msg):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update_idletasks()

    # ── footer ─────────────────────────────────
    footer = tk.Frame(root, bg=DARK_BG, pady=10)
    footer.pack(fill="x")
    tk.Label(footer, text="Unpacked files are stored in  unpacked/  beside this script.",
             font=SANS_SM, fg=TEXT_DIM, bg=DARK_BG).pack()

    # center window
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth()  - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"+{x}+{y}")

    root.mainloop()


if __name__ == "__main__":
    build_gui()