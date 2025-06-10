#!/usr/bin/env python3
"""
ESP Log Reader - Unified log viewer for all ESP32 traffic light controllers
This script reads logs from all ESP devices and displays them in chronological order
"""

import os
import time
import re
from datetime import datetime
import argparse
import serial
import serial.tools.list_ports
from typing import List, Dict, Optional
import threading
import queue

class ESPLogReader:
    def __init__(self):
        self.serial_connections = {}
        self.log_queue = queue.Queue()
        self.running = False
        self.log_file = "unified_log.txt"
        
    def find_esp_ports(self) -> List[str]:
        """Find all available ESP32 serial ports"""
        ports = []
        available_ports = serial.tools.list_ports.comports()
        
        for port in available_ports:
            # Look for ESP32 devices (may need adjustment based on your ESP32 board)
            if any(keyword in port.description.lower() for keyword in ['esp32', 'usb', 'serial']):
                ports.append(port.device)
                print(f"Found potential ESP32 at: {port.device} - {port.description}")
        
        return ports

    def connect_to_esp(self, port: str, lane_id: int) -> Optional[serial.Serial]:
        """Connect to an ESP32 device"""
        try:
            ser = serial.Serial(port, 115200, timeout=1)
            print(f"Connected to Lane {lane_id} at {port}")
            return ser
        except Exception as e:
            print(f"Failed to connect to {port}: {e}")
            return None

    def read_serial_data(self, ser: serial.Serial, lane_id: int):
        """Read data from serial port and add to queue"""
        while self.running:
            try:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if line:
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        log_entry = f"[{timestamp}] [SERIAL-LANE{lane_id}] {line}"
                        self.log_queue.put(log_entry)
                time.sleep(0.01)  # Small delay to prevent excessive CPU usage
            except Exception as e:
                print(f"Error reading from Lane {lane_id}: {e}")
                break

    def log_writer_thread(self):
        """Write logs to file and display them"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            while self.running:
                try:
                    log_entry = self.log_queue.get(timeout=1)
                    # Write to file
                    f.write(log_entry + '\n')
                    f.flush()
                    
                    # Display to console
                    print(log_entry)
                    
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Error writing log: {e}")

    def start_monitoring(self, ports: List[str] = None):
        """Start monitoring ESP devices"""
        if ports is None:
            ports = self.find_esp_ports()
        
        if not ports:
            print("No ESP32 devices found. Please check connections.")
            return
        
        self.running = True
        threads = []
        
        # Create log file header
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"ESP32 Traffic Light System - Log Session Started\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*80}\n")
        
        # Start log writer thread
        writer_thread = threading.Thread(target=self.log_writer_thread)
        writer_thread.daemon = True
        writer_thread.start()
        threads.append(writer_thread)
        
        # Connect to each ESP and start reading
        for i, port in enumerate(ports[:4]):  # Max 4 lanes
            lane_id = i + 1
            ser = self.connect_to_esp(port, lane_id)
            
            if ser:
                self.serial_connections[lane_id] = ser
                
                # Start reading thread for this ESP
                read_thread = threading.Thread(
                    target=self.read_serial_data, 
                    args=(ser, lane_id)
                )
                read_thread.daemon = True
                read_thread.start()
                threads.append(read_thread)
        
        if not self.serial_connections:
            print("No ESP32 devices connected successfully.")
            return
        
        print(f"\nMonitoring {len(self.serial_connections)} ESP32 devices...")
        print(f"Logs are being written to: {self.log_file}")
        print("Press Ctrl+C to stop monitoring\n")
        
        try:
            # Keep main thread alive
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping monitoring...")
            self.stop_monitoring()

    def stop_monitoring(self):
        """Stop monitoring and close connections"""
        self.running = False
        
        for lane_id, ser in self.serial_connections.items():
            try:
                ser.close()
                print(f"Closed connection to Lane {lane_id}")
            except Exception as e:
                print(f"Error closing Lane {lane_id}: {e}")
        
        self.serial_connections.clear()

    def read_log_file(self, lines: int = 100):
        """Read and display last N lines from log file"""
        if not os.path.exists(self.log_file):
            print(f"Log file {self.log_file} not found.")
            return
        
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                
            if lines > 0:
                display_lines = all_lines[-lines:]
            else:
                display_lines = all_lines
            
            print(f"\n{'='*80}")
            print(f"Displaying last {len(display_lines)} lines from {self.log_file}")
            print(f"{'='*80}")
            
            for line in display_lines:
                print(line.rstrip())
                
        except Exception as e:
            print(f"Error reading log file: {e}")

    def filter_logs(self, keyword: str = None, lane: int = None, log_type: str = None):
        """Filter logs by keyword, lane, or type"""
        if not os.path.exists(self.log_file):
            print(f"Log file {self.log_file} not found.")
            return
        
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            filtered_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Apply filters
                if keyword and keyword.lower() not in line.lower():
                    continue
                
                if lane and f"LANE{lane}" not in line:
                    continue
                
                if log_type and f"[{log_type.upper()}]" not in line:
                    continue
                
                filtered_lines.append(line)
            
            print(f"\n{'='*80}")
            print(f"Filtered logs (found {len(filtered_lines)} matches)")
            if keyword:
                print(f"Keyword: {keyword}")
            if lane:
                print(f"Lane: {lane}")
            if log_type:
                print(f"Type: {log_type}")
            print(f"{'='*80}")
            
            for line in filtered_lines:
                print(line)
                
        except Exception as e:
            print(f"Error filtering logs: {e}")

def main():
    parser = argparse.ArgumentParser(description='ESP32 Traffic Light Log Reader')
    parser.add_argument('-m', '--monitor', action='store_true',
                       help='Start real-time monitoring of ESP devices')
    parser.add_argument('-r', '--read', type=int, default=100,
                       help='Read last N lines from log file (default: 100)')
    parser.add_argument('-f', '--filter', type=str,
                       help='Filter logs by keyword')
    parser.add_argument('-l', '--lane', type=int, choices=[1, 2, 3, 4],
                       help='Filter logs by lane number')
    parser.add_argument('-t', '--type', type=str,
                       help='Filter logs by type (INFO, ERROR, MQTT, SYSTEM, etc.)')
    parser.add_argument('-p', '--ports', nargs='+',
                       help='Specify serial ports manually (e.g., /dev/ttyUSB0 /dev/ttyUSB1)')
    
    args = parser.parse_args()
    
    log_reader = ESPLogReader()
    
    if args.monitor:
        # Real-time monitoring
        log_reader.start_monitoring(args.ports)
    elif args.filter or args.lane or args.type:
        # Filter logs
        log_reader.filter_logs(keyword=args.filter, lane=args.lane, log_type=args.type)
    else:
        # Read log file
        log_reader.read_log_file(args.read)

if __name__ == "__main__":
    main() 