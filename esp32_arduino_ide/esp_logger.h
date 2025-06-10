#ifndef ESP_LOGGER_H
#define ESP_LOGGER_H

#include <WiFi.h>
#include <FS.h>
#include <SPIFFS.h>
#include <ArduinoJson.h>
#include <time.h>

// Log file settings
const char* LOG_FILE = "/log.txt";
const int MAX_LOG_SIZE = 1024 * 1024; // 1MB max log size
const int MAX_LOG_LINES = 1000; // Maximum lines to keep

// Log levels
enum LogLevel {
    LOG_DEBUG = 0,
    LOG_INFO = 1,
    LOG_WARNING = 2,
    LOG_ERROR = 3,
    LOG_MQTT = 4,
    LOG_SYSTEM = 5
};

// Initialize logging system
bool initLogger() {
    if (!SPIFFS.begin(true)) {
        Serial.println("Failed to mount SPIFFS");
        return false;
    }
    
    // Check if log file exists, create if not
    if (!SPIFFS.exists(LOG_FILE)) {
        File file = SPIFFS.open(LOG_FILE, FILE_WRITE);
        if (file) {
            file.println("=== ESP Traffic Light System Log Started ===");
            file.close();
        } else {
            Serial.println("Failed to create log file");
            return false;
        }
    }
    
    return true;
}

// Get current timestamp as string
String getLogTimestamp() {
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo)) {
        return String(millis()) + "ms"; // Fallback to millis if NTP not available
    }
    
    char buffer[64];
    strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", &timeinfo);
    return String(buffer);
}

// Get log level string
String getLogLevelString(LogLevel level) {
    switch (level) {
        case LOG_DEBUG: return "DEBUG";
        case LOG_INFO: return "INFO";
        case LOG_WARNING: return "WARNING";
        case LOG_ERROR: return "ERROR";
        case LOG_MQTT: return "MQTT";
        case LOG_SYSTEM: return "SYSTEM";
        default: return "UNKNOWN";
    }
}

// Check and rotate log if it's too large
void rotateLogIfNeeded() {
    File file = SPIFFS.open(LOG_FILE, FILE_READ);
    if (!file) return;
    
    size_t fileSize = file.size();
    file.close();
    
    if (fileSize > MAX_LOG_SIZE) {
        // Create backup and truncate
        SPIFFS.remove("/log_old.txt");
        SPIFFS.rename(LOG_FILE, "/log_old.txt");
        
        File newFile = SPIFFS.open(LOG_FILE, FILE_WRITE);
        if (newFile) {
            newFile.println("=== Log rotated - Previous log saved as log_old.txt ===");
            newFile.println("=== ESP Traffic Light System Log Continued ===");
            newFile.close();
        }
    }
}

// Core logging function
void writeToLog(LogLevel level, int laneId, String message) {
    rotateLogIfNeeded();
    
    File file = SPIFFS.open(LOG_FILE, FILE_APPEND);
    if (!file) {
        Serial.println("Failed to open log file for writing");
        return;
    }
    
    String timestamp = getLogTimestamp();
    String logLevel = getLogLevelString(level);
    String logEntry = "[" + timestamp + "] [LANE" + String(laneId) + "] [" + logLevel + "] " + message;
    
    // Write to file
    file.println(logEntry);
    file.close();
    
    // Also print to serial for immediate debugging
    Serial.println(logEntry);
}

// Convenience logging functions
void logDebug(int laneId, String message) {
    writeToLog(LOG_DEBUG, laneId, message);
}

void logInfo(int laneId, String message) {
    writeToLog(LOG_INFO, laneId, message);
}

void logWarning(int laneId, String message) {
    writeToLog(LOG_WARNING, laneId, message);
}

void logError(int laneId, String message) {
    writeToLog(LOG_ERROR, laneId, message);
}

void logMqtt(int laneId, String topic, String message, bool isIncoming = true) {
    String direction = isIncoming ? "RECEIVED" : "SENT";
    String logMessage = direction + " - Topic: " + topic + " | Message: " + message;
    writeToLog(LOG_MQTT, laneId, logMessage);
}

void logSystem(int laneId, String message) {
    writeToLog(LOG_SYSTEM, laneId, message);
}

// Log vehicle count data
void logVehicleCount(int laneId, int totalVehicles, float duration) {
    String message = "Vehicle Count: " + String(totalVehicles) + " | Duration: " + String(duration) + "s";
    writeToLog(LOG_INFO, laneId, message);
}

// Log traffic light state changes
void logTrafficLightState(int laneId, String state, String reason = "") {
    String message = "Traffic Light: " + state;
    if (reason.length() > 0) {
        message += " | Reason: " + reason;
    }
    writeToLog(LOG_INFO, laneId, message);
}

// Log countdown sync events
void logCountdownSync(int laneId, int remainingSeconds, String phase, String source) {
    String message = "Countdown Sync - Phase: " + phase + " | Remaining: " + String(remainingSeconds) + "s | Source: " + source;
    writeToLog(LOG_SYSTEM, laneId, message);
}

// Log WiFi connection events
void logWiFiStatus(int laneId, String status, String details = "") {
    String message = "WiFi Status: " + status;
    if (details.length() > 0) {
        message += " | " + details;
    }
    writeToLog(LOG_SYSTEM, laneId, message);
}

// Log MQTT connection events
void logMqttStatus(int laneId, String status, String details = "") {
    String message = "MQTT Status: " + status;
    if (details.length() > 0) {
        message += " | " + details;
    }
    writeToLog(LOG_SYSTEM, laneId, message);
}

// Log fuzzy logic calculations
void logFuzzyCalculation(int laneId, float vehicleCount, bool jamSibuk, float duration) {
    String message = "Fuzzy Logic - Vehicles: " + String(vehicleCount) + 
                    " | Rush Hour: " + (jamSibuk ? "Yes" : "No") + 
                    " | Calculated Duration: " + String(duration) + "s";
    writeToLog(LOG_DEBUG, laneId, message);
}

// Log green light permission requests and grants
void logGreenLightRequest(int laneId, String action, String details = "") {
    String message = "Green Light " + action;
    if (details.length() > 0) {
        message += " | " + details;
    }
    writeToLog(LOG_INFO, laneId, message);
}

// Read and display log file content (for debugging)
void printLogFile() {
    File file = SPIFFS.open(LOG_FILE, FILE_READ);
    if (!file) {
        Serial.println("Failed to open log file for reading");
        return;
    }
    
    Serial.println("=== LOG FILE CONTENT ===");
    while (file.available()) {
        Serial.write(file.read());
    }
    Serial.println("=== END OF LOG FILE ===");
    file.close();
}

// Clear log file
void clearLog(int laneId) {
    SPIFFS.remove(LOG_FILE);
    File file = SPIFFS.open(LOG_FILE, FILE_WRITE);
    if (file) {
        file.println("=== ESP Traffic Light System Log Cleared ===");
        file.close();
        logSystem(laneId, "Log file cleared by user request");
    }
}

// Get log file statistics
void logFileStats(int laneId) {
    File file = SPIFFS.open(LOG_FILE, FILE_READ);
    if (!file) {
        logError(laneId, "Cannot access log file for statistics");
        return;
    }
    
    size_t fileSize = file.size();
    int lineCount = 0;
    
    while (file.available()) {
        if (file.read() == '\n') {
            lineCount++;
        }
    }
    file.close();
    
    String stats = "Log Statistics - Size: " + String(fileSize) + " bytes | Lines: " + String(lineCount);
    logSystem(laneId, stats);
}

#endif // ESP_LOGGER_H 