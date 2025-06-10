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
const char *mqtt_client_id = "esp32_traffic_controller_lane1";  // Unique client ID for Lane 1
const char *mqtt_green_status_topic = "traffic/green_status";   // New topic for tracking green status
const char *mqtt_green_request_topic = "traffic/green_request"; // New topic for requesting green light

// NTP Server Settings
const char *ntpServer = "pool.ntp.org";
const long gmtOffset_sec = 25200; // GMT+7 timezone offset in seconds (7*3600)
const int daylightOffset_sec = 0; // No DST offset

// Traffic Light Pin Definitions for Lane 1
const int RED_PIN = 19;    // GPIO19 (D19)
const int YELLOW_PIN = 18; // GPIO18 (D18)
const int GREEN_PIN = 5;   // GPIO5 (D5)

// Lane ID for this ESP
const int LANE_ID = 1;
const int ROAD_SECTION_ID = 1;

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
};

MqttData lastReceivedData = {0, 0, "", false};

// Global variable to track if any section has the green light
int currentGreenSection = 0; // 0 means no section is green
bool greenLightRequested = false;
bool waitingForGreenPermission = false;

// Define light state for this lane
struct TrafficLight
{
    bool red;
    bool yellow;
    bool green;
};

TrafficLight light;

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
    if (strcmp(topic, mqtt_topic) == 0)
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
            lastReceivedData.timestamp = "2025-04-22 10:58:50";
        }
        
        lastReceivedData.new_data = true;

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
            }
            else if (status == "red" && currentGreenSection == section)
            {
                currentGreenSection = 0;
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
            
            // If no one has green light, grant permission
            if (currentGreenSection == 0)
            {
                // Publish permission
                DynamicJsonDocument responseDoc(256);
                responseDoc["section"] = requesting_section;
                responseDoc["permission"] = "granted";
                responseDoc["from_section"] = ROAD_SECTION_ID;
                
                String response;
                serializeJson(responseDoc, response);
                mqtt_client.publish("traffic/green_permission", response.c_str());
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

void setTrafficLight(bool red, bool yellow, bool green)
{
    digitalWrite(RED_PIN, red ? HIGH : LOW);
    digitalWrite(YELLOW_PIN, yellow ? HIGH : LOW);
    digitalWrite(GREEN_PIN, green ? HIGH : LOW);
    
    light.red = red;
    light.yellow = yellow;
    light.green = green;
    
    Serial.print("Lane ");
    Serial.print(LANE_ID);
    Serial.print(" - Light state: ");
    if (red) Serial.print("RED ");
    if (yellow) Serial.print("YELLOW ");
    if (green) Serial.print("GREEN ");
    Serial.println();
}

void allRed()
{
    setTrafficLight(true, false, false);
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
    doc["timestamp"] = "2025-04-22 10:58:50"; // You can implement proper timestamp
    
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
    doc["timestamp"] = "2025-04-22 10:58:50";
    
    String message;
    serializeJson(doc, message);
    mqtt_client.publish(mqtt_green_request_topic, message.c_str());
    
    greenLightRequested = true;
    waitingForGreenPermission = true;
    
    Serial.print("Lane ");
    Serial.print(LANE_ID);
    Serial.println(" requested green light permission");
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
        
        delay(1000);
        mqtt_client.loop(); // Keep MQTT connection alive
    }
}

void publish_duration(float duration)
{
    if (lastReceivedData.new_data)
    {
        DynamicJsonDocument doc(512);
        doc["road_section_id"] = lastReceivedData.road_section_id;
        doc["total_vehicles"] = lastReceivedData.total_vehicles;
        doc["duration"] = duration;
        doc["timestamp"] = lastReceivedData.timestamp;

        String message;
        serializeJson(doc, message);

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
            Serial.println("Failed to publish duration");
        }

        lastReceivedData.new_data = false;
    }
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
    if (lastReceivedData.new_data && vehicleCount > 0)
    {
        // Only proceed if no other section has green light or if we already have it
        if (currentGreenSection == 0 || currentGreenSection == ROAD_SECTION_ID)
        {
            if (currentGreenSection == 0)
            {
                // Request green light permission
                request_green_permission();
                
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
                    return;
                }
            }

            // Calculate green light duration using fuzzy logic
            float duration = defuzzify(vehicleCount, jamSibuk);
            
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Calculated duration: ");
            Serial.print(duration);
            Serial.println(" seconds");

            // Set current section as having green light
            currentGreenSection = ROAD_SECTION_ID;
            publish_green_status("green");

            // Traffic light sequence
            // Red to Off (brief)
            setTrafficLight(false, false, false);
            delay(500);
            
            // Off to Yellow
            setTrafficLight(false, true, false);
            delay(2000);

            // Yellow to Off (brief)
            setTrafficLight(false, false, false);
            delay(500);

            // Off to Green
            setTrafficLight(false, false, true);
            
            // Green light duration with countdown
            countdownTimer((int)duration);

            // Green to Off (brief)
            setTrafficLight(false, false, false);
            delay(500);

            // Off to Red
            setTrafficLight(true, false, false);

            // Publish that green is over
            publish_green_status("red");
            currentGreenSection = 0;

            // Publish the duration data
            publish_duration(duration);

            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.println(" - Traffic light cycle completed");
        }
        else
        {
            Serial.print("Lane ");
            Serial.print(LANE_ID);
            Serial.print(" - Waiting... Section ");
            Serial.print(currentGreenSection);
            Serial.println(" currently has green light");
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