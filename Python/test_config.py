#!/usr/bin/env python3
"""
Test Configuration for Multi-Lane RTSP YOLO
Quick setup for different testing scenarios
"""

import os

# Test configurations
TEST_CONFIGS = {
    "webcam": {
        "name": "Webcam Test",
        "streams": [0, 0, 0, 0],  # Use webcam for all lanes
        "description": "Use webcam for all 4 lanes (testing)"
    },
    
    "mixed": {
        "name": "Mixed Test", 
        "streams": [
            0,  # Webcam for lane 1
            "test_lane_2.mp4",  # Video file for lane 2
            "test_lane_3.mp4",  # Video file for lane 3
            "test_lane_4.mp4"   # Video file for lane 4
        ],
        "description": "Webcam + test videos"
    },
    
    "rtsp": {
        "name": "RTSP Streams",
        "streams": [
            "rtsp://localhost:8554/cctv1",
            "rtsp://localhost:8554/cctv2", 
            "rtsp://localhost:8554/cctv3",
            "rtsp://localhost:8554/cctv4"
        ],
        "description": "Full RTSP server setup"
    },
    
    "single": {
        "name": "Single Lane Test",
        "streams": [0],  # Just one lane for testing
        "description": "Test with single webcam"
    }
}

def generate_command(config_name, model_path="best.pt"):
    """Generate command to run multi-lane detection"""
    if config_name not in TEST_CONFIGS:
        print(f"❌ Unknown config: {config_name}")
        return None
    
    config = TEST_CONFIGS[config_name]
    streams = config["streams"]
    
    if config_name == "single":
        # For single lane, modify the script call
        cmd = f"python multi_lane_rtsp_yolo.py --model {model_path} --streams {streams[0]}"
    else:
        # For multi-lane
        stream_args = " ".join([f'"{s}"' for s in streams])
        cmd = f"python multi_lane_rtsp_yolo.py --model {model_path} --streams {stream_args}"
    
    return cmd

def main():
    print("🧪 Multi-Lane RTSP YOLO Test Configuration")
    print("=" * 50)
    
    # Show available configurations
    print("📋 Available test configurations:")
    for i, (key, config) in enumerate(TEST_CONFIGS.items(), 1):
        print(f"{i}. {config['name']}: {config['description']}")
    
    print(f"\n{len(TEST_CONFIGS)+1}. Custom setup")
    
    choice = input(f"\nChoose configuration (1-{len(TEST_CONFIGS)+1}): ").strip()
    
    try:
        choice_num = int(choice)
        config_keys = list(TEST_CONFIGS.keys())
        
        if 1 <= choice_num <= len(TEST_CONFIGS):
            config_name = config_keys[choice_num - 1]
            config = TEST_CONFIGS[config_name]
            
            print(f"\n📋 Selected: {config['name']}")
            print(f"📝 Description: {config['description']}")
            print(f"🎥 Streams: {config['streams']}")
            
            # Check model file
            model_path = input("\n📁 Model file path (default: best.pt): ").strip()
            if not model_path:
                model_path = "best.pt"
            
            if not os.path.exists(model_path):
                print(f"⚠️  Model file {model_path} not found!")
                create_model = input("Create dummy model for testing? (y/n): ").strip().lower()
                if create_model == 'y':
                    # Create a dummy model file
                    with open(model_path, 'w') as f:
                        f.write("# Dummy model file for testing")
                    print(f"✅ Created dummy model: {model_path}")
                else:
                    print("❌ Cannot proceed without model file")
                    return
            
            # Generate command
            cmd = generate_command(config_name, model_path)
            if cmd:
                print(f"\n🚀 Command to run:")
                print(f"   {cmd}")
                
                print(f"\n📋 Pre-flight checklist:")
                if config_name == "rtsp":
                    print("   ✅ RTSP server running (run test_rtsp_setup.py first)")
                if config_name in ["mixed", "single"] and any("test_lane" in str(s) for s in config['streams']):
                    print("   ✅ Test videos created (run test_rtsp_setup.py first)")
                if config_name == "webcam":
                    print("   ✅ Webcam connected and working")
                
                print("   ✅ MQTT broker accessible (broker.emqx.io)")
                print("   ✅ Database accessible (optional)")
                print("   ✅ YOLO model available")
                
                run_now = input("\n🎬 Run detection now? (y/n): ").strip().lower()
                if run_now == 'y':
                    print(f"\n🚀 Starting detection...")
                    os.system(cmd)
        
        elif choice_num == len(TEST_CONFIGS) + 1:
            print("\n🛠️  Custom setup:")
            print("Edit multi_lane_rtsp_yolo.py directly or create your own configuration")
            
    except ValueError:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main() 