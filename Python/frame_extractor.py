import cv2
import os
import argparse
import gc
import time
from pathlib import Path

def extract_frames(video_path, output_dir="extracted_frames", interval_seconds=1.0, max_frames=None, quality=95):
    """
    Extract frames from a video at specified intervals with memory optimization.
    
    Args:
        video_path (str): Path to the input video file
        output_dir (str): Directory to save extracted frames
        interval_seconds (float): Interval between frame extractions in seconds
        max_frames (int): Maximum number of frames to extract (None for no limit)
        quality (int): JPEG quality (1-100, higher = better quality but larger files)
    """
    
    # Create output directory if it doesn't exist
    Path(output_dir).mkdir(exist_ok=True)
    
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        return
    
    # Get video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # Calculate estimated output
    frame_interval = int(fps * interval_seconds)
    estimated_frames = total_frames // frame_interval
    if max_frames:
        estimated_frames = min(estimated_frames, max_frames)
    
    print(f"Video info:")
    print(f"  - Resolution: {width}x{height}")
    print(f"  - FPS: {fps}")
    print(f"  - Total frames: {total_frames}")
    print(f"  - Duration: {duration:.2f} seconds")
    print(f"  - File size: {os.path.getsize(video_path) / (1024**3):.2f} GB")
    print(f"  - Extracting every {interval_seconds} seconds")
    print(f"  - Estimated frames to extract: {estimated_frames}")
    print(f"  - JPEG quality: {quality}%")
    print()
    
    # JPEG compression parameters for memory efficiency
    jpeg_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    
    frame_count = 0
    extracted_count = 0
    start_time = time.time()
    last_progress_time = start_time
    
    print("Starting extraction...")
    
    while True:
        ret, frame = cap.read()
        
        if not ret:
            break
        
        # Extract frame at specified intervals
        if frame_count % frame_interval == 0:
            # Generate filename with timestamp
            timestamp = frame_count / fps
            filename = f"frame_{extracted_count:06d}_t{timestamp:.2f}s.jpg"
            filepath = os.path.join(output_dir, filename)
            
            # Save the frame with compression
            success = cv2.imwrite(filepath, frame, jpeg_params)
            
            if success:
                extracted_count += 1
                
                # Progress reporting every 5 seconds
                current_time = time.time()
                if current_time - last_progress_time >= 5.0:
                    progress = (frame_count / total_frames) * 100
                    elapsed = current_time - start_time
                    fps_processing = frame_count / elapsed if elapsed > 0 else 0
                    eta = (total_frames - frame_count) / fps_processing / fps if fps_processing > 0 else 0
                    
                    print(f"Progress: {progress:.1f}% | Extracted: {extracted_count} frames | "
                          f"Processing: {fps_processing:.1f} fps | ETA: {eta/60:.1f} min")
                    last_progress_time = current_time
                
                # Check if we've reached the maximum number of frames
                if max_frames and extracted_count >= max_frames:
                    print(f"Reached maximum frame limit: {max_frames}")
                    break
            else:
                print(f"Warning: Failed to save frame at {timestamp:.2f}s")
        
        frame_count += 1
        
        # Force garbage collection every 100 frames for memory management
        if frame_count % 100 == 0:
            gc.collect()
    
    # Release the video capture object
    cap.release()
    
    # Final statistics
    end_time = time.time()
    total_time = end_time - start_time
    
    print(f"\nExtraction complete!")
    print(f"Total frames extracted: {extracted_count}")
    print(f"Total processing time: {total_time/60:.2f} minutes")
    print(f"Average processing speed: {frame_count/total_time:.1f} fps")
    print(f"Frames saved in: {output_dir}")
    
    # Calculate output size
    if extracted_count > 0:
        sample_file = os.path.join(output_dir, os.listdir(output_dir)[0])
        if os.path.exists(sample_file):
            avg_frame_size = os.path.getsize(sample_file)
            estimated_total_size = avg_frame_size * extracted_count
            print(f"Estimated output size: {estimated_total_size / (1024**2):.1f} MB")

def main():
    parser = argparse.ArgumentParser(description="Extract frames from video at specified intervals")
    parser.add_argument("video_path", help="Path to the input video file")
    parser.add_argument("-o", "--output", default="extracted_frames", help="Output directory for frames")
    parser.add_argument("-i", "--interval", type=float, default=1.0, help="Interval between frames in seconds")
    parser.add_argument("-m", "--max-frames", type=int, help="Maximum number of frames to extract")
    parser.add_argument("-q", "--quality", type=int, default=95, help="JPEG quality (1-100)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.video_path):
        print(f"Error: Video file '{args.video_path}' not found")
        return
    
    extract_frames(args.video_path, args.output, args.interval, args.max_frames, args.quality)

if __name__ == "__main__":
    # If run without command line arguments, use the video file in the workspace
    if len(os.sys.argv) == 1:
        video_file = "watafa - Made with Clipchamp.mp4"
        if os.path.exists(video_file):
            print("No arguments provided. Using default settings:")
            print(f"Video: {video_file}")
            print("Interval: 1 second")
            print("Output directory: extracted_frames")
            print()
            extract_frames(video_file)
        else:
            print(f"Error: Default video file '{video_file}' not found")
            print("Usage: python frame_extractor.py <video_path> [-o output_dir] [-i interval] [-m max_frames] [-q quality]")
    else:
        main() 