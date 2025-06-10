# Smart Traffic Light System

An intelligent IoT traffic management system that combines computer vision (YOLOv11) with ESP32 microcontrollers and MQTT communication for real-time traffic monitoring and adaptive signal control.

## 🚦 Overview

This project implements a smart traffic light system that uses AI-powered vehicle detection to optimize traffic flow at intersections. The system consists of:

- **Computer Vision Module**: YOLOv11-based vehicle detection from RTSP camera streams
- **ESP32 Controllers**: Hardware controllers for each traffic lane with fuzzy logic decision making
- **MQTT Communication**: Real-time data exchange between components
- **Database Integration**: Traffic data logging and analysis

## 🏗️ System Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   RTSP Camera   │    │   RTSP Camera   │    │   RTSP Camera   │
│     (Lane 1)    │    │     (Lane 2)    │    │     (Lane 3)    │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 │
                    ┌─────────────┴─────────────┐
                    │    Python YOLOv11         │
                    │   Detection Engine        │
                    │  (multi_lane_rtsp_yolo.py)│
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    │      MQTT Broker          │
                    │   (broker.emqx.io)        │
                    └─────────────┬─────────────┘
                                  │
          ┌───────────────────────┼───────────────────────┐
          │                       │                       │
┌─────────┴───────┐    ┌─────────┴───────┐    ┌─────────┴───────┐
│   ESP32 Lane 1  │    │   ESP32 Lane 2  │    │   ESP32 Lane 3  │
│  (Traffic Light)│    │  (Traffic Light)│    │  (Traffic Light)│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 🎯 Key Features

### Computer Vision (Python)
- **Multi-lane Detection**: Simultaneous processing of 4 RTSP camera streams
- **YOLOv11 Integration**: Advanced vehicle detection with custom trained weights
- **Real-time Processing**: Optimized for live video streams with threading
- **Vehicle Classification**: Detects cars, trucks, motorcycles, and buses
- **MQTT Publishing**: Sends vehicle counts and traffic data to ESP32 controllers

### ESP32 Controllers
- **Fuzzy Logic Control**: Intelligent traffic light timing based on vehicle density
- **MQTT Communication**: Receives vehicle data and coordinates with other lanes
- **Traffic Light Control**: Direct control of red, yellow, and green signals
- **Time-based Optimization**: Considers peak hours and traffic patterns
- **Synchronization**: Coordinates timing between multiple lanes

### System Integration
- **Real-time Coordination**: ESP32s communicate to prevent conflicts
- **Database Logging**: Traffic data stored for analysis and optimization
- **Adaptive Timing**: Dynamic green light duration based on traffic density
- **Fault Tolerance**: Robust error handling and reconnection logic

## 📁 Project Structure

```
Smart Traffic Light/
├── Python/                          # Computer vision and AI components
│   ├── multi_lane_rtsp_yolo.py     # Main detection engine
│   ├── requirements.txt             # Python dependencies
│   ├── YOLOv11_trained_weights/    # Custom trained YOLO model
│   ├── rtsp_yolo_detection.py      # Single lane detection
│   └── ...                         # Additional utility scripts
├── esp32_arduino_ide/              # ESP32 Arduino projects
│   ├── esp32_lane1/                # Lane 1 controller
│   ├── esp32_lane2/                # Lane 2 controller
│   ├── esp32_lane3/                # Lane 3 controller
│   ├── esp32_lane4/                # Lane 4 controller
│   └── esp_logger.h                # Shared logging utilities
├── esp1_lane1.cpp                  # Lane 1 ESP32 code
├── esp2_lane2.cpp                  # Lane 2 ESP32 code
├── esp3_lane3.cpp                  # Lane 3 ESP32 code
├── esp4_lane4.cpp                  # Lane 4 ESP32 code
├── connection.cpp                  # Database connection utilities
└── README.md                       # This file
```

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Arduino IDE with ESP32 board support
- ESP32 development boards (4 units)
- RTSP cameras (4 units)
- MQTT broker access (broker.emqx.io used in this project)

### Python Setup

1. **Install Dependencies**:
   ```bash
   cd Python
   pip install -r requirements.txt
   ```

2. **Configure RTSP Streams**:
   Edit `multi_lane_rtsp_yolo.py` and update the RTSP URLs:
   ```python
   rtsp_urls = {
       1: "rtsp://camera1_ip:port/stream",
       2: "rtsp://camera2_ip:port/stream",
       3: "rtsp://camera3_ip:port/stream",
       4: "rtsp://camera4_ip:port/stream"
   }
   ```

3. **Run Detection Engine**:
   ```bash
   python multi_lane_rtsp_yolo.py
   ```

### ESP32 Setup

1. **Install Required Libraries**:
   - PubSubClient (MQTT)
   - ArduinoJson
   - WiFi (built-in)

2. **Configure Network Settings**:
   Update WiFi credentials and MQTT settings in each ESP32 file:
   ```cpp
   const char *ssid = "YOUR_WIFI_SSID";
   const char *password = "YOUR_WIFI_PASSWORD";
   const char *mqtt_broker = "broker.emqx.io";
   ```

3. **Upload to ESP32**:
   - Open the respective `.ino` file in Arduino IDE
   - Select your ESP32 board
   - Upload the code

## 🔧 Configuration

### MQTT Topics

- `traffic/vehicle_count` - Vehicle detection data
- `traffic/duration` - Traffic light timing information
- `traffic/green_status` - Current green light status
- `traffic/green_request` - Green light permission requests

### Traffic Light Pins

Each ESP32 uses the following GPIO pins:
- **Red Light**: GPIO19
- **Yellow Light**: GPIO18  
- **Green Light**: GPIO5

### Fuzzy Logic Parameters

The system uses fuzzy logic for traffic density classification:
- **Low Density**: 0-5 vehicles
- **Medium Density**: 3-10 vehicles
- **High Density**: 5+ vehicles

## 📊 Features in Detail

### Vehicle Detection
- Real-time processing of RTSP streams
- Multi-threaded frame processing for performance
- Vehicle counting and classification
- Confidence threshold filtering

### Traffic Light Control
- Fuzzy logic-based timing decisions
- Peak hour detection and optimization
- Inter-lane coordination to prevent conflicts
- Dynamic green light duration adjustment

### Data Management
- MySQL database integration for traffic logging
- Real-time MQTT communication
- Error handling and reconnection logic
- Performance monitoring and logging

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:
1. Check the existing issues
2. Create a new issue with detailed information
3. Include system logs and error messages

## 🔮 Future Enhancements

- [ ] Web dashboard for real-time monitoring
- [ ] Machine learning-based traffic prediction
- [ ] Integration with city traffic management systems
- [ ] Mobile app for traffic light status
- [ ] Advanced analytics and reporting
