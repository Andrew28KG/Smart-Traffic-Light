#include <iostream>
#include <cmath>
#include <string>
#include <vector>
#include <chrono>
#include <thread>
#include <WiFi.h> // For ESP32 (use ESP8266WiFi.h for ESP8266)
#include <PubSubClient.h>
#include <ArduinoJson.h> // Add JSON library for parsing
#include <time.h>        // Include time library for NTP

using namespace std;

// WiFi settings
const char *ssid = "PSS";         // Replace with your WiFi SSID
const char *password = "S3rpong!"; // Replace with your WiFi password

// MQTT settings
const char *mqtt_broker = "broker.emqx.io";
const int mqtt_port = 1883;
const char *mqtt_topic = "traffic/vehicle_count";
const char *mqtt_duration_topic = "traffic/duration";           // New topic for publishing duration
const char *mqtt_countdown_sync_topic = "traffic/countdown_sync"; // NEW: Topic for countdown synchronization
const char *mqtt_client_id = "esp32_traffic_controller_lane3";  // Unique client ID for Lane 3
const char *mqtt_green_status_topic = "traffic/green_status";   // New topic for tracking green status
const char *mqtt_green_request_topic = "traffic/green_request"; // New topic for requesting green light
const char *mqtt_reset_topic = "traffic/reset"; // New topic for resetting all data and states

// NTP Server Settings
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 25200; // GMT+7 timezone offset in seconds (7*3600)
const int daylightOffset_sec = 0; // No DST offset

// Traffic Light Pin Definitions for Lane 3
const int RED_PIN = 19;    // GPIO19 (D19)
const int YELLOW_PIN = 18; // GPIO18 (D18)
const int GREEN_PIN = 5;   // GPIO5 (D5)

// Lane ID for this ESP
const int LANE_ID = 3;
const int ROAD_SECTION_ID = 3;

WiFiClient espClient;
PubSubClient mqtt_client(espClient);

// Store vehicle count for this lane
float vehicleCount = 0;

// Store last received MQTT data
struct MqttData
{
    int road_section_id;
    int total_vehicles;
    String timestamp;
    bool new_data;
    bool duration_published;
    bool green_request_sent; // Track if green request was already sent for this data
    unsigned long data_received_time; // When this ESP received the data
};

MqttData lastReceivedData = {0, 0, "", false, false, false, 0};

// Global variable to track if any section has the green light
int currentGreenSection = 0; // 0 means no section is green
bool greenLightRequested = false;
bool waitingForGreenPermission = false;

// Circular queue for traffic light ordering
int nextExpectedSection = 1; // Always start with section 1
int getNextSection(int current) {
    return (current % 4) + 1; // 1->2->3->4->1
}

// Define light state for this lane
struct TrafficLight
{
    bool red;
    bool yellow;
    bool green;
};

TrafficLight light;

// Function declarations
void publish_countdown_sync(int remaining_seconds, String phase = "green");

// Membership Functions for Vehicle Count
float sedikit(float x)
{
    if (x <= 3)
        return 1.0;
    else if (x > 3 && x < 5)
        return (5 - x) / 2.0;
    else
        return 0.0;
}

float sedang(float x)
{
    if (x <= 3 || x >= 10)
        return 0.0;
    else if (x > 3 && x <= 5)
        return (x - 3) / 2.0;
    else if (x > 5 && x < 10)
        return (10 - x) / 5.0;
    return 0.0;
}

float padat(float x)
{
    if (x <= 5)
        return 0.0;
    else if (x > 5 && x < 10)
        return (x - 5) / 5.0;
    else
        return 1.0;
}

// MQTT message callback
void mqtt_callback(char *topic, uint8_t *payload, unsigned int length)
{
    Serial.print("Message arrived [");
    Serial.print(topic);
    Serial.print("] ");

    // Convert payload to string
    String message;
    for (int i = 0; i < length; i++)
    {
        message += (char)payload[i];
    }
    Serial.println(message);

    // Check which topic the message came from
    if (strcmp(topic, mqtt_countdown_sync_topic) == 0)
    {
        // Handle countdown sync messages from Python
        message.replace("'", "\"");
        DynamicJsonDocument doc(1024);
        DeserializationError error = deserializeJson(doc, message);
        
        if (!error && doc.containsKey("lane_id") && doc.containsKey("remaining_seconds"))
        {
            int sync_lane = doc["lane_id"];
            int python_remaining = doc["remaining_seconds"];
            String source = doc["source"].as<String>();
            
            // Only sync if this is for our lane and from Python
            if (sync_lane == LANE_ID && source == "python")
            {
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.print(" - SYNC: Python reports ");
                Serial.print(python_remaining);
                Serial.println("s remaining");
                
                // Note: ESP doesn't need to adjust its countdown since it's hardware-based
                // This is mainly for monitoring and debugging sync status
            }
        }
    }
    else if (strcmp(topic, mqtt_topic) == 0)
    {
        // Handle vehicle count data - only process if it's for this lane
        message.replace("'", "\"");
        Serial.print("Converted JSON: ");
        Serial.println(message);

        // Parse JSON message
        DynamicJsonDocument doc(1024);
        DeserializationError error = deserializeJson(doc, message);

        if (error)
        {
            Serial.print("deserializeJson() failed: ");
            Serial.println(error.c_str());
            return;
        }

        // Extract road section ID
        int road_section_id = doc["road_section_id"];

        // Only process if this message is for our lane
        if (road_section_id != ROAD_SECTION_ID)
        {
            return; // Ignore messages for other lanes
        }

        // Calculate total vehicles
        int total_vehicles = 0;
        if (doc.containsKey("total_vehicles"))
        {
            total_vehicles = doc["total_vehicles"];
        }
        else if (doc.containsKey("vehicle_counts"))
        {
            JsonObject vehicle_counts = doc["vehicle_counts"];
            for (JsonPair kv : vehicle_counts)
            {
                total_vehicles += kv.value().as<int>();
            }
        }

        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Total Vehicles: ");
        Serial.println(total_vehicles);

        // Get timestamp from message
        String msgTimestamp = "";
        if (doc.containsKey("timestamp"))
        {
            msgTimestamp = doc["timestamp"].as<String>();
        }
        
        // Check if message is too old (more than 5 minutes)
        if (!msgTimestamp.isEmpty())
        {
            // Get current timestamp
            String currentTimestamp = getCurrentTimestamp();
            
            // Simple check: if timestamps differ significantly, reject old messages
            // Extract hour and minute from both timestamps for comparison
            int msgHour = 0, msgMin = 0, currentHour = 0, currentMin = 0;
            
            // Parse message timestamp (format: "YYYY-MM-DD HH:MM:SS")
            if (msgTimestamp.length() >= 16)
            {
                msgHour = msgTimestamp.substring(11, 13).toInt();
                msgMin = msgTimestamp.substring(14, 16).toInt();
            }
            
            // Parse current timestamp
            if (currentTimestamp.length() >= 16)
            {
                currentHour = currentTimestamp.substring(11, 13).toInt();
                currentMin = currentTimestamp.substring(14, 16).toInt();
            }
            
            // Calculate time difference in minutes
            int timeDiffMinutes = (currentHour * 60 + currentMin) - (msgHour * 60 + msgMin);
            
            // Handle day rollover (rough approximation)
            if (timeDiffMinutes < 0) timeDiffMinutes += 24 * 60;
            
            // Reject messages older than 2 minutes
            if (timeDiffMinutes > 2)
            {
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.print(" - Ignoring old message (");
                Serial.print(timeDiffMinutes);
                Serial.print(" minutes old): ");
                Serial.println(msgTimestamp);
                return;
            }
        }
        
        // Check if this is duplicate data (same vehicle count, road section, and timestamp)
        bool isDuplicateData = (lastReceivedData.total_vehicles == total_vehicles && 
                               lastReceivedData.road_section_id == road_section_id &&
                               lastReceivedData.timestamp == msgTimestamp &&
                               lastReceivedData.new_data);
        
        if (isDuplicateData)
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Ignoring duplicate/retained MQTT message");
            return; // Skip processing duplicate data
        }
        
        // Store data for this lane
        vehicleCount = total_vehicles;
        lastReceivedData.road_section_id = road_section_id;
        lastReceivedData.total_vehicles = total_vehicles;
        
        if (doc.containsKey("timestamp"))
        {
            lastReceivedData.timestamp = doc["timestamp"].as<String>();
        }
        else
        {
            lastReceivedData.timestamp = getCurrentTimestamp();
        }
        
        lastReceivedData.new_data = true;
        lastReceivedData.duration_published = false;
        lastReceivedData.green_request_sent = false; // Reset green request flag for new data
        lastReceivedData.data_received_time = millis(); // Record when data was received

        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.println(" data updated!");
    }
    else if (strcmp(topic, mqtt_green_status_topic) == 0)
    {
        // Handle green status updates from other lanes
        DynamicJsonDocument doc(256);
        DeserializationError error = deserializeJson(doc, message);
        
        if (!error && doc.containsKey("section") && doc.containsKey("status"))
        {
            int section = doc["section"];
            String status = doc["status"].as<String>();
            
            if (status == "green")
            {
                currentGreenSection = section;
                Serial.print("Section ");
                Serial.print(section);
                Serial.println(" is now GREEN");
            }
            else if (status == "red" && currentGreenSection == section)
            {
                currentGreenSection = 0;
                nextExpectedSection = getNextSection(section);
                Serial.print("Section ");
                Serial.print(section);
                Serial.print(" is now RED - Next expected section: ");
                Serial.println(nextExpectedSection);
            }
        }
    }
    else if (strcmp(topic, mqtt_green_request_topic) == 0)
    {
        // Handle green light requests from other lanes
        DynamicJsonDocument doc(256);
        DeserializationError error = deserializeJson(doc, message);
        
        if (!error && doc.containsKey("section"))
        {
            int requesting_section = doc["section"];
            unsigned long requesting_time = 0;
            
            if (doc.containsKey("data_received_time"))
            {
                requesting_time = doc["data_received_time"];
            }
            
            // If no one has green light and it's the requesting section's turn, grant permission
            if (currentGreenSection == 0)
            {
                bool should_grant = (requesting_section == nextExpectedSection);
                
                // If this ESP also has pending data and it's not our turn, deny
                if (lastReceivedData.new_data && vehicleCount > 0 && ROAD_SECTION_ID == nextExpectedSection)
                {
                    should_grant = false;
                    Serial.print("Lane ");
                    Serial.print(LANE_ID);
                    Serial.print(" - Denying permission to section ");
                    Serial.print(requesting_section);
                    Serial.print(" (it's our turn, next expected: ");
                    Serial.print(nextExpectedSection);
                    Serial.println(")");
                }
                
                if (should_grant)
                {
                    // Publish permission
                    DynamicJsonDocument responseDoc(256);
                    responseDoc["section"] = requesting_section;
                    responseDoc["permission"] = "granted";
                    responseDoc["from_section"] = ROAD_SECTION_ID;
                    
                    String response;
                    serializeJson(responseDoc, response);
                    mqtt_client.publish("traffic/green_permission", response.c_str());
                    
                    Serial.print("Lane ");
                    Serial.print(LANE_ID);
                    Serial.print(" - Granted permission to section ");
                    Serial.print(requesting_section);
                    Serial.print(" (expected: ");
                    Serial.print(nextExpectedSection);
                    Serial.println(")");
                }
                else if (requesting_section != nextExpectedSection)
                {
                    Serial.print("Lane ");
                    Serial.print(LANE_ID);
                    Serial.print(" - Denying permission to section ");
                    Serial.print(requesting_section);
                    Serial.print(" (not their turn, expected: ");
                    Serial.print(nextExpectedSection);
                    Serial.println(")");
                }
            }
        }
    }
    else if (strcmp(topic, "traffic/green_permission") == 0)
    {
        // Handle green light permission responses
        DynamicJsonDocument doc(256);
        DeserializationError error = deserializeJson(doc, message);
        
        if (!error && doc.containsKey("section") && doc.containsKey("permission"))
        {
            int permitted_section = doc["section"];
            String permission = doc["permission"].as<String>();
            
            // Check if this permission is for our section
            if (permitted_section == ROAD_SECTION_ID && permission == "granted")
            {
                waitingForGreenPermission = false;
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.println(" - Green light permission granted!");
            }
        }
    }
    else if (strcmp(topic, mqtt_reset_topic) == 0)
    {
        // Handle reset command
        String resetCommand = message;
        resetCommand.trim();
        resetCommand.toLowerCase();
        
        if (resetCommand == "true" || resetCommand == "1" || resetCommand == "reset")
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - RESET command received!");
            resetAllData();
        }
        else
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Invalid reset command: ");
            Serial.println(resetCommand);
        }
    }
    else if (strcmp(topic, "traffic/next_lane_ready") == 0)
    {
        // Handle next lane ready notification
        DynamicJsonDocument doc(256);
        DeserializationError error = deserializeJson(doc, message);
        
        if (!error && doc.containsKey("next_expected_section"))
        {
            int nextExpected = doc["next_expected_section"];
            int fromLane = doc.containsKey("from_lane") ? doc["from_lane"] : 0;
            
            // Update our next expected section
            nextExpectedSection = nextExpected;
            
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Next lane notification from Lane ");
            Serial.print(fromLane);
            Serial.print(". Next expected: ");
            Serial.print(nextExpectedSection);
            Serial.print(", Our ID: ");
            Serial.print(ROAD_SECTION_ID);
            Serial.print(", Match: ");
            Serial.println(ROAD_SECTION_ID == nextExpectedSection ? "YES" : "NO");
            
            // If we are the next expected lane, trigger immediate processing regardless of vehicle data
            if (ROAD_SECTION_ID == nextExpectedSection)
            {
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.println(" - We're next! Triggering immediate activation");
                
                // Force trigger the cycle regardless of existing data status
                lastReceivedData.new_data = true;
                lastReceivedData.duration_published = false;
                lastReceivedData.green_request_sent = false;
                lastReceivedData.data_received_time = millis();
                
                // If we don't have recent vehicle data, use zero count
                if (vehicleCount < 0) {
                    vehicleCount = 0;
                }
                
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.print(" - Forced activation with vehicle count: ");
                Serial.println(vehicleCount);
            }
        }
        else
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Invalid next_lane_ready message received");
        }
    }
}

void setup_wifi()
{
    delay(10);
    Serial.println();
    Serial.print("Connecting to ");
    Serial.println(ssid);

    WiFi.begin(ssid, password);

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        Serial.print(".");
    }

    Serial.println("");
    Serial.println("WiFi connected");
    Serial.println("IP address: ");
    Serial.println(WiFi.localIP());

    // Configure time
    configTime(gmtOffset_sec, daylightOffset_sec, ntpServer);
    Serial.println("Time configured");

    // Wait for time to be set
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
    {
        Serial.println("Failed to obtain time");
        return;
    }
    Serial.println("Time obtained successfully");
}

void connect_mqtt()
{
    while (!mqtt_client.connected())
    {
        Serial.print("Attempting MQTT connection...");
        if (mqtt_client.connect(mqtt_client_id))
        {
            Serial.println("connected");
            Serial.println("Subscribing to topics:");
            
            if (mqtt_client.subscribe(mqtt_topic)) {
                Serial.println("  ✓ " + String(mqtt_topic));
            } else {
                Serial.println("  ✗ Failed: " + String(mqtt_topic));
            }
            
            if (mqtt_client.subscribe(mqtt_countdown_sync_topic)) {
                Serial.println("  ✓ " + String(mqtt_countdown_sync_topic));
            } else {
                Serial.println("  ✗ Failed: " + String(mqtt_countdown_sync_topic));
            }
            
            if (mqtt_client.subscribe(mqtt_green_status_topic)) {
                Serial.println("  ✓ " + String(mqtt_green_status_topic));
            } else {
                Serial.println("  ✗ Failed: " + String(mqtt_green_status_topic));
            }
            
            if (mqtt_client.subscribe(mqtt_green_request_topic)) {
                Serial.println("  ✓ " + String(mqtt_green_request_topic));
            } else {
                Serial.println("  ✗ Failed: " + String(mqtt_green_request_topic));
            }
            
            if (mqtt_client.subscribe("traffic/green_permission")) {
                Serial.println("  ✓ traffic/green_permission");
            } else {
                Serial.println("  ✗ Failed: traffic/green_permission");
            }
            
            if (mqtt_client.subscribe(mqtt_reset_topic)) {
                Serial.println("  ✓ " + String(mqtt_reset_topic));
            } else {
                Serial.println("  ✗ Failed: " + String(mqtt_reset_topic));
            }
            
            if (mqtt_client.subscribe("traffic/next_lane_ready")) {
                Serial.println("  ✓ traffic/next_lane_ready");
            } else {
                Serial.println("  ✗ Failed: traffic/next_lane_ready");
            }
            
            Serial.println("Lane " + String(LANE_ID) + " ready to receive MQTT messages!");
        }
        else
        {
            Serial.print("failed, rc=");
            Serial.print(mqtt_client.state());
            Serial.println(" try again in 5 seconds");
            delay(5000);
        }
    }
}

void testTrafficLights()
{
    Serial.println("Testing traffic lights for Lane " + String(LANE_ID) + "...");
    
    // Test Red
    digitalWrite(RED_PIN, HIGH);
    digitalWrite(YELLOW_PIN, LOW);
    digitalWrite(GREEN_PIN, LOW);
    Serial.println("Red ON");
    delay(2000);

    // Test Yellow
    digitalWrite(RED_PIN, LOW);
    digitalWrite(YELLOW_PIN, HIGH);
    digitalWrite(GREEN_PIN, LOW);
    Serial.println("Yellow ON");
    delay(2000);

    // Test Green
    digitalWrite(RED_PIN, LOW);
    digitalWrite(YELLOW_PIN, LOW);
    digitalWrite(GREEN_PIN, HIGH);
    Serial.println("Green ON");
    delay(2000);

    // Back to Red (default)
    digitalWrite(RED_PIN, HIGH);
    digitalWrite(YELLOW_PIN, LOW);
    digitalWrite(GREEN_PIN, LOW);
    Serial.println("Back to Red");
}

void setup()
{
    Serial.begin(115200);
    Serial.println("ESP32 Traffic Light Controller - Lane " + String(LANE_ID));

    // Initialize traffic light pins
    pinMode(RED_PIN, OUTPUT);
    pinMode(YELLOW_PIN, OUTPUT);
    pinMode(GREEN_PIN, OUTPUT);

    // Set initial state to red
    digitalWrite(RED_PIN, HIGH);
    digitalWrite(YELLOW_PIN, LOW);
    digitalWrite(GREEN_PIN, LOW);

    // Initialize light state
    light.red = true;
    light.yellow = false;
    light.green = false;

    setup_wifi();
    mqtt_client.setServer(mqtt_broker, mqtt_port);
    mqtt_client.setCallback(mqtt_callback);

    testTrafficLights();
    Serial.println("Setup completed for Lane " + String(LANE_ID));
}

bool isJamSibuk(int jam)
{
    return (jam >= 7 && jam <= 9) || (jam >= 17 && jam <= 19);
}

String getCurrentTimestamp()
{
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
    {
        return "1970-01-01 00:00:00"; // Fallback if time not available
    }
    
    char timeStr[20];
    strftime(timeStr, sizeof(timeStr), "%Y-%m-%d %H:%M:%S", &timeinfo);
    return String(timeStr);
}

void setTrafficLight(bool red, bool yellow, bool green)
{
    digitalWrite(RED_PIN, red ? HIGH : LOW);
    digitalWrite(YELLOW_PIN, yellow ? HIGH : LOW);
    digitalWrite(GREEN_PIN, green ? HIGH : LOW);
    
    light.red = red;
    light.yellow = yellow;
    light.green = green;
    
    // Removed repetitive light state logging to prevent spam
    // Serial.print("Lane ");
    // Serial.print(LANE_ID);
    // Serial.print(" - Light state: ");
    // if (red) Serial.print("RED ");
    // if (yellow) Serial.print("YELLOW ");
    // if (green) Serial.print("GREEN ");
    // Serial.println();
}

void allRed()
{
    setTrafficLight(true, false, false);
}

void resetAllData()
{
    Serial.print("Lane ");
    Serial.print(LANE_ID);
    Serial.println(" - RESET: Clearing all data and states");
    
    // Reset vehicle count
    vehicleCount = 0;
    
    // Reset MQTT data structure
    lastReceivedData.road_section_id = 0;
    lastReceivedData.total_vehicles = 0;
    lastReceivedData.timestamp = "";
    lastReceivedData.new_data = false;
    lastReceivedData.duration_published = false;
    lastReceivedData.green_request_sent = false;
    lastReceivedData.data_received_time = 0;
    
    // Reset green light coordination variables
    currentGreenSection = 0;
    greenLightRequested = false;
    waitingForGreenPermission = false;
    nextExpectedSection = 1; // Reset to starting sequence
    
    // Set traffic light to red
    allRed();
    
    Serial.print("Lane ");
    Serial.print(LANE_ID);
    Serial.println(" - RESET: All data and states cleared successfully");
}

float defuzzify(float kendaraan, bool jamSibuk)
{
    float mu_sedikit = sedikit(kendaraan);
    float mu_sedang = sedang(kendaraan);
    float mu_padat = padat(kendaraan);

    float durasi_pendek, durasi_sedang, durasi_lama;

    if (jamSibuk)
    {
        durasi_pendek = 15.0;
        durasi_sedang = 30.0;
        durasi_lama = 60.0;
    }
    else
    {
        durasi_pendek = 10.0;
        durasi_sedang = 20.0;
        durasi_lama = 40.0;
    }

    float numerator = (mu_sedikit * durasi_pendek) + (mu_sedang * durasi_sedang) + (mu_padat * durasi_lama);
    float denominator = mu_sedikit + mu_sedang + mu_padat;

    if (denominator == 0)
    {
        return jamSibuk ? 30.0 : 20.0;
    }

    return numerator / denominator;
}

void publish_green_status(String status)
{
    DynamicJsonDocument doc(256);
    doc["section"] = ROAD_SECTION_ID;
    doc["status"] = status;
    doc["timestamp"] = getCurrentTimestamp();
    
    String message;
    serializeJson(doc, message);
    mqtt_client.publish(mqtt_green_status_topic, message.c_str());
    
    Serial.print("Published green status for Lane ");
    Serial.print(LANE_ID);
    Serial.print(": ");
    Serial.println(status);
}

void request_green_permission()
{
    DynamicJsonDocument doc(256);
    doc["section"] = ROAD_SECTION_ID;
    doc["timestamp"] = getCurrentTimestamp();
    doc["data_received_time"] = lastReceivedData.data_received_time; // Include timing for priority
    
    String message;
    serializeJson(doc, message);
    mqtt_client.publish(mqtt_green_request_topic, message.c_str());
    
    greenLightRequested = true;
    waitingForGreenPermission = true;
    
    Serial.print("Lane ");
    Serial.print(LANE_ID);
    Serial.print(" requested green light permission with priority timestamp: ");
    Serial.println(lastReceivedData.data_received_time);
}

void publish_countdown_sync(int remaining_seconds, String phase)
{
    // NEW: Publish countdown sync message to help Python stay synchronized
    DynamicJsonDocument doc(512);
    doc["lane_id"] = LANE_ID;
    doc["remaining_seconds"] = remaining_seconds;
    doc["phase"] = phase;
    doc["timestamp"] = millis() / 1000;  // Use millis for timestamp
    doc["source"] = "esp";

    String message;
    serializeJson(doc, message);

    // Ensure MQTT connection is active
    if (!mqtt_client.connected())
    {
        connect_mqtt();
    }

    if (mqtt_client.publish(mqtt_countdown_sync_topic, message.c_str()))
    {
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Published countdown sync: ");
        Serial.print(remaining_seconds);
        Serial.println("s remaining");
    }
}

void countdownTimer(int seconds)
{
    for (int i = seconds; i > 0; i--)
    {
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Countdown: ");
        Serial.print(i);
        Serial.println(" seconds remaining");
        
        // NEW: Publish countdown sync every 2 seconds to help Python stay synchronized
        if (i % 2 == 0 || i <= 3)  // Every 2 seconds, or every second for last 3 seconds
        {
            publish_countdown_sync(i, "green");
        }
        
        delay(1000);
        mqtt_client.loop(); // Keep MQTT connection alive
    }
}

void publish_duration(float duration)
{
    // Always publish duration when called, regardless of new_data flag
    DynamicJsonDocument doc(512);
    doc["road_section_id"] = lastReceivedData.road_section_id;
    doc["total_vehicles"] = lastReceivedData.total_vehicles;
    doc["duration"] = duration;
    doc["timestamp"] = lastReceivedData.timestamp;

    String message;
    serializeJson(doc, message);

    // Ensure MQTT connection is active
    if (!mqtt_client.connected())
    {
        connect_mqtt();
    }

    if (mqtt_client.publish(mqtt_duration_topic, message.c_str()))
    {
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Published duration: ");
        Serial.print(duration);
        Serial.println(" seconds");
    }
    else
    {
        Serial.println("Failed to publish duration - retrying...");
        delay(100);
        // Retry once
        if (mqtt_client.publish(mqtt_duration_topic, message.c_str()))
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Duration published on retry");
        }
        else
        {
            Serial.println("Duration publish failed after retry");
        }
    }

    // Do NOT reset new_data flag here - let it be reset only after traffic light sequence completes
}

void loop()
{
    if (!mqtt_client.connected())
    {
        connect_mqtt();
    }
    mqtt_client.loop();

    // Get current time
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
    {
        Serial.println("Failed to obtain time");
        delay(1000);
        return;
    }

    int currentHour = timeinfo.tm_hour;
    bool jamSibuk = isJamSibuk(currentHour);

            // Check if we have new data for our lane
    // Also add timeout to prevent processing old retained messages indefinitely
    unsigned long dataAge = millis() - lastReceivedData.data_received_time;
    bool dataTimeout = dataAge > 120000; // 2 minutes timeout
    
    if (dataTimeout)
    {
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.println(" - Data timeout reached, resetting flags");
        lastReceivedData.new_data = false;
        lastReceivedData.duration_published = false;
        lastReceivedData.green_request_sent = false;
    }
    
    if (lastReceivedData.new_data)
    {
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Processing new data: vehicles=");
        Serial.print(vehicleCount);
        Serial.print(", currentGreenSection=");
        Serial.println(currentGreenSection);
        
        // Calculate green light duration using fuzzy logic (always calculate for traffic light control)
        float duration = defuzzify(vehicleCount, jamSibuk);
        
        Serial.print("Lane ");
        Serial.print(LANE_ID);
        Serial.print(" - Calculated duration: ");
        Serial.print(duration);
        Serial.println(" seconds");

        // Publish duration only once per vehicle count message
        if (!lastReceivedData.duration_published)
        {
            // Always publish the duration data immediately after calculation
            publish_duration(duration);
            lastReceivedData.duration_published = true;
        }
        
                                                  // Only proceed with traffic light control if we have vehicles, no other section has green light,
         // it's our turn in the sequence, and we haven't already sent a request for this data
         if (vehicleCount > 0 && currentGreenSection == 0 && ROAD_SECTION_ID == nextExpectedSection && !lastReceivedData.green_request_sent)
             {
                 Serial.print("Lane ");
                 Serial.print(LANE_ID);
                 Serial.print(" - It's our turn! Requesting green light! Expected: ");
                 Serial.print(nextExpectedSection);
                 Serial.print(", Our ID: ");
                 Serial.println(ROAD_SECTION_ID);
                
                // Immediately claim the green section to prevent race conditions
                currentGreenSection = ROAD_SECTION_ID;
            
                            // Request green light permission
                request_green_permission();
                lastReceivedData.green_request_sent = true; // Mark that we've sent the request
            
            // Wait for permission (timeout after 5 seconds)
            unsigned long startTime = millis();
            while (waitingForGreenPermission && (millis() - startTime < 5000))
            {
                mqtt_client.loop();
                delay(100);
            }
            
            if (waitingForGreenPermission)
            {
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.println(" - Timeout waiting for permission");
                waitingForGreenPermission = false;
                // Release the green section claim on timeout
                currentGreenSection = 0;
                // Don't reset new_data flag on timeout - allow it to try again later
                return;
            }
            
            // Double-check that we still hold the green section claim
            if (currentGreenSection != ROAD_SECTION_ID)
            {
                Serial.print("Lane ");
                Serial.print(LANE_ID);
                Serial.print(" - Lost green section claim while waiting. Section ");
                Serial.print(currentGreenSection);
                Serial.println(" is now green.");
                // Don't reset new_data flag - allow it to try again when other section finishes
                return;
            }

            // Traffic light sequence
            // Start with all red (ensure only one green light at a time)
            setTrafficLight(true, false, false);
            delay(1000);
            
            // Red to Yellow (prepare for green)
            setTrafficLight(false, true, false);
            delay(3000); // Yellow preparation phase for 3 seconds

            // Yellow to Green
            setTrafficLight(false, false, true);
            
            // NOW publish green status when light is actually green
            publish_green_status("green");
            
            // Green light duration with countdown
            countdownTimer((int)duration);

            // Green to Yellow (proper transition)
            setTrafficLight(false, true, false);
            
            // IMPORTANT: When entering yellow state, immediately advance to next lane
            // and notify next lane to publish their duration if they have data waiting
            int nextLaneInSequence = getNextSection(ROAD_SECTION_ID);
            nextExpectedSection = nextLaneInSequence;
            
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Entered YELLOW state. Next expected lane: ");
            Serial.println(nextExpectedSection);
            
            // Publish notification that next lane should activate if it has vehicles
            DynamicJsonDocument nextLaneDoc(256);
            nextLaneDoc["next_expected_section"] = nextExpectedSection;
            nextLaneDoc["from_lane"] = LANE_ID;
            nextLaneDoc["message"] = "yellow_state_entered";
            
            String nextLaneMessage;
            serializeJson(nextLaneDoc, nextLaneMessage);
            mqtt_client.publish("traffic/next_lane_ready", nextLaneMessage.c_str());
            
            delay(3000); // Yellow phase for 3 seconds

            // Yellow to Red
            setTrafficLight(true, false, false);

            // Publish that green is over and clear current section
            publish_green_status("red");
            currentGreenSection = 0;

            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Traffic light cycle completed");
            
            // Reset new_data flag only after completing the full traffic light sequence
            lastReceivedData.new_data = false;
            lastReceivedData.duration_published = false;
            lastReceivedData.green_request_sent = false;
        }
        else if (vehicleCount > 0 && currentGreenSection != 0)
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Waiting... Section ");
            Serial.print(currentGreenSection);
            Serial.println(" currently has green light");
            
            // Don't reset the new_data flag - keep it for when the other section finishes
        }
        else if (vehicleCount > 0 && ROAD_SECTION_ID != nextExpectedSection)
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Not our turn yet. Expected: ");
            Serial.print(nextExpectedSection);
            Serial.print(", Our ID: ");
            Serial.println(ROAD_SECTION_ID);
            
            // Don't reset the new_data flag - keep it for when it's our turn
        }
        else if (vehicleCount == 0 && currentGreenSection == 0 && ROAD_SECTION_ID == nextExpectedSection && !lastReceivedData.green_request_sent)
        {
            // Process the countdown even when vehicle count is 0, since fuzzy still returns duration
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - No vehicles, but still running traffic light sequence");
            
            // Immediately claim the green section to prevent race conditions
            currentGreenSection = ROAD_SECTION_ID;
            lastReceivedData.green_request_sent = true; // Mark that we've processed this data

            // Traffic light sequence (same as vehicleCount > 0 case)
            // Start with all red (ensure only one green light at a time)
            setTrafficLight(true, false, false);
            delay(1000);
            
            // Red to Yellow (prepare for green)
            setTrafficLight(false, true, false);
            delay(3000); // Yellow preparation phase for 3 seconds

            // Yellow to Green
            setTrafficLight(false, false, true);
            
            // NOW publish green status when light is actually green
            publish_green_status("green");
            
            // Green light duration with countdown
            countdownTimer((int)duration);

            // Green to Yellow (proper transition)
            setTrafficLight(false, true, false);
            
            // IMPORTANT: When entering yellow state, immediately advance to next lane
            // and notify next lane to publish their duration if they have data waiting
            int nextLaneInSequence = getNextSection(ROAD_SECTION_ID);
            nextExpectedSection = nextLaneInSequence;
            
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Entered YELLOW state. Next expected lane: ");
            Serial.println(nextExpectedSection);
            
            // Publish notification that next lane should activate if it has vehicles
            DynamicJsonDocument nextLaneDoc(256);
            nextLaneDoc["next_expected_section"] = nextExpectedSection;
            nextLaneDoc["from_lane"] = LANE_ID;
            nextLaneDoc["message"] = "yellow_state_entered";
            
            String nextLaneMessage;
            serializeJson(nextLaneDoc, nextLaneMessage);
            mqtt_client.publish("traffic/next_lane_ready", nextLaneMessage.c_str());
            
            delay(3000); // Yellow phase for 3 seconds

            // Yellow to Red
            setTrafficLight(true, false, false);

            // Publish that green is over and clear current section
            publish_green_status("red");
            currentGreenSection = 0;

            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Traffic light cycle completed (zero vehicles)");
            
            // Reset new_data flag only after completing the full traffic light sequence
            lastReceivedData.new_data = false;
            lastReceivedData.duration_published = false;
            lastReceivedData.green_request_sent = false;
        }
        else
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - No vehicles or other condition not met, resetting data flag");
            
            // Reset new_data flag for zero vehicle case since no traffic light sequence needed
            lastReceivedData.new_data = false;
            lastReceivedData.duration_published = false;
            lastReceivedData.green_request_sent = false;
        }
    }
    else
    {
        // Keep red light on when no vehicle data
        allRed();
    }

    delay(1000);
}

int main()
{
    setup();
    while (true)
    {
        loop();
    }
    return 0;
} 