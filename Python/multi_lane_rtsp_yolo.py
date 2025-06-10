#!/usr/bin/env python3
"""
Multi-Lane RTSP YOLO Vehicle Detection
Based on nod.py algorithm for intersection traffic monitoring
Detects and counts vehicles in 4 separate lanes with MQTT reporting
"""

import cv2
import time
import numpy as np
from ultralytics import YOLO
import threading
import queue
from collections import defaultdict
from datetime import datetime
import paho.mqtt.client as mqtt
from paho.mqtt.client import CallbackAPIVersion
import json
import gc
import argparse
import os
import sys
import mysql.connector

# Define model path manually - change this if needed
DEFAULT_MODEL_PATH = "Python/YOLOv11_trained_weights/train1.pt"

# Screen resolution settings - dynamically adjust based on your display
SCREEN_WIDTH = 1600  # Default screen width (adjust based on your display)
SCREEN_HEIGHT = 900  # Default screen height (adjust based on your display)
SCREEN_REFRESH_RATE = 60  # Hz

# Calculate window sizes based on screen resolution
WINDOW_WIDTH = SCREEN_WIDTH // 2
WINDOW_HEIGHT = SCREEN_HEIGHT // 2

# Try to import SORT tracker (optional)
try:
    from sort_tracker import Sort
    SORT_AVAILABLE = True
except ImportError:
    print("⚠️  SORT tracker not found. Using simple tracking.")
    SORT_AVAILABLE = False

# Shared state between lane processors
class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.active_lane = 1  # Start with lane 1 active (following nod.py logic)
        self.next_lane_trigger_time = None
        self.lane_states = {
            1: {'active': False, 'duration_threshold': 26, 'last_send_time': time.time()},
            2: {'active': False, 'duration_threshold': 26, 'last_send_time': time.time()},
            3: {'active': False, 'duration_threshold': 26, 'last_send_time': time.time()},
            4: {'active': False, 'duration_threshold': 26, 'last_send_time': time.time()}
        }
        
        # Data storage for lane coordination
        self.lane_data = {
            1: None, 2: None, 3: None, 4: None
        }
        
        # Data sending status tracking for each lane
        self.data_sending_status = {
            1: {'sending': False, 'completed': True},
            2: {'sending': False, 'completed': True},
            3: {'sending': False, 'completed': True},
            4: {'sending': False, 'completed': True}
        }
        
        # Switching control
        self.last_switch_time = time.time()
        self.switching_cooldown = 1.0
        self.switching_blocked = False
        
        # System startup control - modified as per request
        self.system_started = False
        self.startup_delay = 15  # 15 second startup delay as requested
        self.startup_time = time.time()
        self.lane1_activation_time = self.startup_time + 5  # Activate lane 1 detection after 5 seconds
        
        # Transition timing
        self.green_to_red_transition = 3  # 3 second transition from green to red
        self.red_to_green_transition = 3  # 3 second transition from red to green
        
        # ADD SYNCHRONIZATION VARIABLES
        self.esp_sync_timestamp = None  # When ESP starts its cycle
        self.python_sync_timestamp = None  # When Python starts its cycle
        self.sync_offset = 0  # Difference between ESP and Python start times
        self.last_esp_duration = 20  # Last received ESP duration
        self.sync_established = False  # Whether sync is established
        self.force_sync_next_cycle = False  # Force sync on next cycle
        
        # Countdown display variables
        self.current_countdown = 0
        self.countdown_start_time = None
        self.countdown_active = False
        
        # Countdown sync coordination variables
        self.last_countdown_publisher = None  # Which lane last published countdown sync
        self.last_countdown_time = 0  # When the last countdown sync was published

# Create global shared state
shared_state = SharedState()

class LaneProcessor:
    def __init__(self, rtsp_url, model_path, lane_id=1, confidence=0.25):
        """
        Initialize lane processor for vehicle detection and counting
        
        :param rtsp_url: RTSP stream URL
        :param model_path: Path to YOLO model  
        :param lane_id: Lane identifier (1-4)
        :param confidence: Detection confidence threshold
        """
        self.rtsp_url = rtsp_url
        self.lane_id = lane_id
        self.confidence = confidence
        self.is_running = False
        
        # Load YOLO model (shared across lanes)
        try:
            self.model = YOLO(model_path)
            print(f"[Lane {self.lane_id}] ✅ YOLO model loaded: {model_path}")
        except Exception as e:
            print(f"[Lane {self.lane_id}] ⚠️ Error loading model from {model_path}: {e}")
            print(f"[Lane {self.lane_id}] Attempting to load default model from {DEFAULT_MODEL_PATH}")
            try:
                self.model = YOLO(DEFAULT_MODEL_PATH)
                print(f"[Lane {self.lane_id}] ✅ YOLO model loaded from default path: {DEFAULT_MODEL_PATH}")
            except Exception as e2:
                print(f"[Lane {self.lane_id}] ❌ Failed to load default model: {e2}")
                raise
        
        # Vehicle classes to detect and count
        self.vehicle_classes = ['mobil', 'truck', 'motor', 'bus']
        
        # Vehicle counting
        self.vehicle_counts = defaultdict(int)
        self.total_vehicles = 0
        
        # Initialize tracker if available
        if SORT_AVAILABLE:
            self.tracker = Sort(max_age=20, min_hits=1, iou_threshold=0.4)
        else:
            self.tracker = None
            
        # Threading for performance
        self.frame_queue = queue.Queue(maxsize=32)
        self.result_queue = queue.Queue(maxsize=16)
        
        # Performance tracking
        self.frame_count = 0
        self.fps = 0
        self.last_fps_time = time.time()
        self.fps_counter = 0
        
        # Timing for sequential operation (following nod.py logic)
        self.last_mqtt_send_time = time.time()
        # Default durations, but will be updated via MQTT traffic/duration messages
        self.green_to_red_transition = 3  # Changed from 4 to 3 seconds
        self.red_to_green_transition = 3  # Changed from 4 to 3 seconds
        self.esp_green_duration = 20  # Default green duration, will be updated from MQTT
        self.duration_threshold = self.esp_green_duration + self.green_to_red_transition + self.red_to_green_transition  # Total cycle duration
        self.duration_remaining = self.duration_threshold
        
        # Lane status following nod.py pattern - all lanes start inactive during startup
        self.is_active = False  # All lanes inactive during startup delay
        self.waiting_for_mqtt_response = False
        self.became_active_time = time.time() if self.is_active else None
        self.sent_data_after_delay = not self.is_active
        
        # Memory management
        self.last_gc_time = time.time()
        self.gc_interval = 10.0
        
        # Stream connection
        self.cap = None
        
        # Window name for display
        self.window_name = f"Lane {self.lane_id} - RTSP YOLO Detection"
        
        # Use global window size variables (dynamically calculated based on screen resolution)
        self.window_width = WINDOW_WIDTH
        self.window_height = WINDOW_HEIGHT
        
        # Calculate window position based on lane_id and screen dimensions
        if self.lane_id == 1:  # Top-left
            self.window_x, self.window_y = 0, 0
        elif self.lane_id == 2:  # Top-right
            self.window_x, self.window_y = WINDOW_WIDTH, 0
        elif self.lane_id == 3:  # Bottom-left
            self.window_x, self.window_y = 0, WINDOW_HEIGHT
        elif self.lane_id == 4:  # Bottom-right
            self.window_x, self.window_y = WINDOW_WIDTH, WINDOW_HEIGHT
        else:
            self.window_x, self.window_y = 0, 0
        
        # Database connection (following nod.py pattern)
        self.db_connection = None
        self.cursor = None
        
        # Vehicle type mapping to database IDs (from nod.py)
        self.vehicle_type_ids = {
            'mobil': 1,  # Mobil
            'motor': 2,  # Motor
            'truck': 3,  # Truck
            'bus': 4     # Bus
        }
        
        # MQTT setup
        self.setup_mqtt()
        
        # Connect to database
        self.connect_to_database()
        
        # Register in shared state (following nod.py pattern)
        with shared_state.lock:
            # Update lane state if lane_id exists
            if self.lane_id in shared_state.lane_states:
                shared_state.lane_states[self.lane_id].update({
                    'active': self.is_active,
                    'duration_threshold': self.duration_threshold,
                    'last_send_time': self.last_mqtt_send_time
                })
            else:
                # Create entry if it doesn't exist
                shared_state.lane_states[self.lane_id] = {
                    'active': self.is_active,
                    'duration_threshold': self.duration_threshold,
                    'last_send_time': self.last_mqtt_send_time
                }
                
            # If this is lane 1, set it as active initially
            if self.lane_id == 1:
                shared_state.active_lane = 1
                shared_state.next_lane_trigger_time = self.last_mqtt_send_time + self.duration_threshold - 5
    
    def setup_mqtt(self):
        """Setup MQTT client for this lane"""
        try:
            # Create MQTT client with unique ID
            client_id = f"lane_{self.lane_id}_{int(time.time())}"
            
            # Try modern MQTT client first
            try:
                self.mqtt_client = mqtt.Client(
                    callback_api_version=CallbackAPIVersion.VERSION2,
                    client_id=client_id,
                    protocol=mqtt.MQTTv5
                )
                print(f"[Lane {self.lane_id}] Using MQTTv5 client")
            except:
                # Fallback to older client
                self.mqtt_client = mqtt.Client(client_id=client_id)
                print(f"[Lane {self.lane_id}] Using legacy MQTT client")
                
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            self.mqtt_client.on_message = self.on_mqtt_message
            
            # MQTT broker settings
            self.mqtt_broker = "broker.emqx.io"
            self.mqtt_port = 1883
            
            # Connect to MQTT broker
            self.connect_mqtt()
            
        except Exception as e:
            print(f"[Lane {self.lane_id}] ❌ MQTT setup error: {e}")
            self.mqtt_client = None
    
    def on_mqtt_connect(self, client, userdata, flags, rc, *args):
        """MQTT connection callback"""
        if rc == 0:
            print(f"[Lane {self.lane_id}] ✅ Connected to MQTT broker")
            
            # Subscribe to duration updates
            self.mqtt_client.subscribe("traffic/duration")
            self.mqtt_client.subscribe("traffic/duration/#")
            self.mqtt_client.subscribe("traffic/vehicle_count")  # User's ESP sends duration in vehicle_count topic
            self.mqtt_client.subscribe(f"traffic/command/{self.lane_id}")
            self.mqtt_client.subscribe("traffic/command/all")
            
            # Subscribe to sync topics
            self.mqtt_client.subscribe("traffic/sync")
            self.mqtt_client.subscribe("traffic/sync/#")
            self.mqtt_client.subscribe(f"traffic/sync/{self.lane_id}")
            
            # NEW: Subscribe to countdown sync topic for ESP synchronization
            self.mqtt_client.subscribe("traffic/countdown_sync")
            print(f"[Lane {self.lane_id}] 🔄 Subscribed to countdown sync topic")
            
            # Subscribe to ESP green status to handle lane switching
            self.mqtt_client.subscribe("traffic/green_status")
            self.mqtt_client.subscribe("traffic/next_lane_ready")
            print(f"[Lane {self.lane_id}] 🚦 Subscribed to ESP green status and lane switching topics")
            
            # Publish connection status
            self.mqtt_client.publish(f"traffic/status/{self.lane_id}", "online", qos=1, retain=True)
            
            # Sync lane status
            self.sync_lane_status()
        else:
            print(f"[Lane {self.lane_id}] ❌ MQTT connection failed: {rc}")
    
    def on_mqtt_disconnect(self, client, userdata, rc, *args):
        """MQTT disconnection callback"""
        print(f"[Lane {self.lane_id}] ⚠️  MQTT disconnected: {rc}")
    
    def on_mqtt_message(self, client, userdata, message):
        """Handle incoming MQTT messages for this lane"""
        try:
            # Extract topic and payload
            topic = message.topic
            payload = message.payload.decode('utf-8')
            
            print(f"[Lane {self.lane_id}] 📩 MQTT Message: {topic}: {payload}")
            
            # NEW: Handle countdown sync messages from ESP
            if topic == "traffic/countdown_sync":
                try:
                    data = json.loads(payload.replace("'", "\""))
                    if ("lane_id" in data and "remaining_seconds" in data and 
                        "source" in data and data["source"] == "esp"):
                        
                        esp_lane_id = data["lane_id"]
                        esp_remaining = int(data["remaining_seconds"])
                        esp_phase = data.get("phase", "unknown")
                        esp_timestamp = data.get("timestamp", time.time())
                        
                        # Only sync if this is for our lane and we're active and in green phase
                        if esp_lane_id == self.lane_id and self.is_active:
                            current_time = time.time()
                            
                            # Check if we're in the green phase to accept ESP sync
                            red_to_green = self.red_to_green_transition
                            green_to_red = self.green_to_red_transition 
                            current_remaining = int(current_time - self.last_mqtt_send_time)
                            current_duration_remaining = max(0, self.duration_threshold - current_remaining)
                            
                            # Only sync if we're in green phase (between red>green and green>red)
                            in_green_phase = (current_duration_remaining <= (self.esp_green_duration + green_to_red) and 
                                             current_duration_remaining > green_to_red)
                            
                            if in_green_phase or esp_phase == "green":
                                # CRITICAL FIX: ESP countdown is for GREEN PHASE ONLY, not total cycle
                                # ESP sends remaining green time, we need to match it exactly
                                # Our duration_remaining should match ESP's countdown exactly during green phase
                                
                                # ESP countdown is for green phase only, so we need to adjust our cycle timing
                                # If ESP shows 12s remaining in green, we should show 12s + green_to_red in our countdown
                                target_python_remaining = esp_remaining + green_to_red
                                
                                # Calculate new start time to match ESP exactly
                                total_cycle_time = self.duration_threshold
                                new_elapsed_time = total_cycle_time - target_python_remaining
                                
                                # Store old values for offset calculation
                                old_remaining = self.duration_remaining
                                
                                # Adjust our timing to match ESP exactly
                                with shared_state.lock:
                                    # Reset our cycle start time to match ESP countdown
                                    new_start_time = current_time - new_elapsed_time
                                    shared_state.lane_states[self.lane_id]['last_send_time'] = new_start_time
                                    self.last_mqtt_send_time = new_start_time
                                    
                                    # Update countdown display variables to show ESP's countdown directly
                                    shared_state.current_countdown = esp_remaining
                                    shared_state.countdown_start_time = current_time
                                    shared_state.countdown_active = True
                                    shared_state.sync_established = True
                                    
                                    # Calculate sync offset for monitoring
                                    sync_difference = abs(old_remaining - target_python_remaining)
                                    shared_state.sync_offset = sync_difference
                                
                                # Update our duration_remaining to match the adjusted timing
                                self.duration_remaining = target_python_remaining
                                
                                print(f"[Lane {self.lane_id}] 🔄 SYNC: ESP reports {esp_remaining}s green remaining")
                                print(f"[Lane {self.lane_id}] 🔄 SYNC: Adjusted Python to {target_python_remaining}s total remaining (ESP {esp_remaining}s + {green_to_red}s transition)")
                                print(f"[Lane {self.lane_id}] 🔄 SYNC: Offset corrected by {sync_difference:.1f}s")
                                
                                # DO NOT send acknowledgment back to ESP to avoid sync ping-pong loop
                                # The sync should be one-way: ESP → Python
                                # self.publish_countdown_sync(esp_remaining, esp_phase)
                            else:
                                print(f"[Lane {self.lane_id}] 🔄 SYNC: Ignoring ESP sync - not in green phase (remaining: {current_duration_remaining}s)")
                            
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] ❌ Error parsing countdown sync JSON: {e}")
            
            # Handle ESP green status messages for lane switching
            elif topic == "traffic/green_status":
                try:
                    data = json.loads(payload.replace("'", "\""))
                    if "section" in data and "status" in data:
                        esp_section = data["section"]
                        esp_status = data["status"]
                        
                        print(f"[Lane {self.lane_id}] 🚦 ESP Section {esp_section} status: {esp_status}")
                        
                        # When ESP goes to RED, trigger lane switching in Python
                        if esp_status == "red" and esp_section == self.lane_id:
                            current_time = time.time()
                            
                            # CRITICAL FIX: Immediately stop countdown sync by setting duration to 0
                            print(f"[Lane {self.lane_id}] 🛑 ESP RED - immediately stopping countdown sync")
                            self.duration_remaining = 0  # Force countdown sync to stop immediately
                            
                            # Clear all countdown sync state immediately
                            with shared_state.lock:
                                shared_state.countdown_active = False
                                shared_state.sync_established = False
                                shared_state.last_countdown_publisher = None
                                shared_state.last_countdown_time = 0
                            
                            print(f"[Lane {self.lane_id}] 🔒 Cleared all countdown sync state to prevent stale messages")
                            
                            with shared_state.lock:
                                # Only switch if this lane is currently active
                                if shared_state.active_lane == self.lane_id and self.is_active:
                                    # Determine next lane in sequence (1→2→3→4→1)
                                    next_lane_id = (self.lane_id % 4) + 1
                                    
                                    print(f"[Lane {self.lane_id}] 🔄 ESP went to RED - switching to Lane {next_lane_id}")
                                    shared_state.active_lane = next_lane_id
                                    shared_state.last_switch_time = current_time
                                    self.is_active = False
                                    
                                    # Update all lane states
                                    for lane_id in range(1, 5):
                                        is_next = (lane_id == next_lane_id)
                                        if lane_id in shared_state.lane_states:
                                            shared_state.lane_states[lane_id]['active'] = is_next
                                            if is_next:
                                                # Start new lane with fresh cycle
                                                shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                                print(f"[LANE SWITCH] Lane {lane_id} starts fresh cycle")
                                                if lane_id in shared_state.data_sending_status:
                                                    shared_state.data_sending_status[lane_id]['sending'] = False
                                                    shared_state.data_sending_status[lane_id]['completed'] = False
                                    
                                    # Clear sync data for completed lane
                                    shared_state.countdown_active = False
                                    shared_state.sync_established = False
                                    
                                    print(f"[LANE SWITCH] Completed: {self.lane_id} -> {next_lane_id}")
                                    
                                    # Publish green permission for the next lane
                                    if self.mqtt_client:
                                        green_permission_data = {
                                            "section": next_lane_id,
                                            "permission": "granted",
                                            "timestamp": current_time,
                                            "source": "python_esp_red_trigger"
                                        }
                                        self.mqtt_client.publish("traffic/green_permission", 
                                                               json.dumps(green_permission_data), qos=1)
                                        print(f"[LANE SWITCH] Published green permission for Lane {next_lane_id}")
                                elif self.is_active:
                                    # If we're active but not the shared active lane, deactivate immediately
                                    print(f"[Lane {self.lane_id}] 🛑 ESP RED - deactivating lane")
                                    self.is_active = False
                        
                        # When ESP goes to GREEN, sync with that specific lane and start countdown
                        elif esp_status == "green":
                            with shared_state.lock:
                                current_time = time.time()
                                
                                # Set the ESP section as active lane if it's not already
                                if shared_state.active_lane != esp_section:
                                    shared_state.active_lane = esp_section
                                    shared_state.last_switch_time = current_time
                                    
                                    # Update all lane states
                                    for lane_id in range(1, 5):
                                        is_active = (lane_id == esp_section)
                                        if lane_id in shared_state.lane_states:
                                            shared_state.lane_states[lane_id]['active'] = is_active
                                            if is_active:
                                                shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                    
                                    print(f"[LANE SYNC] ESP Section {esp_section} green - Python switched to Lane {esp_section}")
                                
                                # CRITICAL: Start countdown sync NOW when ESP is actually green
                                if esp_section == self.lane_id and self.is_active:
                                    # ESP is green, start our countdown sync from ESP green duration
                                    shared_state.countdown_active = True
                                    shared_state.countdown_start_time = current_time
                                    shared_state.current_countdown = int(self.esp_green_duration)
                                    shared_state.sync_established = True
                                    
                                    # Reset our timing to match ESP green start
                                    red_to_green_elapsed = self.red_to_green_transition
                                    adjusted_start_time = current_time - red_to_green_elapsed
                                    shared_state.lane_states[self.lane_id]['last_send_time'] = adjusted_start_time
                                    self.last_mqtt_send_time = adjusted_start_time
                                    
                                    print(f"[Lane {self.lane_id}] 🟢 ESP GREEN detected - starting countdown sync from {self.esp_green_duration}s")
                                    
                                    # Immediately publish first countdown sync to match ESP
                                    self.publish_countdown_sync(int(self.esp_green_duration), "green")
                                
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] ❌ Error parsing green status JSON: {e}")
            
            # Handle next lane ready messages from ESP
            elif topic == "traffic/next_lane_ready":
                try:
                    data = json.loads(payload.replace("'", "\""))
                    if "next_expected_section" in data and "from_lane" in data:
                        next_section = data["next_expected_section"]
                        from_lane = data["from_lane"]
                        
                        print(f"[Lane {self.lane_id}] 📡 ESP Lane {from_lane} signals next lane: {next_section}")
                        
                        # If we're the next expected section, get ready
                        if next_section == self.lane_id:
                            current_time = time.time()
                            with shared_state.lock:
                                # Set ourselves as the active lane
                                shared_state.active_lane = self.lane_id
                                shared_state.last_switch_time = current_time
                                
                                # Update all lane states
                                for lane_id in range(1, 5):
                                    is_active = (lane_id == self.lane_id)
                                    if lane_id in shared_state.lane_states:
                                        shared_state.lane_states[lane_id]['active'] = is_active
                                        if is_active:
                                            shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                
                                # Clear previous sync data
                                shared_state.countdown_active = False
                                shared_state.sync_established = False
                            
                            # Update instance variables for the newly active lane
                            self.is_active = True
                            self.last_mqtt_send_time = current_time
                            self.duration_remaining = self.duration_threshold
                            self.became_active_time = current_time
                            self.sent_data_after_delay = False
                            
                            print(f"[Lane {self.lane_id}] 🚀 Prepared as next active lane (signaled by ESP)")
                        
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] ❌ Error parsing next lane ready JSON: {e}")
            
            # Process traffic duration messages
            elif topic == "traffic/duration" or topic == "traffic/vehicle_count":
                # Deserialize JSON payload
                try:
                    data = json.loads(payload.replace("'", "\""))
                    if "lane_id" in data and "duration" in data:
                        lane_id = data["lane_id"]
                        duration = float(data["duration"])
                        
                        print(f"[Lane {self.lane_id}] 🕒 Received duration {duration}s for lane {lane_id}")
                        
                        # Update this lane's duration if it matches
                        if lane_id == self.lane_id:
                            self.esp_green_duration = duration  # Store actual green duration from ESP
                            self.duration_threshold = duration + self.green_to_red_transition + self.red_to_green_transition
                            self.duration_remaining = self.duration_threshold  # Reset to TOTAL cycle time, not just green
                            self.waiting_for_mqtt_response = False
                            
                            # Enhanced synchronization: force immediate alignment with ESP
                            current_time = time.time()
                            with shared_state.lock:
                                shared_state.esp_sync_timestamp = current_time 
                                shared_state.python_sync_timestamp = current_time
                                shared_state.last_esp_duration = duration
                                shared_state.sync_established = True
                                
                                # Only reset timing if this lane is active, otherwise let it start fresh when it becomes active
                                if self.is_active:
                                    # Start fresh cycle from the beginning (RED>GREEN phase)
                                    shared_state.lane_states[self.lane_id]['last_send_time'] = current_time
                                    self.last_mqtt_send_time = current_time
                                    self.duration_remaining = self.duration_threshold  # Full cycle time
                                    print(f"[Lane {self.lane_id}] 🔄 SYNC: Started fresh cycle - {self.duration_threshold}s total")
                                else:
                                    # Not active yet, will sync when it becomes active
                                    print(f"[Lane {self.lane_id}] 🔄 SYNC: Duration updated, will sync when active")
                                
                                # Set countdown variables for display
                                shared_state.current_countdown = int(self.duration_threshold)
                                shared_state.countdown_start_time = current_time
                                shared_state.countdown_active = True
                            
                            print(f"[Lane {self.lane_id}] ⏱️ Updated ESP green duration to {duration}s, total cycle duration to {self.duration_threshold}s")
                            print(f"[Lane {self.lane_id}] 📊 Breakdown: Green={self.esp_green_duration}s + GreenToRed={self.green_to_red_transition}s + RedToGreen={self.red_to_green_transition}s = {self.duration_threshold}s total")
                            
                            # Update shared state
                            with shared_state.lock:
                                shared_state.lane_states[self.lane_id]['duration_threshold'] = self.duration_threshold
                                shared_state.last_esp_duration = duration  # Store the ESP green phase duration
                        
                        # For any lane, update the shared state duration
                        with shared_state.lock:
                            if lane_id in shared_state.lane_states:
                                shared_state.lane_states[lane_id]['duration_threshold'] = duration + self.green_to_red_transition + self.red_to_green_transition
                                # Also update last_esp_duration for the specified lane
                                shared_state.last_esp_duration = duration
                                
                                # Force sync if it's this lane and it's active
                                if lane_id == self.lane_id and self.is_active:
                                    shared_state.force_sync_next_cycle = True
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] ❌ Error parsing duration JSON: {e}")
            
            # Handle sync commands
            elif message.topic == "traffic/sync" or message.topic.startswith("traffic/sync/"):
                try:
                    data = json.loads(payload)
                    command = data.get("command")
                    
                    if command == "request_sync":
                        # ESP is requesting synchronization
                        with shared_state.lock:
                            shared_state.force_sync_next_cycle = True
                            print(f"[Lane {self.lane_id}] 🔄 ESP requested sync - will sync on next cycle")
                    
                    elif command == "phase_change":
                        # ESP is signaling a phase change
                        esp_phase = data.get("phase")
                        esp_lane = data.get("lane", 1)
                        esp_timestamp = data.get("timestamp", time.time())
                        
                        if esp_lane == self.lane_id and self.is_active:
                            print(f"[Lane {self.lane_id}] 🚦 ESP phase change: {esp_phase}")
                            
                            # Sync based on ESP phase
                            if esp_phase == "green":
                                # ESP started green, we should be past red-to-green
                                red_to_green = self.red_to_green_transition
                                self.last_mqtt_send_time = time.time() - red_to_green
                                print(f"[Lane {self.lane_id}] 🟢 Synced to ESP green phase")
                                
                            elif esp_phase == "yellow" or esp_phase == "red":
                                # ESP started yellow/red, we should be in green-to-red
                                red_to_green = self.red_to_green_transition
                                green_duration = self.esp_green_duration
                                self.last_mqtt_send_time = time.time() - (red_to_green + green_duration)
                                print(f"[Lane {self.lane_id}] 🟡 Synced to ESP yellow/red phase")
                                
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] Sync JSON decode error: {e}")
            
            # Handle command messages (following nod.py pattern)
            elif message.topic == f"traffic/command/{self.lane_id}" or message.topic == "traffic/command/all":
                try:
                    data = json.loads(payload)
                    command = data.get("command")
                    
                    if command == "set_active":
                        # Force this lane to be active
                        with shared_state.lock:
                            current_time = time.time()
                            shared_state.active_lane = self.lane_id
                            shared_state.last_switch_time = current_time
                            shared_state.next_lane_trigger_time = None
                            shared_state.force_sync_next_cycle = True  # Force sync when manually activated
                            
                            # Update lane states
                            for lane_id in range(1, 5):
                                is_active = (lane_id == self.lane_id)
                                if lane_id in shared_state.lane_states:
                                    shared_state.lane_states[lane_id]['active'] = is_active
                                    if is_active:
                                        shared_state.lane_states[lane_id]['last_send_time'] = current_time
                            
                            # Update this lane's status - START WITH RED>GREEN TRANSITION
                            self.is_active = True
                            self.last_mqtt_send_time = current_time
                            self.became_active_time = current_time
                            self.sent_data_after_delay = False
                            self.duration_remaining = self.duration_threshold  # Start with full duration
                            print(f"[Lane {self.lane_id}] Forced to be active - starting with RED>GREEN transition")
                    
                    elif command == "send_update":
                        if self.is_active:
                            self.publish_vehicle_count()
                            self.waiting_for_mqtt_response = True
                    
                    elif command == "force_sync":
                        # Force synchronization
                        with shared_state.lock:
                            shared_state.force_sync_next_cycle = True
                            if self.is_active:
                                # Start fresh cycle with RED>GREEN transition
                                self.last_mqtt_send_time = time.time()
                                self.duration_remaining = self.duration_threshold
                                print(f"[Lane {self.lane_id}] 🔄 Forced sync - starting fresh cycle with RED>GREEN transition")
                    
                    # Acknowledge command
                    self.mqtt_client.publish(f"traffic/command_ack/{self.lane_id}", 
                                           json.dumps({
                                               "received": command,
                                               "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                           }), qos=1)
                except json.JSONDecodeError as e:
                    print(f"[Lane {self.lane_id}] Command JSON decode error: {e}")
                    
        except Exception as e:
            print(f"[Lane {self.lane_id}] Error processing MQTT message: {e}")
    
    def connect_mqtt(self):
        """Connect to MQTT broker"""
        try:
            if self.mqtt_client:
                print(f"[Lane {self.lane_id}] Connecting to MQTT broker {self.mqtt_broker}:{self.mqtt_port}...")
                self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, 60)
                self.mqtt_client.loop_start()
        except Exception as e:
            print(f"[Lane {self.lane_id}] ❌ MQTT connection error: {e}")
            # Don't let MQTT failure stop the application
            print(f"[Lane {self.lane_id}] Continuing without MQTT connection")
    
    def publish_countdown_sync(self, remaining_seconds, phase="green"):
        """Publish countdown sync message to help ESP stay synchronized"""
        try:
            if not self.mqtt_client:
                return
            
            # CRITICAL SAFETY CHECK: Don't publish if we're not active or countdown is disabled
            with shared_state.lock:
                if not self.is_active or not shared_state.countdown_active:
                    print(f"[Lane {self.lane_id}] 🚫 Blocked countdown sync - inactive or countdown disabled")
                    return
                
            # Additional safety: Don't publish if remaining_seconds is 0 or negative
            if remaining_seconds <= 0:
                print(f"[Lane {self.lane_id}] 🚫 Blocked countdown sync - invalid remaining_seconds: {remaining_seconds}")
                return
                
            sync_data = {
                "lane_id": self.lane_id,
                "remaining_seconds": int(remaining_seconds),
                "phase": phase,
                "timestamp": time.time(),
                "source": "python"
            }
            
            message = json.dumps(sync_data)
            
            # Publish countdown sync
            result = self.mqtt_client.publish("traffic/countdown_sync", message, qos=1)
            
            if result[0] == 0:
                print(f"[Lane {self.lane_id}] 📡 Published countdown sync: {remaining_seconds}s remaining")
            else:
                print(f"[Lane {self.lane_id}] ❌ Failed to publish countdown sync")
                
        except Exception as e:
            print(f"[Lane {self.lane_id}] ❌ Error publishing countdown sync: {e}")
    
    def sync_lane_status(self):
        """Synchronize lane status with shared state (following nod.py pattern)"""
        try:
            previous_active_state = self.is_active
            
            with shared_state.lock:
                # Add timeout protection for lane switching
                current_time = time.time()
                current_lane = shared_state.active_lane
                
                # Check if current active lane has exceeded timeout (30 seconds)
                if (current_lane in shared_state.lane_states and 
                    self.lane_id == current_lane and 
                    self.is_active):
                    
                    active_lane_duration = shared_state.lane_states[current_lane]['duration_threshold']
                    time_since_start = current_time - shared_state.lane_states[current_lane]['last_send_time']
                    timeout_threshold = active_lane_duration + 5  # 5 second grace period
                    
                    if time_since_start > timeout_threshold:
                        # Force lane switch due to timeout
                        next_lane_id = (current_lane % 4) + 1
                        print(f"[Lane {current_lane}] ⏰ TIMEOUT PROTECTION: Forcing switch to Lane {next_lane_id} after {time_since_start:.1f}s")
                        
                        # Trigger lane switch
                        shared_state.active_lane = next_lane_id
                        shared_state.last_switch_time = current_time
                        self.is_active = False
                        
                        # Update all lane states
                        for lane_id in range(1, 5):
                            is_next = (lane_id == next_lane_id)
                            if lane_id in shared_state.lane_states:
                                shared_state.lane_states[lane_id]['active'] = is_next
                                if is_next:
                                    # Start new lane with fresh cycle
                                    shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                    print(f"[TIMEOUT SWITCH] Lane {lane_id} starts fresh cycle")
                                    if lane_id in shared_state.data_sending_status:
                                        shared_state.data_sending_status[lane_id]['sending'] = False
                                        shared_state.data_sending_status[lane_id]['completed'] = False
                        
                        # Clear sync data for completed lane
                        shared_state.countdown_active = False
                        shared_state.sync_established = False
                        
                        # Publish green permission for the next lane
                        if self.mqtt_client:
                            green_permission_data = {
                                "section": next_lane_id,
                                "permission": "granted",
                                "timestamp": current_time,
                                "source": "python_timeout_protection"
                            }
                            self.mqtt_client.publish("traffic/green_permission", 
                                                   json.dumps(green_permission_data), qos=1)
                            print(f"[TIMEOUT SWITCH] Published green permission for Lane {next_lane_id}")
                
                # Update our active status from shared state
                self.is_active = (shared_state.active_lane == self.lane_id)
                
                # Update active status in shared state
                if self.lane_id in shared_state.lane_states:
                    shared_state.lane_states[self.lane_id]['active'] = self.is_active
                
                # If we just became active, reset our timer
                if self.is_active and not previous_active_state:
                    current_time = time.time()
                    self.last_mqtt_send_time = current_time
                    self.became_active_time = current_time
                    self.sent_data_after_delay = False
                    
                    # Update in shared state
                    if self.lane_id in shared_state.lane_states:
                        shared_state.lane_states[self.lane_id]['last_send_time'] = current_time
                    
                    print(f"[Lane {self.lane_id}] Became active, timer reset")
            
            # Publish current status
            status = "active" if self.is_active else "standby"
            if hasattr(self, 'mqtt_client') and self.mqtt_client:
                self.mqtt_client.publish(f"traffic/lane_status/{self.lane_id}", 
                                        json.dumps({
                                            "status": status,
                                            "lane_id": self.lane_id,
                                            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                                        }), qos=1, retain=True)
            
            print(f"[Lane {self.lane_id}] Synchronized status: {status}")
        except Exception as e:
            print(f"[Lane {self.lane_id}] Error synchronizing lane status: {e}")
    
    def connect_to_database(self):
        """Connect to the MySQL database (from nod.py)"""
        try:
            # Close existing connection if any
            if self.db_connection is not None:
                try:
                    self.cursor.close()
                    self.db_connection.close()
                except:
                    pass  # Ignore errors during cleanup
            
            # Retry logic for database connection
            max_retries = 3 if self.lane_id == 1 else 1
            retry_count = 0
            last_error = None
            
            while retry_count < max_retries:
                try:
                    self.db_connection = mysql.connector.connect(
                        host="api-traffic-light.apotekbless.my.id",
                        user="u190944248_traffic_light",
                        password="TrafficLight2025.",
                        database="u190944248_traffic_light",
                        connection_timeout=5,
                        autocommit=True,
                        use_pure=True
                    )
                    self.cursor = self.db_connection.cursor()
                    print(f"[Lane {self.lane_id}] ✅ Connected to database")
                    return True
                except mysql.connector.Error as err:
                    last_error = err
                    retry_count += 1
                    if retry_count < max_retries:
                        retry_delay = 0.2 * retry_count
                        print(f"[Lane {self.lane_id}] Connection attempt {retry_count} failed: {err}. Retrying in {retry_delay:.1f}s...")
                        time.sleep(retry_delay)
                    else:
                        break
            
            # If we got here, all retries failed
            if last_error:
                print(f"[Lane {self.lane_id}] ❌ Database connection error after {retry_count} attempts: {last_error}")
            self.db_connection = None
            self.cursor = None
            
            # Don't let database connection failure stop the application
            print(f"[Lane {self.lane_id}] Continuing without database connection")
            
            # Special handling for Lane 1 - try fallback connection
            if self.lane_id == 1:
                try:
                    print(f"[Lane 1] Attempting fallback minimal connection...")
                    self.db_connection = mysql.connector.connect(
                        host="api-traffic-light.apotekbless.my.id",
                        user="u190944248_traffic_light",
                        password="TrafficLight2025.",
                        connection_timeout=3
                    )
                    self.db_connection.database = "u190944248_traffic_light"
                    self.cursor = self.db_connection.cursor()
                    print(f"[Lane 1] ✅ Established fallback connection")
                    return True
                except Exception as fallback_err:
                    print(f"[Lane 1] ❌ Fallback connection failed: {fallback_err}")
            
            return False
        except Exception as err:
            print(f"[Lane {self.lane_id}] ❌ Unexpected error during database connection: {err}")
            self.db_connection = None
            self.cursor = None
            return False
    
    def log_traffic_data_startup(self):
        """Log Lane 1's own data to database during startup"""
        try:
            # Check database connection and reconnect if needed
            if not self.db_connection or not self.cursor:
                print(f"[Lane {self.lane_id}] Database connection not available. Trying to reconnect...")
                connection_success = self.connect_to_database()
                if not connection_success:
                    print(f"[Lane {self.lane_id}] Failed to reconnect to database during startup.")
                    return
            
            db_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # During startup, Lane 1 logs its own data (road_section_id = 1)
            target_lane_id = 1
            target_vehicle_counts = dict(self.vehicle_counts)
            
            print(f"[Lane {self.lane_id}] Logging own data (Lane {target_lane_id}) during startup")
            
            try:
                # Check if connection is still alive
                try:
                    self.db_connection.ping(reconnect=True, attempts=3, delay=1)
                except:
                    print(f"[Lane {self.lane_id}] Database connection lost. Reconnecting...")
                    connection_success = self.connect_to_database()
                    if not connection_success:
                        print(f"[Lane {self.lane_id}] Failed to reconnect to database.")
                        return
                
                # Log data, even if all counts are zero
                has_data = False
                
                # Insert counts for each vehicle type
                for vehicle_type, count in target_vehicle_counts.items():
                    if vehicle_type in self.vehicle_type_ids:
                        vehicle_type_id = self.vehicle_type_ids[vehicle_type]
                        
                        # Insert into traffic_logs table using target_lane_id
                        insert_query = """
                        INSERT INTO traffic_logs 
                        (road_section_id, datetime, vehicle_type_id, amount) 
                        VALUES (%s, %s, %s, %s)
                        """
                        values = (target_lane_id, db_time, vehicle_type_id, count)
                        
                        self.cursor.execute(insert_query, values)
                        has_data = True
                
                # If no valid vehicle types found, log zero count for default type
                if not has_data:
                    insert_query = """
                    INSERT INTO traffic_logs 
                    (road_section_id, datetime, vehicle_type_id, amount) 
                    VALUES (%s, %s, %s, %s)
                    """
                    values = (target_lane_id, db_time, 1, 0)  # mobil (ID 1) with zero count
                    self.cursor.execute(insert_query, values)
                
                # Commit the transaction
                self.db_connection.commit()
                
                print(f"[Lane {self.lane_id}] 💾 Startup data for Lane {target_lane_id} logged to database")
                
            except mysql.connector.Error as err:
                print(f"[Lane {self.lane_id}] ❌ Database error during startup: {err}")
                
        except Exception as e:
            print(f"[Lane {self.lane_id}] ❌ Error in startup database logging: {e}")
    
    def log_traffic_data(self):
        """Log traffic data to database and MQTT based on the new requirements"""
        current_time = time.time()
        
        # Skip if this lane is not active
        if not self.is_active:
            return False
        
        with shared_state.lock:
            # Check if we're within the startup period
            if not shared_state.system_started:
                elapsed_since_startup = current_time - shared_state.startup_time
                
                # At 5 seconds into startup, activate lane 1 detection
                if self.lane_id == 1 and elapsed_since_startup >= 5 and elapsed_since_startup < 15:
                    if not shared_state.data_sending_status[1]['sending'] and shared_state.data_sending_status[1]['completed']:
                        print(f"[Lane 1] 🚦 Initial data collection started at 5 seconds into startup")
                        shared_state.data_sending_status[1]['sending'] = True
                        shared_state.data_sending_status[1]['completed'] = False
                        return self.publish_vehicle_count_startup()
                
                return False
        
        # For regular operation after startup is complete
        # Check if we're in a green->red transition period (last 3 seconds of green)
        current_lane = shared_state.active_lane
        next_lane = 1 if current_lane == 4 else current_lane + 1
        
        with shared_state.lock:
            if shared_state.system_started:
                # Calculate how much time is left in the current active lane's cycle
                active_lane_duration = shared_state.lane_states[current_lane]['duration_threshold']
                time_since_active = current_time - shared_state.lane_states[current_lane]['last_send_time']
                time_remaining = active_lane_duration - time_since_active
                
                # If we're in the transition period (last 3 seconds of green light)
                if time_remaining <= shared_state.green_to_red_transition and self.lane_id == next_lane:
                    # If we haven't started sending data for the next lane
                    if not shared_state.data_sending_status[next_lane]['sending'] and shared_state.data_sending_status[next_lane]['completed']:
                        print(f"[Lane {self.lane_id}] 🚦 Preparing data for next lane {next_lane}")
                        shared_state.data_sending_status[next_lane]['sending'] = True
                        shared_state.data_sending_status[next_lane]['completed'] = False
                        
                        # If 5 seconds into the red->green transition, send data for lane 2
                        if current_time - (shared_state.lane_states[current_lane]['last_send_time'] + active_lane_duration - shared_state.green_to_red_transition) >= 5:
                            print(f"[Lane {self.lane_id}] 📊 Sending data for next lane at transition point")
                            return self.publish_vehicle_count()
        
        return False
    
    def connect_to_stream(self, retry_attempts=3):
        """Connect to RTSP stream with retry mechanism"""
        for attempt in range(retry_attempts):
            try:
                print(f"[Lane {self.lane_id}] 🔄 Connecting to stream (attempt {attempt + 1}/{retry_attempts})")
                print(f"[Lane {self.lane_id}] 📡 URL: {self.rtsp_url}")
                
                # Configure OpenCV for RTSP
                cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FPS, 25)
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000)
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000)
                
                # Test connection
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        print(f"[Lane {self.lane_id}] ✅ Connected! Resolution: {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
                        return cap
                    else:
                        cap.release()
                        
            except Exception as e:
                print(f"[Lane {self.lane_id}] ❌ Connection attempt {attempt + 1} failed: {e}")
            
            if attempt < retry_attempts - 1:
                time.sleep(3)
        
        print(f"[Lane {self.lane_id}] ❌ Failed to connect after {retry_attempts} attempts")
        return None
    
    def fetch_frames(self):
        """Fetch frames from RTSP stream in separate thread"""
        while self.is_running:
            try:
                if self.cap and self.cap.isOpened():
                    ret, frame = self.cap.read()
                    if ret and frame is not None:
                        # Add frame to queue (drop old frames if queue is full)
                        if not self.frame_queue.full():
                            self.frame_queue.put(frame)
                        else:
                            # Drop oldest frame and add new one
                            try:
                                self.frame_queue.get_nowait()
                                self.frame_queue.put(frame)
                            except:
                                pass
                    else:
                        # Reconnect if stream fails
                        print(f"[Lane {self.lane_id}] ⚠️  Stream lost, reconnecting...")
                        self.cap.release()
                        self.cap = self.connect_to_stream(retry_attempts=2)
                        if not self.cap:
                            break
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"[Lane {self.lane_id}] ❌ Frame fetch error: {e}")
                time.sleep(0.5)
    
    def process_frames(self):
        """Process frames with sophisticated timing logic from nod.py"""
        # Track data sending status for this lane
        data_sent_in_current_period = False
        data_send_initiated = False
        
        # Flag to indicate if we're in startup delay
        in_startup_delay = True
        
        # Track if this is the very first cycle after startup
        first_cycle_after_startup = False
        
        while self.is_running:
            try:
                current_time = time.time()
                
                                    # Check if system is still in startup delay (following nod.py pattern)
                with shared_state.lock:
                    if not shared_state.system_started:
                        elapsed_startup = current_time - shared_state.startup_time
                        
                        # Check if we should send startup data (2 seconds before end = at 18 seconds)
                        if (elapsed_startup >= 18 and not shared_state.startup_data_sent and 
                            self.lane_id == 1):
                            print(f"[Lane 1] 🚀 Sending startup data at 18s (2s before delay ends)")
                            shared_state.startup_data_sent = True
                            
                            # Send Lane 1's own data during startup
                            threading.Timer(0.1, lambda: self.log_traffic_data_startup()).start()
                            threading.Timer(0.3, lambda: self.publish_vehicle_count_startup()).start()
                        
                        if elapsed_startup >= shared_state.startup_delay:
                            shared_state.system_started = True
                            in_startup_delay = False
                            print(f"[SYSTEM] 🚀 Startup delay complete - Lane 1 becoming active")
                            
                            # Mark that this is the first cycle after startup
                            if self.lane_id == 1:
                                first_cycle_after_startup = True
                                print(f"[Lane 1] First cycle after startup - normal operation begins")
                            
                            # Ensure Lane 1 is properly set as active
                            shared_state.active_lane = 1
                            for lane_id in range(1, 5):
                                is_active = (lane_id == 1)
                                if lane_id in shared_state.lane_states:
                                    shared_state.lane_states[lane_id]['active'] = is_active
                                    if is_active:
                                        shared_state.lane_states[lane_id]['last_send_time'] = current_time
                        else:
                            # Still in startup delay
                            in_startup_delay = True
                            remaining_startup = shared_state.startup_delay - elapsed_startup
                            if self.lane_id == 1:  # Only show countdown from Lane 1
                                print(f"[SYSTEM] 🕐 Startup delay: {remaining_startup:.1f}s remaining")
                            
                            # Don't skip frame processing during startup delay
                            # Instead, we'll show the frames but skip detection
                
                if not self.frame_queue.empty():
                    frame = self.frame_queue.get()
                    
                    # Handle lane activation logic (following nod.py pattern) - ONLY AFTER STARTUP
                    with shared_state.lock:
                        system_started = shared_state.system_started
                    
                    if system_started:  # Only run normal lane logic after startup delay
                        with shared_state.lock:
                            # Check if this lane just became active
                            if self.is_active == False and shared_state.active_lane == self.lane_id:
                                print(f"[CRITICAL] Lane {self.lane_id} detected it just became active")
                                self.is_active = True
                                self.last_mqtt_send_time = current_time  # Start fresh cycle
                                self.became_active_time = current_time
                                self.sent_data_after_delay = False
                                self.duration_remaining = self.duration_threshold  # Start with full duration
                                
                                # Update in shared state
                                shared_state.lane_states[self.lane_id]['last_send_time'] = current_time
                                shared_state.lane_states[self.lane_id]['active'] = True
                                
                                # Reset data sending flags
                                data_sent_in_current_period = False
                                data_send_initiated = False
                                if self.lane_id in shared_state.data_sending_status:
                                    shared_state.data_sending_status[self.lane_id]['sending'] = False
                                    shared_state.data_sending_status[self.lane_id]['completed'] = False
                                
                                print(f"[Lane {self.lane_id}] ✅ FRESH CYCLE START: RED>GREEN(4s) -> GREEN -> GREEN>RED(4s)")
                            
                            # Handle lane timing and switching for active lane
                            if self.is_active:
                                elapsed_time = int(current_time - self.last_mqtt_send_time)
                                previous_remaining = self.duration_remaining
                                self.duration_remaining = max(0, self.duration_threshold - elapsed_time)
                                
                                # Log phase transitions for clarity
                                red_to_green = self.red_to_green_transition  # Use instance variable (3s)
                                green_to_red = self.green_to_red_transition   # Use instance variable (3s)
                                esp_duration = self.esp_green_duration        # Use actual ESP duration
                                
                                # Red-to-Green transition ending
                                if (previous_remaining > (esp_duration + green_to_red) and 
                                    self.duration_remaining <= (esp_duration + green_to_red) and 
                                    self.duration_remaining > green_to_red):
                                    print(f"[Lane {self.lane_id}] 🟢 RED>GREEN COMPLETE - ENTERING GREEN PHASE ({esp_duration}s)")
                                
                                # Green phase ending
                                elif (previous_remaining > green_to_red and 
                                      self.duration_remaining <= green_to_red and 
                                      self.duration_remaining > 0):
                                    print(f"[Lane {self.lane_id}] 🟡 GREEN PHASE ENDED ({esp_duration}s) - ENTERING GREEN>RED TRANSITION ({green_to_red}s)")
                                
                                # Check if this lane has completed sending data when duration is up
                                if elapsed_time >= self.duration_threshold:
                                    # Check if we have completed sending data
                                    data_sending_complete = True
                                    if self.lane_id in shared_state.data_sending_status:
                                        if shared_state.data_sending_status[self.lane_id]['sending'] == True:
                                            data_sending_complete = False
                                            shared_state.switching_blocked = True
                                            print(f"[Lane {self.lane_id}] Blocking lane switch - still sending data")
                                        elif not data_sent_in_current_period and not data_send_initiated:
                                            print(f"[Lane {self.lane_id}] Duration elapsed but data not sent yet - forcing send")
                                            threading.Timer(0.1, self.log_traffic_data).start()
                                            threading.Timer(0.3, self.publish_vehicle_count).start()
                                            data_send_initiated = True
                                            shared_state.data_sending_status[self.lane_id]['sending'] = True
                                            shared_state.switching_blocked = True
                                            data_sending_complete = False
                                        else:
                                            data_sending_complete = True
                                            shared_state.switching_blocked = False
                                    
                                    # Only switch if data sending is complete
                                    if data_sending_complete and not shared_state.switching_blocked:
                                        # Determine next lane in sequence (1→2→3→4→1)
                                        next_lane_id = (self.lane_id % 4) + 1
                                        
                                        print(f"[Lane {self.lane_id}] Duration elapsed, switching to Lane {next_lane_id}")
                                        shared_state.active_lane = next_lane_id
                                        shared_state.last_switch_time = current_time
                                        self.is_active = False
                                        
                                        # Update all lane states
                                        for lane_id in range(1, 5):
                                            is_next = (lane_id == next_lane_id)
                                            if lane_id in shared_state.lane_states:
                                                shared_state.lane_states[lane_id]['active'] = is_next
                                                if is_next:
                                                    # CRITICAL FIX: Set new lane timer to START of cycle (RED>GREEN phase)
                                                    shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                                    print(f"[CRITICAL] Lane {lane_id} starts fresh cycle: RED>GREEN(4s) -> GREEN -> GREEN>RED(4s)")
                                                    if lane_id in shared_state.data_sending_status:
                                                        shared_state.data_sending_status[lane_id]['sending'] = False
                                                        shared_state.data_sending_status[lane_id]['completed'] = False
                                        
                                        # Reset our tracking variables
                                        self.last_mqtt_send_time = current_time
                                        data_sent_in_current_period = False
                                        data_send_initiated = False
                                        first_cycle_after_startup = False  # Ensure normal behavior for subsequent cycles
                                        self.clear_queues()
                                
                                # If we're approaching the end of our duration, prepare next lane data
                                if self.duration_remaining <= 4 and shared_state.next_lane_trigger_time is None:
                                    next_lane_id = (self.lane_id % 4) + 1
                                    shared_state.next_lane_trigger_time = current_time
                                    print(f"[Lane {self.lane_id}] Preparing Lane {next_lane_id} data - GREEN>RED phase: {self.duration_remaining}s remaining")
                                    
                                    # Ensure next lane has timer set
                                    if next_lane_id in shared_state.lane_states:
                                        shared_state.lane_states[next_lane_id]['last_send_time'] = current_time
                            
                            # Update lane status from shared state
                            self.is_active = (shared_state.active_lane == self.lane_id)
                            if self.lane_id in shared_state.lane_states:
                                shared_state.lane_states[self.lane_id]['active'] = self.is_active
                    else:
                        # During startup delay, keep lanes in standby mode
                        self.is_active = False
                        self.duration_remaining = self.duration_threshold
                    
                    # Check if we're in startup delay
                    with shared_state.lock:
                        in_startup_delay = not shared_state.system_started
                        just_started = shared_state.system_started and (current_time - shared_state.startup_time < 2.0)
                    
                    if in_startup_delay:
                        # During startup delay, skip detection but still show frames
                        # Create empty results for display
                        current_vehicle_counts = defaultdict(int)
                        detections = []
                        tracked_objects = []
                        
                        # Create a dummy results object for display with proper methods
                        class DummyBoxes:
                            def __init__(self):
                                self.xyxy = None
                                self.conf = None
                                self.cls = None
                            
                            def cpu(self):
                                # Return empty tensor that can be converted to numpy
                                import numpy as np
                                return np.array([])
                                
                        class DummyResults:
                            def __init__(self):
                                self.boxes = None  # Set to None to avoid processing during startup
                                self.names = {0: 'mobil', 1: 'motor', 2: 'truck', 3: 'bus'}
                        
                        dummy_result = DummyResults()
                        results = [dummy_result]
                        
                        # Add "DETECTION PAUSED" text to the frame
                        h, w = frame.shape[:2]
                        cv2.putText(frame, "DETECTION PAUSED - STARTUP DELAY", 
                                   (w//2 - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                                   0.8, (0, 0, 255), 2)
                    else:
                        # Normal operation after startup delay
                        # Run YOLO detection
                        results = self.model(frame, conf=self.confidence, verbose=False)
                        
                        # Process detections for tracking
                        detections = []
                        try:
                            if results[0] is not None and hasattr(results[0], 'boxes') and results[0].boxes is not None:
                                boxes = results[0].boxes.xyxy.cpu().numpy() if hasattr(results[0].boxes, 'xyxy') else None
                                scores = results[0].boxes.conf.cpu().numpy() if hasattr(results[0].boxes, 'conf') else None
                                classes = results[0].boxes.cls.cpu().numpy() if hasattr(results[0].boxes, 'cls') else None
                                
                                if boxes is not None and scores is not None and classes is not None:
                                    # Reset vehicle counts for processing
                                    current_vehicle_counts = defaultdict(int)
                                    
                                    for i, (box, score, cls) in enumerate(zip(boxes, scores, classes)):
                                        # Only process detections with confidence >= 0.60
                                        if score >= 0.60:
                                            class_name = results[0].names[int(cls)].lower()
                                            if class_name in self.vehicle_classes:
                                                # Count this vehicle
                                                current_vehicle_counts[class_name] += 1
                                                # Add to detections
                                                detections.append([box[0], box[1], box[2], box[3], score, int(cls)])
                                    
                                    # Update vehicle counts
                                    self.vehicle_counts = dict(current_vehicle_counts)
                                    self.total_vehicles = sum(current_vehicle_counts.values())
                        except Exception as e:
                            # Silently handle errors during detection processing
                            if not in_startup_delay:  # Only print errors if not in startup delay
                                print(f"[Lane {self.lane_id}] Detection error: {e}")
                        
                        # Update tracking if available
                        tracked_objects = []
                        class_names = []
                        if self.tracker and len(detections) > 0:
                            # Extract class names for tracker
                            for det in detections:
                                class_name = results[0].names[int(det[5])].lower()
                                class_names.append(class_name)
                            
                            tracked_objects = self.tracker.update(np.array(detections), class_names)
                        
                        # Count vehicles based on tracking results OR direct detections
                        current_vehicle_counts = defaultdict(int)
                        if len(tracked_objects) > 0:
                            # Use tracking results
                            for bbox, track_id, class_name in tracked_objects:
                                if class_name in self.vehicle_classes:
                                    current_vehicle_counts[class_name] += 1
                        else:
                            # Fallback to direct detection counting (without SORT)
                            if len(detections) > 0:
                                for det in detections:
                                    class_name = results[0].names[int(det[5])].lower()
                                    if class_name in self.vehicle_classes:
                                        current_vehicle_counts[class_name] += 1
                        
                        # Update vehicle counts
                        self.vehicle_counts = dict(current_vehicle_counts)
                        self.total_vehicles = sum(current_vehicle_counts.values())
                        
                        # Store our data in shared state for other lanes to access
                        with shared_state.lock:
                            lane_data = {
                                "road_section_id": self.lane_id,
                                "total_vehicles": self.total_vehicles,
                                "vehicle_counts": dict(current_vehicle_counts),
                                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                            }
                            shared_state.lane_data[self.lane_id] = lane_data
                    
                    # Regular timed data sending (last 5 seconds) - ONLY AFTER STARTUP
                    with shared_state.lock:
                        system_started = shared_state.system_started
                    
                    # Send data at start of green-to-red transition (4 seconds remaining)
                    if (system_started and self.is_active and self.duration_remaining <= 4 and 
                        not self.waiting_for_mqtt_response and not data_send_initiated):
                        
                        # Check if we're not in switching process
                        switching_in_progress = False
                        with shared_state.lock:
                            switching_in_progress = (current_time - shared_state.last_switch_time < 1.0)
                        
                        if not switching_in_progress:
                            # Determine which phase we're in for clearer messaging
                            red_to_green = self.red_to_green_transition
                            green_to_red = self.green_to_red_transition
                            esp_duration = self.esp_green_duration
                            
                            if self.duration_remaining > (esp_duration + green_to_red):
                                red_green_remaining = self.duration_remaining - (esp_duration + green_to_red)
                                print(f"[Lane {self.lane_id}] 📡 Sending data - RED>GREEN: {red_green_remaining}s")
                            elif self.duration_remaining > green_to_red:
                                green_remaining = self.duration_remaining - green_to_red
                                print(f"[Lane {self.lane_id}] 📡 Sending data - GREEN: {green_remaining}s")
                            else:
                                print(f"[Lane {self.lane_id}] 📡 Sending data - GREEN>RED PHASE: {self.duration_remaining}s remaining")
                            
                            # Mark data sending as in progress
                            with shared_state.lock:
                                if self.lane_id in shared_state.data_sending_status:
                                    shared_state.data_sending_status[self.lane_id]['sending'] = True
                                    shared_state.data_sending_status[self.lane_id]['completed'] = False
                            
                            # Send data using threading to prevent blocking
                            threading.Timer(0.1, self.log_traffic_data).start()
                            threading.Timer(0.3, self.publish_vehicle_count).start()
                            
                            # Update tracking variables
                            self.waiting_for_mqtt_response = True
                            data_send_initiated = True
                            print(f"[Lane {self.lane_id}] Data send initiated (DB + MQTT), waiting for response")
                    
                    # NEW: Publish countdown sync every 2 seconds during active phase
                    if (system_started and self.is_active and 
                        int(current_time) % 2 == 0 and  # Every 2 seconds
                        int(current_time) != getattr(self, 'last_sync_publish_time', 0)):  # Avoid duplicate sends
                        
                        self.last_sync_publish_time = int(current_time)
                        
                        # Check if we're still the active lane before publishing sync
                        with shared_state.lock:
                            still_active = (shared_state.active_lane == self.lane_id)
                        
                        # CRITICAL FIX: Stop publishing countdown sync if cycle is complete (duration_remaining <= 0)
                        # ENHANCED FIX: Also check if countdown is still active and ESP hasn't gone RED yet
                        with shared_state.lock:
                            countdown_should_continue = (still_active and 
                                                       self.duration_remaining > 0 and 
                                                       shared_state.countdown_active)
                        
                        if countdown_should_continue:
                            # Additional check: Only one lane should publish countdown sync at a time
                            other_lanes_publishing = False
                            with shared_state.lock:
                                for other_lane_id in range(1, 5):
                                    if (other_lane_id != self.lane_id and 
                                        other_lane_id in shared_state.data_sending_status and
                                        hasattr(shared_state, 'last_countdown_publisher') and
                                        shared_state.last_countdown_publisher == other_lane_id and
                                        time.time() - getattr(shared_state, 'last_countdown_time', 0) < 3):
                                        other_lanes_publishing = True
                                        break
                            
                            if not other_lanes_publishing and shared_state.countdown_active:
                                # Only publish countdown sync if ESP has started the green phase
                                # Determine current phase for sync message
                                red_to_green = self.red_to_green_transition
                                green_to_red = self.green_to_red_transition
                                esp_duration = self.esp_green_duration
                                
                                if self.duration_remaining > (esp_duration + green_to_red):
                                    current_phase = "red_to_green"
                                    # Don't publish countdown sync during red-to-green phase
                                    print(f"[Lane {self.lane_id}] ⏸️ In red-to-green phase - waiting for ESP green signal")
                                elif self.duration_remaining > green_to_red:
                                    current_phase = "green"
                                    # Mark this lane as the countdown publisher
                                    with shared_state.lock:
                                        shared_state.last_countdown_publisher = self.lane_id
                                        shared_state.last_countdown_time = current_time
                                    
                                    # Publish countdown sync to help ESP monitor Python's timing
                                    self.publish_countdown_sync(self.duration_remaining, current_phase)
                                else:
                                    current_phase = "green_to_red"
                                    # Mark this lane as the countdown publisher
                                    with shared_state.lock:
                                        shared_state.last_countdown_publisher = self.lane_id
                                        shared_state.last_countdown_time = current_time
                                    
                                    # Publish countdown sync to help ESP monitor Python's timing
                                    self.publish_countdown_sync(self.duration_remaining, current_phase)
                            else:
                                print(f"[Lane {self.lane_id}] ⏸️ Skipping countdown sync - another lane is publishing")
                        else:
                            # Log why countdown sync stopped
                            if not still_active:
                                print(f"[Lane {self.lane_id}] 🛑 Stopped countdown sync - no longer active lane")
                            elif self.duration_remaining <= 0:
                                print(f"[Lane {self.lane_id}] 🛑 Stopped countdown sync - cycle complete (duration: {self.duration_remaining}s)")
                                
                                # CRITICAL FIX: Force immediate lane switch ONLY when cycle is complete (duration_remaining <= 0)
                                with shared_state.lock:
                                    if shared_state.active_lane == self.lane_id and self.is_active:
                                        next_lane_id = (self.lane_id % 4) + 1
                                        print(f"[Lane {self.lane_id}] 🔄 FORCE SWITCH: Cycle complete - switching to Lane {next_lane_id}")
                                        
                                        shared_state.active_lane = next_lane_id
                                        shared_state.last_switch_time = current_time
                                        self.is_active = False
                                        
                                        # Update all lane states
                                        for lane_id in range(1, 5):
                                            is_next = (lane_id == next_lane_id)
                                            if lane_id in shared_state.lane_states:
                                                shared_state.lane_states[lane_id]['active'] = is_next
                                                if is_next:
                                                    shared_state.lane_states[lane_id]['last_send_time'] = current_time
                                                    print(f"[FORCE SWITCH] Lane {lane_id} starts fresh cycle")
                                                    if lane_id in shared_state.data_sending_status:
                                                        shared_state.data_sending_status[lane_id]['sending'] = False
                                                        shared_state.data_sending_status[lane_id]['completed'] = False
                                        
                                        # Clear sync data for completed lane
                                        shared_state.countdown_active = False
                                        shared_state.sync_established = False
                                        
                                        print(f"[FORCE SWITCH] Completed: {self.lane_id} -> {next_lane_id}")
                                         
                                         # Publish green permission for the next lane
                                        if self.mqtt_client:
                                             green_permission_data = {
                                                 "section": next_lane_id,
                                                 "permission": "granted",
                                                 "timestamp": current_time,
                                                 "source": "python_force_switch"
                                             }
                                             self.mqtt_client.publish("traffic/green_permission", 
                                                                    json.dumps(green_permission_data), qos=1)
                                             print(f"[FORCE SWITCH] Published green permission for Lane {next_lane_id}")
                            else:
                                print(f"[Lane {self.lane_id}] 🛑 Stopped countdown sync - unknown reason")
                    
                    # Add result to queue for display
                    if not self.result_queue.full():
                        # Create frame_vehicles for display - include ALL detected vehicles
                        frame_vehicles = []
                        if len(tracked_objects) > 0:
                            # Use tracked objects when available
                            for bbox, track_id, class_name in tracked_objects:
                                x1, y1, x2, y2 = bbox
                                frame_vehicles.append((class_name, (x1, y1, x2, y2, track_id)))
                        else:
                            # Fallback for direct detections - include ALL detections
                            for i, det in enumerate(detections):
                                class_name = results[0].names[int(det[5])].lower()
                                if class_name in self.vehicle_classes:
                                    x1, y1, x2, y2 = det[0], det[1], det[2], det[3]
                                    score = det[4]  # Include confidence score
                                    frame_vehicles.append((class_name, (x1, y1, x2, y2, i)))
                        
                        self.result_queue.put({
                            'frame': frame,
                            'results': results[0],
                            'tracked': tracked_objects,
                            'detections': len(detections),
                            'vehicles': frame_vehicles
                        })
                    
                    # Update frame counter and FPS
                    self.frame_count += 1
                    self.fps_counter += 1
                    
                    # Calculate FPS
                    if current_time - self.last_fps_time >= 1.0:
                        self.fps = self.fps_counter
                        self.fps_counter = 0
                        self.last_fps_time = current_time
                    
                    # Garbage collection
                    if current_time - self.last_gc_time >= self.gc_interval:
                        gc.collect()
                        self.last_gc_time = current_time
                        
                else:
                    time.sleep(0.01)  # Small delay if no frames
                    
            except Exception as e:
                print(f"[Lane {self.lane_id}] ❌ Processing error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
    
    def clear_queues(self):
        """Clear frame and result queues to prevent backlog during lane switching"""
        try:
            while not self.frame_queue.empty():
                try:
                    self.frame_queue.get_nowait()
                except:
                    break
                    
            while not self.result_queue.empty():
                try:
                    self.result_queue.get_nowait()
                except:
                    break
                    
            print(f"[Lane {self.lane_id}] Cleared queues during lane switch")
        except Exception as e:
            print(f"[Lane {self.lane_id}] Error clearing queues: {e}")
    
    def publish_vehicle_count_startup(self):
        """Publish Lane 1's own data to MQTT during startup"""
        try:
            if not self.mqtt_client:
                print(f"[Lane {self.lane_id}] Cannot publish - MQTT client not initialized")
                return
            
            # During startup, Lane 1 sends its own data (road_section_id = 1)
            target_data = {
                "road_section_id": 1,  # Lane 1's own data
                "total_vehicles": self.total_vehicles,
                "vehicle_counts": dict(self.vehicle_counts),
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            print(f"[Lane {self.lane_id}] Sending own data (Lane 1) during startup")
            
            message = json.dumps(target_data)
            
            # Publish to MQTT
            try:
                topic = "traffic/vehicle_count"
                result = self.mqtt_client.publish(topic, message, qos=1, retain=True)
                
                # Check publish status
                status = result[0]
                
                if status != 0:
                    print(f"[Lane {self.lane_id}] Failed to publish startup data, retrying...")
                    time.sleep(0.2)
                    self.mqtt_client.reconnect()
                    self.mqtt_client.publish(topic, message, qos=1, retain=True)
                
                print(f"[Lane {self.lane_id}] 📡 MQTT sent: Lane 1 startup data with {target_data.get('total_vehicles', 0)} vehicles")
                
            except Exception as publish_error:
                print(f"[Lane {self.lane_id}] Error publishing startup data to MQTT: {publish_error}")
                    
        except Exception as e:
            print(f"[Lane {self.lane_id}] Error in startup MQTT publishing: {e}")
    
    def publish_vehicle_count(self):
        """Publish vehicle count data to MQTT following nod.py sequential pattern"""
        try:
            # Set waiting_for_mqtt_response flag to trigger alert in display
            self.waiting_for_mqtt_response = True
            
            # Set data sending in progress in shared state
            with shared_state.lock:
                if self.lane_id in shared_state.data_sending_status:
                    shared_state.data_sending_status[self.lane_id]['sending'] = True
                    shared_state.data_sending_status[self.lane_id]['completed'] = False
            
            if not self.mqtt_client:
                print(f"[Lane {self.lane_id}] Cannot publish - MQTT client not initialized")
                self.waiting_for_mqtt_response = False
                with shared_state.lock:
                    if self.lane_id in shared_state.data_sending_status:
                        shared_state.data_sending_status[self.lane_id]['sending'] = False
                        shared_state.data_sending_status[self.lane_id]['completed'] = False
                        shared_state.switching_blocked = False
                return
            
            # Check if we're in switching process
            current_time = time.time()
            with shared_state.lock:
                switching_in_progress = (current_time - shared_state.last_switch_time < 1.0)
            
            if switching_in_progress and not self.is_active:
                print(f"[Lane {self.lane_id}] Skipping MQTT publish during lane switch")
                self.waiting_for_mqtt_response = False
                with shared_state.lock:
                    if self.lane_id in shared_state.data_sending_status:
                        shared_state.data_sending_status[self.lane_id]['sending'] = False
                        shared_state.data_sending_status[self.lane_id]['completed'] = False
                        shared_state.switching_blocked = False
                return
            
            # Check if we should publish (only active lane or transitioning)
            should_publish = False
            is_transition = False
            
            with shared_state.lock:
                if shared_state.active_lane == self.lane_id:
                    should_publish = True
                elif (shared_state.next_lane_trigger_time is not None and 
                      current_time >= shared_state.next_lane_trigger_time and
                      self.lane_id == ((shared_state.active_lane % 4) + 1)):
                    should_publish = True
                    is_transition = True
            
            if not should_publish:
                print(f"[Lane {self.lane_id}] Skipping publish - lane not active or transitioning")
                self.waiting_for_mqtt_response = False
                with shared_state.lock:
                    if self.lane_id in shared_state.data_sending_status:
                        shared_state.data_sending_status[self.lane_id]['sending'] = False
                        shared_state.data_sending_status[self.lane_id]['completed'] = False
                        shared_state.switching_blocked = False
                return
            
            # Sequential data sending pattern: Lane 1→2, Lane 2→3, Lane 3→4, Lane 4→1
            target_lane_id = (self.lane_id % 4) + 1
            
            # Get target lane's data from shared state
            target_data = None
            with shared_state.lock:
                if target_lane_id in shared_state.lane_data and shared_state.lane_data[target_lane_id] is not None:
                    target_data = shared_state.lane_data[target_lane_id]
                    print(f"[Lane {self.lane_id}] Using stored data for Lane {target_lane_id}")
            
            # If no target data, use our own data with target lane ID
            if target_data is None:
                target_data = {
                    "road_section_id": target_lane_id,  # Use target lane ID
                    "total_vehicles": self.total_vehicles,
                    "vehicle_counts": dict(self.vehicle_counts),
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                print(f"[Lane {self.lane_id}] Using own data for Lane {target_lane_id} (fallback)")
            
            # Important: Include duration and lane_id for proper synchronization
            with shared_state.lock:
                target_data["duration"] = shared_state.last_esp_duration
                target_data["lane_id"] = target_lane_id
            
            # Log sending action
            if is_transition:
                print(f"[Lane {self.lane_id}] Sending Lane {target_lane_id} data during transition")
            else:
                print(f"[Lane {self.lane_id}] Sending Lane {target_lane_id} data")
            
            message = json.dumps(target_data)
            
            # Publish to a single topic for simplicity
            try:
                # General topic only
                topic = "traffic/vehicle_count"
                result = self.mqtt_client.publish(topic, message, qos=1, retain=True)
                
                # Check publish status
                status = result[0]
                
                if status != 0:
                    print(f"[Lane {self.lane_id}] Failed to publish, retrying...")
                    time.sleep(0.2)
                    self.mqtt_client.reconnect()
                    
                    # Retry publishing
                    self.mqtt_client.publish(topic, message, qos=1, retain=True)
                    print(f"[Lane {self.lane_id}] MQTT publish retry completed")
                
                # Force MQTT message flush
                try:
                    self.mqtt_client.loop_stop()
                    self.mqtt_client.loop_start()
                except Exception as loop_error:
                    print(f"[Lane {self.lane_id}] Error during MQTT loop restart: {loop_error}")
                
                # Mark data sending as completed
                with shared_state.lock:
                    if self.lane_id in shared_state.data_sending_status:
                        shared_state.data_sending_status[self.lane_id]['sending'] = False
                        shared_state.data_sending_status[self.lane_id]['completed'] = True
                        print(f"[Lane {self.lane_id}] Data sending completed successfully")
                        shared_state.switching_blocked = False
                
                # Reset waiting flag after successful send
                self.waiting_for_mqtt_response = False
                
                print(f"[Lane {self.lane_id}] 📡 MQTT sent: Lane {target_lane_id} data with {target_data.get('total_vehicles', 0)} vehicles")
                
            except Exception as publish_error:
                print(f"[Lane {self.lane_id}] Error publishing to MQTT: {publish_error}")
                # Mark data sending as failed
                with shared_state.lock:
                    if self.lane_id in shared_state.data_sending_status:
                        shared_state.data_sending_status[self.lane_id]['sending'] = False
                        shared_state.data_sending_status[self.lane_id]['completed'] = False
                        shared_state.switching_blocked = False
                
                # Try to reconnect and retry
                try:
                    self.mqtt_client.reconnect()
                    time.sleep(0.2)
                    
                    # Retry after reconnection
                    print(f"[Lane {self.lane_id}] Retrying MQTT publish after reconnection")
                    self.mqtt_client.publish(topic_specific, message, qos=1, retain=True)
                    self.mqtt_client.publish(topic_general, message, qos=1, retain=True)
                    self.mqtt_client.publish(topic_alt, message, qos=1, retain=True)
                    self.mqtt_client.publish(topic_lane, message, qos=1, retain=True)
                    
                    # If retry succeeds, mark as completed
                    with shared_state.lock:
                        if self.lane_id in shared_state.data_sending_status:
                            shared_state.data_sending_status[self.lane_id]['sending'] = False
                            shared_state.data_sending_status[self.lane_id]['completed'] = True
                            print(f"[Lane {self.lane_id}] Data sending completed after retry")
                            shared_state.switching_blocked = False
                except:
                    pass
                    
        except Exception as e:
            print(f"[Lane {self.lane_id}] Error in publish_vehicle_count method: {e}")
            self.waiting_for_mqtt_response = False
            
            # Mark data sending as failed
            with shared_state.lock:
                if self.lane_id in shared_state.data_sending_status:
                    shared_state.data_sending_status[self.lane_id]['sending'] = False
                    shared_state.data_sending_status[self.lane_id]['completed'] = False
                    shared_state.switching_blocked = False
    
    def display_results(self):
        """Display results with sophisticated timing information from nod.py"""
        # Track when data is being sent for visual alert
        sending_data = False
        sending_data_start_time = 0
        sending_data_duration = 1.5  # Show alert for 1.5 seconds
        
        # Set up the window
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, self.window_width, self.window_height)
        cv2.moveWindow(self.window_name, self.window_x, self.window_y)
        
        while self.is_running:
            try:
                if not self.result_queue.empty():
                    result_data = self.result_queue.get(timeout=1)
                    
                    frame = result_data['frame']
                    results = result_data['results']
                    detections_count = result_data['detections']
                    vehicles = result_data.get('vehicles', [])
                    
                    # Resize frame to fit window
                    frame_resized = cv2.resize(frame, (self.window_width, self.window_height))
                    
                    # Don't use YOLO's plot() to avoid extra annotations, start with clean frame
                    annotated_frame = frame_resized.copy()
                    
                    # Draw boxes for all detected vehicles with confidence scores
                    if vehicles:
                        # Define consistent colors for each vehicle type (BGR format)
                        vehicle_type_colors = {
                            'mobil': (255, 0, 0),      # Blue for cars
                            'motor': (0, 255, 0),      # Green for motorcycles  
                            'truck': (0, 0, 255),      # Red for trucks
                            'bus': (0, 255, 255)       # Yellow for buses
                        }
                        
                        # Get original frame dimensions for scaling
                        original_height, original_width = frame.shape[:2]
                        scale_x = self.window_width / original_width
                        scale_y = self.window_height / original_height
                        
                        # Draw bounding boxes for all detected vehicles
                        try:
                            if hasattr(results, 'boxes') and results.boxes is not None:
                                boxes = results.boxes.xyxy.cpu().numpy() if hasattr(results.boxes, 'xyxy') else None
                                scores = results.boxes.conf.cpu().numpy() if hasattr(results.boxes, 'conf') else None
                                classes = results.boxes.cls.cpu().numpy() if hasattr(results.boxes, 'cls') else None
                                
                                if boxes is not None and scores is not None and classes is not None:
                                    # Reset vehicle counts for display
                                    display_vehicle_counts = defaultdict(int)
                                    
                                    for i, (box, score, cls) in enumerate(zip(boxes, scores, classes)):
                                        # Only show detections with confidence >= 0.60
                                        if score >= 0.60:
                                            class_name = results.names[int(cls)].lower()
                                            if class_name in self.vehicle_classes:
                                                # Count this vehicle for display
                                                display_vehicle_counts[class_name] += 1
                                                
                                                # Scale coordinates to resized frame
                                                x1 = int(box[0] * scale_x)
                                                y1 = int(box[1] * scale_y)
                                                x2 = int(box[2] * scale_x)
                                                y2 = int(box[3] * scale_y)
                                                
                                                # Use consistent color based on vehicle type
                                                box_color = vehicle_type_colors.get(class_name, (255, 255, 255))
                                                
                                                # Draw bounding box
                                                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), box_color, 2)
                                                
                                                # Add vehicle type label with confidence
                                                label = f"{class_name.upper()} - {score:.2f}"
                                                text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
                                                
                                                # Draw label background
                                                cv2.rectangle(annotated_frame, 
                                                            (x1, y1 - text_size[1] - 5), 
                                                            (x1 + text_size[0] + 5, y1), 
                                                            box_color, -1)
                                                
                                                # Draw label text
                                                cv2.putText(annotated_frame, label, 
                                                          (x1 + 3, y1 - 3), 
                                                          cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                                    
                                    # Update vehicle counts for this frame
                                    if not in_startup_delay:
                                        self.vehicle_counts = dict(display_vehicle_counts)
                                        self.total_vehicles = sum(display_vehicle_counts.values())
                        except Exception as e:
                            # Don't print errors during startup delay
                            pass
                    
                    # Add simplified lane information overlay
                    final_frame = self.add_sophisticated_info_overlay(annotated_frame, detections_count, sending_data, sending_data_start_time, sending_data_duration)
                    
                    # Display frame
                    cv2.imshow(self.window_name, final_frame)
                    
                    # Handle key press
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        self.is_running = False
                        break
                    elif key == ord(str(self.lane_id)):
                        # Switch active display to this lane (visual only, doesn't affect processing)
                        with shared_state.lock:
                            shared_state.active_lane = self.lane_id
                        print(f"[System] Switched display focus to Lane {self.lane_id}")
                else:
                    time.sleep(0.01)
                    
            except Exception as e:
                print(f"[Lane {self.lane_id}] ❌ Display error: {e}")
                time.sleep(0.1)
    
    def add_sophisticated_info_overlay(self, frame, detections_count, sending_data, sending_data_start_time, sending_data_duration):
        """Add sophisticated overlay with lane status and sync information"""
        height, width = frame.shape[:2]  # Use resized frame dimensions
        current_time = time.time()
        
        # Make a copy of the frame to modify
        display_frame = frame.copy()
        
        # Adjust overlay size for smaller windows
        overlay_width = min(280, width - 20)
        overlay_height = min(180, height - 20)
        
        # Determine position based on lane - Lane 2 and 4 on right, Lane 1 and 3 on left
        if self.lane_id in [2, 4]:  # Right side for lanes 2 and 4
            overlay_x = width - overlay_width - 10
            text_x = width - overlay_width - 5
        else:  # Left side for lanes 1 and 3
            overlay_x = 10
            text_x = 20
        
        # Simple background for main info panel
        overlay = display_frame.copy()
        cv2.rectangle(overlay, (overlay_x, 10), (overlay_x + overlay_width, 10 + overlay_height), (0, 0, 0), -1)
        display_frame = cv2.addWeighted(display_frame, 0.8, overlay, 0.2, 0)
        
        # Check system startup status
        with shared_state.lock:
            system_started = shared_state.system_started
            startup_remaining = max(0, shared_state.startup_delay - (current_time - shared_state.startup_time))
        
        # Lane information
        y_offset = 35
        font_scale = 0.6  # Smaller font for smaller windows
        
        # === MAIN STATUS DISPLAY ===
        if not system_started:
            # Add more visible startup indication
            cv2.putText(display_frame, f"STARTUP DELAY", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            y_offset += 30
            cv2.putText(display_frame, f"{startup_remaining:.1f}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            y_offset += 30
            
            # Add lane info during startup
            cv2.putText(display_frame, f"LANE {self.lane_id}", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            y_offset += 25
            cv2.putText(display_frame, "DETECTION PAUSED", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            
            # Add a large countdown in the center of the screen
            countdown_text = f"{int(startup_remaining)}"
            text_size = cv2.getTextSize(countdown_text, cv2.FONT_HERSHEY_SIMPLEX, 4, 6)[0]
            text_x = (width - text_size[0]) // 2
            text_y = (height + text_size[1]) // 2
            
            # Draw semi-transparent background
            countdown_bg = display_frame.copy()
            cv2.rectangle(countdown_bg, 
                         (text_x - 20, text_y - text_size[1] - 20),
                         (text_x + text_size[0] + 20, text_y + 20),
                         (0, 0, 0), -1)
            display_frame = cv2.addWeighted(display_frame, 0.7, countdown_bg, 0.3, 0)
            
            # Draw countdown text
            cv2.putText(display_frame, countdown_text, (text_x, text_y), 
                       cv2.FONT_HERSHEY_SIMPLEX, 4, (0, 165, 255), 6)
        else:
            # === SIMPLE LANE STATUS ===
            status_text = "ACTIVE" if self.is_active else "STANDBY"
            status_color = (0, 255, 0) if self.is_active else (128, 128, 128)
            
            # Lane status
            cv2.putText(display_frame, f"LANE {self.lane_id}", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            cv2.putText(display_frame, f"{status_text}", (text_x, y_offset + 25), cv2.FONT_HERSHEY_SIMPLEX, font_scale, status_color, 2)
            y_offset += 50
            
            # === THREE-PHASE TIMING DISPLAY ===
            if self.is_active:
                # CRITICAL FIX: Use shared state timing for accurate countdown
                with shared_state.lock:
                    lane_start_time = shared_state.lane_states[self.lane_id]['last_send_time']
                    # Get ESP green phase duration from shared state
                    actual_esp_duration = shared_state.last_esp_duration
                
                elapsed_time = int(current_time - lane_start_time)
                real_time_remaining = max(0, self.duration_threshold - elapsed_time)
                
                # Debug output (remove after testing)
                if self.lane_id == 1:  # Only show for lane 1 to avoid spam
                    print(f"[TIMER DEBUG] Lane {self.lane_id}: elapsed={elapsed_time}, remaining={real_time_remaining}, ESP green={actual_esp_duration}, total={self.duration_threshold}")
                
                red_to_green = self.red_to_green_transition
                green_to_red = self.green_to_red_transition
                
                # Always use the ESP duration from MQTT instead of static value
                esp_duration = actual_esp_duration
                
                # FIXED PHASE CALCULATION
                # Phase boundaries: 
                # - RED>GREEN: duration_threshold down to (esp_duration + green_to_red)
                # - GREEN: (esp_duration + green_to_red) down to green_to_red  
                # - GREEN>RED: green_to_red down to 0
                
                if real_time_remaining > (esp_duration + green_to_red):
                    # RED→GREEN phase (always 4 seconds)
                    red_green_remaining = real_time_remaining - (esp_duration + green_to_red)
                    # Cap at 4 seconds max
                    if red_green_remaining > red_to_green:
                        red_green_remaining = red_to_green
                    
                    cv2.putText(display_frame, f"RED>GREEN: {red_green_remaining}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 165, 0), 2)
                    y_offset += 25
                    cv2.putText(display_frame, f"GREEN: {esp_duration}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (128, 128, 128), 1)
                    y_offset += 25
                    cv2.putText(display_frame, f"GREEN>RED: {green_to_red}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (128, 128, 128), 1)
                    y_offset += 25
                
                elif real_time_remaining > green_to_red:
                    # GREEN phase - Show ESP synchronized countdown
                    green_remaining = real_time_remaining - green_to_red
                    
                    # If we have ESP sync data, use it directly for green countdown
                    with shared_state.lock:
                        if (shared_state.countdown_active and shared_state.sync_established):
                            elapsed_since_sync = current_time - shared_state.countdown_start_time
                            esp_green_remaining = max(0, shared_state.current_countdown - int(elapsed_since_sync))
                            if esp_green_remaining > 0:
                                green_remaining = esp_green_remaining
                    
                    # Cap green remaining at ESP duration
                    if green_remaining > esp_duration:
                        green_remaining = esp_duration
                    
                    cv2.putText(display_frame, f"RED>GREEN: DONE", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 0), 1)
                    y_offset += 25
                    
                    green_color = (0, 255, 0) if green_remaining > 5 else (0, 165, 255)
                    cv2.putText(display_frame, f"GREEN: {green_remaining}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, green_color, 2)
                    y_offset += 25
                    cv2.putText(display_frame, f"GREEN>RED: {green_to_red}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (128, 128, 128), 1)
                    y_offset += 25
                    
                else:
                    # GREEN→RED phase (always 4 seconds)
                    green_red_remaining = real_time_remaining
                    # Cap at 4 seconds max
                    if green_red_remaining > green_to_red:
                        green_red_remaining = green_to_red
                    
                    cv2.putText(display_frame, f"RED>GREEN: DONE", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 0), 1)
                    y_offset += 25
                    cv2.putText(display_frame, f"GREEN: ENDED", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 255), 2)
                    y_offset += 25
                    
                    transition_color = (255, 165, 0) if green_red_remaining > 2 else (255, 0, 0)
                    cv2.putText(display_frame, f"GREEN>RED: {green_red_remaining}s", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, font_scale, transition_color, 2)
                    y_offset += 25
                
                # Show next lane preparation when in green-to-red phase
                if real_time_remaining <= green_to_red:
                    next_lane = (self.lane_id % 4) + 1
                    cv2.putText(display_frame, f">> Lane {next_lane}", (text_x, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
                    y_offset += 20
        
        # === SIMPLE VEHICLE COUNTER ===
        if system_started:
            # Add total vehicle count
            total_count = sum(self.vehicle_counts.values()) if hasattr(self, 'vehicle_counts') else 0
            cv2.putText(display_frame, f"TOTAL: {total_count}", (text_x, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            y_offset += 25
            
            # Individual vehicle counts - show all detected types
            vehicle_types = ['mobil', 'motor', 'truck', 'bus']
            
            for vehicle_type in vehicle_types:
                count = self.vehicle_counts.get(vehicle_type, 0)
                if count > 0:  # Only show types that have been detected
                    # Use consistent colors for vehicle types
                    if vehicle_type == 'mobil':
                        color = (255, 0, 0)  # Blue for cars
                    elif vehicle_type == 'motor':
                        color = (0, 255, 0)  # Green for motorcycles
                    elif vehicle_type == 'truck':
                        color = (0, 0, 255)  # Red for trucks
                    elif vehicle_type == 'bus':
                        color = (0, 255, 255)  # Yellow for buses
                    else:
                        color = (255, 255, 255)  # White for others
                        
                    cv2.putText(display_frame, f"{vehicle_type.upper()}: {count}", (text_x, y_offset), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
                    y_offset += 18
        
        # === SIMPLE ACTIVE LANE INDICATOR (top right) ===
        if system_started:
            with shared_state.lock:
                active_lane = shared_state.active_lane
                sync_established = shared_state.sync_established
                sync_offset = shared_state.sync_offset
            
            # Simple active lane box - adjust size for smaller windows
            indicator_width = min(120, width - 20)
            indicator_height = 60 if sync_established else 40
            cv2.rectangle(display_frame, (width-indicator_width-10, 10), (width-10, 10+indicator_height), (40, 40, 40), -1)
            cv2.putText(display_frame, f"ACTIVE: {active_lane}", (width-indicator_width-5, 28), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            
            # Add sync status
            if sync_established:
                sync_color = (0, 255, 0) if abs(sync_offset) < 1.0 else (0, 165, 255)
                cv2.putText(display_frame, f"SYNC: {sync_offset:.1f}s", (width-indicator_width-5, 48), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.35, sync_color, 1)
            else:
                cv2.putText(display_frame, "SYNC: NO", (width-indicator_width-5, 48), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
        
        # === SIMPLE CONTROLS ===
        cv2.putText(display_frame, f"Q=Quit", (width-80, height-10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        
        # === ENHANCED DATA SENDING ALERT ===
        if (system_started and self.is_active and self.duration_remaining <= 4 and 
            self.waiting_for_mqtt_response):
            # Enhanced alert for data sending during green-to-red phase
            alert_width = min(160, width - 40)
            alert_color = (255, 0, 0)  # Red for green-to-red transition
            cv2.rectangle(display_frame, (width//2 - alert_width//2, 10), (width//2 + alert_width//2, 40), alert_color, -1)
            cv2.putText(display_frame, f"SENDING DATA", (width//2 - 50, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        
        # Enhanced sync status display
        with shared_state.lock:
            if shared_state.sync_established:
                sync_color = (0, 255, 0) if shared_state.sync_offset < 1.0 else (0, 165, 255)
                sync_text = f"SYNC: ±{shared_state.sync_offset:.1f}s"
                
                # Display sync status in bottom right corner for active lane
                if self.is_active and system_started:
                    cv2.putText(display_frame, sync_text, (width - 120, height - 30), 
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, sync_color, 1)
                    
                    # Show ESP/Python countdown comparison if available
                    if shared_state.countdown_active:
                        elapsed = time.time() - shared_state.countdown_start_time
                        esp_green_remaining = max(0, shared_state.current_countdown - int(elapsed))
                        
                        # Calculate Python's green phase remaining (subtract green_to_red transition)
                        python_green_remaining = max(0, self.duration_remaining - self.green_to_red_transition)
                        
                        # Compare green phase countdowns (what matters for sync)
                        diff = abs(esp_green_remaining - python_green_remaining)
                        diff_color = (0, 255, 0) if diff <= 1 else (0, 165, 255) if diff <= 2 else (0, 0, 255)
                        
                        cv2.putText(display_frame, f"ESP: {esp_green_remaining}s", (width - 120, height - 50), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
                        cv2.putText(display_frame, f"PY: {python_green_remaining}s", (width - 120, height - 70), 
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.35, diff_color, 1)
        
        return display_frame
    
    def run(self):
        """Main processing loop for this lane"""
        print(f"[Lane {self.lane_id}] 🚀 Starting processor...")
        
        # Connect to stream
        try:
            self.cap = self.connect_to_stream()
            if not self.cap:
                print(f"[Lane {self.lane_id}] ⚠️ Cannot connect to stream - will continue with dummy stream")
                # Create a dummy black frame to avoid crashes
                dummy_frame = np.zeros((540, 960, 3), dtype=np.uint8)
                self.cap = cv2.VideoCapture()
                self.cap.open = lambda: True
                self.cap.isOpened = lambda: True
                self.cap.read = lambda: (True, dummy_frame.copy())
                self.cap.release = lambda: None
        except Exception as e:
            print(f"[Lane {self.lane_id}] ❌ Stream connection error: {e}")
            # Create a dummy black frame to avoid crashes
            dummy_frame = np.zeros((540, 960, 3), dtype=np.uint8)
            self.cap = cv2.VideoCapture()
            self.cap.open = lambda: True
            self.cap.isOpened = lambda: True
            self.cap.read = lambda: (True, dummy_frame.copy())
            self.cap.release = lambda: None
        
        self.is_running = True
        
        # Start processing threads
        fetch_thread = threading.Thread(target=self.fetch_frames, daemon=True)
        process_thread = threading.Thread(target=self.process_frames, daemon=True)
        display_thread = threading.Thread(target=self.display_results, daemon=True)
        
        fetch_thread.start()
        process_thread.start()
        display_thread.start()
        
        try:
            # Wait for threads
            while self.is_running:
                time.sleep(0.1)
                
        except KeyboardInterrupt:
            print(f"[Lane {self.lane_id}] ⚠️  Interrupted by user")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up resources"""
        print(f"[Lane {self.lane_id}] 🧹 Cleaning up...")
        self.is_running = False
        
        if self.cap:
            self.cap.release()
        
        if self.mqtt_client:
            self.mqtt_client.publish(f"traffic/status/{self.lane_id}", "offline", qos=1, retain=True)
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        
        # Close database connection (from nod.py)
        if self.db_connection:
            try:
                self.cursor.close()
                self.db_connection.close()
                print(f"[Lane {self.lane_id}] 💾 Database connection closed")
            except:
                pass
        
        cv2.destroyWindow(self.window_name)
        print(f"[Lane {self.lane_id}] ✅ Cleanup complete")

def main():
    parser = argparse.ArgumentParser(description='Multi-Lane RTSP YOLO Vehicle Detection')
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL_PATH, 
                       help=f'Path to YOLO model (.pt file) (default: {DEFAULT_MODEL_PATH})')
    parser.add_argument('--conf', type=float, default=0.25, help='Confidence threshold (default: 0.25)')
    parser.add_argument('--streams', type=str, nargs=4, 
                       default=[
                        #    'rtsp://localhost:8554/cctv1',
                        #    'rtsp://localhost:8554/cctv2', 
                        #    'rtsp://localhost:8554/cctv3',
                        #    'rtsp://localhost:8554/cctv4'
                            'rtsp://opr:User321@@@10.10.1.7:554/Streaming/channels/101',
                            'rtsp://opr:User321@@@10.10.1.7:554/Streaming/channels/201',
                            'rtsp://opr:User321@@@10.10.1.7:554/Streaming/channels/302',
                            'rtsp://opr:User321@@@10.10.1.7:554/Streaming/channels/502'
                       ],
                       help='RTSP stream URLs for 4 lanes')
    parser.add_argument('--screen-width', type=int, default=SCREEN_WIDTH, 
                       help=f'Screen width in pixels (default: {SCREEN_WIDTH})')
    parser.add_argument('--screen-height', type=int, default=SCREEN_HEIGHT, 
                       help=f'Screen height in pixels (default: {SCREEN_HEIGHT})')
    
    args = parser.parse_args()
    
    # Update screen dimensions if provided via arguments
    # Access the global variables directly
    globals()['SCREEN_WIDTH'] = args.screen_width
    globals()['SCREEN_HEIGHT'] = args.screen_height
    globals()['WINDOW_WIDTH'] = args.screen_width // 2
    globals()['WINDOW_HEIGHT'] = args.screen_height // 2
    
    print("🚦 Multi-Lane RTSP YOLO Vehicle Detection")
    print("=" * 60)
    print(f"📹 Model: {args.model}")
    print(f"🎯 Confidence: {args.conf}")
    print(f"🔗 Streams:")
    for i, stream in enumerate(args.streams, 1):
        print(f"   Lane {i}: {stream}")
    print("=" * 60)
    print(f"🖥️  DISPLAY LAYOUT ({SCREEN_WIDTH}x{SCREEN_HEIGHT}, {SCREEN_REFRESH_RATE} Hz):")
    print(f"  📺 4 windows in 2x2 grid ({WINDOW_WIDTH}x{WINDOW_HEIGHT} each)")
    print("  🎯 Lane 1: Top-left    | Lane 2: Top-right")
    print("  🎯 Lane 3: Bottom-left | Lane 4: Bottom-right")
    print("  🚗 Display boxes for detected vehicles with vehicle type and confidence")
    print("  🌈 Consistent colors: Cars=Blue, Motors=Green, Trucks=Red, Buses=Yellow")
    print("=" * 60)
    print("🚀 SYSTEM LOGIC (following nod.py):")
    print("  ⏱️  20-second startup delay - WINDOWS VISIBLE BUT DETECTION PAUSED")
    print("  🚀 STARTUP: Lane 1 sends OWN data 2 seconds before delay ends (at 18s)")
    print("  🔄 Sequential lane switching: 1>2>3>4>1")
    print("  📊 NORMAL: Each lane sends NEXT lane's data")
    print("  ⏰ 28-second total duration per lane (4s red>green + ESP duration + 4s green>red)")
    print("  🔴 RED>GREEN: 4 seconds transition to green")
    print("  🟢 GREEN PHASE: ESP duration only (e.g., 20s)")
    print("  🟡 GREEN>RED: 4 seconds transition to red")
    print("  📡 Data sent at start of green>red transition (4s before ESP ends)")
    print("  🔁 MQTT duration feedback controls timing")
    print("=" * 60)
    
    # Initialize shared state with startup delay (following nod.py pattern)
    start_time = time.time()
    with shared_state.lock:
        # Reset system to initial state
        shared_state.system_started = False
        shared_state.startup_time = start_time
        shared_state.startup_delay = 20  # 20-second startup delay
        shared_state.active_lane = 1  # Lane 1 will become active after startup
        shared_state.next_lane_trigger_time = None
        shared_state.last_switch_time = start_time - 10  # Avoid cooldown at startup
        shared_state.switching_blocked = False
        
        # Set all lanes to standby during startup delay, Lane 1 will activate after startup
        shared_state.lane_states = {
            1: {'active': False, 'duration_threshold': 26, 'last_send_time': start_time},
            2: {'active': False, 'duration_threshold': 26, 'last_send_time': start_time},
            3: {'active': False, 'duration_threshold': 26, 'last_send_time': start_time},
            4: {'active': False, 'duration_threshold': 26, 'last_send_time': start_time}
        }
        
        # Initialize data storage
        shared_state.lane_data = {1: None, 2: None, 3: None, 4: None}
        
        # Initialize data sending status
        shared_state.data_sending_status = {
            1: {'sending': False, 'completed': True},
            2: {'sending': False, 'completed': True},
            3: {'sending': False, 'completed': True},
            4: {'sending': False, 'completed': True}
        }
        
        # Track startup data sending
        shared_state.startup_data_sent = False
        
        print(f"\n🕐 STARTUP SEQUENCE INITIATED")
        print(f"   ⏳ 20-second preparation delay starting...")
        print(f"   👁️ Windows will show RTSP streams during delay (detection paused)")
        print(f"   🚀 Lane 1 will send data 2 seconds before startup delay ends (at 18s)")
        print(f"   🎯 Lane 1 will become active after full delay")
        print(f"   📤 STARTUP: Lane 1 sends Lane 1 data")
        print(f"   📋 Sequential pattern: Lane 1>2>3>4>1")
        print(f"   📤 NORMAL: Lane X sends Lane X+1 data")
        print("=" * 60 + "\n")
    
    # Create lane processors
    processors = []
    for lane_id, stream_url in enumerate(args.streams, 1):
        processor = LaneProcessor(
            rtsp_url=stream_url,
            model_path=args.model,
            lane_id=lane_id,
            confidence=args.conf
        )
        processors.append(processor)
        print(f"✅ Created processor for Lane {lane_id}: {stream_url}")
    
    # Start all processors in separate threads
    processor_threads = []
    for processor in processors:
        thread = threading.Thread(target=processor.run, daemon=True)
        thread.start()
        processor_threads.append(thread)
        time.sleep(0.5)  # Stagger startup to avoid resource conflicts
    
    print(f"\n🎬 All lanes started!")
    print("💡 Controls:")
    print("  - Press 1, 2, 3, 4 to focus display on specific lane")
    print("  - Press Q to quit")
    print("  - System follows nod.py timing logic")
    print("  - MQTT topic 'traffic/duration' controls timing")
    print("  - STARTUP: Lane 1 sends OWN data at 18s (2s before 20s delay ends)")
    print("  - NORMAL: Each lane sends NEXT lane's data at green>red transition")
    print("  - Each lane active for 28s total (4s red>green + ESP + 4s green>red)")
    
    try:
        # Wait for all threads
        for thread in processor_threads:
            thread.join()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all lanes...")
        for processor in processors:
            processor.is_running = False
        time.sleep(2)
        cv2.destroyAllWindows()
        print("✅ All lanes stopped")

if __name__ == "__main__":
    # Example usage without arguments
    if len(sys.argv) == 1:
        print("🚦 Multi-Lane RTSP YOLO Vehicle Detection")
        print("\nExample usage:")
        print(f"python multi_lane_rtsp_yolo.py --model {DEFAULT_MODEL_PATH}")
        print(f"python multi_lane_rtsp_yolo.py --model {DEFAULT_MODEL_PATH} --conf 0.3")
        print(f"python multi_lane_rtsp_yolo.py --screen-width 1920 --screen-height 1080")
        print("\n🚀 Starting with default settings...")
        
        # Check if default model exists
        if not os.path.exists(DEFAULT_MODEL_PATH):
            print(f"⚠️ Default model file {DEFAULT_MODEL_PATH} not found!")
            print("Checking for alternative model paths...")
            
            # Try some alternative paths
            alternative_paths = [
                "best.pt",
                "Python/best.pt",
                "YOLOv11_trained_weights/train1.pt",
                "yolov8n.pt"  # Fallback to a standard model
            ]
            
            model_found = False
            for alt_path in alternative_paths:
                if os.path.exists(alt_path):
                    print(f"✅ Found alternative model at: {alt_path}")
                    # Set default arguments with the found model
                    sys.argv = ['multi_lane_rtsp_yolo.py', '--model', alt_path]
                    model_found = True
                    break
            
            if not model_found:
                print("❌ No model files found!")
                print("Please specify model path: python multi_lane_rtsp_yolo.py --model your_model.pt")
                sys.exit(1)
        else:
            # Set default arguments with the default model
            sys.argv = ['multi_lane_rtsp_yolo.py']  # Model will be loaded from default
    
    main() 