#!/usr/bin/env python3
"""
Video Compilation Script
Reads a config file and creates a compiled video with text overlays, plus a
WhatsApp-friendly SDR version.
Requires: ffmpeg/ffprobe (with libx264, libx265, zscale) installed on your system
"""

import argparse
import json
import math
import re
import subprocess
import sys
import textwrap
from pathlib import Path

HDR_TRANSFERS = ('arib-std-b67', 'smpte2084')
AUDIO_ARGS = ['-c:a', 'aac', '-b:a', '128k', '-ar', '44100', '-ac', '2']
AUDIO_KBPS = 128
WHATSAPP_MAX_MB = 185
WHATSAPP_MAX_KBPS = 7000
WHATSAPP_FPS = 30
TEMP_DIR = 'temp_clips'


def parse_time(time_str):
    """Convert '26', '26.5', '1:12' or '1:12:30' to seconds."""
    parts = time_str.strip().split(':')
    if len(parts) > 3:
        raise ValueError(f"Invalid time format: {time_str}")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def parse_config(config_file):
    """Parse the video configuration file."""
    clips = []

    with open(config_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            parts = [p.strip() for p in line.split('|')]
            if len(parts) < 2:
                print(f"Warning: Line {line_num} has invalid format, skipping")
                continue

            if parts[0].upper() == 'BLACK':
                try:
                    clips.append({
                        'type': 'black',
                        'duration': parse_time(parts[1]),
                        'text': parts[2] if len(parts) > 2 else '',
                    })
                except ValueError as e:
                    print(f"Warning: Line {line_num} has invalid duration, skipping: {e}")
                continue

            if len(parts) < 3:
                print(f"Warning: Line {line_num} has invalid format for video clip, skipping")
                continue

            try:
                start = parse_time(parts[1])
                end = parse_time(parts[2])
            except ValueError as e:
                print(f"Warning: Line {line_num} has invalid time values, skipping: {e}")
                continue
            if end <= start:
                print(f"Warning: Line {line_num} end time is not after start time, skipping")
                continue

            clip = {
                'type': 'video', 'filename': parts[0], 'start': start, 'end': end,
                'text': '', 'speed': 1.0, 'reverse': False, 'arrow': '',
                'waveform': False, 'noaudio': False,
            }

            # Optional fields may come in any order
            for field in parts[3:]:
                low = field.lower()
                if not field:
                    continue
                if low == 'waveform':
                    clip['waveform'] = True
                elif low == 'noaudio':
                    clip['noaudio'] = True
                elif low == 'reverse':
                    clip['reverse'] = True
                elif low == 'arrow' or low.startswith('arrow '):
                    clip['arrow'] = field[5:].strip() or '0'
                elif re.fullmatch(r'-?\d+(\.\d+)?:\d+:\d+', field):
                    # Legacy format: arrow spec without the "arrow" keyword
                    clip['arrow'] = field
                elif is_number(field):
                    speed = float(field)
                    if speed == 0:
                        print(f"Warning: Line {line_num} speed 0 is invalid, using 1")
                        continue
                    clip['reverse'] = clip['reverse'] or speed < 0
                    clip['speed'] = abs(speed)
                elif not clip['text']:
                    clip['text'] = field
                else:
                    print(f"Warning: Line {line_num} unknown field '{field}', ignoring")

            clips.append(clip)

    return clips


def probe_video(path):
    """Return width, height, fps and color transfer of the first video stream."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,avg_frame_rate,color_transfer:stream_side_data=rotation',
         '-of', 'json', path],
        capture_output=True, text=True, check=True)
    stream = json.loads(result.stdout)['streams'][0]

    width, height = stream['width'], stream['height']
    rotation = next((int(sd['rotation']) for sd in stream.get('side_data_list', []) if 'rotation' in sd), 0)
    if abs(rotation) % 180 == 90:
        width, height = height, width

    num, _, den = stream.get('avg_frame_rate', '30/1').partition('/')
    fps = float(num) / float(den or 1) if float(den or 1) else 30
    fps = min(max(round(fps), 24), 60)

    return {'width': width, 'height': height, 'fps': fps,
            'transfer': stream.get('color_transfer', '')}


def probe_duration(path):
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True, text=True, check=True)
    return float(result.stdout.strip())


def master_video_args(fmt):
    """Encoder settings for the master; keeps HDR (HLG/PQ) when the source has it."""
    common = ['-preset', 'medium', '-crf', '18', '-video_track_timescale', '90000']
    if fmt['transfer'] in HDR_TRANSFERS:
        return ['-c:v', 'libx265', *common, '-pix_fmt', 'yuv420p10le',
                '-x265-params',
                f"log-level=error:colorprim=bt2020:transfer={fmt['transfer']}:colormatrix=bt2020nc",
                '-color_primaries', 'bt2020', '-color_trc', fmt['transfer'],
                '-colorspace', 'bt2020nc', '-tag:v', 'hvc1']
    return ['-c:v', 'libx264', *common, '-pix_fmt', 'yuv420p',
            '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']


def pix_fmt(fmt):
    return 'yuv420p10le' if fmt['transfer'] in HDR_TRANSFERS else 'yuv420p'


def write_text_file(text, path, width):
    # textfile + expansion=none avoids having to escape ':', ',', '%' etc. for ffmpeg
    Path(path).write_text(textwrap.fill(text, width), encoding='utf-8')


def drawtext_filter(textfile, fontsize, y):
    return (f"drawtext=textfile={textfile}:expansion=none:fontsize={fontsize}:"
            f"fontcolor=white:bordercolor=black:borderw=3:line_spacing=10:text_align=C:"
            f"x=(w-text_w)/2:y={y}")


def get_arrow_filter(arrow_spec, fmt):
    """Arrow spec: 'degrees' or 'degrees:x:y'. 0=right, 90=down, 180=left, 270=up."""
    parts = arrow_spec.split(':')
    try:
        degrees = float(parts[0])
        x = int(parts[1]) if len(parts) > 1 else fmt['width'] // 2
        y = int(parts[2]) if len(parts) > 2 else fmt['height'] // 2
    except ValueError:
        print(f"Warning: Invalid arrow '{arrow_spec}', skipping arrow")
        return ''

    arrow_length, head_length, thickness, color = 150, 30, 8, 'yellow'
    radians = math.radians(degrees)
    head_angle = math.radians(30)

    end_x = x + int(arrow_length * math.cos(radians))
    end_y = y + int(arrow_length * math.sin(radians))
    left_x = end_x - int(head_length * math.cos(radians - head_angle))
    left_y = end_y - int(head_length * math.sin(radians - head_angle))
    right_x = end_x - int(head_length * math.cos(radians + head_angle))
    right_y = end_y - int(head_length * math.sin(radians + head_angle))

    def line(x0, y0, x1, y1, steps):
        return [f"drawbox=x={int(x0 + t / steps * (x1 - x0))}:y={int(y0 + t / steps * (y1 - y0))}:"
                f"w={thickness}:h={thickness}:color={color}:t=fill" for t in range(steps + 1)]

    filters = line(x, y, end_x, end_y, 30)
    filters += line(end_x, end_y, left_x, left_y, 10)
    filters += line(end_x, end_y, right_x, right_y, 10)
    return ','.join(filters)


def atempo_chain(speed):
    """atempo only supports 0.5-2.0 per filter, so chain several for extreme speeds."""
    filters = []
    while speed < 0.5:
        filters.append('atempo=0.5')
        speed *= 2
    while speed > 2.0:
        filters.append('atempo=2.0')
        speed /= 2
    filters.append(f'atempo={speed}')
    return filters


def normalize_filters(fmt):
    w, h = fmt['width'], fmt['height']
    return [f'scale={w}:{h}:force_original_aspect_ratio=decrease',
            f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2', 'setsar=1', f"fps={fmt['fps']}"]


def build_black_cmd(clip, fmt, index, output):
    w, h, fps = fmt['width'], fmt['height'], fmt['fps']
    vf = []
    if clip['text']:
        textfile = f'{TEMP_DIR}/text_{index:03d}.txt'
        write_text_file(clip['text'], textfile, 40)
        vf.append(drawtext_filter(textfile, 72, '(h-text_h)/2'))
    vf.append(f'format={pix_fmt(fmt)}')

    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-stats', '-y',
            '-f', 'lavfi', '-i', f"color=c=black:s={w}x{h}:r={fps}:d={clip['duration']}",
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
            '-filter_complex', f"[0:v]{','.join(vf)}[vout]",
            '-map', '[vout]', '-map', '1:a', '-t', str(clip['duration']),
            *master_video_args(fmt), *AUDIO_ARGS, output]


def build_video_cmd(clip, fmt, index, input_file, output):
    speed = clip['speed']
    duration = clip['end'] - clip['start']
    out_duration = duration / speed
    # Stretched audio sounds bad, so slow motion is always silent
    noaudio = clip['noaudio'] or speed < 1

    video = ['setpts=PTS-STARTPTS']
    audio = ['asetpts=PTS-STARTPTS']
    if clip['reverse']:
        video.append('reverse')
        audio.append('areverse')
    if speed != 1.0:
        video.append(f'setpts=PTS/{speed}')
        audio += atempo_chain(speed)
    video += normalize_filters(fmt)
    audio += ['aresample=44100', 'aformat=channel_layouts=stereo']

    graph = []
    if clip['waveform']:
        graph.append(f"[0:v]{','.join(video)}[base]")
        if noaudio:
            graph.append(f"[0:a]{','.join(audio)}[aw]")
        else:
            graph.append(f"[0:a]{','.join(audio)},asplit=2[a0][aw]")
        graph.append(f"[aw]showwaves=s={fmt['width']}x150:mode=cline:rate={fmt['fps']}:colors=white[wave]")
        overlay = ['[base][wave]overlay=0:H-h-200:shortest=1']
    else:
        overlay = [f"[0:v]{','.join(video)}"]
        if not noaudio:
            graph.append(f"[0:a]{','.join(audio)}[a0]")

    if noaudio:
        graph.append('anullsrc=channel_layout=stereo:sample_rate=44100[aout]')
    else:
        graph.append('[a0]apad[aout]')

    if clip['text']:
        textfile = f'{TEMP_DIR}/text_{index:03d}.txt'
        write_text_file(clip['text'], textfile, 60)
        overlay.append(drawtext_filter(textfile, 48, 'h-text_h-60'))
    if clip['arrow']:
        arrow_filter = get_arrow_filter(clip['arrow'], fmt)
        if arrow_filter:
            overlay.append(arrow_filter)
    overlay.append(f'format={pix_fmt(fmt)}[vout]')
    graph.append(','.join(overlay))

    return ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-stats', '-y',
            '-ss', str(clip['start']), '-t', str(duration), '-i', input_file,
            '-filter_complex', ';'.join(graph),
            '-map', '[vout]', '-map', '[aout]', '-t', str(out_duration),
            *master_video_args(fmt), *AUDIO_ARGS, output]


def create_compilation(clips, output_file):
    """Encode every clip with identical settings, then concatenate without re-encoding."""
    video_clips = [c for c in clips if c['type'] == 'video']
    for clip in video_clips:
        clip['filename'] = str(Path(clip['filename']).expanduser())
    missing = [c['filename'] for c in video_clips if not Path(c['filename']).exists()]
    for name in sorted(set(missing)):
        print(f"Warning: File '{name}' not found, its clips will be skipped")

    reference = next((c['filename'] for c in video_clips if c['filename'] not in missing), None)
    if reference is None:
        print("Error: No existing video files found in configuration file")
        return None

    fmt = probe_video(reference)
    hdr = fmt['transfer'] in HDR_TRANSFERS
    print(f"Output format (from {Path(reference).name}): {fmt['width']}x{fmt['height']} "
          f"@ {fmt['fps']}fps, {'HDR ' + fmt['transfer'] if hdr else 'SDR'}\n")

    Path(TEMP_DIR).mkdir(exist_ok=True)
    concat_list = []

    for i, clip in enumerate(clips):
        temp_output = f'{TEMP_DIR}/clip_{i:03d}.mp4'

        if clip['type'] == 'black':
            print(f"Creating black screen {i+1}/{len(clips)}: {clip['duration']}s '{clip['text']}'")
            cmd = build_black_cmd(clip, fmt, i, temp_output)
        else:
            if clip['filename'] in missing:
                continue
            print(f"Processing clip {i+1}/{len(clips)}: {Path(clip['filename']).name} "
                  f"({clip['start']}s - {clip['end']}s)")
            cmd = build_video_cmd(clip, fmt, i, clip['filename'], temp_output)

        try:
            subprocess.run(cmd, check=True)
            concat_list.append(f"file '{Path(temp_output).name}'")
        except subprocess.CalledProcessError as e:
            print(f"Error processing clip {i+1}: {e}")

    if not concat_list:
        print("Error: No clips were successfully processed")
        return None

    concat_file = Path(TEMP_DIR) / 'concat_list.txt'
    concat_file.write_text('\n'.join(concat_list) + '\n')

    print(f"\nCombining {len(concat_list)} clips into {output_file}...")
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'concat', '-safe', '0', '-i', str(concat_file.resolve()),
                    '-c', 'copy', '-movflags', '+faststart', '-f', 'mp4', output_file], check=True)
    print(f"✓ Created: {output_file}")
    return fmt


def create_whatsapp_version(master_file, output_file, fmt, max_mb):
    """Re-encode the master as 8-bit SDR H.264 (WhatsApp has no HDR support) under max_mb."""
    duration = probe_duration(master_file)
    budget_kbps = int(max_mb * 8000 / duration * 0.95) - AUDIO_KBPS
    maxrate = min(WHATSAPP_MAX_KBPS, budget_kbps)
    if maxrate < 500:
        print(f"Warning: Video too long for {max_mb}MB at reasonable quality "
              f"(would need {maxrate}kbps), skipping WhatsApp version")
        return False

    vf = []
    if fmt['transfer'] in HDR_TRANSFERS:
        # npl=320 matches the brightness of the earlier WhatsApp exports
        vf += [f"zscale=tin={fmt['transfer']}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=320",
               'format=gbrpf32le', 'zscale=p=bt709', 'tonemap=tonemap=hable:desat=0',
               'zscale=t=bt709:m=bt709:r=tv']
    vf += [f'fps={min(fmt["fps"], WHATSAPP_FPS)}', 'format=yuv420p']

    print(f"\nCreating WhatsApp version (SDR, H.264, maxrate {maxrate}kbps)...")
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-stats', '-y', '-i', master_file,
                    '-vf', ','.join(vf),
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
                    '-maxrate', f'{maxrate}k', '-bufsize', f'{2 * maxrate}k',
                    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                    '-c:a', 'copy', '-movflags', '+faststart', '-f', 'mp4', output_file], check=True)

    size_mb = Path(output_file).stat().st_size / 1_000_000
    print(f"✓ Created: {output_file} ({size_mb:.1f} MB)")
    if size_mb > max_mb:
        print(f"Warning: WhatsApp version is larger than {max_mb} MB")
    return True


def main():
    parser = argparse.ArgumentParser(description='Create a highlight compilation from a config file.')
    parser.add_argument('config', nargs='?', default='video_config.txt', help='config file')
    parser.add_argument('-o', '--output', default='compilation.mp4',
                        help='output base name; written as <name>.mp41 and <name>_Whatsapp.mp42')
    parser.add_argument('--no-whatsapp', action='store_true', help='skip the WhatsApp version')
    parser.add_argument('--whatsapp-only', action='store_true',
                        help='only create the WhatsApp version from an existing master (.mp41)')
    parser.add_argument('--whatsapp-max-mb', type=float, default=WHATSAPP_MAX_MB,
                        help=f'size limit for the WhatsApp version (default {WHATSAPP_MAX_MB})')
    args = parser.parse_args()

    if not args.whatsapp_only and not Path(args.config).exists():
        print(f"Error: Configuration file '{args.config}' not found")
        sys.exit(1)

    for tool in ('ffmpeg', 'ffprobe'):
        try:
            subprocess.run([tool, '-version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"Error: {tool} is not installed or not in PATH (sudo apt install ffmpeg)")
            sys.exit(1)

    output = Path(args.output)
    suffix = output.suffix or '.mp4'
    master_file = str(output.with_name(f'{output.stem}{suffix}1'))
    whatsapp_file = str(output.with_name(f'{output.stem}_Whatsapp{suffix}2'))

    if args.whatsapp_only:
        if not Path(master_file).exists():
            print(f"Error: Master file '{master_file}' not found")
            sys.exit(1)
        create_whatsapp_version(master_file, whatsapp_file, probe_video(master_file),
                                args.whatsapp_max_mb)
        print("\nDone!")
        return

    print("Reading configuration file...")
    clips = parse_config(args.config)
    print(f"Found {len(clips)} clips to process")
    if not clips:
        sys.exit(1)

    fmt = create_compilation(clips, master_file)
    if fmt is None:
        print("\nCompilation failed. Check the errors above.")
        sys.exit(1)

    if not args.no_whatsapp:
        create_whatsapp_version(master_file, whatsapp_file, fmt, args.whatsapp_max_mb)

    print("\nDone!")


if __name__ == '__main__':
    main()
