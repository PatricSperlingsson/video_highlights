# Video Compilation Guide

This folder contains tools to create a compiled video from your MP4 files with custom time ranges and text overlays.

## Files

- **video_config.txt** - Configuration file where you specify which clips to use
- **create_compilation.py** - Python script that creates the compiled video
- **README_VIDEO_COMPILATION.md** - This guide

## How to Use

### Step 1: Edit video_config.txt

Open `video_config.txt` and add your video clips in this format:

```
filename | start_time | end_time | text_overlay
```

**Example:**
```
20251108_090053.mp4 | 3 | 5 | jada
20251018_090600.mp4 | 0 | 10 | 
20251018_091008.mp4 | 2.5 | 6 | awesome goal!
```

- **filename**: Name of the MP4 file (must be in the same folder)
- **start_time**: Start time in seconds (can use decimals like 3.5)
- **end_time**: End time in seconds
- **text_overlay**: Text to display on the video (leave blank for no text)

Lines starting with `#` are comments and will be ignored.

### Step 2: Install ffmpeg (if not already installed)

```bash
# On Ubuntu/Debian
sudo apt install ffmpeg

# On macOS
brew install ffmpeg

# Check if installed
ffmpeg -version
```

### Step 3: Run the Script

```bash
python3 create_compilation.py
```

The script will:
1. Read your configuration from `video_config.txt`
2. Extract the specified time ranges from each video
3. Add text overlays where specified
4. Combine everything into `compilation.mp4`

## Output

- **compilation.mp4** - Your final compiled video
- **temp_clips/** - Temporary folder with processed clips (can be deleted after)

## Tips

- Time ranges can overlap or be non-consecutive
- Text overlays appear at the bottom center of the video
- All clips will be re-encoded to ensure compatibility
- The script preserves audio from each clip

## Troubleshooting

**"File not found" error**: Make sure the MP4 filename in video_config.txt matches exactly (including case)

**ffmpeg not found**: Install ffmpeg using the commands in Step 2

**Text not displaying**: Check that you're using the pipe (|) separator correctly

## Your Available Videos

You have 74 MP4 files in this folder. Some examples:
- 20251108_090053.mp4
- 20251018_090600.mp4
- 20251018_091008.mp4
- 20251122_095544.mp4
- And 70 more...

Run this command to see all your videos:
```bash
ls -1 *.mp4
```
