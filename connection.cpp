#include "Credentials.h"

#include <ESP32_MySQL.h>

#define ESP32_MYSQL_DEBUG_PORT Serial

// Debug Level from 0 to 4
#define _ESP32_MYSQL_LOGLEVEL_ 1

#define USING_HOST_NAME true

#if USING_HOST_NAME
// Optional using hostname
char server[] = "api-traffic-light.apotekbless.my.id";
#else
IPAddress server(153, 92, 15, 3);
#endif

uint16_t server_port = 3306;

char default_database[] = "u190944248_traffic_light";
char default_table[] = "road_sections";

String SELECT_column = "Name";
String WHERE_column = "is_active";
String default_value = "0";

String query = String("SELECT ") + SELECT_column + " FROM " + default_database + "." + default_table + " WHERE " + WHERE_column + " = '" + 0 + "';";

ESP32_MySQL_Connection conn((Client *)&client);

// Create an instance of the cursor passing in the connection
ESP32_MySQL_Query sql_query = ESP32_MySQL_Query(&conn);

void setup()
{
    Serial.begin(115200);
    while (!Serial && millis() < 5000)
        ; // wait for serial port to connect

    ESP32_MYSQL_DISPLAY1("\nStarting Basic_Insert_ESP on", ARDUINO_BOARD);

    // Begin WiFi section
    ESP32_MYSQL_DISPLAY1("Connecting to", ssid);

    WiFi.begin(ssid, pass);

    while (WiFi.status() != WL_CONNECTED)
    {
        delay(500);
        ESP32_MYSQL_DISPLAY0(".");
    }

    // print out info about the connection:
    ESP32_MYSQL_DISPLAY1("Connected to network. My IP address is:", WiFi.localIP());

    ESP32_MYSQL_DISPLAY3("Connecting to SQL Server @", server, ", Port =", server_port);
    ESP32_MYSQL_DISPLAY5("User =", user, ", PW =", password, ", DB =", default_database);
}

void runQuery()
{

    ESP32_MySQL_Query query_mem = ESP32_MySQL_Query(&conn);

    // Execute the query
    ESP32_MYSQL_DISPLAY(query);

    if (!query_mem.execute(query.c_str()))
    {
        ESP32_MYSQL_DISPLAY("Querying error");
        return;
    }

    // Fetch the columns and print them
    column_names *cols = query_mem.get_columns();

    for (int f = 0; f < cols->num_fields; f++)
    {
        ESP32_MYSQL_DISPLAY0(cols->fields[f]->name);

        if (f < cols->num_fields - 1)
        {
            ESP32_MYSQL_DISPLAY0(",");
        }
    }
    ESP32_MYSQL_DISPLAY("\n--------------------");

    // Read the rows and print them
    row_values *row = NULL;

    do
    {
        row = query_mem.get_next_row();

        if (row != NULL)
        {
            for (int f = 0; f < cols->num_fields; f++)
            {
                ESP32_MYSQL_DISPLAY0(row->values[f]);
                if (f < cols->num_fields - 1)
                {
                    ESP32_MYSQL_DISPLAY0(",");
                }
            }

            ESP32_MYSQL_DISPLAY();
        }
    } while (row != NULL);

    delay(500);
}

void loop()
{
    ESP32_MYSQL_DISPLAY("Connecting...");

    // if (conn.connect(server, server_port, user, password))
    if (conn.connectNonBlocking(server, server_port, user, password) != RESULT_FAIL)
    {
        delay(500);
        runQuery();
        conn.close();
    }
    else
    {
        ESP32_MYSQL_DISPLAY("\nConnect failed. Trying again on next iteration.");
    }

    ESP32_MYSQL_DISPLAY("\nSleeping...");
    ESP32_MYSQL_DISPLAY("================================================");

    delay(10000);
}
