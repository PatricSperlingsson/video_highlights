# Video Compilation Guide

Create a compilation from video excerpts, still images and black title screens.
Video clips support text, speed changes, reverse playback, freeze frames, arrows
and audio waveforms. Screen recordings without an audio track are supported.

## Tools

| Tool | Purpose |
|---|---|
| [create_compilation.py](create_compilation.py) | Build the compilation from [video_config.txt](video_config.txt); optional WhatsApp export. |
| [frame_viewer.py](frame_viewer.py) | Step through an original video frame by frame with exact timestamps; mark the ball and reference points. |
| [shot_overlay.py](shot_overlay.py) | Draw a shot-speed analysis image (ball ring, trail, km/h) from the marked points. |

The frame viewer and shot overlay need the optional setup in
[Frame Viewer](#frame-viewer). See [Shot Speed Analysis](#shot-speed-analysis)
for the complete step-by-step workflow.

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
For video clips, end time must be after start time, except freezes (speed `0`),
where the third field is a duration. Use positive durations for
images and black screens.

### Video Clips

```text
filename | start_time | end_time | [text] | [speed] | [arrow] | [waveform] | [noaudio] | [textbox]

video.mp4 | 3 | 5 | Great goal!
video.mp4 | 12 | 25 | | 5
video.mp4 | 3 | 5 | Replay | 0.5
video.mp4 | 3 | 5 | Reverse | -1
video.mp4 | 3 | 5 | Reverse slow | -0.5
video.mp4 | 3 | 3 | Look here! | 0
video.mp4 | 3 | 3 | Look here! | 0 | textbox
video.mp4 | 3 | 5 | First line\nSecond line | arrow 270
video.mp4 | 3 | 5 | | arrow 45:800:600 | waveform
video.mp4 | 3 | 5 | Quiet clip | noaudio
```

Optional video fields may appear in any order. Text appears at the bottom
centre; literal `\n` forces a new line and long lines are wrapped automatically.
Keep each config entry on a single physical line.

Text uses white lettering with a black outline by default. Add `textbox` for
a semi-transparent black background (60% opacity) with 12 pixels of padding;
the outline remains. This works on moving clips, freeze frames and still images,
including multiline text. Without text, the keyword has no visual effect.
Black title screens already have a black background and do not use this keyword.

To compare both styles, place these entries consecutively:

```text
video.mp4 | 1:10 | 3 | Frislag! | 0
video.mp4 | 1:10 | 3 | Frislag! | 0 | textbox
```

Both show the same frame for three seconds; only the text background differs.

- Speed defaults to `1`. `2` is twice as fast; `0.5` is half speed.
- Negative speed reverses playback; `reverse` is also accepted as a keyword.
- Speed `0` freezes the frame at start time. The third field is then the
	**duration** in seconds, not an end time: `video.mp4 | 1:15.5 | 3 | Frislag! | 0`
	freezes 1:15.5 for 3 seconds, even near the end of the video. Freezes longer
	than 10 seconds print a warning, since older configs used an end time here.
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
IMAGE | filename | duration | [text] | [textbox]

IMAGE | screenshot.png | 5 |
IMAGE | collage.png | 5 | Final result
IMAGE | collage.png | 5 | Final result | textbox
```

Images are stretched to exactly the master resolution, without preserving their
aspect ratio. Prepare a collage at that resolution to avoid distortion. Image
clips are silent; optional text appears at the bottom. SDR screenshots inserted
into an HDR master are not tone-mapped and may have unexpected colours.

## Shot Speed Analysis

This is the complete workflow for showing an estimated shot speed, for example
a free hit, as a frozen analysis image in the compilation. Details for each tool
follow in [Frame Viewer](#frame-viewer) and [Shot Speed Overlay](#shot-speed-overlay).

1. **Find the shot roughly.** Watch the original video and note the time,
   for example `1:15.8`.
2. **Measure a known distance.** Pick a distance the ball travels that you
   know in metres, for example shot position to goal line (5.5 m) plus goal
   depth to the back of the net (0.6 m) = 6.1 m.
3. **Open the frame viewer** on the original video, slightly before the shot:
   ```sh
   .venv-frame-viewer/bin/python frame_viewer.py "original-video.mp4" --start 1:15.7
   ```
4. **Find the start time.** Step with **E** and note the last frame before
   the ball leaves the stick and the first frame after. Use the midpoint, for
   example `01:15.804` and `01:15.838` give `1:15.821`.
5. **Find the end time:** the frame where the ball reaches the end of the
   distance, for example hits the back of the net at `01:16.038`.
6. **Mark the ball.** In **Ball** mode click the ball centre in at least two
   frames (first and last position of the trail), and click **Save Points** on
   each. The **latest** marked frame becomes the frozen analysis image, so
   choose one where the ball is clearly visible.
7. **Create the image:**
   ```sh
   .venv-frame-viewer/bin/python shot_overlay.py frame_snapshots/*_points.json \
       --distance 6.1 --from 1:15.821 --to 1:16.038 -o shot_overlay.png
   ```
   This prints the result, for example `≈ 101 km/h (6,1 m in 0.217 s)`.
8. **Add it to the config**, with the freeze time equal to the latest marked
   frame so the video continues seamlessly:
   ```text
   video.mp4 | 1:15.5 | 1:15.971 | Frislag! | 0.25 | textbox
   IMAGE | shot_overlay.png | 3 |
   video.mp4 | 1:15.971 | 1:20 | | 1
   ```
9. **Build** with `./create_compilation.py` and check the result in VLC.

Tips:

- Always measure on the **original** video. Slowed clips from the compilation
  duplicate frames, so their frame counts and times are misleading.
- VLC's **E** key steps frames but does not show precise timestamps; use the
  frame viewer for times.
- Prefer longer distances. One frame (about 0.033 s at 30 fps) is roughly 15%
  of a 0.2 s shot; over a shorter distance the error is even larger.
- Present the value as an estimate (the default caption is *Uppskattad
  medelhastighet*). It is the average speed over the distance, not the speed
  as the ball leaves the stick.
- Point files are saved in `frame_snapshots/`. Use a separate `--save-dir`
  per shot, otherwise `frame_snapshots/*_points.json` mixes points from
  different shots; the overlay refuses points from different videos.
- Use a different `-o` name per shot, for example `shot_lukas_frislag.png`.

## Frame Viewer

Use [frame_viewer.py](frame_viewer.py) to inspect an original video frame by
frame. This is separate from compilation and does not modify the source or
config. It uses PyAV presentation timestamps rather than assuming a fixed frame
rate, so it is suitable for locating frames for later shot-speed analysis.
It does not track the ball automatically; you mark it, and
[shot_overlay.py](shot_overlay.py) turns the marks into an analysis image.

Install the optional dependencies on Ubuntu/Debian (run these commands yourself):

```sh
sudo apt install python3-tk python3-venv
python3 -m venv .venv-frame-viewer
.venv-frame-viewer/bin/python -m pip install -r requirements-frame-viewer.txt
```

Run from the project folder, supplying the original video path in quotes:

```sh
.venv-frame-viewer/bin/python frame_viewer.py "original-video.mp4" --start 1:15.8
```

`--start` accepts the same time formats as the compilation config. The viewer
starts at the first frame at or after that time. It shows a millisecond time,
seconds to six decimal places, and the original PTS/time base. Displayed elapsed
time is relative to the video stream's start timestamp; the JSON also records
the raw presentation time. No missing timestamps are guessed from frame rate.

- **Right** or **E:** next decoded frame.
- **Left:** previous frame within the last 20 visited frames. Restart with an
	earlier `--start` to inspect frames outside that history window.
- **S** or **Save Snapshot:** save a full-resolution PNG and matching JSON file.
- **Q** or **Quit:** close the viewer.

The window scales only the preview to fit. Saved images have no timestamp text
burned into them; filenames contain the timestamp and PTS, and the JSON contains
the exact PTS and time base for measurement. Existing snapshots are not
overwritten. Files go to `frame_snapshots/` by default; use `--save-dir PATH` to
choose another folder. The viewer requires a graphical desktop session.

### Mark The Ball And Reference Points

Restart the viewer after updating the script. Select **Ball**, then click the
centre of the ball in the preview. A blue marker appears; another click replaces
that frame's ball position. Select **Reference** to add numbered green markers
on identifiable stationary court features.

For each useful frame:

1. Navigate to the frame and click the ball centre in Ball mode.
2. In Reference mode, click court reference points in a consistent order.
	Ideally use four corners of a known floor rectangle, with its real width and
	length measured in metres. Mark the same physical points in later frames to
	help account for handheld camera movement.
3. Click **Save Points** before moving on. This writes a separate `_points.json`
	file with the original frame dimensions, ball/reference pixel coordinates,
	PTS and time base. It does not need to reopen or replace an existing PNG.

**Undo Point** removes the ball in Ball mode or the last reference in Reference
mode. **Clear Points** clears all marks on the current frame. Previously saved
points are loaded automatically when you open a frame, so adding references
later keeps the saved ball. Unsaved marks are lost when the frame leaves the
20-frame history or the window closes. Replacing a saved point JSON requires
confirmation.

Coordinates are saved in original-image pixels, independent of preview size.
Markers appear only in the viewer, not in the saved PNG; **Save Snapshot** also
includes current points in its JSON when creating a new snapshot. These are
manual observations, not a calibration or speed result. Ball speed still needs
known-distance calibration, movement compensation and consideration of the
ball's height above the floor.

## Shot Speed Overlay

[shot_overlay.py](shot_overlay.py) draws an analysis image on the **latest**
marked frame: a cyan ring around the ball, a straight fading trail from the
first to the last marked ball position (positions in between are not drawn),
and a panel with the estimated average speed. With `--floor-line`, dashed
helper lines form a triangle with the blue trail: a horizontal leg from the
first ball position labelled with the distance, a vertical leg up to the last
reference point on that frame (for example R2 = back of the net), and a line
from the last ball position to that reference. Helper lines are drawn beneath
the blue trail. It is off by default because the blue trail usually shows enough.

```sh
.venv-frame-viewer/bin/python shot_overlay.py frame_snapshots/*_points.json \
    --distance 6.1 --from 1:15.821 --to 1:16.038 -o shot_overlay.png
```

Speed is `distance / (to - from) * 3.6`, rounded to whole km/h. `--from` and
`--to` are the times you judged the ball left the stick and reached the end of
the distance. Use `--title` to change the caption (default: *Uppskattad
medelhastighet*). The video path is read from the point files; use `--video`
if it has moved. The output PNG is overwritten if it exists.

Add the image to the config as a freeze, for example after the slowed shot:

```text
video.mp4 | 1:15.5 | 1:15.971 | | 0.25
IMAGE | shot_overlay.png | 3 |
video.mp4 | 1:15.971 | 1:20 | | 1
```

This is an estimate of average speed over the chosen distance, not a measured
instantaneous shot speed. One frame of timing error changes the result
considerably at short distances. HDR source frames are converted to plain RGB,
so colours may differ slightly from an HDR compilation.

## Tests

Run the regression suite from the project folder:

```sh
python3 -m unittest -v test_create_compilation
python3 -m unittest -v test_frame_viewer
python3 -m unittest -v test_shot_overlay
# Or run all tests:
python3 -m unittest discover -v
```

The tests use Python's standard library; no extra packages or FFmpeg are needed.
Filesystem and subprocess operations are mocked, so no media is opened or
encoded. Coverage includes config parsing, explicit text line breaks, silent
sources, freeze frames, images, text outline/background options, black-screen audio offsets, duration fallbacks,
missing-source errors, failed clips and export CLI options. These are unit tests;
they do not verify actual encoded video, audio playback or FFmpeg compatibility.
The frame-viewer tests cover timestamp decoding, seeking, bounded frame history,
snapshot metadata, point selection, saving and reloading, and CLI errors without
requiring PyAV, Pillow or a desktop. The shot-overlay tests cover the speed
calculation, point loading, frame lookup by PTS and rendering on synthetic
images; Pillow is needed (available in the frame-viewer environment).

## Commit And Push To GitHub

Authenticate to your personal GitHub account using GitHub CLI with HTTPS,
or use an SSH key as an alternative.

### One-Time Setup On A New Computer Or Clone

#### GitHub CLI With HTTPS

Run in your terminal:

```sh
gh auth login --hostname github.com --git-protocol https --web
```

Follow the browser instructions and sign in as **PatricSperlingsson**. If asked
to authenticate Git with your GitHub credentials, choose **Yes**. Then run:

```sh
gh auth setup-git
git remote set-url origin https://github.com/PatricSperlingsson/video_highlights.git
git push origin main
```

The credential setup and remote URL persist, so future pushes normally need
only `git push origin main`. HTTPS authentication does not require an SSH agent.
The branch is `main`, not `master`.

#### SSH Alternative

The computer needs the private SSH key matching a public key registered under
your personal GitHub account in **Settings > SSH and GPG keys**. Never share
the private key. An SSH key or its fingerprint is not a personal access token
and cannot be entered at an HTTPS password prompt.

```sh
ssh -T git@github.com
```

Check that the greeting says `Hi PatricSperlingsson!`. GitHub's successful SSH
test normally exits with code 1 because it does not provide shell access.
If it greets your work account or reports `Permission denied (publickey)`,
resolve which SSH key is being used before pushing.

Configure this clone to use SSH rather than HTTPS:

```sh
git remote set-url origin git@github.com:PatricSperlingsson/video_highlights.git
```

This setting persists for this clone, so you do not need to repeat it for each
push. SSH uses your local key, not the credentials in `.netrc`. If prompted for
a key passphrase, enter it directly in your terminal.

### Normal Workflow

Run from the project folder after editing:

```sh
python3 -m unittest discover -v
git status --short
git diff
git add create_compilation.py frame_viewer.py shot_overlay.py \
    test_create_compilation.py test_frame_viewer.py test_shot_overlay.py \
    requirements-frame-viewer.txt README_VIDEO_COMPILATION.md video_config.txt
git diff --cached
git commit -m "Describe your changes"
git push origin main
```

Stage only the files you intend to publish; the explicit list above leaves out
media files and extra local configs. Inspect the staged diff before committing.
If the changes are already committed, just run `git push origin main`.
Pushing uploads all local commits on `main` not yet on GitHub, but does not
upload untracked or uncommitted files. No force push is needed.

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
- **"end time is not after start time":** the third field of a moving video
	clip is an end time, not a duration. To play `1:15.8` to `1:18.8`, write
	`1:15.8 | 1:18.8`. Only freezes (speed `0`) use a duration.
- **"No ball point saved" from shot_overlay.py:** open that frame in the viewer,
	click the ball in **Ball** mode and **Save Points** again.

Exports overwrite existing output files with the same name. Choose a different
`-o` name when you want to keep an earlier compilation.
