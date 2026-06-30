import os
import shutil
import threading
import subprocess
import tempfile
import zipfile
import io
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from PIL import Image
import pikepdf

# Define compression profiles
PROFILES = {
    "High Compression (Low Quality)": {"img_q": 50, "vid_crf": "32", "aud_b": "64k"},
    "Medium Compression (Balanced)":  {"img_q": 70, "vid_crf": "28", "aud_b": "128k"},
    "Low Compression (High Quality)": {"img_q": 90, "vid_crf": "23", "aud_b": "192k"},
    "Skip (No Compression)": None
}

# Standard fonts
FONT_MAIN = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_LOG = ("Consolas", 9)

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        
        # Make canvas background match ttk frame background
        bg_color = ttk.Style().lookup('TFrame', 'background')
        
        canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0, bg=bg_color)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

class AdvancedCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Advanced Universal File Compressor")
        self.root.geometry("850x700")
        self.root.minsize(800, 650)
        
        # Apply some global styles
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        
        style.configure("TButton", font=FONT_MAIN, padding=5)
        style.configure("Accent.TButton", font=FONT_BOLD, padding=6)
        style.configure("TLabel", font=FONT_MAIN)
        style.configure("Header.TLabel", font=FONT_BOLD)
        style.configure("TCheckbutton", font=FONT_MAIN)

        self.target_folder = ""
        self.folder_profiles = {}  
        self.is_processing = False

        self.setup_ui()

    def setup_ui(self):
        # --- HEADER ---
        frame_header = ttk.Frame(self.root, padding=(20, 15, 20, 5))
        frame_header.pack(fill=tk.X)
        
        ttk.Label(frame_header, text="Universal File Compressor", font=FONT_TITLE).pack(side=tk.LEFT)

        # --- TOP SELECTION FRAME ---
        frame_top = ttk.Frame(self.root, padding=(20, 10))
        frame_top.pack(fill=tk.X)

        self.btn_select = ttk.Button(frame_top, text="Select Root Folder", command=self.select_folder, width=20)
        self.btn_select.pack(side=tk.LEFT, padx=(0, 10))

        # Read-only entry for folder path (looks better than a label for long paths)
        self.folder_var = tk.StringVar(value="No folder selected...")
        self.entry_folder = ttk.Entry(frame_top, textvariable=self.folder_var, state="readonly", font=FONT_MAIN)
        self.entry_folder.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 15))

        self.overwrite_var = tk.BooleanVar(value=False)
        self.chk_overwrite = ttk.Checkbutton(frame_top, text="Overwrite Original Files", variable=self.overwrite_var)
        self.chk_overwrite.pack(side=tk.RIGHT)

        # --- MIDDLE FRAME (Scrollable) ---
        frame_middle = ttk.LabelFrame(self.root, text=" Per-Folder Compression Settings ", padding=(10, 10))
        frame_middle.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        self.scroll_frame = ScrollableFrame(frame_middle)
        self.scroll_frame.pack(fill=tk.BOTH, expand=True)
        self.folder_ui_container = self.scroll_frame.scrollable_frame

        # Initial placeholder text
        ttk.Label(self.folder_ui_container, text="Select a folder above to see subfolders here.", foreground="gray").grid(row=0, column=0, padx=10, pady=10)

        # --- BOTTOM FRAME (Controls & Logs) ---
        frame_bottom = ttk.Frame(self.root, padding=(20, 10, 20, 20))
        frame_bottom.pack(fill=tk.X)

        self.btn_start = ttk.Button(frame_bottom, text="Start Compression", command=self.start_compression, style="Accent.TButton", state=tk.DISABLED)
        self.btn_start.pack(pady=(0, 10), fill=tk.X)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_bottom, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.lbl_status = ttk.Label(frame_bottom, text="Ready.", font=("Segoe UI", 9, "italic"), foreground="#555555")
        self.lbl_status.pack(pady=(0, 10))

        # Styled Terminal-like Log Area
        self.log_area = scrolledtext.ScrolledText(
            frame_bottom, height=10, state=tk.DISABLED, 
            font=FONT_LOG, bg="#1e1e1e", fg="#d4d4d4", 
            insertbackground="white", padx=10, pady=10
        )
        self.log_area.pack(fill=tk.X)

    def log(self, message):
        def update():
            self.log_area.config(state=tk.NORMAL)
            self.log_area.insert(tk.END, message + "\n")
            self.log_area.see(tk.END)
            self.log_area.config(state=tk.DISABLED)
        self.root.after(0, update)

    def update_status(self, text, progress):
        def update():
            self.lbl_status.config(text=text)
            self.progress_var.set(progress)
        self.root.after(0, update)

    def select_folder(self):
        folder = filedialog.askdirectory(title="Select Root Folder")
        if folder:
            self.target_folder = os.path.abspath(folder)
            self.folder_var.set(self.target_folder)
            self.build_folder_list()
            self.btn_start.config(state=tk.NORMAL)

    def build_folder_list(self):
        for widget in self.folder_ui_container.winfo_children():
            widget.destroy()
        self.folder_profiles.clear()

        dirs_to_list = [self.target_folder]
        for root, dirs, files in os.walk(self.target_folder):
            for d in dirs:
                dirs_to_list.append(os.path.abspath(os.path.join(root, d)))

        ttk.Label(self.folder_ui_container, text="Target Folder", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=5, pady=(0, 10))
        ttk.Label(self.folder_ui_container, text="Compression Profile", style="Header.TLabel").grid(row=0, column=1, sticky="w", padx=15, pady=(0, 10))

        for i, dir_path in enumerate(dirs_to_list):
            row = i + 1
            if dir_path == self.target_folder:
                display_name = "[ROOT FOLDER]"
                lbl_font = FONT_BOLD
            else:
                display_name = "   " + os.path.relpath(dir_path, self.target_folder)
                lbl_font = FONT_MAIN

            lbl = ttk.Label(self.folder_ui_container, text=display_name, width=60, anchor="w", wraplength=450, font=lbl_font)
            lbl.grid(row=row, column=0, sticky="w", padx=5, pady=4)

            var = tk.StringVar(value="Medium Compression (Balanced)")
            combo = ttk.Combobox(self.folder_ui_container, textvariable=var, values=list(PROFILES.keys()), state="readonly", width=35, font=FONT_MAIN)
            combo.grid(row=row, column=1, padx=15, pady=4)

            self.folder_profiles[dir_path] = var

    def check_ffmpeg(self):
        try:
            subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except FileNotFoundError:
            return False

    def start_compression(self):
        if not self.check_ffmpeg():
            messagebox.showwarning("Warning", "FFmpeg is not installed or not in PATH.\n\nMedia (Audio/Video) compression will fail, but documents and images will still process.")

        is_overwrite = self.overwrite_var.get()
        if is_overwrite:
            confirm = messagebox.askyesno("Warning", "OVERWRITE MODE ENABLED\n\nOriginal files will be permanently replaced.\nPlease ensure you have backups if needed.\n\nContinue?")
            if not confirm:
                return

        self.btn_select.config(state=tk.DISABLED)
        self.btn_start.config(state=tk.DISABLED)
        self.chk_overwrite.config(state=tk.DISABLED)
        self.is_processing = True
        
        self.log_area.config(state=tk.NORMAL)
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state=tk.DISABLED)

        active_profiles = {path: var.get() for path, var in self.folder_profiles.items()}

        thread = threading.Thread(target=self.process_folder, args=(active_profiles, is_overwrite))
        thread.start()

    def process_folder(self, active_profiles, is_overwrite):
        output_base_folder = self.target_folder + "_compressed"
        
        all_files = []
        for root, dirs, files in os.walk(self.target_folder):
            for file in files:
                all_files.append(os.path.abspath(os.path.join(root, file)))

        total_files = len(all_files)
        if total_files == 0:
            self.log("[INFO] No files found in selected directory.")
            self.finish_processing()
            return

        self.log(f"[START] Processing {total_files} files...")

        for index, file_path in enumerate(all_files):
            parent_dir = os.path.abspath(os.path.dirname(file_path))
            profile_name = active_profiles.get(parent_dir, "Medium Compression (Balanced)")
            profile_settings = PROFILES[profile_name]

            filename = os.path.basename(file_path)
            ext = file_path.lower().split('.')[-1]
            
            self.update_status(f"Processing ({index+1}/{total_files}): {filename}", (index / total_files) * 100)

            is_text_file = ext in ['txt', 'csv', 'log', 'json', 'xml']

            if is_overwrite:
                if is_text_file:
                    out_path = file_path + ".zip"
                else:
                    fd, out_path = tempfile.mkstemp(suffix=f".{ext}")
                    os.close(fd)
            else:
                rel_path = os.path.relpath(file_path, self.target_folder)
                if is_text_file:
                    rel_path += ".zip"
                out_path = os.path.join(output_base_folder, rel_path)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

            if profile_settings is None:
                if not is_overwrite:
                    shutil.copy2(file_path, out_path.replace('.zip', '') if is_text_file else out_path)
                    self.log(f"[SKIPPED] Copied: {filename}")
                else:
                    if not is_text_file: os.remove(out_path)
                    self.log(f"[SKIPPED] Ignored: {filename}")
                continue

            success = False
            try:
                if ext in ['jpg', 'jpeg', 'png', 'webp']:
                    self.compress_image(file_path, out_path, profile_settings["img_q"])
                    success = True
                elif ext == 'pdf':
                    self.compress_pdf(file_path, out_path)
                    success = True
                elif ext in ['mp4', 'avi', 'mkv', 'mov']:
                    self.compress_video(file_path, out_path, profile_settings["vid_crf"])
                    success = True
                elif ext in ['mp3', 'wav', 'm4a', 'aac']:
                    self.compress_audio(file_path, out_path, profile_settings["aud_b"])
                    success = True
                elif ext in ['docx', 'xlsx', 'pptx']:
                    self.compress_office_file(file_path, out_path, profile_settings["img_q"])
                    success = True
                elif is_text_file:
                    self.compress_text_to_zip(file_path, out_path)
                    success = True
                else:
                    if not is_overwrite:
                        shutil.copy2(file_path, out_path)
                    success = True
                    self.log(f"[COPIED] Unsupported file: {filename}")
                    continue

                if success:
                    self.log(f"[COMPRESSED] {filename}")
                    if is_overwrite:
                        if is_text_file:
                            os.remove(file_path) 
                        else:
                            shutil.move(out_path, file_path) 

            except Exception as e:
                self.log(f"[FAILED] {filename}: {str(e)}")
                if is_overwrite and os.path.exists(out_path):
                    os.remove(out_path) 
                elif not is_overwrite:
                    try:
                        shutil.copy2(file_path, out_path.replace('.zip', '') if is_text_file else out_path)
                    except:
                        pass

        self.update_status("Compression Complete!", 100)
        self.log("\n[DONE] --- All processes finished successfully ---")
        self.finish_processing()

    def finish_processing(self):
        def update():
            self.btn_select.config(state=tk.NORMAL)
            self.btn_start.config(state=tk.NORMAL)
            self.chk_overwrite.config(state=tk.NORMAL)
            self.is_processing = False
            messagebox.showinfo("Success", "Process completed successfully!")
        self.root.after(0, update)

    # --- COMPRESSION LOGIC ---

    def compress_image(self, input_path, output_path, quality):
        with Image.open(input_path) as img:
            if img.mode in ("RGBA", "P") and output_path.lower().endswith(('jpg', 'jpeg')):
                img = img.convert("RGB")
            img.save(output_path, optimize=True, quality=quality)

    def compress_pdf(self, input_path, output_path):
        with pikepdf.open(input_path) as pdf:
            pdf.save(output_path, compress_streams=True)

    def compress_video(self, input_path, output_path, crf):
        cmd = ["ffmpeg", "-y", "-i", input_path, "-vcodec", "libx264", "-crf", crf, output_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    def compress_audio(self, input_path, output_path, bitrate):
        cmd = ["ffmpeg", "-y", "-i", input_path, "-b:a", bitrate, output_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    def compress_office_file(self, input_path, output_path, quality):
        with zipfile.ZipFile(input_path, 'r') as zin:
            with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    buffer = zin.read(item.filename)
                    if item.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                        try:
                            img = Image.open(io.BytesIO(buffer))
                            out_io = io.BytesIO()
                            img_format = img.format if img.format else 'JPEG'
                            img.save(out_io, format=img_format, optimize=True, quality=quality)
                            buffer = out_io.getvalue()
                        except Exception:
                            pass
                    zout.writestr(item, buffer)

    def compress_text_to_zip(self, input_path, output_path):
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(input_path, os.path.basename(input_path))

if __name__ == "__main__":
    root = tk.Tk()
    app = AdvancedCompressorApp(root)
    root.mainloop()
