"""Run: python3 frame_viewer.py VIDEO --start 1:15.8

Install python3-tk and the packages in requirements-frame-viewer.txt first.
Keys: Right/E = next frame, Left = previous frame, S = save, Q = quit.
"""

import argparse
from dataclasses import dataclass, field
from fractions import Fraction
import json
from pathlib import Path
import sys

from create_compilation import parse_time


def format_timestamp(seconds):
    milliseconds = round(seconds * 1000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


@dataclass
class PointSelection:
    ball: tuple = None
    references: list = field(default_factory=list)

    def metadata(self):
        return {
            'ball': {'x': self.ball[0], 'y': self.ball[1]} if self.ball is not None else None,
            'reference_points': [
                {'id': index, 'x': point[0], 'y': point[1]}
                for index, point in enumerate(self.references, 1)
            ],
        }


@dataclass
class PreviewTransform:
    original_width: int
    original_height: int
    left: float
    top: float
    width: int
    height: int

    def to_original(self, x, y):
        if not (self.left <= x < self.left + self.width and
                self.top <= y < self.top + self.height):
            return None
        return ((x - self.left) * self.original_width / self.width,
                (y - self.top) * self.original_height / self.height)

    def to_preview(self, point):
        return (self.left + point[0] * self.width / self.original_width,
                self.top + point[1] * self.height / self.original_height)


@dataclass
class TimedFrame:
    frame: object
    seconds: Fraction
    origin: Fraction
    points: PointSelection = field(default_factory=PointSelection)
    checked_saved: bool = False

    @classmethod
    def from_frame(cls, frame, origin):
        if frame.pts is None or frame.time_base is None:
            raise ValueError('Frame has no presentation timestamp; cannot show reliable timing.')
        return cls(frame, Fraction(frame.pts) * frame.time_base - origin, origin)

    def metadata(self, source):
        return {
            'source': str(source.resolve()),
            'timestamp': format_timestamp(self.seconds),
            'seconds': float(self.seconds),
            'pts': self.frame.pts,
            'time_base': str(self.frame.time_base),
            'timeline_origin_seconds': float(self.origin),
            'presentation_seconds': float(self.seconds + self.origin),
            'image_width': self.frame.width,
            'image_height': self.frame.height,
            'coordinate_system': 'original image pixels; origin at top left',
            **self.points.metadata(),
        }


def decode_from(container, stream, start):
    origin = Fraction(stream.start_time or 0) * stream.time_base
    target = Fraction(str(start))
    if target > 0:
        container.seek(int((origin + target) / stream.time_base),
                       stream=stream, backward=True, any_frame=False)
    for frame in container.decode(stream):
        timed = TimedFrame.from_frame(frame, origin)
        if timed.seconds >= target:
            yield timed


class FrameHistory:
    def __init__(self, frames, limit=20):
        self.frames = iter(frames)
        self.limit = limit
        self.history = []
        self.position = -1
        self.finished = False

    @property
    def current(self):
        return self.history[self.position] if self.position >= 0 else None

    def next(self):
        if self.position + 1 < len(self.history):
            self.position += 1
        elif not self.finished:
            timed = next(self.frames, None)
            if timed is None:
                self.finished = True
                return False
            self.history.append(timed)
            if len(self.history) > self.limit:
                self.history.pop(0)
            self.position = len(self.history) - 1
        else:
            return False
        return True

    def previous(self):
        if self.position <= 0:
            return False
        self.position -= 1
        return True


def save_snapshot(timed, source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    stamp = format_timestamp(timed.seconds).replace(':', '-')
    base = f'{source.stem}_{stamp}_pts-{timed.frame.pts}'
    image_path = directory / f'{base}.png'
    metadata_path = directory / f'{base}.json'
    if image_path.exists() or metadata_path.exists():
        raise FileExistsError(f'Snapshot already exists: {image_path}')
    timed.frame.to_image().save(image_path)
    metadata_path.write_text(json.dumps(timed.metadata(source), indent=2) + '\n',
                             encoding='utf-8')
    return image_path


def points_path(timed, source, directory):
    stamp = format_timestamp(timed.seconds).replace(':', '-')
    return directory / f'{source.stem}_{stamp}_pts-{timed.frame.pts}_points.json'


def load_saved_points(timed, source, directory):
    path = points_path(timed, source, directory)
    if not path.is_file():
        return False
    data = json.loads(path.read_text(encoding='utf-8'))
    ball = data.get('ball')
    timed.points = PointSelection(
        (ball['x'], ball['y']) if ball else None,
        [(item['x'], item['y']) for item in data.get('reference_points', [])])
    return True


def save_points(timed, source, directory, overwrite=False):
    if timed.points.ball is None and not timed.points.references:
        raise ValueError('Select a ball or reference point first.')
    directory.mkdir(parents=True, exist_ok=True)
    path = points_path(timed, source, directory)
    if path.exists() and not overwrite:
        raise FileExistsError(f'Point selection already exists: {path}')
    path.write_text(json.dumps(timed.metadata(source), indent=2) + '\n', encoding='utf-8')
    return path


def show_viewer(container, stream, source, start, directory):
    import tkinter as tk
    from tkinter import messagebox
    from PIL import Image, ImageTk

    root = tk.Tk()
    root.title(f'Frame Viewer - {source.name}')
    root.geometry('1100x760')
    root.minsize(500, 350)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    canvas = tk.Canvas(root, background='#181818', highlightthickness=0)
    canvas.grid(row=0, column=0, sticky='nsew')
    controls = tk.Frame(root)
    controls.grid(row=1, column=0, sticky='ew')
    selection_controls = tk.Frame(root)
    selection_controls.grid(row=2, column=0, sticky='ew')
    selection_mode = tk.StringVar(value='ball')
    status = tk.StringVar()
    tk.Label(root, textvariable=status, anchor='w', wraplength=1000).grid(
        row=3, column=0, sticky='ew', padx=8, pady=8)

    history = FrameHistory(decode_from(container, stream, start))
    display_image = None
    photo = None
    resize_job = None
    transform = None

    def redraw():
        nonlocal photo, transform
        if display_image is None:
            return
        preview = display_image.copy()
        preview.thumbnail((max(1, canvas.winfo_width()), max(1, canvas.winfo_height())),
                          Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(preview)
        canvas.delete('all')
        canvas.create_image(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                            image=photo, anchor='center')
        transform = PreviewTransform(display_image.width, display_image.height,
                                     canvas.winfo_width() // 2 - preview.width / 2,
                                     canvas.winfo_height() // 2 - preview.height / 2,
                                     preview.width, preview.height)
        points = history.current.points
        markers = [('Ball', points.ball, '#00d4ff')] if points.ball is not None else []
        markers += [(f'R{index}', point, '#8bff53')
                    for index, point in enumerate(points.references, 1)]
        for label, point, color in markers:
            x, y = transform.to_preview(point)
            canvas.create_oval(x - 8, y - 8, x + 8, y + 8, outline='black', width=4)
            canvas.create_oval(x - 8, y - 8, x + 8, y + 8, outline=color, width=2)
            canvas.create_text(x + 13, y - 13, text=label, fill=color, anchor='w',
                               font=('TkDefaultFont', 11, 'bold'))

    def select_point(event):
        if transform is None or history.current is None:
            return
        point = transform.to_original(event.x, event.y)
        if point is None:
            return
        points = history.current.points
        if selection_mode.get() == 'ball':
            points.ball = point
            label = 'Ball'
        else:
            points.references.append(point)
            label = f'R{len(points.references)}'
        status.set(f'{format_timestamp(history.current.seconds)}  |  {label}: '
                   f'x={point[0]:.2f}, y={point[1]:.2f} original pixels (unsaved)')
        redraw()

    def undo_point():
        points = history.current.points
        if selection_mode.get() == 'ball':
            points.ball = None
        elif points.references:
            points.references.pop()
        status.set(f'{format_timestamp(history.current.seconds)}  |  Selection changed (unsaved)')
        redraw()

    def clear_points():
        history.current.points = PointSelection()
        status.set(f'{format_timestamp(history.current.seconds)}  |  Selection cleared (unsaved)')
        redraw()

    def save_selection():
        try:
            try:
                path = save_points(history.current, source, directory)
            except FileExistsError:
                if not messagebox.askyesno('Replace saved points?',
                                          'Replace the point JSON for this frame?', parent=root):
                    return
                path = save_points(history.current, source, directory, overwrite=True)
            status.set(f'Saved points: {path.name} in {directory}')
        except Exception as error:
            messagebox.showerror('Cannot save points', str(error), parent=root)

    def refresh():
        nonlocal display_image
        timed = history.current
        display_image = timed.frame.to_image()
        status.set(f'{format_timestamp(timed.seconds)}  |  {float(timed.seconds):.6f} s'
                   f'  |  PTS {timed.frame.pts}  |  time base {timed.frame.time_base}')
        previous_button.config(state='normal' if history.position > 0 else 'disabled')
        next_button.config(state='normal' if not history.finished or
                           history.position + 1 < len(history.history) else 'disabled')
        if not timed.checked_saved:
            timed.checked_saved = True
            try:
                if load_saved_points(timed, source, directory):
                    status.set(status.get() + '  |  Loaded saved points')
            except (OSError, ValueError, KeyError, TypeError) as error:
                messagebox.showwarning('Cannot load saved points', str(error), parent=root)
        redraw()

    def advance(event=None):
        try:
            if history.next():
                refresh()
            else:
                next_button.config(state='disabled')
                status.set('End of video. ' + status.get())
        except Exception as error:
            messagebox.showerror('Cannot decode frame', str(error), parent=root)

    def previous(event=None):
        if history.previous():
            refresh()

    def save(event=None):
        try:
            path = save_snapshot(history.current, source, directory)
            status.set(f'Saved {path.name} and timestamp JSON in {directory}')
        except Exception as error:
            messagebox.showerror('Cannot save snapshot', str(error), parent=root)

    def resized(event=None):
        nonlocal resize_job
        if resize_job is not None:
            root.after_cancel(resize_job)
        resize_job = root.after(80, redraw)

    previous_button = tk.Button(controls, text='Previous', command=previous)
    previous_button.pack(side='left', padx=8, pady=8)
    next_button = tk.Button(controls, text='Next', command=advance)
    next_button.pack(side='left', padx=8, pady=8)
    tk.Button(controls, text='Save Snapshot', command=save).pack(side='left', padx=8, pady=8)
    tk.Button(controls, text='Quit', command=root.destroy).pack(side='right', padx=8, pady=8)
    for label, value in [('Ball', 'ball'), ('Reference', 'reference')]:
        tk.Radiobutton(selection_controls, text=label, variable=selection_mode,
                       value=value).pack(side='left', padx=8, pady=8)
    tk.Button(selection_controls, text='Undo Point', command=undo_point).pack(side='left', padx=8)
    tk.Button(selection_controls, text='Clear Points', command=clear_points).pack(side='left', padx=8)
    tk.Button(selection_controls, text='Save Points', command=save_selection).pack(side='left', padx=8)
    for key in ('<Right>', 'e', 'E'):
        root.bind(key, advance)
    root.bind('<Left>', previous)
    for key in ('s', 'S'):
        root.bind(key, save)
    for key in ('q', 'Q'):
        root.bind(key, lambda event: root.destroy())
    canvas.bind('<Configure>', resized)
    canvas.bind('<Button-1>', select_point)
    try:
        if not history.next():
            raise ValueError('No video frame at or after the requested start time.')
        refresh()
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def main():
    parser = argparse.ArgumentParser(description='Inspect original video frames and presentation timestamps.')
    parser.add_argument('video', type=Path, help='original video file')
    parser.add_argument('--start', default='0', help='start time: seconds, mm:ss or hh:mm:ss')
    parser.add_argument('--save-dir', type=Path, default=Path('frame_snapshots'), help='snapshot directory')
    args = parser.parse_args()
    try:
        start = parse_time(args.start)
        if not 0 <= start < float('inf'):
            raise ValueError('Start time must be finite and nonnegative.')
    except ValueError as error:
        parser.error(str(error))
    source = args.video.expanduser()
    if not source.is_file():
        parser.error(f'Video file not found: {source}')
    try:
        import av
        with av.open(str(source)) as container:
            if not container.streams.video:
                raise ValueError('File has no video stream.')
            show_viewer(container, container.streams.video[0], source, start,
                        args.save_dir.expanduser())
    except ImportError as error:
        print(f'Error: Missing dependency: {error.name}. Install python3-tk and '
              'requirements-frame-viewer.txt.', file=sys.stderr)
        return 1
    except Exception as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())