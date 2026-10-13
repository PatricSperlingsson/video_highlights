"""Draw a shot-speed analysis on the latest marked frame and save it as PNG.

Run: .venv-frame-viewer/bin/python shot_overlay.py frame_snapshots/*_points.json \
         --distance 6.1 --from 1:15.821 --to 1:16.038 -o shot_overlay.png
Then add to the config: IMAGE | shot_overlay.png | 3 |
"""

import argparse
import json
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from create_compilation import parse_time
from frame_viewer import decode_from

CYAN = (0, 212, 255)
FONT_PATHS = (
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/Library/Fonts/Arial Bold.ttf',
    'C:/Windows/Fonts/arialbd.ttf',
)


def estimate_speed(distance, start, end):
    if not 0 < distance < math.inf:
        raise ValueError('Distance must be a positive number of metres.')
    if not end > start:
        raise ValueError('End time must be after start time.')
    return distance / (end - start) * 3.6


def format_number(value):
    return f'{value:g}'.replace('.', ',')


def load_marks(paths):
    marks = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if not data.get('ball'):
            raise ValueError(f'No ball point saved in {path}')
        marks.append(data)
    if len({mark['source'] for mark in marks}) != 1:
        raise ValueError('Point files come from different videos.')
    if len({(mark['image_width'], mark['image_height']) for mark in marks}) != 1:
        raise ValueError('Point files have different image sizes.')
    return sorted(marks, key=lambda mark: mark['seconds'])


def find_frame(container, stream, mark):
    # Seek slightly early: the stored seconds are rounded from the exact PTS.
    for timed in decode_from(container, stream, max(0.0, mark['seconds'] - 0.05)):
        if timed.frame.pts == mark['pts']:
            return timed.frame
        if timed.frame.pts > mark['pts']:
            break
    raise ValueError(f"Frame with PTS {mark['pts']} not found in video.")


def load_font(size):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def dashed_line(draw, start, end, fill, width, dash, gap):
    (x0, y0), (x1, y1) = start, end
    length = math.hypot(x1 - x0, y1 - y0)
    if length == 0:
        return
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    position = 0.0
    while position < length:
        stop = min(position + dash, length)
        draw.line([(x0 + dx * position, y0 + dy * position), (x0 + dx * stop, y0 + dy * stop)],
                  fill=fill, width=width)
        position += dash + gap


def point(data):
    return (data['x'], data['y'])


def render_overlay(image, marks, speed_kmh, distance, title, floor_line=False):
    base = image.convert('RGBA')
    scale = base.height / 1080

    def px(value):
        return max(1, round(value * scale))

    glow = Image.new('RGBA', base.size, (0, 0, 0, 0))
    shapes = Image.new('RGBA', base.size, (0, 0, 0, 0))
    helpers = Image.new('RGBA', base.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    draw = ImageDraw.Draw(shapes)

    trail = [point(mark['ball']) for mark in marks]
    references = marks[-1].get('reference_points', [])
    if floor_line and references:
        helper_draw = ImageDraw.Draw(helpers)
        start, last, end = trail[0], trail[-1], point(references[-1])
        corner = (end[0], start[1])
        for color, width in (((0, 0, 0, 200), px(9)), ((255, 255, 255, 235), px(5))):
            for a, b in ((start, corner), (corner, end), (last, end)):
                dashed_line(helper_draw, a, b, color, width, px(28), px(16))
        label = ((start[0] + corner[0]) / 2, start[1] + px(34))
        helper_draw.text(label, f'≈ {format_number(distance)} m', font=load_font(px(40)), anchor='mm',
                         fill=(255, 255, 255, 255), stroke_width=px(3), stroke_fill=(0, 0, 0, 255))

    if len(trail) >= 2:
        (x0, y0), (x1, y1) = trail[0], trail[-1]
        steps = 24
        for index in range(steps):
            a = (x0 + (x1 - x0) * index / steps, y0 + (y1 - y0) * index / steps)
            b = (x0 + (x1 - x0) * (index + 1) / steps, y0 + (y1 - y0) * (index + 1) / steps)
            alpha = round(80 + 175 * (index + 1) / steps)
            glow_draw.line([a, b], fill=CYAN + (alpha,), width=px(16))
            draw.line([a, b], fill=CYAN + (alpha,), width=px(6))
        draw.ellipse([x0 - px(6), y0 - px(6), x0 + px(6), y0 + px(6)], fill=CYAN + (200,))

    x, y = trail[-1]
    radius = px(30)
    ring = [x - radius, y - radius, x + radius, y + radius]
    glow_draw.ellipse(ring, outline=CYAN + (255,), width=px(14))
    draw.ellipse(ring, outline=CYAN + (255,), width=px(6))

    result = Image.alpha_composite(base, helpers)
    result = Image.alpha_composite(result, glow.filter(ImageFilter.GaussianBlur(px(8))))
    result = Image.alpha_composite(result, shapes)

    speed_text = f'≈ {round(speed_kmh)} km/h'
    big, small = load_font(px(96)), load_font(px(40))
    measure = ImageDraw.Draw(result)
    speed_box = measure.textbbox((0, 0), speed_text, font=big)
    title_box = measure.textbbox((0, 0), title, font=small)
    pad = px(28)
    width = max(speed_box[2] - speed_box[0], title_box[2] - title_box[0]) + 2 * pad
    speed_height = speed_box[3] - speed_box[1]
    height = speed_height + (title_box[3] - title_box[1]) + 3 * pad
    left, top = (result.width - width) / 2, px(40)

    panel = Image.new('RGBA', result.size, (0, 0, 0, 0))
    panel_draw = ImageDraw.Draw(panel)
    panel_draw.rounded_rectangle([left, top, left + width, top + height], radius=px(18),
                                 fill=(0, 0, 0, 170), outline=CYAN + (255,), width=px(3))
    centre = result.width / 2
    panel_draw.text((centre, top + pad), speed_text, font=big, anchor='mt', fill=(255, 255, 255, 255))
    panel_draw.text((centre, top + 2 * pad + speed_height), title, font=small, anchor='mt',
                    fill=(200, 240, 255, 255))
    return Image.alpha_composite(result, panel).convert('RGB')


def main():
    parser = argparse.ArgumentParser(description='Render a shot-speed analysis image from saved ball points.')
    parser.add_argument('points', nargs='+', type=Path, help='_points.json files from frame_viewer.py')
    parser.add_argument('--distance', type=float, required=True, help='distance travelled in metres')
    parser.add_argument('--from', dest='start', required=True, help='time the ball leaves the stick')
    parser.add_argument('--to', dest='end', required=True, help='time the ball reaches the distance end')
    parser.add_argument('--title', default='Uppskattad medelhastighet', help='text below the speed')
    parser.add_argument('--floor-line', action='store_true',
                        help='also draw a dashed triangle to the last reference point with the distance label')
    parser.add_argument('--video', type=Path, help='override the video path stored in the point files')
    parser.add_argument('-o', '--output', type=Path, required=True, help='output PNG file')
    args = parser.parse_args()

    if args.output.suffix.lower() != '.png':
        parser.error('Output must be a .png file.')
    try:
        speed = estimate_speed(args.distance, parse_time(args.start), parse_time(args.end))
    except ValueError as error:
        parser.error(str(error))

    try:
        marks = load_marks(args.points)
        source = (args.video or Path(marks[0]['source'])).expanduser()
        if not source.is_file():
            raise ValueError(f'Video file not found: {source}')
        import av
        with av.open(str(source)) as container:
            frame = find_frame(container, container.streams.video[0], marks[-1])
            image = frame.to_image()
        if image.size != (marks[-1]['image_width'], marks[-1]['image_height']):
            raise ValueError('Video frame size does not match the saved points.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        render_overlay(image, marks, speed, args.distance, args.title,
                       args.floor_line).save(args.output)
    except ImportError as error:
        print(f'Error: Missing dependency: {error.name}. Use .venv-frame-viewer/bin/python.', file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1

    elapsed = parse_time(args.end) - parse_time(args.start)
    print(f'Saved {args.output}: ≈ {round(speed)} km/h '
          f'({format_number(args.distance)} m in {elapsed:.3f} s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
