#!/usr/bin/env python3
"""
Video Compilation Script
Reads video_config.txt and creates a compiled video with text overlays
Requires: ffmpeg installed on your system
"""

import os
import subprocess
import sys
from pathlib import Path

def parse_config(config_file):
    """Parse the video configuration file."""
    clips = []
    
    def parse_time(time_str):
        """Convert time string to seconds. Supports formats: 
        - seconds: '26' or '26.5'
        - mm:ss: '1:12' 
        - hh:mm:ss: '1:12:30'
        """
        time_str = str(time_str).strip()
        parts = time_str.split(':')
        
        if len(parts) == 1:
            # Just seconds
            return float(parts[0])
        elif len(parts) == 2:
            # mm:ss
            minutes = float(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds
        elif len(parts) == 3:
            # hh:mm:ss
            hours = float(parts[0])
            minutes = float(parts[1])
            seconds = float(parts[2])
            return hours * 3600 + minutes * 60 + seconds
        else:
            raise ValueError(f"Invalid time format: {time_str}")
    
    with open(config_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            # Parse the line
            parts = [p.strip() for p in line.split('|')]
            
            if len(parts) < 2:
                print(f"Warning: Line {line_num} has invalid format, skipping")
                continue
            
            filename = parts[0]
            
            # Check if this is a BLACK SCREEN entry
            if filename.upper() == 'BLACK':
                try:
                    duration = parse_time(parts[1])
                    text_overlay = parts[2] if len(parts) > 2 else ""
                    
                    clips.append({
                        'type': 'black',
                        'duration': duration,
                        'text': text_overlay
                    })
                except ValueError as e:
                    print(f"Warning: Line {line_num} has invalid duration value, skipping: {e}")
                    continue
            else:
                # Regular video clip
                if len(parts) < 3:
                    print(f"Warning: Line {line_num} has invalid format for video clip, skipping")
                    continue
                    
                try:
                    start_time = parse_time(parts[1])
                    end_time = parse_time(parts[2])
                    text_overlay = parts[3] if len(parts) > 3 else ""
                    speed = parts[4] if len(parts) > 4 else "1"
                    arrow = parts[5] if len(parts) > 5 else ""
                    
                    # Parse speed: can be a number (0.5 for slow, 2 for fast, negative for reverse)
                    reverse = False
                    speed_value = 1.0
                    
                    if speed.lower() == 'reverse':
                        reverse = True
                    elif speed:
                        try:
                            speed_value = float(speed)
                            if speed_value < 0:
                                reverse = True
                                speed_value = abs(speed_value)
                        except ValueError:
                            speed_value = 1.0
                    
                    clips.append({
                        'type': 'video',
                        'filename': filename,
                        'start': start_time,
                        'end': end_time,
                        'text': text_overlay,
                        'arrow': arrow,
                        'speed': speed_value,
                        'reverse': reverse,
                        'duration': end_time - start_time
                    })
                except ValueError as e:
                    print(f"Warning: Line {line_num} has invalid time values, skipping: {e}")
                    continue
    
    return clips

def get_arrow_filter(arrow_spec):
    """Generate drawbox and drawtext filters for arrow overlay.
    
    Arrow format: degrees:x:y or degrees (uses default position)
    Degrees: 0-360 (0=right, 90=down, 180=left, 270=up)
    Example: '45:500:300' or just '0'
    """
    if not arrow_spec:
        return ""
    
    import math
    
    parts = arrow_spec.split(':')
    
    try:
        degrees = float(parts[0])
    except ValueError:
        print(f"Warning: Invalid arrow degrees '{parts[0]}', skipping arrow")
        return ""
    
    # Default positions (center of screen for 1920x1080)
    x = int(parts[1]) if len(parts) > 1 else 960
    y = int(parts[2]) if len(parts) > 2 else 540
    
    # Arrow size parameters
    arrow_length = 150
    thickness = 8
    color = "yellow"
    
    # Convert degrees to radians (0° = right, 90° = down, etc.)
    radians = math.radians(degrees)
    
    # Calculate end point of arrow
    end_x = x + int(arrow_length * math.cos(radians))
    end_y = y + int(arrow_length * math.sin(radians))
    
    # Calculate perpendicular points for arrow head
    head_length = 30
    head_angle = math.radians(30)  # 30 degree angle for arrow head
    
    left_x = end_x - int(head_length * math.cos(radians - head_angle))
    left_y = end_y - int(head_length * math.sin(radians - head_angle))
    
    right_x = end_x - int(head_length * math.cos(radians + head_angle))
    right_y = end_y - int(head_length * math.sin(radians + head_angle))
    
    # Create multiple small boxes to simulate a line
    filters = []
    steps = 30
    for i in range(steps + 1):
        t = i / steps
        line_x = int(x + t * (end_x - x))
        line_y = int(y + t * (end_y - y))
        filters.append(f"drawbox=x={line_x}:y={line_y}:w={thickness}:h={thickness}:color={color}:t=fill")
    
    # Draw arrow head (two lines)
    head_steps = 10
    for i in range(head_steps + 1):
        t = i / head_steps
        # Left side of arrow head
        hx1 = int(end_x + t * (left_x - end_x))
        hy1 = int(end_y + t * (left_y - end_y))
        filters.append(f"drawbox=x={hx1}:y={hy1}:w={thickness}:h={thickness}:color={color}:t=fill")
        # Right side of arrow head
        hx2 = int(end_x + t * (right_x - end_x))
        hy2 = int(end_y + t * (right_y - end_y))
        filters.append(f"drawbox=x={hx2}:y={hy2}:w={thickness}:h={thickness}:color={color}:t=fill")
    
    return ','.join(filters) if filters else ""

def create_compilation(clips, output_file='compilation.mp4', temp_dir='temp_clips'):
    """Create the video compilation using ffmpeg."""
    
    if not clips:
        print("Error: No valid clips found in configuration file")
        return False
    
    # Create temporary directory for processed clips
    Path(temp_dir).mkdir(exist_ok=True)
    
    # Process each clip
    processed_clips = []
    concat_list = []
    
    for i, clip in enumerate(clips):
        temp_output = f"{temp_dir}/clip_{i:03d}.mp4"
        
        if clip.get('type') == 'black':
            # Create black screen with text
            print(f"Creating black screen {i+1}/{len(clips)}: {clip['duration']}s with text '{clip['text']}'")
            
            if clip['text']:
                # Black screen with text
                filter_complex = (
                    f"color=c=black:s=1920x1080:d={clip['duration']}:r=30[v];"
                    f"[v]drawtext=text='{clip['text']}':fontsize=72:fontcolor=white:"
                    f"x=(w-text_w)/2:y=(h-text_h)/2[vout];"
                    f"anullsrc=channel_layout=stereo:sample_rate=44100:d={clip['duration']}[a]"
                )
                
                cmd = [
                    'ffmpeg',
                    '-filter_complex', filter_complex,
                    '-map', '[vout]', '-map', '[a]',
                    '-c:v', 'libx264', '-c:a', 'aac',
                    '-y', temp_output
                ]
            else:
                # Plain black screen
                cmd = [
                    'ffmpeg',
                    '-f', 'lavfi', '-i', f'color=c=black:s=1920x1080:d={clip["duration"]}:r=30',
                    '-f', 'lavfi', '-i', f'anullsrc=channel_layout=stereo:sample_rate=44100:d={clip["duration"]}',
                    '-c:v', 'libx264', '-c:a', 'aac',
                    '-y', temp_output
                ]
        else:
            # Regular video clip
            input_file = os.path.expanduser(clip['filename'])
            
            if not os.path.exists(input_file):
                print(f"Warning: File '{input_file}' not found, skipping")
                continue
            
            # Build ffmpeg command
            # Extract clip segment and optionally add text, arrow overlays, speed, and reverse
            has_text = bool(clip.get('text'))
            has_arrow = bool(clip.get('arrow'))
            speed = clip.get('speed', 1.0)
            reverse = clip.get('reverse', False)
            
            # Check if we need filter_complex
            needs_filters = has_text or has_arrow or speed != 1.0 or reverse
            
            if needs_filters:
                # Build filter chain
                video_filter = f"[0:v]trim=start={clip['start']}:end={clip['end']},setpts=PTS-STARTPTS"
                audio_filter = f"[0:a]atrim=start={clip['start']}:end={clip['end']},asetpts=PTS-STARTPTS"
                
                # Apply reverse if specified
                if reverse:
                    video_filter += ",reverse"
                    audio_filter += ",areverse"
                
                # Apply speed change if not 1.0
                # atempo only supports 0.5 to 2.0, so we need to chain multiple atempo filters for extreme speeds
                if speed != 1.0:
                    video_filter += f",setpts={1.0/speed}*PTS"
                    
                    # Handle audio tempo changes with chaining for values outside 0.5-2.0 range
                    if speed > 0:
                        tempo_value = speed
                        tempo_filters = []
                        
                        # atempo must be between 0.5 and 2.0, so chain multiple filters if needed
                        while tempo_value < 0.5:
                            tempo_filters.append("atempo=0.5")
                            tempo_value *= 2
                        while tempo_value > 2.0:
                            tempo_filters.append("atempo=2.0")
                            tempo_value /= 2
                        tempo_filters.append(f"atempo={tempo_value}")
                        
                        audio_filter += "," + ",".join(tempo_filters)
                
                # Add text overlay if specified
                if has_text:
                    video_filter += (
                        f",drawtext=text='{clip['text']}':fontsize=48:fontcolor=white:"
                        f"bordercolor=black:borderw=2:x=(w-text_w)/2:y=h-100"
                    )
                
                # Add arrow overlay if specified
                if has_arrow:
                    arrow_filter = get_arrow_filter(clip['arrow'])
                    if arrow_filter:
                        video_filter += f",{arrow_filter}"
                
                video_filter += "[v]"
                audio_filter += "[a]"
                
                filter_complex = f"{video_filter};{audio_filter}"
                
                cmd = [
                    'ffmpeg', '-i', input_file,
                    '-filter_complex', filter_complex,
                    '-map', '[v]', '-map', '[a]',
                    '-c:v', 'libx264', '-c:a', 'aac',
                    '-y', temp_output
                ]
            else:
                # No filters needed - simple cut
                cmd = [
                    'ffmpeg', '-i', input_file,
                    '-ss', str(clip['start']),
                    '-t', str(clip['duration']),
                    '-c:v', 'libx264', '-c:a', 'aac',
                    '-y', temp_output
                ]
            
            print(f"Processing clip {i+1}/{len(clips)}: {input_file} ({clip['start']}s - {clip['end']}s)")
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            processed_clips.append(temp_output)
            concat_list.append(f"file '{os.path.basename(temp_output)}'")
        except subprocess.CalledProcessError as e:
            print(f"Error processing clip: {e}")
            continue
    
    if not processed_clips:
        print("Error: No clips were successfully processed")
        return False
    
    # Create concat list file
    concat_file = f"{temp_dir}/concat_list.txt"
    with open(concat_file, 'w') as f:
        f.write('\n'.join(concat_list))
    
    # Concatenate all clips
    print(f"\nCombining {len(processed_clips)} clips into final video...")
    
    # Use absolute path for concat file
    abs_concat_file = os.path.abspath(concat_file)
    
    concat_cmd = [
        'ffmpeg', '-f', 'concat', '-safe', '0',
        '-i', abs_concat_file,
        '-c', 'copy',
        '-y', output_file
    ]
    
    try:
        subprocess.run(concat_cmd, check=True)
        print(f"\n✓ Successfully created: {output_file}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error creating final compilation: {e}")
        return False

def main():
    config_file = 'video_config.txt'
    output_file = 'compilation.mp4'
    
    # Check if config file exists
    if not os.path.exists(config_file):
        print(f"Error: Configuration file '{config_file}' not found")
        print("Please create video_config.txt with your video specifications")
        sys.exit(1)
    
    # Check if ffmpeg is installed
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: ffmpeg is not installed or not in PATH")
        print("Install ffmpeg: sudo apt install ffmpeg  (on Ubuntu/Debian)")
        sys.exit(1)
    
    # Parse configuration and create compilation
    print("Reading configuration file...")
    clips = parse_config(config_file)
    print(f"Found {len(clips)} clips to process\n")
    
    success = create_compilation(clips, output_file)
    
    if success:
        print(f"\nDone! Your compiled video is ready: {output_file}")
    else:
        print("\nCompilation failed. Check the errors above.")
        sys.exit(1)

if __name__ == '__main__':
    main()
