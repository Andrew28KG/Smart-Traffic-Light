#!/usr/bin/env python3
"""
Simple RTSP Test Setup
Creates test video streams for multi-lane RTSP YOLO testing
"""

import cv2
import numpy as np
import threading
import time
from datetime import datetime
import subprocess
import os

def create_test_video(filename, duration=60, fps=25):
    """Create a test video with moving objects"""
    width, height = 640, 480
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filename, fourcc, fps, (width, height))
    
    print(f"🎬 Creating test video: {filename}")
    
    for frame_num in range(duration * fps):
        # Create frame with moving objects
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (50, 50, 50)  # Dark gray background
        
        # Add moving "vehicles"
        t = frame_num / fps
        
        # Car 1 - moving left to right
        x1 = int((50 + t * 30) % (width + 100)) - 50
        if 0 < x1 < width - 60:
            cv2.rectangle(frame, (x1, 200), (x1 + 60, 240), (0, 255, 0), -1)
            cv2.putText(frame, "CAR", (x1 + 10, 225), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
        
        # Truck - moving right to left
        x2 = int(width - (30 + t * 20) % (width + 120))
        if 0 < x2 < width - 80:
            cv2.rectangle(frame, (x2, 300), (x2 + 80, 350), (0, 0, 255), -1)
            cv2.putText(frame, "TRUCK", (x2 + 10, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        
        # Motorcycle - moving diagonally
        x3 = int((100 + t * 40) % (width + 50)) - 25
        y3 = int(150 + 50 * np.sin(t * 0.5))
        if 0 < x3 < width - 30 and 0 < y3 < height - 20:
            cv2.rectangle(frame, (x3, y3), (x3 + 30, y3 + 20), (255, 255, 0), -1)
            cv2.putText(frame, "BIKE", (x3, y3 + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 0, 0), 1)
        
        # Add lane info
        cv2.putText(frame, f"LANE TEST - Frame {frame_num}", (10, 30), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"Time: {t:.1f}s", (10, 60), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        out.write(frame)
        
        if frame_num % (fps * 5) == 0:
            print(f"  📹 Progress: {frame_num // fps}s / {duration}s")
    
    out.release()
    print(f"✅ Test video created: {filename}")

def start_ffmpeg_rtsp_server(video_file, rtsp_url):
    """Start FFmpeg RTSP server"""
    cmd = [
        'ffmpeg',
        '-re',  # Read input at native frame rate
        '-stream_loop', '-1',  # Loop indefinitely
        '-i', video_file,
        '-c', 'copy',  # Copy without re-encoding
        '-f', 'rtsp',
        rtsp_url
    ]
    
    print(f"🚀 Starting RTSP server: {rtsp_url}")
    print(f"   📁 Video: {video_file}")
    
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return process
    except FileNotFoundError:
        print("❌ FFmpeg not found! Please install FFmpeg first.")
        print("   Download from: https://ffmpeg.org/download.html")
        return None

def main():
    print("🎥 RTSP Test Setup for Multi-Lane Detection")
    print("=" * 50)
    
    # Create test videos for 4 lanes
    test_videos = []
    for i in range(1, 5):
        video_file = f"test_lane_{i}.mp4"
        if not os.path.exists(video_file):
            create_test_video(video_file, duration=120)  # 2 minutes loop
        test_videos.append(video_file)
    
    print("\n🚀 RTSP Server Setup Options:")
    print("1. FFmpeg RTSP Streams (requires FFmpeg)")
    print("2. Generate test videos only")
    print("3. Test with webcam")
    
    choice = input("\nChoose option (1-3): ").strip()
    
    if choice == "1":
        # Start FFmpeg RTSP servers
        print("\n🎬 Starting RTSP servers...")
        rtsp_urls = [
            'rtsp://localhost:8554/cctv1',
            'rtsp://localhost:8554/cctv2',
            'rtsp://localhost:8554/cctv3',
            'rtsp://localhost:8554/cctv4'
        ]
        
        processes = []
        for i, (video_file, rtsp_url) in enumerate(zip(test_videos, rtsp_urls)):
            process = start_ffmpeg_rtsp_server(video_file, rtsp_url)
            if process:
                processes.append(process)
                time.sleep(2)  # Stagger startup
        
        if processes:
            print(f"\n✅ {len(processes)} RTSP streams started!")
            print("\n📡 RTSP URLs:")
            for i, url in enumerate(rtsp_urls[:len(processes)], 1):
                print(f"   Lane {i}: {url}")
            
            print("\n🚀 Now run the multi-lane detection:")
            print("   python multi_lane_rtsp_yolo.py --model best.pt")
            
            print("\n⚠️  Press Ctrl+C to stop all servers")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 Stopping RTSP servers...")
                for process in processes:
                    process.terminate()
    
    elif choice == "2":
        print("\n✅ Test videos created! You can use them with:")
        print("1. MediaMTX server")
        print("2. VLC streaming")
        print("3. Any RTSP server software")
        
    elif choice == "3":
        print("\n📷 Webcam test setup:")
        print("Replace RTSP URLs in multi_lane_rtsp_yolo.py with:")
        print("   Lane 1: 0 (default webcam)")
        print("   Lane 2-4: Use test videos or duplicate webcam")
        
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main() 