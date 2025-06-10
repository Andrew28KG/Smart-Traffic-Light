#!/usr/bin/env python3
"""
Test script for checking dependencies required by multi_lane_rtsp_yolo.py
"""

import sys
import os
import traceback
import time

def test_opencv():
    """Test if OpenCV is working properly"""
    print("\n=== Testing OpenCV ===")
    try:
        import cv2
        print(f"✅ OpenCV imported successfully (version {cv2.__version__})")
        
        # Try to create a VideoCapture object
        try:
            cap = cv2.VideoCapture(0)
            print("✅ VideoCapture object created")
            
            if cap.isOpened():
                print("✅ Default camera opened successfully")
                ret, frame = cap.read()
                if ret:
                    print(f"✅ Frame read successfully ({frame.shape[1]}x{frame.shape[0]})")
                else:
                    print("⚠️ Could not read frame from camera")
                cap.release()
            else:
                print("⚠️ Could not open default camera")
        except Exception as e:
            print(f"❌ Error with VideoCapture: {e}")
            traceback.print_exc()
    except ImportError:
        print("❌ OpenCV (cv2) not installed")
        print("   Install with: pip install opencv-python")
    except Exception as e:
        print(f"❌ Error importing OpenCV: {e}")
        traceback.print_exc()

def test_mqtt():
    """Test if MQTT is working properly"""
    print("\n=== Testing MQTT ===")
    try:
        import paho.mqtt.client as mqtt
        print(f"✅ paho-mqtt imported successfully")
        
        # Check version
        try:
            import paho.mqtt
            print(f"✅ paho-mqtt version: {paho.mqtt.__version__}")
        except:
            print("⚠️ Could not determine paho-mqtt version")
        
        # Check for MQTTv5
        try:
            from paho.mqtt.client import MQTTv5
            print("✅ MQTTv5 support available")
        except ImportError:
            print("⚠️ MQTTv5 support not available")
        
        # Check for CallbackAPIVersion
        try:
            from paho.mqtt.client import CallbackAPIVersion
            print("✅ CallbackAPIVersion support available")
        except ImportError:
            print("⚠️ CallbackAPIVersion not available")
        
        # Try to create a client
        try:
            # Try modern client first
            try:
                from paho.mqtt.client import MQTTv5, CallbackAPIVersion
                client = mqtt.Client(
                    callback_api_version=CallbackAPIVersion.VERSION2,
                    client_id="test_client",
                    protocol=MQTTv5
                )
                print("✅ MQTTv5 client created successfully")
            except Exception as e:
                print(f"⚠️ Error creating MQTTv5 client: {e}")
                print("   Trying legacy client...")
                client = mqtt.Client(client_id="test_client")
                print("✅ Legacy MQTT client created successfully")
            
            # Define callbacks
            def on_connect(client, userdata, flags, rc, *args):
                print(f"✅ Connected with result code {rc}")
                client.disconnect()
            
            def on_disconnect(client, userdata, rc, *args):
                print(f"✅ Disconnected with result code {rc}")
            
            # Set callbacks
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            
            # Try to connect
            print("Attempting to connect to broker.emqx.io...")
            client.connect("broker.emqx.io", 1883, 5)
            client.loop_start()
            
            # Wait for connection
            time.sleep(3)
            client.loop_stop()
            
        except Exception as e:
            print(f"❌ Error with MQTT client: {e}")
            traceback.print_exc()
    except ImportError:
        print("❌ paho-mqtt not installed")
        print("   Install with: pip install paho-mqtt")
    except Exception as e:
        print(f"❌ Error importing paho-mqtt: {e}")
        traceback.print_exc()

def test_ultralytics():
    """Test if Ultralytics YOLO is working properly"""
    print("\n=== Testing Ultralytics YOLO ===")
    try:
        from ultralytics import YOLO
        print(f"✅ Ultralytics imported successfully")
        
        # Check if a model file exists
        model_paths = [
            "best.pt",
            "YOLOv11_trained_weights/train1.pt",
            "yolov8n.pt"
        ]
        
        model_found = False
        for model_path in model_paths:
            if os.path.exists(model_path):
                print(f"✅ Found model file: {model_path}")
                model_found = True
                
                # Try to load the model
                try:
                    print(f"Loading model {model_path}...")
                    model = YOLO(model_path)
                    print(f"✅ Model loaded successfully")
                except Exception as e:
                    print(f"❌ Error loading model: {e}")
                    traceback.print_exc()
                
                break
        
        if not model_found:
            print("⚠️ No model files found")
    except ImportError:
        print("❌ Ultralytics not installed")
        print("   Install with: pip install ultralytics")
    except Exception as e:
        print(f"❌ Error importing Ultralytics: {e}")
        traceback.print_exc()

def test_mysql():
    """Test if MySQL connector is working properly"""
    print("\n=== Testing MySQL Connector ===")
    try:
        import mysql.connector
        print(f"✅ MySQL connector imported successfully")
        
        # Try to create a connection
        try:
            print("Attempting to connect to database...")
            conn = mysql.connector.connect(
                host="api-traffic-light.apotekbless.my.id",
                user="u190944248_traffic_light",
                password="TrafficLight2025.",
                connection_timeout=5
            )
            print("✅ Connected to database server")
            
            try:
                conn.database = "u190944248_traffic_light"
                cursor = conn.cursor()
                print("✅ Database selected")
                cursor.close()
            except Exception as e:
                print(f"❌ Error selecting database: {e}")
            
            conn.close()
            print("✅ Database connection closed")
        except Exception as e:
            print(f"❌ Error connecting to database: {e}")
            traceback.print_exc()
    except ImportError:
        print("❌ MySQL connector not installed")
        print("   Install with: pip install mysql-connector-python")
    except Exception as e:
        print(f"❌ Error importing MySQL connector: {e}")
        traceback.print_exc()

def main():
    """Run all tests"""
    print("=== Dependency Test for multi_lane_rtsp_yolo.py ===")
    print(f"Python version: {sys.version}")
    print(f"Platform: {sys.platform}")
    
    # Run tests
    test_opencv()
    test_mqtt()
    test_ultralytics()
    test_mysql()
    
    print("\n=== Test Summary ===")
    print("If any tests failed, please fix the issues before running multi_lane_rtsp_yolo.py")
    print("You can run with --disable-mqtt flag if MQTT is causing problems")

if __name__ == "__main__":
    main() 