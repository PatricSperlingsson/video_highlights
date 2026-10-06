# Video Compilation Guide

Create a compilation from video excerpts, still images and black title screens.
Video clips support text, speed changes, reverse playback, freeze frames, arrows
and audio waveforms. Screen recordings without an audio track are supported.

## Requirements

Install Python 3 and FFmpeg, including ffprobe. FFmpeg needs libx264 for SDR,
libx265 for HDR, drawtext for text overlays, and zscale/tonemap for HDR-to-SDR
WhatsApp exports.

```sh
# On Ubuntu/Debian
sudo apt install python3 ffmpeg

# On macOS
brew install python ffmpeg

ffmpeg -version
ffprobe -version
```

## Run

Run from the project folder. By default, the script reads
[video_config.txt](video_config.txt) and creates only the source-format master:

```sh
./create_compilation.py
# Output: compilation.mp4

./create_compilation.py --whatsapp
# Output: compilation.mp4 and compilation_Whatsapp.mp4

./create_compilation.py my_config.txt -o highlights.mp4
# Output: highlights.mp4

./create_compilation.py my_config.txt -o highlights.mp4 --whatsapp
# Output: highlights.mp4 and highlights_Whatsapp.mp4

./create_compilation.py --whatsapp --whatsapp-max-mb 50
# Master plus WhatsApp export with a 50 MB size target

./create_compilation.py -o highlights.mp4 --whatsapp-only
# Convert existing highlights.mp4; do not rebuild it or read the config

./create_compilation.py --help
```

You can also use `python3 create_compilation.py` with the same arguments.
`-o` accepts a path and a name with or without an extension; the output extension
is always `.mp4`. Create the destination folder first.

The old `.mp41`/`.mp42` naming is no longer used. Existing files are not renamed
or deleted. WhatsApp export is now opt-in; the old `--no-whatsapp` flag remains
accepted for compatibility, but is unnecessary and cannot be combined with
`--whatsapp`.

## Output Format

The first existing video in the config sets the master resolution (accounting
for rotation), frame rate and HDR/SDR mode. Frame rate is rounded to an integer
and limited to 24-60 fps. At least one existing video is required, even when
other entries are images or black screens.

The master is re-encoded, not an unchanged copy of the source. SDR uses H.264;
HLG/PQ HDR uses 10-bit HEVC. Video clips are scaled proportionally and padded
with black bars to match the master. All clips use stereo AAC at 44.1 kHz.
Processed clips and overlay text are kept in `temp_clips/`, which can be removed
after export.

With `--whatsapp`, a second export is made from the master. It uses H.264 SDR,
converts HDR with tone mapping, limits frame rate to 30 fps and video maxrate to
7000 kbps, and retains the master resolution. The default file-size target is
185 MB. This is a target, not a hard guarantee: the script warns if exceeded
and skips the export if the calculated bitrate would be below 500 kbps.

## Configuration

Each nonempty, non-comment line adds one entry, in order. Separate fields with
`|`; filenames may contain spaces and do not need quotes. Paths are relative
to the working directory, not the config file's folder. Absolute paths and
`~/` paths are also supported. Blank lines and lines starting with `#` are ignored.

Times accept seconds (`26`, `26.23`), `mm:ss` (`1:12`) or `hh:mm:ss` (`1:12:30`).
For video clips, end time must be after start time. Use positive durations for
images and black screens.

### Video Clips

```text
filename | start_time | end_time | [text] | [speed] | [arrow] | [waveform] | [noaudio]

video.mp4 | 3 | 5 | Great goal!
video.mp4 | 12 | 25 | | 5
video.mp4 | 3 | 5 | Replay | 0.5
video.mp4 | 3 | 5 | Reverse | -1
video.mp4 | 3 | 5 | Reverse slow | -0.5
video.mp4 | 3 | 6 | Look here! | 0
video.mp4 | 3 | 5 | First line\nSecond line | arrow 270
video.mp4 | 3 | 5 | | arrow 45:800:600 | waveform
video.mp4 | 3 | 5 | Quiet clip | noaudio
```

Optional video fields may appear in any order. Text appears at the bottom
centre; literal `\n` forces a new line and long lines are wrapped automatically.
Keep each config entry on a single physical line.

- Speed defaults to `1`. `2` is twice as fast; `0.5` is half speed.
- Negative speed reverses playback; `reverse` is also accepted as a keyword.
- Speed `0` freezes the frame at start time for `end_time - start_time` seconds.
- Slow motion (speed below `1`) and freeze frames are silent.
- Normal and fast clips retain audio; fast clips adjust audio tempo.
- Inputs without audio automatically get silence. `noaudio` also forces silence.
- `waveform` shows an audio amplitude visualization. Without source audio, or
	on a frozen frame, it shows a flat line. Muting source audio does not otherwise
	remove the visualization.
- `arrow` defaults to pointing right. `arrow 270` points up;
	`arrow 45:800:600` sets angle and pixel position. Angles run clockwise:
	`0` right, `90` down, `180` left, `270` up. Legacy `45:800:600` is accepted too.

### Black Screens And Audio

```text
BLACK | duration | text | [audio_file] | [audio_start]

BLACK | 3 | A few moments later
BLACK | 3 | And the result in\ngittools gerrit is...
BLACK | 3 | A few moments later | sound.flac | 0
BLACK | 3 | A few moments later | sound.flac | 0.7
BLACK | 3 | A few moments later | sound.flac
```

Text is centred on the black screen; leave the text field empty for plain black.
Without an audio file, the screen is silent.

With an explicit `audio_start`, audio plays from that offset for at most the
screen duration. For example, `BLACK | 3 | Title | sound.flac | 0` plays the first
three seconds of a four-second file and cuts the last second. Pre-trimming your
audio and using `| 0` is a predictable choice.

Without `audio_start`, the script uses a centred window in the audio file. A
four-second file on a three-second screen loses 0.5 seconds from each end. If
the length cannot be read, a warning is printed and playback starts at zero.
Short audio is padded with silence. A missing audio file stops the compilation
with an error. The original sound file is never modified.

### Still Images

```text
IMAGE | filename | duration | [text]

IMAGE | screenshot.png | 5 |
IMAGE | collage.png | 5 | Final result
```

Images are stretched to exactly the master resolution, without preserving their
aspect ratio. Prepare a collage at that resolution to avoid distortion. Image
clips are silent; optional text appears at the bottom. SDR screenshots inserted
into an HDR master are not tone-mapped and may have unexpected colours.

## Tests

Run the regression suite from the project folder:

```sh
python3 -m unittest -v test_create_compilation
```

The tests use Python's standard library; no extra packages or FFmpeg are needed.
Filesystem and subprocess operations are mocked, so no media is opened or
encoded. Coverage includes config parsing, explicit text line breaks, silent
sources, freeze frames, images, black-screen audio offsets, duration fallbacks,
missing-source errors, failed clips and export CLI options. These are unit tests;
they do not verify actual encoded video, audio playback or FFmpeg compatibility.

## Troubleshooting

- **Missing media:** check paths and filename case. All configured video, image
	and audio sources must be regular files. Missing sources stop the compilation
	before encoding, with an error and exit code 1; nothing is silently skipped.
	A clip encoding failure also stops the run rather than exporting a partial
	compilation. Existing output files remain unchanged after a preflight failure.
- **No audio in the preview:** try an external player such as VLC. An editor's
	media preview may not support the AAC audio even when the output is valid.
- **Cannot read audio length:** supply `audio_start` explicitly (for example
	`| 0`) to avoid automatic duration detection for black-screen audio.
- **Missing FFmpeg filters/codecs:** check your FFmpeg build supports the
	requirements above; some distributions package a limited build.
- **Text formatting:** use `|` as the field separator and literal `\n` for
	line breaks. Text files use UTF-8, supporting accented characters.

Exports overwrite existing output files with the same name. Choose a different
`-o` name when you want to keep an earlier compilation.
