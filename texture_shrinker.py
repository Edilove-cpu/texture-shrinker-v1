"""
Texture Shrinker - baja la resolución de las texturas de los juegos que elijas.
Soporta carpetas sueltas y también paquetes (desempaqueta, reduce y vuelve a empaquetar).

Requisitos:  pip install pillow
Opcional:
  - texconv.exe (DirectXTex) para texturas .dds
  - quickbms.exe + script .bms del juego para paquetes que no son ZIP
Ejecutar:    python texture_shrinker.py
"""
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image # type: ignore

Image.MAX_IMAGE_PIXELS = None
BACKUP_DIR = "_texture_backup"
IMG_EXT = {".png", ".jpg", ".jpeg", ".tga", ".bmp"}
TEX_EXT = IMG_EXT | {".dds"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def parse_exts(text):
    return {("." + e.strip().lstrip(".")).lower() for e in text.replace(",", " ").split() if e.strip()}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Texture Shrinker")
        self.geometry("760x760")
        self.games = []
        self.stop = False
        self.dsr_stop = False

        # Contenedor desplazable para que el apartado DSR también quepa en pantallas pequeñas.
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        notebook = ttk.Notebook(canvas)
        canvas_window = canvas.create_window((0, 0), window=notebook, anchor="nw")
        notebook.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        top = ttk.Frame(notebook, padding=10)
        extreme_tab = ttk.Frame(notebook, padding=14)
        notebook.add(top, text="Modo normal")
        notebook.add(extreme_tab, text="🔥 Downgrade EXTREMO")

        ttk.Label(top, text="Juegos seleccionados:").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x")
        self.lb = tk.Listbox(row, height=5)
        self.lb.pack(side="left", fill="both", expand=True)
        btns = ttk.Frame(row)
        btns.pack(side="left", padx=6)
        ttk.Button(btns, text="Añadir juego…", command=self.add_game).pack(fill="x")
        ttk.Button(btns, text="Quitar", command=self.remove_game).pack(fill="x", pady=4)

        # ---- opciones generales
        opts = ttk.LabelFrame(top, text="Opciones", padding=8)
        opts.pack(fill="x", pady=6)
        ttk.Label(opts, text="Escala:").grid(row=0, column=0, sticky="w")
        self.scale = tk.StringVar(value="50%")
        ttk.Combobox(opts, textvariable=self.scale, state="readonly", width=8,
                     values=["75%", "50%", "25%", "12.5%"]).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(opts, text="Ignorar menores de (px):").grid(row=0, column=2, padx=(20, 0))
        self.minpx = tk.IntVar(value=128)
        ttk.Spinbox(opts, from_=4, to=4096, textvariable=self.minpx, width=6).grid(row=0, column=3, padx=6)
        self.backup = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="Guardar copia de seguridad de los originales",
                        variable=self.backup).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.texconv = tk.StringVar()
        ttk.Label(opts, text="texconv.exe (para .dds):").grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Entry(opts, textvariable=self.texconv, width=52).grid(row=3, column=0, columnspan=3, sticky="we")
        ttk.Button(opts, text="Buscar…", command=lambda: self.pick(self.texconv, "texconv.exe")).grid(row=3, column=3, padx=6)

        # ---- paquetes
        pk = ttk.LabelFrame(top, text="Desempaquetar paquetes del juego", padding=8)
        pk.pack(fill="x", pady=6)

        self.use_zip = tk.BooleanVar(value=True)
        ttk.Checkbutton(pk, text="Paquetes ZIP (integrado, sin herramientas extra)",
                        variable=self.use_zip).grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(pk, text="Extensiones:").grid(row=1, column=0, sticky="w")
        self.zip_exts = tk.StringVar(value=".zip .pk3 .pk4 .pak .pk7 .xpi")
        ttk.Entry(pk, textvariable=self.zip_exts, width=40).grid(row=1, column=1, sticky="we", padx=6)

        self.use_bms = tk.BooleanVar(value=False)
        ttk.Checkbutton(pk, text="Otros formatos con QuickBMS (necesita el script .bms del juego)",
                        variable=self.use_bms).grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.qb = tk.StringVar()
        self.bms = tk.StringVar()
        self.bms_exts = tk.StringVar(value=".bnd .pak .arc .bin")
        ttk.Label(pk, text="quickbms.exe:").grid(row=3, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.qb, width=40).grid(row=3, column=1, sticky="we", padx=6)
        ttk.Button(pk, text="Buscar…", command=lambda: self.pick(self.qb, "quickbms.exe")).grid(row=3, column=2)
        ttk.Label(pk, text="Script .bms:").grid(row=4, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.bms, width=40).grid(row=4, column=1, sticky="we", padx=6)
        ttk.Button(pk, text="Buscar…", command=lambda: self.pick(self.bms, "script .bms")).grid(row=4, column=2)
        ttk.Label(pk, text="Extensiones:").grid(row=5, column=0, sticky="w")
        ttk.Entry(pk, textvariable=self.bms_exts, width=40).grid(row=5, column=1, sticky="we", padx=6)
        pk.columnconfigure(1, weight=1)

        # ---- acciones
        act = ttk.Frame(top)
        act.pack(fill="x", pady=4)
        self.run_btn = ttk.Button(act, text="Reducir texturas", command=self.start)
        self.run_btn.pack(side="left")
        ttk.Button(act, text="Restaurar originales", command=self.restore).pack(side="left", padx=6)
        ttk.Button(act, text="Cancelar", command=lambda: setattr(self, "stop", True)).pack(side="left")

        self.bar = ttk.Progressbar(top, mode="determinate")
        self.bar.pack(fill="x", pady=6)
        # ---- flujo dedicado para Dark Souls Remastered (DSR-TPUP)
        dsr = ttk.LabelFrame(top, text="Dark Souls Remastered — DSR Texture Packer & Unpacker", padding=8)
        dsr.pack(fill="x", pady=6)
        self.dsr_unpacker = tk.StringVar()
        self.dsr_game_dir = tk.StringVar()
        self.dsr_dump_dir = tk.StringVar()
        self.dsr_override_dir = tk.StringVar()

        ttk.Label(dsr, text="Ejecutable del DSR Texture Packer & Unpacker:").grid(row=0, column=0, sticky="w")
        ttk.Entry(dsr, textvariable=self.dsr_unpacker).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dsr, text="Buscar…", command=lambda: self.pick_exe(self.dsr_unpacker, "Selecciona el ejecutable del DSR Texture Packer & Unpacker")).grid(row=1, column=1)

        ttk.Label(dsr, text="Carpeta del juego (contiene DarkSoulsRemastered.exe):").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(dsr, textvariable=self.dsr_game_dir).grid(row=3, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dsr, text="Buscar…", command=lambda: self.pick_dir(self.dsr_game_dir, "Selecciona la carpeta de Dark Souls Remastered")).grid(row=3, column=1)

        ttk.Label(dsr, text="Carpeta de texturas extraídas (Dump):").grid(row=4, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(dsr, textvariable=self.dsr_dump_dir).grid(row=5, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dsr, text="Buscar…", command=lambda: self.pick_dir(self.dsr_dump_dir, "Selecciona la carpeta Dump de DSR-TPUP")).grid(row=5, column=1)

        ttk.Label(dsr, text="Carpeta de salida para texturas reducidas (Override):").grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(dsr, textvariable=self.dsr_override_dir).grid(row=7, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(dsr, text="Buscar…", command=lambda: self.pick_dir(self.dsr_override_dir, "Selecciona la carpeta Texture Override de DSR-TPUP")).grid(row=7, column=1)

        dsr_actions = ttk.Frame(dsr)
        dsr_actions.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Button(dsr_actions, text="Abrir unpacker", command=self.launch_dsr_unpacker).pack(side="left")
        self.dsr_run_btn = ttk.Button(dsr_actions, text="Reducir texturas extraídas", command=self.start_dsr)
        self.dsr_run_btn.pack(side="left", padx=6)
        ttk.Button(dsr_actions, text="EXTREMO", command=lambda: self.start_dsr(extreme=True)).pack(side="left")
        ttk.Label(dsr, text="Flujo: abrir TPUP y pulsar Unpack → reducir aquí → volver a TPUP y pulsar Repack.",
                  foreground="#555555", wraplength=650).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        dsr.columnconfigure(0, weight=1)

        self.log = tk.Text(top, height=8, state="disabled")
        self.log.pack(fill="both", expand=True)

        # ---- pestaña de downgrade extremo
        ttk.Label(extreme_tab, text="MODO EXTREMO: calidad visual al mínimo", font=("TkDefaultFont", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.Label(
            extreme_tab,
            text=("Usa una escala fija del 12.5% y procesa texturas desde 4 px en adelante, "
                  "ignorando el umbral normal de 128 px. Esto puede dejar las texturas "
                  "muy borrosas o irreconocibles. Los DDS necesitan texconv.exe.\n\n"
                  "Primero selecciona el juego en la pestaña Modo normal. Activa la copia de "
                  "seguridad antes de empezar. El modo extremo no puede modificar formatos "
                  "que el programa no soporte ni texturas empaquetadas en formatos no configurados."),
            wraplength=650, justify="left").pack(anchor="w", fill="x", pady=(0, 12))
        ttk.Label(extreme_tab, text="Ajustes que aplicará: 12.5% de tamaño · umbral mínimo 4 px · copia de seguridad según la opción normal.").pack(anchor="w", pady=(0, 12))
        ttk.Button(extreme_tab, text="💀 EJECUTAR DOWNGRADE EXTREMO", command=lambda: self.start(extreme=True)).pack(anchor="w", pady=4)
        ttk.Button(extreme_tab, text="Restaurar originales", command=self.restore).pack(anchor="w", pady=4)

    # ---------- UI helpers ----------
    def say(self, msg):
        def _w():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.after(0, _w)

    def add_game(self):
        d = filedialog.askdirectory(title="Carpeta del juego")
        if d and d not in self.games:
            self.games.append(d)
            self.lb.insert("end", d)

    def remove_game(self):
        for i in reversed(self.lb.curselection()):
            self.lb.delete(i)
            del self.games[i]

    def pick(self, var, title):
        f = filedialog.askopenfilename(title=title)
        if f:
            var.set(f)

    def pick_exe(self, var, title):
        f = filedialog.askopenfilename(title=title, filetypes=[("Aplicaciones", "*.exe"), ("Todos los archivos", "*.*")])
        if f:
            var.set(f)
            # Sugiere las carpetas habituales junto al ejecutable; el usuario puede corregirlas.
            base = os.path.dirname(f)
            if not self.dsr_dump_dir.get():
                for name in ("Texture Dump", "Dump", "dump"):
                    candidate = os.path.join(base, name)
                    if os.path.isdir(candidate):
                        self.dsr_dump_dir.set(candidate)
                        break
            if not self.dsr_override_dir.get():
                for name in ("Texture Override", "Override", "override"):
                    candidate = os.path.join(base, name)
                    if os.path.isdir(candidate):
                        self.dsr_override_dir.set(candidate)
                        break

    def pick_dir(self, var, title):
        d = filedialog.askdirectory(title=title)
        if d:
            var.set(d)

    def factor(self):
        return float(self.scale.get().rstrip("%")) / 100.0

    # ---------- núcleo: reducir un archivo de textura ----------
    def new_size(self, w, h, factor, minpx):
        if max(w, h) <= minpx:
            return None
        nw = max(4, int(w * factor) // 4 * 4)
        nh = max(4, int(h * factor) // 4 * 4)
        return None if (nw, nh) == (w, h) else (nw, nh)

    def backup_file(self, game, path):
        if not self.backup.get():
            return
        dst = os.path.join(game, BACKUP_DIR, os.path.relpath(path, game))
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(path, dst)

    def shrink_file(self, path, factor, minpx, texconv, before=None):
        """Reduce una textura en su sitio. 'before' se llama justo antes de modificarla."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".dds":
            if not texconv or not os.path.isfile(texconv):
                return "dds sin texconv válido"
            # Pillow no lee de forma fiable los DDS modernos de DSR. Usamos texconv
            # para obtener temporalmente un PNG y averiguar las dimensiones.
            with tempfile.TemporaryDirectory(prefix="tshrink_dds_") as tmp:
                probe_dir = os.path.join(tmp, "probe")
                resized_dir = os.path.join(tmp, "resized")
                os.makedirs(probe_dir)
                os.makedirs(resized_dir)
                probe = subprocess.run(
                    [texconv, "-ft", "PNG", "-y", "-nologo", "-o", probe_dir, path],
                    capture_output=True, text=True, creationflags=NO_WINDOW)
                pngs = [os.path.join(probe_dir, n) for n in os.listdir(probe_dir)
                        if n.lower().endswith(".png")]
                if probe.returncode != 0 or not pngs:
                    return "error leyendo DDS con texconv"
                with Image.open(pngs[0]) as im:
                    size = self.new_size(*im.size, factor, minpx)
                if not size:
                    return "omitida"
                resized = subprocess.run(
                    [texconv, "-w", str(size[0]), "-h", str(size[1]), "-m", "0",
                     "-y", "-nologo", "-o", resized_dir, path],
                    capture_output=True, text=True, creationflags=NO_WINDOW)
                dds_files = [os.path.join(resized_dir, n) for n in os.listdir(resized_dir)
                             if n.lower().endswith(".dds")]
                if resized.returncode != 0 or not dds_files:
                    return "error redimensionando DDS con texconv"
                # Reemplazar solo después de que texconv haya generado el resultado.
                if before:
                    before()
                shutil.copy2(dds_files[0], path)
                return "ok"

        with Image.open(path) as im:
            w, h = im.size
            size = self.new_size(w, h, factor, minpx)
            if not size:
                return "omitida"
            fmt = im.format
            res = im.resize(size, Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS)
            if fmt == "JPEG" and res.mode != "RGB":
                res = res.convert("RGB")
            elif fmt == "JPEG" and res.mode == "RGBA":
                res = res.convert("RGB")
        if before:
            before()
        res.save(path, format=fmt)
        return "ok"

    def shrink_tree(self, folder, factor, minpx, texconv):
        changed = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if self.stop:
                    return changed
                if os.path.splitext(f)[1].lower() in TEX_EXT:
                    try:
                        if self.shrink_file(os.path.join(root, f), factor, minpx, texconv) == "ok":
                            changed += 1
                    except Exception as e:
                        self.say(f"    ! {f}: {e}")
        return changed

    # ---------- paquetes ----------
    def process_zip(self, game, path, factor, minpx, texconv):
        tmp = tempfile.mkdtemp(prefix="tshrink_")
        try:
            changed = set()
            extracted_paths = {}
            with zipfile.ZipFile(path) as z:
                infos = z.infolist()
                for info in infos:
                    if self.stop:
                        return "cancelado"
                    if info.is_dir() or os.path.splitext(info.filename)[1].lower() not in TEX_EXT:
                        continue
                    # Let zipfile sanitize the entry path, and retain the actual extracted path.
                    out = z.extract(info, tmp)
                    extracted_paths[info.filename] = out
                    try:
                        if self.shrink_file(out, factor, minpx, texconv) == "ok":
                            changed.add(info.filename)
                    except Exception as e:
                        self.say(f"    ! {info.filename}: {e}")
                if not changed:
                    return "omitida"
                self.backup_file(game, path)
                new_path = path + ".tmp"
                try:
                    with zipfile.ZipFile(new_path, "w") as nz:
                        for info in infos:
                            if info.filename in changed:
                                with open(extracted_paths[info.filename], "rb") as fh:
                                    data = fh.read()
                            else:
                                data = z.read(info)
                            nz.writestr(info, data, compress_type=info.compress_type)
                    os.replace(new_path, path)
                finally:
                    if os.path.exists(new_path):
                        os.remove(new_path)
            return f"ok ({len(changed)} texturas dentro)"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def process_bms(self, game, path, factor, minpx, texconv):
        qb, script = self.qb.get().strip(), self.bms.get().strip()
        if not (os.path.isfile(qb) and os.path.isfile(script)):
            return "falta quickbms o el script"
        tmp = tempfile.mkdtemp(prefix="tshrink_")
        try:
            r = subprocess.run([qb, "-o", script, path, tmp], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=3600, creationflags=NO_WINDOW)
            if r.returncode != 0:
                return "error al extraer"
            changed = self.shrink_tree(tmp, factor, minpx, texconv)
            if not changed:
                return "omitida"
            self.backup_file(game, path)
            r = subprocess.run([qb, "-w", "-r", script, path, tmp], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=3600, creationflags=NO_WINDOW)
            if r.returncode != 0:
                return "error al reempaquetar (¿el script soporta reimportar?)"
            return f"ok ({changed} texturas dentro)"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---------- flujo principal ----------
    def collect(self, game):
        zip_exts = parse_exts(self.zip_exts.get()) if self.use_zip.get() else set()
        bms_exts = parse_exts(self.bms_exts.get()) if self.use_bms.get() else set()
        items = []
        for root, dirs, files in os.walk(game):
            dirs[:] = [d for d in dirs if d != BACKUP_DIR]
            for f in files:
                p = os.path.join(root, f)
                ext = os.path.splitext(f)[1].lower()
                if ext in TEX_EXT:
                    items.append(("tex", p))
                elif ext in zip_exts and zipfile.is_zipfile(p):
                    items.append(("zip", p))
                elif ext in bms_exts:
                    items.append(("bms", p))
        return items

    def start(self, extreme=False):
        if not self.games:
            messagebox.showinfo("Texture Shrinker", "Añade al menos un juego.")
            return
        if not messagebox.askyesno("Confirmar",
                                   "Se modificarán archivos del juego (hay copia de seguridad si la opción está activa).\n"
                                   "Úsalo solo en juegos offline: el anti-cheat puede detectarlo.\n\n¿Continuar?"):
            return
        self.stop = False
        self.run_btn.config(state="disabled")
        threading.Thread(target=self.worker, args=(extreme,), daemon=True).start()

    def worker(self, extreme=False):
        factor, minpx = (0.125, 4) if extreme else (self.factor(), self.minpx.get())
        if extreme:
            self.say("!!! MODO EXTREMO activo: escala 12.5%, umbral mínimo 4 px.")
        texconv = self.texconv.get().strip() or None
        done = skipped = errors = 0
        for game in self.games:
            items = self.collect(game)
            self.say(f"== {game}: {len(items)} archivos a revisar")
            self.after(0, lambda n=len(items): self.bar.config(maximum=max(n, 1), value=0))
            for i, (kind, p) in enumerate(items, 1):
                if self.stop:
                    self.say("Cancelado.")
                    break
                try:
                    if kind == "tex":
                        r = self.shrink_file(p, factor, minpx, texconv,
                                             before=lambda g=game, q=p: self.backup_file(g, q))
                    elif kind == "zip":
                        r = self.process_zip(game, p, factor, minpx, texconv)
                    else:
                        r = self.process_bms(game, p, factor, minpx, texconv)
                    if r.startswith("ok"):
                        done += 1
                        if kind != "tex":
                            self.say(f"  ✓ {os.path.basename(p)}: {r}")
                    else:
                        skipped += 1
                        if r != "omitida":
                            self.say(f"  - {os.path.basename(p)}: {r}")
                except Exception as e:
                    errors += 1
                    self.say(f"  ! {os.path.basename(p)}: {e}")
                self.after(0, lambda v=i: self.bar.config(value=v))
            if self.stop:
                break
        self.say(f"Listo. Reducidos: {done} | Omitidos: {skipped} | Errores: {errors}")
        self.after(0, lambda: self.run_btn.config(state="normal"))

    # ---------- flujo dedicado para Dark Souls Remastered ----------
    def launch_dsr_unpacker(self):
        exe = self.dsr_unpacker.get().strip()
        if not os.path.isfile(exe):
            messagebox.showerror("DSR Texture Shrinker", "Selecciona el ejecutable del DSR Texture Packer & Unpacker.")
            return
        game = self.dsr_game_dir.get().strip()
        if game and not os.path.isfile(os.path.join(game, "DarkSoulsRemastered.exe")):
            if not messagebox.askyesno("Confirmar carpeta", "No encontré DarkSoulsRemastered.exe en esa carpeta. ¿Abrir el unpacker de todos modos?"):
                return
        try:
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
            self.say("DSR Texture Packer & Unpacker abierto. En su ventana configura la carpeta del juego y pulsa Unpack.")
        except Exception as e:
            messagebox.showerror("No se pudo abrir el unpacker", str(e))

    def start_dsr(self, extreme=False):
        exe = self.dsr_unpacker.get().strip()
        game = self.dsr_game_dir.get().strip()
        dump = self.dsr_dump_dir.get().strip()
        override = self.dsr_override_dir.get().strip()
        texconv = self.texconv.get().strip()
        if not os.path.isfile(exe):
            messagebox.showerror("DSR", "Selecciona el ejecutable del DSR Texture Packer & Unpacker.")
            return
        if not os.path.isfile(os.path.join(game, "DarkSoulsRemastered.exe")):
            messagebox.showerror("DSR", "La carpeta del juego debe contener DarkSoulsRemastered.exe.")
            return
        if not os.path.isdir(dump):
            messagebox.showerror("DSR", "Selecciona la carpeta Dump que generó el unpacker. Primero debes abrir TPUP y pulsar Unpack.")
            return
        if not override:
            messagebox.showerror("DSR", "Selecciona la carpeta Texture Override de TPUP.")
            return
        if os.path.abspath(dump) == os.path.abspath(override) or os.path.commonpath([os.path.abspath(dump), os.path.abspath(override)]) == os.path.abspath(dump):
            messagebox.showerror("DSR", "La carpeta Override no puede ser la misma que Dump ni estar dentro de Dump.")
            return
        if os.path.abspath(game) == os.path.abspath(override) or os.path.commonpath([os.path.abspath(game), os.path.abspath(override)]) == os.path.abspath(game):
            messagebox.showerror("DSR", "Por seguridad, elige una carpeta Override fuera de la instalación del juego.")
            return
        if not os.path.isfile(texconv):
            messagebox.showerror("DSR", "Para reducir los DDS de Dark Souls Remastered, selecciona un texconv.exe válido en las opciones generales.")
            return
        if not messagebox.askyesno("Confirmar reducción DSR",
                "Se leerán las texturas de Dump y se escribirán las versiones reducidas en Override. "
                "Si una textura ya existe en Override, se guardará una copia en _texture_shrinker_backup. "
                "No se modificarán directamente los archivos del juego.\n\n¿Continuar?"):
            return
        self.dsr_stop = False
        self.dsr_run_btn.config(state="disabled")
        factor, minpx = (0.125, 4) if extreme else (self.factor(), self.minpx.get())
        threading.Thread(target=self.dsr_worker, args=(dump, override, factor, minpx, texconv, extreme), daemon=True).start()

    def dsr_worker(self, dump, override, factor, minpx, texconv, extreme=False):
        if extreme:
            self.say("!!! MODO EXTREMO DSR activo: escala 12.5%, umbral mínimo 4 px.")
        done = skipped = errors = 0
        jobs = []
        for root, dirs, files in os.walk(dump):
            dirs[:] = [d for d in dirs if d.lower() not in {"_texture_shrinker_backup", "texture override"}]
            for name in files:
                if os.path.splitext(name)[1].lower() in TEX_EXT:
                    src = os.path.join(root, name)
                    rel = os.path.relpath(src, dump)
                    jobs.append((src, rel))
        self.say(f"== Dark Souls Remastered: {len(jobs)} texturas encontradas en Dump")
        self.after(0, lambda n=len(jobs): self.bar.config(maximum=max(n, 1), value=0))
        backup_root = os.path.join(os.path.dirname(os.path.abspath(override)), "_texture_shrinker_backup")
        with tempfile.TemporaryDirectory(prefix="dsr_shrink_work_") as work:
            for i, (src, rel) in enumerate(jobs, 1):
                if self.dsr_stop or self.stop:
                    self.say("Reducción DSR cancelada.")
                    break
                temp_path = os.path.join(work, rel)
                dest = os.path.join(override, rel)
                try:
                    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
                    shutil.copy2(src, temp_path)
                    result = self.shrink_file(temp_path, factor, minpx, texconv)
                    if result == "ok":
                        if os.path.exists(dest):
                            backup = os.path.join(backup_root, rel)
                            os.makedirs(os.path.dirname(backup), exist_ok=True)
                            if not os.path.exists(backup):
                                shutil.copy2(dest, backup)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        shutil.copy2(temp_path, dest)
                        done += 1
                    else:
                        skipped += 1
                        if result != "omitida":
                            self.say(f"  - {rel}: {result}")
                except Exception as e:
                    errors += 1
                    self.say(f"  ! {rel}: {e}")
                self.after(0, lambda v=i: self.bar.config(value=v))
        self.say(f"DSR terminado. Texturas reducidas: {done} | Omitidas: {skipped} | Errores: {errors}")
        self.say("Siguiente paso: abre TPUP, revisa la carpeta Override y usa su pestaña Repack para aplicar los cambios.")
        self.after(0, lambda: self.dsr_run_btn.config(state="normal"))

    def restore(self):
        n = 0
        for game in self.games:
            b = os.path.join(game, BACKUP_DIR)
            if not os.path.isdir(b):
                continue
            for root, _, files in os.walk(b):
                for f in files:
                    src = os.path.join(root, f)
                    dst = os.path.join(game, os.path.relpath(src, b))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    n += 1
        self.say(f"Restauradas {n} archivos originales.")


if __name__ == "__main__":
    App().mainloop()
