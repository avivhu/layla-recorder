#!/usr/bin/env python3
"""
Sleep Monitor - Camera recording
A Python-based sleep monitoring system for Raspberry Pi

Usage:
    See --help
"""

import argparse
import os
import signal
import time
import subprocess
from datetime import datetime
from pathlib import Path

import cv2

class SleepMonitor:
    def __init__(self):
        self.output_dir = Path(__file__).parent / "recordings"
        self.output_dir.mkdir(exist_ok=True)
        self.recording = False
        self.camera = None
        self.recording_process = None
        
    def get_camera_resolution(self):
        """Get the highest available camera resolution"""
        try:
            # Try to open camera and get maximum resolution
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                print("Warning: Could not open camera with OpenCV, using rpicam defaults")
                return 1920, 1080  # Default high resolution for rpicam
            
            # Get maximum resolution supported
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 9999)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 9999)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            
            print(f"Detected camera resolution: {width}x{height}")
            return width, height
        except Exception as e:
            print(f"Error detecting camera resolution: {e}")
            return 1920, 1080  # Default fallback
    
    def cleanup_camera_processes(self):
        """Kill any lingering rpicam-vid or ffmpeg processes"""
        try:
            subprocess.run(['pkill', '-9', 'rpicam-vid'], stderr=subprocess.DEVNULL, timeout=2)
            subprocess.run(['pkill', '-9', 'ffmpeg'], stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.5)  # Give processes time to clean up
        except Exception as e:
            print(f"Error cleaning up processes: {e}")
    
    def record_video_segment(self, duration: float):
        """Record a single video segment using rpicam-vid"""
        # Clean up any lingering processes first
        self.cleanup_camera_processes()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        video_file = self.output_dir / f"video_{timestamp}.mp4"
        pts_file = self.output_dir / f"video_{timestamp}.pts"

        duration_ms = int(duration * 1000)
        
        # Split into separate commands for better control
        rpicam_cmd = [
            'rpicam-vid',
            '--codec', 'mjpeg',
            '--framerate', '10',
            '--width', '2592',
            '--height', '1944',
            '--nopreview',
            '--shutter', '40000',
            '--gain', '2.0',
            '--awbgains', '1.0,2.5',
            '--denoise', 'auto',
            '-t', str(duration_ms),
            '--save-pts', str(pts_file),
            # '--metadata', 'metadata.json','--metadata-format','json',
            '-o', '-'
        ]
        
        ffmpeg_cmd = [
            'ffmpeg',
            '-f', 'mjpeg',
            '-r', '10',
            '-i', '-',
            '-f', 'alsa',
            '-thread_queue_size', '1024',
            '-i', 'sysdefault:CARD=CinemaTM',
            '-vf', "scale=1600:1200,drawtext=text='%{localtime} PTS\\: %{pts}s':fontsize=24:fontcolor=white:x=10:y=10",
            '-c:v', 'h264_v4l2m2m',
            '-pix_fmt', 'yuv420p',
            '-async', '1',
            '-r', '10',
            '-b:v', '1500k',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-shortest',
            str(video_file),
            '-y'
        ]

        rpicam_process = None
        ffmpeg_process = None
        
        try:
            print(f"Recording {duration}s video: {video_file}")
            print(f"Using commands:\n rpicam-vid: {' '.join(rpicam_cmd)}\n ffmpeg: {' '.join(ffmpeg_cmd)}")
            
            # Start rpicam-vid
            rpicam_process = subprocess.Popen(
                rpicam_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid  # Create new process group for easier cleanup
            )
            
            # Start ffmpeg with rpicam output as input
            ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=rpicam_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            # Close rpicam stdout in parent to allow proper pipe handling
            rpicam_process.stdout.close()
            
            # Wait for both processes with timeout
            timeout_deadline = time.time() + duration + 15
            
            while time.time() < timeout_deadline:
                rpicam_poll = rpicam_process.poll()
                ffmpeg_poll = ffmpeg_process.poll()
                
                # Both processes finished
                if rpicam_poll is not None and ffmpeg_poll is not None:
                    if ffmpeg_poll == 0:
                        print(f"Successfully recorded: {video_file}")
                        return True
                    else:
                        _, ffmpeg_err = ffmpeg_process.communicate(timeout=1)
                        print(f"Recording failed: {ffmpeg_err.decode()}")
                        return False
                
                time.sleep(0.5)
            
            # Timeout occurred
            print("Recording timed out")
            return False
            
        except FileNotFoundError as e:
            print(f"Command not found: {e}. Make sure rpicam-vid and ffmpeg are installed.")
            return False
        except Exception as e:
            print(f"Error during recording: {e}")
            return False
        finally:
            # Always clean up processes
            for process in [ffmpeg_process, rpicam_process]:
                if process and process.poll() is None:
                    try:
                        # Kill entire process group
                        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                        time.sleep(0.5)
                        if process.poll() is None:
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except Exception as e:
                        print(f"Error terminating process: {e}")
            
            # Final cleanup
            self.cleanup_camera_processes()
    
    def start_recording(self, duration: float, loop: bool):
        """Start continuous video recording in 60-second segments"""
        print("Starting continuous video recording...")
        print(f"Videos will be saved to: {self.output_dir}")
        
        self.recording = True
        segment_count = 0
        
        try:
            while self.recording:
                segment_count += 1
                print(f"\n--- Recording segment {segment_count} ---")
                
                success = self.record_video_segment(duration=duration)
                if not success:
                    print("Recording failed, waiting 5 seconds before retry...")
                    if loop:
                        time.sleep(5)
                        continue

                if not loop:
                    break

        except KeyboardInterrupt:
            print("\nStopping recording...")
            self.recording = False
        except Exception as e:
            print(f"Error in continuous recording: {e}")
            self.recording = False
    
    def stop_recording(self):
        """Stop the recording"""
        self.recording = False
    
    def get_video_files(self):
        """Get list of recorded video files with metadata"""
        videos = []
        
        if not self.output_dir.exists():
            return videos
            
        for video_file in sorted(self.output_dir.glob("*.mp4"), reverse=True):
            try:
                stat = video_file.stat()
                videos.append({
                    'name': video_file.name,
                    'path': str(video_file),
                    'size': stat.st_size,
                    'size_mb': round(stat.st_size / (1024*1024), 1),
                    'modified': datetime.fromtimestamp(stat.st_mtime),
                    'modified_str': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception as e:
                print(f"Error reading video file {video_file}: {e}")
                continue
                
        return videos
    

def main():
    parser = argparse.ArgumentParser(description='Sleep Monitor - Camera recording')
    subparsers = parser.add_subparsers(dest='command', help='Available commands', required=True)
    
    # Record subcommand
    record_parser = subparsers.add_parser('record', help='Start continuous video recording')
    record_parser.add_argument('--duration', type=int, default=120,
                              help='Duration of each recording segment in seconds (default: 120)')
    record_parser.add_argument('--loop', action='store_true', default=True,
                              help='Loop recording continuously (default: True)')
    record_parser.add_argument('--no-loop', dest='loop', action='store_false',
                              help='Record only one segment and exit')
    
    args = parser.parse_args()
    
    monitor = SleepMonitor()
    
    if args.command == 'record':
        print("Sleep Monitor - Recording Mode")
        print("Press Ctrl+C to stop recording")
        monitor.start_recording(duration=args.duration, loop=args.loop)


if __name__ == '__main__':
    main()
