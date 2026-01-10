#!/usr/bin/env python3
"""
Запись собеседований с GUI, VU-метром и транскрипцией.

Зависимости:
    sudo apt install ffmpeg python3-tk
    pipx install openai-whisper

Запуск:
    python3 interview_recorder.py
"""

import subprocess
import signal
import time
import threading
import struct
import os
import base64
import json
import requests
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class AudioMeter:
    """Читает уровень звука из PulseAudio."""
    
    def __init__(self, callback):
        self.callback = callback
        self.running = False
        self.process = None
        self.thread = None
        
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._read_audio, daemon=True)
        self.thread.start()
        
    def stop(self):
        self.running = False
        if self.process:
            self.process.terminate()
            self.process = None
            
    def _read_audio(self):
        try:
            sink = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True
            ).stdout.strip()
            
            cmd = [
                "ffmpeg",
                "-f", "pulse", "-i", f"{sink}.monitor",
                "-f", "pulse", "-i", "default",
                "-filter_complex", "amix=inputs=2:duration=longest",
                "-f", "s16le",
                "-ac", "1",
                "-ar", "8000",
                "-"
            ]
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            
            chunk_size = 800
            
            while self.running and self.process:
                data = self.process.stdout.read(chunk_size * 2)
                if not data:
                    break
                    
                samples = struct.unpack(f"{len(data)//2}h", data)
                if samples:
                    rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
                    level = min(100, int(rms / 327.67))
                    self.callback(level)
                    
        except Exception as e:
            print(f"[Meter] Error: {e}")


class InterviewRecorder:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🎙 Interview Recorder")
        self.root.geometry("450x450")
        self.root.resizable(False, False)

        self.recording = False
        self.process = None
        self.start_time = None
        self.output_file = None
        self.meter = None
        self.transcribing = False

        # Server transcription settings
        self.runpod_endpoint = "https://api.runpod.ai/v2/yawnskk7m78v7w/run"

        self.setup_ui()
        self.check_dependencies()

        print("=" * 50)
        print("🎙  Interview Recorder")
        print("=" * 50)
        
    def setup_ui(self):
        main = ttk.Frame(self.root, padding=20)
        main.pack(fill=tk.BOTH, expand=True)
        
        # Статус
        self.status_var = tk.StringVar(value="Готов к записи")
        ttk.Label(main, textvariable=self.status_var, font=("", 11)).pack(pady=(0, 5))
        
        # Таймер
        self.timer_var = tk.StringVar(value="00:00:00")
        ttk.Label(main, textvariable=self.timer_var, font=("Monospace", 28, "bold")).pack(pady=(0, 10))
        
        # VU-метр
        meter_frame = ttk.Frame(main)
        meter_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(meter_frame, text="🎤", font=("", 14)).pack(side=tk.LEFT)
        
        self.meter_canvas = tk.Canvas(meter_frame, height=20, bg="#2a2a2a", highlightthickness=0)
        self.meter_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 0))
        
        self.meter_level = 0
        self.draw_meter()
        
        # Опции
        options_frame = ttk.LabelFrame(main, text="Настройки", padding=10)
        options_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Язык и модель
        lang_frame = ttk.Frame(options_frame)
        lang_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(lang_frame, text="Язык:").pack(side=tk.LEFT)
        self.language_var = tk.StringVar(value="ru")
        lang_combo = ttk.Combobox(
            lang_frame, 
            textvariable=self.language_var,
            values=["ru", "en"],
            state="readonly",
            width=5
        )
        lang_combo.pack(side=tk.LEFT, padx=(10, 0))
        
        ttk.Label(lang_frame, text="Модель:").pack(side=tk.LEFT, padx=(20, 0))
        self.model_var = tk.StringVar(value="base")
        model_combo = ttk.Combobox(
            lang_frame,
            textvariable=self.model_var,
            values=["tiny", "base", "small", "medium", "turbo"],
            state="readonly",
            width=8
        )
        model_combo.pack(side=tk.LEFT, padx=(10, 0))
        
        # Чекбоксы
        self.transcribe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="Транскрибировать (Whisper)",
            variable=self.transcribe_var
        ).pack(anchor=tk.W)

        self.keep_audio_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            options_frame,
            text="Сохранить аудио (MP3, ~20 MB/час)",
            variable=self.keep_audio_var
        ).pack(anchor=tk.W)

        self.use_server_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame,
            text="☁️ Транскрибировать на сервере (WhisperX + диаризация)",
            variable=self.use_server_var
        ).pack(anchor=tk.W, pady=(5, 0))
        
        # Кнопки записи
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.record_btn = ttk.Button(
            btn_frame, 
            text="⏺ Начать запись", 
            command=self.toggle_recording
        )
        self.record_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 5))
        
        ttk.Button(
            btn_frame,
            text="📁",
            width=3,
            command=self.open_folder
        ).pack(side=tk.RIGHT)
        
        # Кнопка транскрипции файла
        self.transcribe_file_btn = ttk.Button(
            main,
            text="📄 Транскрибировать файл...",
            command=self.transcribe_existing_file
        )
        self.transcribe_file_btn.pack(fill=tk.X)
        
        # Инфо о файле
        self.file_var = tk.StringVar(value="")
        ttk.Label(main, textvariable=self.file_var, font=("", 9), foreground="gray").pack(pady=(15, 0))
        
    def draw_meter(self):
        self.meter_canvas.delete("all")
        width = self.meter_canvas.winfo_width() or 100
        height = 20
        
        self.meter_canvas.create_rectangle(0, 0, width, height, fill="#2a2a2a", outline="")
        
        if self.meter_level > 0:
            level_width = int(width * self.meter_level / 100)
            
            if self.meter_level < 50:
                color = "#4CAF50"
            elif self.meter_level < 80:
                color = "#FFC107"
            else:
                color = "#F44336"
                
            self.meter_canvas.create_rectangle(0, 0, level_width, height, fill=color, outline="")
        
        for i in range(1, 5):
            x = width * i / 5
            self.meter_canvas.create_line(x, 0, x, height, fill="#555", width=1)
            
    def update_meter(self, level):
        self.meter_level = level
        self.root.after(0, self.draw_meter)
        
    def check_dependencies(self):
        try:
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except FileNotFoundError:
            messagebox.showerror("Ошибка", "ffmpeg не установлен!\n\nsudo apt install ffmpeg")
            self.root.quit()
            
    def get_default_sink(self):
        result = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True)
        return result.stdout.strip()
    
    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()
            
    def start_recording(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = str(Path.home() / f"interview_{timestamp}.mp3")
        
        sink = self.get_default_sink()
        monitor = f"{sink}.monitor"
        
        print(f"\n▶ Начинаю запись: {self.output_file}")
        print(f"  Системный звук: {monitor}")
        print(f"  Микрофон: default")
        
        cmd = [
            "ffmpeg",
            "-f", "pulse", "-i", monitor,
            "-f", "pulse", "-i", "default",
            "-filter_complex", "amix=inputs=2:duration=longest",
            "-ac", "1",
            "-ar", "16000",
            "-codec:a", "libmp3lame",
            "-qscale:a", "4",
            "-y",
            self.output_file
        ]
        
        try:
            self.process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось начать запись:\n{e}")
            return
            
        self.meter = AudioMeter(self.update_meter)
        self.meter.start()
            
        self.recording = True
        self.start_time = time.time()
        
        self.status_var.set("🔴 Идёт запись...")
        self.record_btn.config(text="⏹ Остановить")
        self.transcribe_file_btn.config(state=tk.DISABLED)
        self.file_var.set("")
        
        self.update_timer()
        
    def stop_recording(self):
        if self.meter:
            self.meter.stop()
            self.meter = None
        self.meter_level = 0
        self.draw_meter()
        
        if self.process:
            self.process.send_signal(signal.SIGINT)
            self.process.wait()
            self.process = None
            
        self.recording = False
        self.record_btn.config(text="⏺ Начать запись")
        self.transcribe_file_btn.config(state=tk.NORMAL)
        self.timer_var.set("00:00:00")
        
        elapsed = int(time.time() - self.start_time)
        print(f"\n⏹ Запись остановлена. Длительность: {elapsed // 60}:{elapsed % 60:02d}")
        
        if not self.output_file or not Path(self.output_file).exists():
            self.status_var.set("❌ Ошибка записи")
            print("❌ Ошибка: файл не создан")
            return
        
        mp3_size = Path(self.output_file).stat().st_size / (1024 * 1024)
        print(f"✓ MP3 создан: {mp3_size:.1f} MB")
            
        if self.transcribe_var.get():
            threading.Thread(target=self.transcribe_file, args=(self.output_file,), daemon=True).start()
        else:
            self.status_var.set("✅ Готово!")
            self.file_var.set(f"📁 {Path(self.output_file).name} ({mp3_size:.1f} MB)")
            
        if not self.keep_audio_var.get() and not self.transcribe_var.get():
            os.remove(self.output_file)
            self.file_var.set("")
            
    def transcribe_existing_file(self):
        if self.transcribing:
            messagebox.showwarning("Подождите", "Транскрипция уже выполняется")
            return

        filepath = filedialog.askopenfilename(
            title="Выбери аудиофайл",
            initialdir=Path.home(),
            filetypes=[
                ("Аудиофайлы", "*.mp3 *.wav *.m4a *.ogg *.flac"),
                ("Все файлы", "*.*")
            ]
        )

        if filepath:
            threading.Thread(target=self.transcribe_file, args=(filepath,), daemon=True).start()

    def format_dialogue_to_text(self, dialogue_result):
        """Форматирование результата диалога в текст."""
        if 'error' in dialogue_result:
            return f"ОШИБКА: {dialogue_result['error']}"

        dialogue = dialogue_result.get('dialogue', [])
        language = dialogue_result.get('language', 'unknown')
        num_speakers = dialogue_result.get('num_speakers', 0)

        lines = []
        lines.append(f"Язык: {language}")
        lines.append(f"Количество спикеров: {num_speakers}")
        lines.append("=" * 60)
        lines.append("")

        for turn in dialogue:
            speaker = turn.get('speaker', 'UNKNOWN')
            text = turn.get('text', '')
            start = turn.get('start', 0)
            end = turn.get('end', 0)

            timestamp = f"[{int(start//60):02d}:{int(start%60):02d} - {int(end//60):02d}:{int(end%60):02d}]"
            lines.append(f"{speaker} {timestamp}:")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def transcribe_on_server(self, filepath):
        """Отправка файла на сервер для транскрипции."""
        runpod_key = os.environ.get('RUNPOD_API_KEY')

        if not runpod_key:
            raise ValueError("RUNPOD_API_KEY не установлен в переменных окружения.\n\nДобавьте в ~/.bashrc:\nexport RUNPOD_API_KEY=\"ваш_ключ\"")

        # Читаем файл и конвертируем в base64
        print(f"📤 Отправка на сервер: {filepath}")
        file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
        print(f"   Размер файла: {file_size_mb:.1f} MB")

        self.root.after(0, lambda: self.status_var.set(f"📤 Загрузка файла ({file_size_mb:.1f} MB)..."))

        with open(filepath, 'rb') as f:
            audio_data = f.read()
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        # Подготовка запроса
        lang = self.language_var.get()
        payload = {
            "input": {
                "audio_base64": audio_base64,
                "language": lang,
                "format": "dialogue"
            }
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runpod_key}"
        }

        print(f"   Язык: {lang}")
        print(f"   Формат: dialogue")
        print(f"   Диаризация: включена (HF_TOKEN на сервере)")

        # Отправка запроса
        self.root.after(0, lambda: self.status_var.set("⏳ Обработка на сервере..."))
        print("🔄 Обработка на сервере...")

        try:
            response = requests.post(
                self.runpod_endpoint,
                json=payload,
                headers=headers,
                timeout=600  # 10 минут таймаут
            )
            response.raise_for_status()
            result = response.json()

            # RunPod возвращает результат в поле "output"
            if 'output' in result:
                return result['output']
            elif 'id' in result:
                # Асинхронный запрос - нужно опросить статус
                job_id = result['id']
                return self._poll_runpod_result(job_id, runpod_key)
            else:
                raise ValueError(f"Неожиданный формат ответа: {result}")

        except requests.Timeout:
            raise TimeoutError("Превышено время ожидания ответа от сервера")
        except requests.RequestException as e:
            raise ValueError(f"Ошибка запроса: {str(e)}")

    def _poll_runpod_result(self, job_id, api_key):
        """Опрос статуса задачи RunPod."""
        status_url = f"{self.runpod_endpoint.rsplit('/', 1)[0]}/status/{job_id}"
        headers = {
            "Authorization": f"Bearer {api_key}"
        }

        print(f"⏳ Ожидание результата (Job ID: {job_id})...")
        max_attempts = 120  # 10 минут (120 * 5 секунд)
        attempt = 0

        while attempt < max_attempts:
            try:
                response = requests.get(status_url, headers=headers, timeout=30)
                response.raise_for_status()
                status_data = response.json()

                status = status_data.get('status')
                if status == 'COMPLETED':
                    return status_data.get('output')
                elif status == 'FAILED':
                    error = status_data.get('error', 'Unknown error')
                    raise ValueError(f"Задача завершилась с ошибкой: {error}")
                elif status in ['IN_QUEUE', 'IN_PROGRESS']:
                    attempt += 1
                    time.sleep(5)
                    if attempt % 6 == 0:  # Каждые 30 секунд
                        print(f"   Статус: {status} ({attempt * 5}s)")
                else:
                    raise ValueError(f"Неизвестный статус: {status}")

            except requests.RequestException as e:
                raise ValueError(f"Ошибка при опросе статуса: {str(e)}")

        raise TimeoutError("Превышено время ожидания результата от сервера")
    
    def transcribe_file(self, filepath):
        """Транскрипция файла через CLI whisper или сервер."""
        self.transcribing = True
        self.root.after(0, lambda: self.record_btn.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.transcribe_file_btn.config(state=tk.DISABLED))
        self.root.after(0, lambda: self.status_var.set("⏳ Транскрипция..."))

        # Получаем длительность
        try:
            duration_result = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", filepath
            ], capture_output=True, text=True)
            total_duration = float(duration_result.stdout.strip())
            dur_str = f"{int(total_duration // 60)}:{int(total_duration % 60):02d}"
        except:
            total_duration = 0
            dur_str = "??:??"

        lang = self.language_var.get()
        lang_name = "Русский" if lang == "ru" else "English"

        print(f"\n⏳ Транскрипция: {filepath}")
        print(f"   Длительность: {dur_str}")
        print(f"   Язык: {lang_name}")

        # Проверяем, использовать ли сервер
        use_server = self.use_server_var.get()

        if use_server:
            print(f"   Режим: ☁️  Сервер (WhisperX + диаризация)")
            print("-" * 40)
            self._transcribe_on_server_wrapper(filepath)
        else:
            model = self.model_var.get()
            print(f"   Модель: {model}")
            print(f"   Режим: 💻 Локально (Whisper)")
            print("-" * 40)
            self._transcribe_locally(filepath, lang, model)

    def _transcribe_on_server_wrapper(self, filepath):
        """Обертка для серверной транскрипции."""
        try:
            start_time = time.time()
            result = self.transcribe_on_server(filepath)

            elapsed = time.time() - start_time
            print(f"\n✅ Завершено за {int(elapsed // 60)}:{int(elapsed % 60):02d}")

            # Форматируем результат
            text_content = self.format_dialogue_to_text(result)

            # Сохраняем в файл
            txt_file = filepath.rsplit(".", 1)[0] + ".txt"
            with open(txt_file, 'w', encoding='utf-8') as f:
                f.write(text_content)

            txt_size = Path(txt_file).stat().st_size / 1024
            print(f"✓ Транскрипт: {txt_file} ({txt_size:.1f} KB)")

            num_speakers = result.get('num_speakers', 0)
            self.root.after(0, lambda: self.status_var.set(f"✅ Транскрипция завершена ({num_speakers} спикеров)"))
            self.root.after(0, lambda: self.file_var.set(f"📄 {Path(txt_file).name}"))

            if not self.keep_audio_var.get() and filepath == self.output_file:
                os.remove(filepath)
                print("✓ Аудиофайл удалён")

        except Exception as e:
            print(f"❌ Ошибка: {e}")
            self.root.after(0, lambda: self.status_var.set(f"❌ Ошибка: {str(e)[:30]}"))
            self.root.after(0, lambda: messagebox.showerror("Ошибка транскрипции", str(e)))
        finally:
            self.transcribing = False
            self.root.after(0, lambda: self.record_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.transcribe_file_btn.config(state=tk.NORMAL))
            print("-" * 40)

    def _transcribe_locally(self, filepath, lang, model):
        """Локальная транскрипция через CLI whisper."""
        
        try:
            check = subprocess.run(["whisper", "--help"], capture_output=True)
            if check.returncode != 0:
                raise FileNotFoundError("whisper not found")
            
            output_dir = str(Path(filepath).parent)
            start_time = time.time()
            
            process = subprocess.Popen([
                "whisper", filepath,
                "--model", model,
                "--language", lang,
                "--output_format", "txt",
                "--output_dir", output_dir
            ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            
            for line in process.stdout:
                line = line.strip()
                if line:
                    print(line)
            
            process.wait()
            
            elapsed = time.time() - start_time
            print(f"\nЗавершено за {int(elapsed // 60)}:{int(elapsed % 60):02d}")
            
            txt_file = filepath.rsplit(".", 1)[0] + ".txt"
            if Path(txt_file).exists():
                txt_size = Path(txt_file).stat().st_size / 1024
                print(f"✓ Транскрипт: {txt_file} ({txt_size:.1f} KB)")
                
                self.root.after(0, lambda: self.status_var.set("✅ Транскрипция завершена"))
                self.root.after(0, lambda: self.file_var.set(f"📄 {Path(txt_file).name}"))
                
                if not self.keep_audio_var.get() and filepath == self.output_file:
                    os.remove(filepath)
                    print("✓ Аудиофайл удалён")
            else:
                print("⚠️ Файл транскрипта не создан")
                self.root.after(0, lambda: self.status_var.set("⚠️ Транскрипция не удалась"))
            
        except FileNotFoundError:
            print("❌ Whisper не найден в PATH!")
            print("   Убедись что /media/data/pipx/bin в PATH")
            self.root.after(0, lambda: messagebox.showerror(
                "Whisper не найден",
                "Whisper не найден в PATH.\n\nДобавь в ~/.bashrc:\nexport PATH=\"/media/data/pipx/bin:$PATH\"\n\nИ перезапусти терминал."
            ))
            self.root.after(0, lambda: self.status_var.set("❌ Whisper не найден"))
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            self.root.after(0, lambda: self.status_var.set(f"❌ Ошибка: {str(e)[:30]}"))
        finally:
            self.transcribing = False
            self.root.after(0, lambda: self.record_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.transcribe_file_btn.config(state=tk.NORMAL))
            print("-" * 40)
            
    def update_timer(self):
        if self.recording:
            elapsed = int(time.time() - self.start_time)
            h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
            self.timer_var.set(f"{h:02d}:{m:02d}:{s:02d}")
            self.root.after(1000, self.update_timer)
            
    def open_folder(self):
        subprocess.run(["xdg-open", str(Path.home())])
        
    def run(self):
        def on_close():
            if self.recording:
                self.stop_recording()
            self.root.quit()
            
        self.root.protocol("WM_DELETE_WINDOW", on_close)
        self.root.mainloop()


if __name__ == "__main__":
    app = InterviewRecorder()
    app.run()
