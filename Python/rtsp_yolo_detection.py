import cv2
import torch
from ultralytics import YOLO
import numpy as np
import argparse
import time
import threading
from datetime import datetime
import os

class RTSPYOLODetector:
    def __init__(self, model_path, conf_threshold=0.5):
        """Initialize RTSP YOLO Detector"""
        self.model = self.load_model(model_path)
        self.conf_threshold = conf_threshold
        self.is_running = False
        self.current_stream = None
        
        # RTSP URLs list
        self.rtsp_urls = [
            # Local test streams (for testing with local FFmpeg streams)
            "rtsp://localhost:8554/testpattern",
            "rtsp://localhost:8555/objects", 
            "rtsp://localhost:8556/video",
            "rtsp://localhost:8557/webcam",
            # Public test streams
            "rtsp://wowzaec2demo.streamlock.net/vod/mp4:BigBuckBunny_115k.mov",
            "rtsp://freja.hiof.no:1935/rtplive/definst/hessdalen02.stream",
            "rtsp://freja.hiof.no:1935/rtplive/definst/hessdalen03.stream",
            "rtsp://demo:demo@ipvmdemo.dyndns.org:5542/onvif-media/media.amp?profile=profile_1_h264&sessiontimeout=60&streamtype=unicast"
        ]
        
    def load_model(self, model_path):
        """Load YOLOv11 model"""
        try:
            model = YOLO(model_path)
            print(f"✅ Model loaded successfully from: {model_path}")
            return model
        except Exception as e:
            print(f"❌ Error loading model: {e}")
            return None
    
    def connect_to_stream(self, rtsp_url, retry_attempts=3, timeout=10):
        """Connect to RTSP stream with retry mechanism"""
        for attempt in range(retry_attempts):
            try:
                print(f"🔄 Attempting to connect to stream (attempt {attempt + 1}/{retry_attempts})")
                print(f"📡 URL: {rtsp_url}")
                
                # Configure OpenCV for RTSP with shorter timeouts
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to minimize delay
                cap.set(cv2.CAP_PROP_FPS, 30)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)  # 5 second timeout
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)  # 5 second read timeout
                
                # Test if stream is opened
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        print(f"✅ Successfully connected to RTSP stream!")
                        print(f"📊 Stream resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
                        return cap
                    else:
                        print(f"⚠️ Stream opened but no frames received")
                        cap.release()
                else:
                    print(f"❌ Failed to open stream")
                    
            except Exception as e:
                print(f"❌ Connection attempt {attempt + 1} failed: {e}")
            
            if attempt < retry_attempts - 1:
                print(f"⏳ Waiting {timeout} seconds before retry...")
                time.sleep(timeout)
        
        print(f"❌ Failed to connect after {retry_attempts} attempts")
        return None
    
    def process_rtsp_stream(self, rtsp_url, save_output=False, output_path=None):
        """Process RTSP stream with YOLO detection"""
        if self.model is None:
            print("❌ No model loaded")
            return
        
        # Connect to stream
        cap = self.connect_to_stream(rtsp_url)
        if cap is None:
            return
        
        self.current_stream = cap
        self.is_running = True
        
        # Setup video writer if needed
        out = None
        if save_output and output_path:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_path, fourcc, 20.0, (width, height))
            print(f"💾 Recording to: {output_path}")
        
        frame_count = 0
        last_fps_time = time.time()
        fps_counter = 0
        display_fps = 0
        
        print("🎬 Starting stream processing...")
        print("ℹ️ Press 'q' to quit, 's' to switch stream, 'r' to reconnect")
        
        while self.is_running:
            try:
                ret, frame = cap.read()
                
                if not ret or frame is None:
                    print("⚠️ Lost connection to stream, attempting to reconnect...")
                    cap.release()
                    cap = self.connect_to_stream(rtsp_url, retry_attempts=2, timeout=5)
                    if cap is None:
                        print("❌ Failed to reconnect")
                        break
                    continue
                
                frame_count += 1
                fps_counter += 1
                
                # Calculate FPS
                current_time = time.time()
                if current_time - last_fps_time >= 1.0:
                    display_fps = fps_counter
                    fps_counter = 0
                    last_fps_time = current_time
                
                # Run YOLO detection
                results = self.model(frame, conf=self.conf_threshold, verbose=False)
                
                # Draw detections
                annotated_frame = results[0].plot()
                
                # Add overlay information
                self.add_overlay_info(annotated_frame, frame_count, display_fps, len(results[0].boxes) if results[0].boxes is not None else 0, rtsp_url)
                
                # Save frame if recording
                if out:
                    out.write(annotated_frame)
                
                # Display frame
                cv2.imshow('RTSP YOLOv11 Detection', annotated_frame)
                
                # Handle key presses
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("🛑 Stopping stream...")
                    break
                elif key == ord('s'):
                    print("🔄 Switching to next stream...")
                    break
                elif key == ord('r'):
                    print("🔄 Reconnecting to current stream...")
                    cap.release()
                    cap = self.connect_to_stream(rtsp_url)
                    if cap is None:
                        break
                    
            except Exception as e:
                print(f"❌ Error processing frame: {e}")
                time.sleep(1)
                continue
        
        # Cleanup
        self.is_running = False
        if cap:
            cap.release()
        if out:
            out.release()
        cv2.destroyAllWindows()
        
        print(f"✅ Stream processing stopped. Processed {frame_count} frames")
    
    def add_overlay_info(self, frame, frame_count, fps, detections, rtsp_url):
        """Add information overlay to frame"""
        height, width = frame.shape[:2]
        
        # Background for text
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (400, 120), (0, 0, 0), -1)
        frame = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)
        
        # Stream info
        url_display = rtsp_url.split('/')[-1][:30] + "..." if len(rtsp_url) > 30 else rtsp_url
        cv2.putText(frame, f"Stream: {url_display}", (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Frame: {frame_count}", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"FPS: {fps}", (15, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Detections: {detections}", (15, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Time: {datetime.now().strftime('%H:%M:%S')}", (15, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        
        # Controls
        cv2.putText(frame, "Controls: Q=Quit, S=Switch, R=Reconnect", (width-350, height-20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    
    def run_stream_cycle(self, save_output=False):
        """Run through all RTSP streams in cycle"""
        stream_index = 0
        
        while True:
            rtsp_url = self.rtsp_urls[stream_index]
            print(f"\n🎯 Processing stream {stream_index + 1}/{len(self.rtsp_urls)}")
            
            output_path = None
            if save_output:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"rtsp_output_stream_{stream_index + 1}_{timestamp}.mp4"
            
            self.process_rtsp_stream(rtsp_url, save_output, output_path)
            
            # Move to next stream
            stream_index = (stream_index + 1) % len(self.rtsp_urls)
            
            # Ask user if they want to continue
            print(f"\n🔄 Moving to next stream. Press Enter to continue or 'q' to quit...")
            user_input = input().strip().lower()
            if user_input == 'q':
                break
    
    def list_streams(self):
        """List all available RTSP streams"""
        print("\n📺 Available RTSP Streams:")
        for i, url in enumerate(self.rtsp_urls):
            print(f"{i + 1}. {url}")
        print()

def main():
    parser = argparse.ArgumentParser(description='YOLOv11 RTSP Stream Detection')
    parser.add_argument('--model', type=str, required=True,
                       help='Path to YOLOv11 model (.pt file)')
    parser.add_argument('--rtsp', type=str,
                       help='Custom RTSP URL')
    parser.add_argument('--conf', type=float, default=0.5,
                       help='Confidence threshold (default: 0.5)')
    parser.add_argument('--save', action='store_true',
                       help='Save output video')
    parser.add_argument('--list', action='store_true',
                       help='List available default RTSP streams')
    parser.add_argument('--stream-id', type=int,
                       help='Select specific stream by ID (1-4)')
    
    args = parser.parse_args()
    
    # Create detector
    detector = RTSPYOLODetector(args.model, args.conf)
    
    if detector.model is None:
        return
    
    # List streams if requested
    if args.list:
        detector.list_streams()
        return
    
    # Process specific RTSP URL
    if args.rtsp:
        print(f"🎯 Processing custom RTSP stream: {args.rtsp}")
        output_path = None
        if args.save:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"custom_rtsp_output_{timestamp}.mp4"
        detector.process_rtsp_stream(args.rtsp, args.save, output_path)
    
    # Process specific stream by ID
    elif args.stream_id:
        if 1 <= args.stream_id <= len(detector.rtsp_urls):
            rtsp_url = detector.rtsp_urls[args.stream_id - 1]
            print(f"🎯 Processing stream {args.stream_id}: {rtsp_url}")
            output_path = None
            if args.save:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"rtsp_stream_{args.stream_id}_{timestamp}.mp4"
            detector.process_rtsp_stream(rtsp_url, args.save, output_path)
        else:
            print(f"❌ Invalid stream ID. Available: 1-{len(detector.rtsp_urls)}")
    
    # Run stream cycle
    else:
        detector.run_stream_cycle(args.save)

if __name__ == "__main__":
    # Example usage without command line arguments
    if len(os.sys.argv) == 1:
        print("🎬 YOLOv11 RTSP Stream Detection")
        print("\nExample usage:")
        print("python rtsp_yolo_detection.py --model best.pt --list")
        print("python rtsp_yolo_detection.py --model best.pt --stream-id 1")
        print("python rtsp_yolo_detection.py --model best.pt --rtsp 'rtsp://your-stream-url'")
        print("python rtsp_yolo_detection.py --model best.pt --save")
        print("\n🚀 Starting with default settings...")
        
        # Default settings
        model_path = "best.pt"  # Change this to your model path
        
        detector = RTSPYOLODetector(model_path)
        if detector.model:
            detector.list_streams()
            print("🎯 Starting stream cycle...")
            detector.run_stream_cycle()
        else:
            print(f"❌ Model file {model_path} not found. Please update the path.")
    else:
        main() 