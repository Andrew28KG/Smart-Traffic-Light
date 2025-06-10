#include <iostream>
#include <cmath>
#include <string>
#include <vector>
#include <chrono>
#include <thread>

using namespace std;

// Define light states for simulation
struct TrafficLight
{
    bool red;
    bool yellow;
    bool green;
};

// Array for traffic light states
TrafficLight lights[4];

// Membership Functions for Vehicle Count
float sedikit(float x)
{
    if (x <= 10)
        return 1.0;
    else if (x > 10 && x <= 30)
        return (30 - x) / 20.0;
    else
        return 0.0;
}

float sedang(float x)
{
    if (x <= 10 || x >= 50)
        return 0.0;
    else if (x > 10 && x <= 30)
        return (x - 10) / 20.0;
    else if (x > 30 && x < 50)
        return (50 - x) / 20.0;
    return 0.0;
}

float padat(float x)
{
    if (x <= 30)
        return 0.0;
    else if (x > 30 && x <= 50)
        return (x - 30) / 20.0;
    else
        return 1.0;
}

// Initialize system
void setup()
{
    // Initialize all traffic lights to red
    for (int i = 0; i < 4; i++)
    {
        lights[i].red = true;
        lights[i].yellow = false;
        lights[i].green = false;
    }

    cout << "Sistem Lampu Lalu Lintas Telah Siap" << endl;
}

// Membership function for busy hour (jam sibuk)
bool isJamSibuk(int jam)
{
    // Define busy hours: 7-9 AM and 4-7 PM (rush hours)
    bool sibuk = ((jam >= 7 && jam <= 9) || (jam >= 16 && jam <= 19));

    if (sibuk)
    {
        cout << "Terdeteksi sebagai jam sibuk! Durasi lampu akan lebih panjang." << endl;
    }
    else
    {
        cout << "Terdeteksi sebagai jam normal. Durasi lampu akan lebih pendek." << endl;
    }

    return sibuk;
}

// Set traffic light for a specific lane
void setTrafficLight(int row, bool red, bool yellow, bool green)
{
    int index = row - 1; // Convert from row number (1-4) to array index (0-3)

    lights[index].red = red;
    lights[index].yellow = yellow;
    lights[index].green = green;

    // Display status change
    cout << "Jalur " << row << ": ";
    if (red)
        cout << "MERAH ";
    if (yellow)
        cout << "KUNING ";
    if (green)
        cout << "HIJAU ";
    cout << endl;
}

// Set all traffic lights to red
void allRed()
{
    for (int i = 0; i < 4; i++)
    {
        lights[i].red = true;
        lights[i].yellow = false;
        lights[i].green = false;
    }

    cout << "Semua jalur lampu merah" << endl;
}

// Defuzzification using Centroid Method with fixed crisp values and jam sibuk consideration
float defuzzify(float kendaraan, bool jamSibuk)
{
    // Calculate membership degrees
    float μ_sedikit = sedikit(kendaraan);
    float μ_sedang = sedang(kendaraan);
    float μ_banyak = padat(kendaraan); // Renaming to match your terminology (banyak = padat)

    // Print membership degrees for debugging
    cout << "Derajat Keanggotaan:" << endl;
    cout << "Sedikit: " << μ_sedikit << endl;
    cout << "Sedang: " << μ_sedang << endl;
    cout << "Banyak: " << μ_banyak << endl;
    cout << "Jam Sibuk: " << (jamSibuk ? "Ya" : "Tidak") << endl;

    // Prevent division by zero and add time factor
    if (μ_sedikit + μ_sedang + μ_banyak == 0)
        return jamSibuk ? 55.0 : 25.0; // Default value if all memberships are zero

    // Add time factor adjustment based on jam sibuk
    float timeFactor = jamSibuk ? 1.4 : 0.8; // Increase for busy hour, decrease for normal hours

    // Define base durations with more distinction based on time of day
    float durasi_sedikit = jamSibuk ? 35.0 : 15.0; // Short duration: 15s normal, 35s during busy hour
    float durasi_sedang = jamSibuk ? 55.0 : 30.0;  // Medium duration: 30s normal, 55s during busy hour
    float durasi_padat = jamSibuk ? 90.0 : 50.0;   // Long duration: 50s normal, 90s during busy hour

    // Apply the formula for defuzzification:
    // Durasi Akhir = (μ_sedikit × durasi_sedikit) + (μ_sedang × durasi_sedang) + (μ_padat × durasi_padat) / (μ_sedikit + μ_sedang + μ_padat)
    float numerator = (μ_sedikit * durasi_sedikit) + (μ_sedang * durasi_sedang) + (μ_banyak * durasi_padat);
    float denominator = μ_sedikit + μ_sedang + μ_banyak;

    // Calculate base defuzzified value
    float baseValue = numerator / denominator;

    // Apply time factor to make a clearer distinction between busy and non-busy hours
    float finalValue = baseValue * timeFactor;

    // Output calculation details for debugging
    cout << "Nilai Dasar: " << baseValue << " detik" << endl;
    cout << "Faktor Waktu: " << timeFactor << " (jam " << (jamSibuk ? "sibuk" : "normal") << ")" << endl;
    cout << "Nilai Akhir: " << finalValue << " detik" << endl;

    return finalValue;
}

// Function to simulate the countdown timer with traffic light control
void countdownTimer(int seconds, int row, int totalRows)
{
    cout << "\nMemulai lampu hijau untuk Jalur " << row << " dari " << totalRows << " jalur" << endl;

    // Set current row to green, all others to red
    allRed();
    setTrafficLight(row, false, false, true); // Set green for current row

    for (int i = seconds; i > 0; i--)
    {
        // Switch to yellow light 5 seconds before the end
        if (i == 5)
        {
            setTrafficLight(row, false, true, false); // Set to yellow
            cout << "\n\n*** 5 DETIK TERSISA - SIAPKAN INPUT UNTUK JALUR BERIKUTNYA ***\n"
                 << endl;
        }

        cout << "\rWaktu tersisa: " << i << " detik    ";
        cout.flush();

        // Sleep for 1 second
        this_thread::sleep_for(chrono::seconds(1));
    }

    // Set to red after time is up
    setTrafficLight(row, true, false, false);
    cout << "\rDurasi lampu hijau selesai!                          " << endl;
}

void loop()
{
    const int totalRows = 4;
    int jam;
    vector<float> kendaraanPerRow(totalRows);

    cout << "Masukkan jam (0-23): ";
    cin >> jam;

    // Validate hour input
    if (jam < 0 || jam > 23)
    {
        cout << "Jam harus dalam rentang 0-23!" << endl;
        return;
    }

    // Check if it's busy hour
    bool jamSibuk = isJamSibuk(jam);
    cout << "Status: " << (jamSibuk ? "Jam Sibuk" : "Jam Normal") << endl;

    // Make sure all lights start with red
    allRed();

    // Process each row sequentially
    for (int currentRow = 1; currentRow <= totalRows; currentRow++)
    {
        cout << "\n=== Jalur " << currentRow << " ===\n";

        cout << "Masukkan jumlah kendaraan untuk Jalur " << currentRow << ": ";
        cin >> kendaraanPerRow[currentRow - 1];

        // Validate vehicle count input
        if (kendaraanPerRow[currentRow - 1] < 0)
        {
            cout << "Jumlah kendaraan tidak boleh negatif!" << endl;
            return;
        }

        // Calculate green light duration for this row
        float hasil_durasi = defuzzify(kendaraanPerRow[currentRow - 1], jamSibuk);
        cout << "Durasi Lampu Hijau untuk Jalur " << currentRow << ": " << hasil_durasi << " detik" << endl;

        // Control traffic lights and simulate the countdown
        countdownTimer(static_cast<int>(hasil_durasi), currentRow, totalRows);

        // If this is the last row, we're done
        if (currentRow == totalRows)
        {
            cout << "\nSemua jalur telah diproses." << endl;
        }
    }
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