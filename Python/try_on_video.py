import cv2
import torch
from ultralytics import YOLO
import numpy as np
import argparse
import os

def load_model(model_path):
    """Load YOLOv11 model"""
    try:
        model = YOLO(model_path)
        print(f"Model loaded successfully from: {model_path}")
        return model
    except Exception as e:
        print(f"Error loading model: {e}")
        return None

def process_video(model, video_path, output_path=None, conf_threshold=0.5, show_video=True):
    """Process video with YOLOv11 detection"""
    
    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video {video_path}")
        return
    
    # Get video properties
    fps = int(cap.get(cv2.CAP_PROP_FPS))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    print(f"Video properties: {width}x{height}, {fps} FPS, {total_frames} frames")
    
    # Setup video writer if output path is specified
    out = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        print(f"Output will be saved to: {output_path}")
    
    frame_count = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        print(f"Processing frame {frame_count}/{total_frames}", end='\r')
        
        # Run YOLOv11 inference
        results = model(frame, conf=conf_threshold, verbose=False)
        
        # Draw detections on frame
        annotated_frame = results[0].plot()
        
        # Add frame info
        cv2.putText(annotated_frame, f"Frame: {frame_count}/{total_frames}", 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(annotated_frame, f"Detections: {len(results[0].boxes) if results[0].boxes is not None else 0}", 
                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Save frame if output is specified
        if out:
            out.write(annotated_frame)
        
        # Display frame if show_video is True
        if show_video:
            cv2.imshow('YOLOv11 Detection', annotated_frame)
            
            # Break on 'q' key press
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\nStopped by user")
                break
    
    # Cleanup
    cap.release()
    if out:
        out.release()
    if show_video:
        cv2.destroyAllWindows()
    
    print(f"\nProcessing complete! Processed {frame_count} frames")

def process_webcam(model, conf_threshold=0.5):
    """Process webcam feed with YOLOv11 detection"""
    
    cap = cv2.VideoCapture(0)  # Use default camera
    if not cap.isOpened():
        print("Error: Could not open webcam")
        return
    
    print("Starting webcam detection. Press 'q' to quit.")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: Could not read frame from webcam")
            break
        
        # Run YOLOv11 inference
        results = model(frame, conf=conf_threshold, verbose=False)
        
        # Draw detections on frame
        annotated_frame = results[0].plot()
        
        # Add detection count
        detection_count = len(results[0].boxes) if results[0].boxes is not None else 0
        cv2.putText(annotated_frame, f"Detections: {detection_count}", 
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(annotated_frame, "Press 'q' to quit", 
                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        
        # Display frame
        cv2.imshow('YOLOv11 Webcam Detection', annotated_frame)
        
        # Break on 'q' key press
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    
    cap.release()
    cv2.destroyAllWindows()
    print("Webcam detection stopped")

def main():
    parser = argparse.ArgumentParser(description='YOLOv11 Video Detection')
    parser.add_argument('--model', type=str, required=True, 
                       help='Path to YOLOv11 model (.pt file)')
    parser.add_argument('--video', type=str, 
                       help='Path to input video file')
    parser.add_argument('--output', type=str, 
                       help='Path to output video file')
    parser.add_argument('--conf', type=float, default=0.5, 
                       help='Confidence threshold (default: 0.5)')
    parser.add_argument('--webcam', action='store_true', 
                       help='Use webcam instead of video file')
    parser.add_argument('--no-display', action='store_true', 
                       help='Do not display video (useful for processing only)')
    
    args = parser.parse_args()
    
    # Load model
    model = load_model(args.model)
    if model is None:
        return
    
    # Process webcam or video
    if args.webcam:
        process_webcam(model, args.conf)
    elif args.video:
        if not os.path.exists(args.video):
            print(f"Error: Video file {args.video} does not exist")
            return
        
        show_video = not args.no_display
        process_video(model, args.video, args.output, args.conf, show_video)
    else:
        print("Error: Please specify either --video or --webcam")
        parser.print_help()

if __name__ == "__main__":
    # Example usage without command line arguments
    if len(os.sys.argv) == 1:
        print("YOLOv11 Video Detection Script")
        print("\nExample usage:")
        print("python try_on_video.py --model best.pt --video input.mp4 --output output.mp4")
        print("python try_on_video.py --model best.pt --webcam")
        print("python try_on_video.py --model best.pt --video input.mp4 --conf 0.7")
        print("\nRunning with default settings...")
        
        # Default settings for quick testing
        model_path = "D:/Nico_IOT/YOLOv11_trained_weights/train2.pt"  # Change this to your model path
        video_path = "D:/Nico_IOT/watafa - Made with Clipchamp.mp4"  # Change this to your video path
        
        if os.path.exists(model_path):
            model = load_model(model_path)
            if model and os.path.exists(video_path):
                process_video(model, video_path, conf_threshold=0.5)
            elif model:
                print(f"Model loaded but video {video_path} not found.")
                print("Trying webcam...")
                process_webcam(model)
        else:
            print(f"Model file {model_path} not found. Please update the path.")
    else:
        main()
