#!/usr/bin/env python3
"""
MediaMTX RTSP Server Setup
Downloads and configures MediaMTX for hosting RTSP streams
"""

import subprocess
import time
import os
import requests
import zipfile
import threading

class MediaMTXServer:
    def __init__(self):
        self.server_process = None
        self.stream_processes = []
        
    def download_mediamtx(self):
        """Download MediaMTX if not exists"""
        if os.path.exists("mediamtx.exe"):
            print("✅ MediaMTX already exists")
            return True
            
        print("📥 Downloading MediaMTX...")
        try:
            url = "https://github.com/bluenviron/mediamtx/releases/latest/download/mediamtx_v1.5.1_windows_amd64.zip"
            response = requests.get(url, stream=True)
            
            with open("mediamtx.zip", "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print("📦 Extracting MediaMTX...")
            with zipfile.ZipFile("mediamtx.zip", 'r') as zip_ref:
                zip_ref.extractall()
            
            os.remove("mediamtx.zip")
            print("✅ MediaMTX downloaded and extracted")
            return True
            
        except Exception as e:
            print(f"❌ Failed to download MediaMTX: {e}")
            return False
    
    def start_server(self):
        """Start MediaMTX server"""
        if not os.path.exists("mediamtx.exe"):
            if not self.download_mediamtx():
                return False
        
        print("🚀 Starting MediaMTX RTSP server...")
        try:
            self.server_process = subprocess.Popen(
                ["mediamtx.exe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait a moment for server to start
            time.sleep(3)
            
            if self.server_process.poll() is None:
                print("✅ MediaMTX server started successfully!")
                print("📺 RTSP server running on: rtsp://localhost:8554/")
                print("🌐 Web interface: http://localhost:8889/")
                return True
            else:
                print("❌ MediaMTX server failed to start")
                return False
                
        except Exception as e:
            print(f"❌ Error starting server: {e}")
            return False
    
    def create_test_stream(self, stream_name="test", port=8554):
        """Create a test pattern stream to the RTSP server"""
        cmd = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', 'testsrc=size=1280x720:rate=25',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', '10',
            '-f', 'rtsp',
            f'rtsp://localhost:{port}/{stream_name}'
        ]
        
        print(f"🎬 Starting test stream: rtsp://localhost:{port}/{stream_name}")
        try:
            process = subprocess.Popen(cmd)
            self.stream_processes.append(process)
            return process
        except Exception as e:
            print(f"❌ Failed to start stream: {e}")
            return None
    
    def create_moving_objects_stream(self, stream_name="objects", port=8554):
        """Create a stream with moving objects for YOLO testing"""
        filter_complex = (
            "testsrc=size=1280x720:rate=25:duration=0,"
            "drawbox=x=20+10*t:y=20:w=100:h=100:color=red@0.8:t=fill,"
            "drawbox=x=200+50*sin(t):y=200+50*cos(t):w=80:h=80:color=blue@0.8:t=fill,"
            "drawbox=x=400+30*sin(0.5*t):y=100+30*cos(0.3*t):w=60:h=60:color=green@0.8:t=fill"
        )
        
        cmd = [
            'ffmpeg',
            '-f', 'lavfi',
            '-i', filter_complex,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-g', '10',
            '-f', 'rtsp',
            f'rtsp://localhost:{port}/{stream_name}'
        ]
        
        print(f"🎯 Starting moving objects stream: rtsp://localhost:{port}/{stream_name}")
        try:
            process = subprocess.Popen(cmd)
            self.stream_processes.append(process)
            return process
        except Exception as e:
            print(f"❌ Failed to start moving objects stream: {e}")
            return None
    
    def stop_all(self):
        """Stop all streams and server"""
        print("🛑 Stopping all streams...")
        for process in self.stream_processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        
        if self.server_process:
            print("🛑 Stopping MediaMTX server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
        
        print("✅ All services stopped")

def main():
    server = MediaMTXServer()
    
    print("🎬 MediaMTX RTSP Server Setup")
    print("=" * 40)
    print("1. Start RTSP server only")
    print("2. Start server + test pattern stream")
    print("3. Start server + moving objects stream")
    print("4. Start server + both streams")
    print("0. Exit")
    
    choice = input("\nSelect option (0-4): ").strip()
    
    if choice == "0":
        return
    
    # Start server first
    if not server.start_server():
        return
    
    try:
        if choice == "1":
            print("\n✅ RTSP server is running!")
            print("You can now push streams to rtsp://localhost:8554/[stream_name]")
            
        elif choice == "2":
            time.sleep(2)
            server.create_test_stream("test")
            print("\n📺 Available stream: rtsp://localhost:8554/test")
            
        elif choice == "3":
            time.sleep(2)
            server.create_moving_objects_stream("objects")
            print("\n📺 Available stream: rtsp://localhost:8554/objects")
            
        elif choice == "4":
            time.sleep(2)
            server.create_test_stream("test")
            time.sleep(1)
            server.create_moving_objects_stream("objects")
            print("\n📺 Available streams:")
            print("- rtsp://localhost:8554/test")
            print("- rtsp://localhost:8554/objects")
        
        print("\n🎯 Test with your YOLO detection:")
        print("python rtsp_yolo_detection.py --model best.pt --rtsp 'rtsp://localhost:8554/test'")
        print("python rtsp_yolo_detection.py --model best.pt --rtsp 'rtsp://localhost:8554/objects'")
        print("\nPress Enter to stop...")
        input()
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user")
    finally:
        server.stop_all()

if __name__ == "__main__":
    main() 