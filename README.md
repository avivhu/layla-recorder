# Sleep Monitor - Raspberry Pi Camera System

Continuous video recording and monitoring system for sleep analysis using Raspberry Pi with camera module.

## Features

- **Continuous Recording**: Records 120-second video segments continuously at highest camera resolution
- **High Quality**: Uses camera's maximum resolution with Raspberry Pi's H.264 hardware encoding.

## Quick Start

### Install Dependencies
```bash
uv sync
```

### Recording Mode
Start continuous video recording:
```bash
uv run sleep-monitor.py record
```
- Records 120-second MP4 videos continuously
- Videos saved to `recordings/` directory
- Press Ctrl+C to stop

## Installing as a System Service

To run the sleep monitor automatically in the background and on boot, install it as a systemd service.

### Installation Steps

1. **Copy the service file to systemd directory**:
```bash
sudo cp sleep-monitor.service /etc/systemd/system/
```

2. **Reload systemd to recognize the new service**:
```bash
sudo systemctl daemon-reload
```

## Managing the Service

The `service-control.sh` script provides convenient commands for managing the service.
```bash
./service-control.sh restart
```

## System Requirements

- Raspberry Pi with camera module (V1, V2, HQ, or V3). We target Raspberry Pi 4.
- Python 3.11+ 
- rpicam-vid (Raspberry Pi camera tools)


## Technical Details

### Recording
- Uses `rpicam-vid` for hardware-accelerated recording
- 10 FPS recording with H.264 codec
- Get camera mjpeg feed and pipe into ffmpeg, which performs h264 encoding using Raspberry Pi's hardware.
- Videos named with timestamp: `video_YYYYMMDD_HHMMSS.mp4`



## Troubleshooting

1. Camera Not Found
```bash
# Check camera connection
rpicam-hello --info

# Test camera
rpicam-vid --timeout 5000 --output test.mp4
```

2. Disk full
```bash
df / -h
```