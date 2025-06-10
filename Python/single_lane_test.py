#!/usr/bin/env python3
"""
Single Lane RTSP YOLO Vehicle Detection Test
Simplified version of multi_lane_rtsp_yolo.py for testing
"""

import cv2
import time
import numpy as np
from ultralytics import YOLO
import argparse
import os
import sys
from collections import defaultdict

def main():
    parser = argparse.ArgumentParser(description='Single Lane RTSP YOLO Vehicle Detection Test')
    parser.add_argument('--model', type=str, default="YOLOv11_trained_weights/train1.pt", help='Path to YOLO model (.pt file)')
    parser.add_argument('--conf', type=float, default=0.25, help='Confidence threshold (default: 0.25)')
    parser.add_argument('--stream', type=str, 
                       default='rtsp://opr:User321@@@10.10.1.7:554/Streaming/channels/101',
                       help='RTSP stream URL')
    parser.add_argument('--camera', type=int, default=-1, help='Use local camera (0, 1, etc.) instead of RTSP stream')
    
    args = parser.parse_args()
    
    print("🚦 Single Lane RTSP YOLO Vehicle Detection Test")
    print("=" * 60)
    print(f"📹 Model: {args.model}")
    print(f"🎯 Confidence: {args.conf}")
    
    if args.camera >= 0:
        print(f"📷 Using local camera: {args.camera}")
        stream_source = args.camera
    else:
        print(f"🔗 RTSP Stream: {args.stream}")
        stream_source = args.stream
    
    # Check if model exists
    if not os.path.exists(args.model):
        print(f"❌ Model file {args.model} not found!")
        return
    
    # Load YOLO model
    try:
        print("Loading YOLO model...")
        model = YOLO(args.model)
        print(f"✅ Model loaded successfully")
    except Exception as e:
        print(f"❌ Error loading model: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Vehicle classes to detect and count
    vehicle_classes = ['mobil', 'truck', 'motor', 'bus']
    
    # Connect to stream
    try:
        print(f"Connecting to video source: {stream_source}")
        cap = cv2.VideoCapture(stream_source)
        
        # Set capture properties
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if stream_source != 0 and stream_source != 1:  # Don't set these for webcams
            cap.set(cv2.CAP_PROP_FPS, 25)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        
        if not cap.isOpened():
            print("❌ Failed to open video source")
            return
            
        print(f"✅ Connected! Resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    except Exception as e:
        print(f"❌ Error connecting to video source: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Create window
    window_name = "Single Lane YOLO Detection"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 960, 540)
    
    # Performance tracking
    fps = 0
    fps_counter = 0
    last_fps_time = time.time()
    
    # Vehicle counts
    vehicle_counts = defaultdict(int)
    total_vehicles = 0
    
    print("\n🎬 Starting detection loop...")
    print("Press 'q' to quit")
    
    try:
        while True:
            # Read frame
            ret, frame = cap.read()
            if not ret or frame is None:
                print("⚠️ Failed to read frame, retrying...")
                time.sleep(0.5)
                continue
            
            # Run YOLO detection
            results = model(frame, conf=args.conf, verbose=False)
            
            # Process detections
            current_vehicle_counts = defaultdict(int)
            if results[0].boxes is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                scores = results[0].boxes.conf.cpu().numpy()
                classes = results[0].boxes.cls.cpu().numpy()
                
                for i, (box, score, cls) in enumerate(zip(boxes, scores, classes)):
                    class_name = results[0].names[int(cls)].lower()
                    if class_name in vehicle_classes:
                        current_vehicle_counts[class_name] += 1
                        
                        # Draw bounding box
                        x1, y1, x2, y2 = map(int, box)
                        
                        # Different color for each vehicle type
                        if class_name == 'mobil':
                            color = (255, 0, 0)  # Blue for cars
                        elif class_name == 'motor':
                            color = (0, 255, 0)  # Green for motorcycles
                        elif class_name == 'truck':
                            color = (0, 0, 255)  # Red for trucks
                        else:  # bus
                            color = (0, 255, 255)  # Yellow for buses
                        
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        # Add label with confidence
                        label = f"{class_name}: {score:.2f}"
                        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            
            # Update vehicle counts
            vehicle_counts = current_vehicle_counts
            total_vehicles = sum(current_vehicle_counts.values())
            
            # Update FPS
            fps_counter += 1
            current_time = time.time()
            if current_time - last_fps_time >= 1.0:
                fps = fps_counter
                fps_counter = 0
                last_fps_time = current_time
            
            # Add info overlay
            cv2.rectangle(frame, (10, 10), (250, 120), (0, 0, 0), -1)
            cv2.putText(frame, f"FPS: {fps}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.putText(frame, f"Total: {total_vehicles}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Show individual counts
            y_offset = 90
            for vehicle_type, count in vehicle_counts.items():
                cv2.putText(frame, f"{vehicle_type}: {count}", (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                y_offset += 20
            
            # Display frame
            cv2.imshow(window_name, frame)
            
            # Check for exit
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
    
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"❌ Error in main loop: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        cap.release()
        cv2.destroyAllWindows()
        print("✅ Cleanup complete")

if __name__ == "__main__":
    main() 