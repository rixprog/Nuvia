#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SoftwareSerial.h>

// ===============================
// LCD
// ===============================
LiquidCrystal_I2C lcd(0x27, 16, 2);

// ===============================
// HC-05
// Arduino/ATmega328P D10 = RX  (not used)
// Arduino/ATmega328P D11 = TX  → HC-05 RXD
// ===============================
SoftwareSerial HC05(10, 11);

// ===============================
// Pin assignments
// ===============================
const int comp1Pin = 2;   // Upper threshold comparator
const int comp2Pin = 3;   // Lower threshold comparator
const int buzzerPin = 8;  // Buzzer

// ===============================
// Timing variables
// ===============================
unsigned long startTime = 0;
unsigned long duration = 0;
bool measuring = false;

// ===============================
// Breath pattern
// ===============================
char breathPattern[3];
int breathCount = 0;

String lastWord = "******";

// ===============================
// Idle timeout
// ===============================
unsigned long lastUpdateTime = 0;
const unsigned long idleTimeout = 5000;


// =====================================================
// Interpret the 3-breath Morse-like pattern
// =====================================================
String interpretPattern()
{
  String pattern = "";

  for (int i = 0; i < 3; i++)
  {
    pattern += breathPattern[i];
  }

  if (pattern == ".-.")
    return "FOOD";

  else if (pattern == ".--")
    return "WATER";

  else if (pattern == "---")
    return "EMERGENCY";

  else if (pattern == "-.-")
    return "TOILET";

  else if (pattern == "--.")
    return "MEDICINE";

  else if (pattern == "...")
    return "YES";

  else if (pattern == "-..")
    return "NO";

  else
    return "******";
}


// =====================================================
// Update LCD
// =====================================================
void updateLCD(String line2)
{
  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print("RespTalk-(BCAI)");

  lcd.setCursor(0, 1);
  lcd.print(line2);
}


// =====================================================
// Setup
// =====================================================
void setup()
{
  // Debug serial
  Serial.begin(9600);

  // HC-05 serial
  HC05.begin(9600);

  // Comparator inputs
  pinMode(comp1Pin, INPUT);
  pinMode(comp2Pin, INPUT);

  // Buzzer
  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);

  // LCD
  lcd.init();
  lcd.backlight();

  updateLCD(lastWord);

  Serial.println("RespTalk started...");
}


// =====================================================
// Main loop
// =====================================================
void loop()
{
  int comp1 = digitalRead(comp1Pin);
  int comp2 = digitalRead(comp2Pin);


  // ===================================================
  // Start measuring when comparator 1 goes HIGH
  // ===================================================
  if (comp1 == HIGH && !measuring)
  {
    measuring = true;
    startTime = millis();
  }


  // ===================================================
  // Stop measuring when comparator 2 goes LOW
  // ===================================================
  if (measuring && comp2 == LOW)
  {
    duration = millis() - startTime;
    measuring = false;

    char breathType;

    // Short breath
    if (duration < 1000)
    {
      breathType = '.';

      Serial.println("Short breath (.)");
    }

    // Long breath
    else
    {
      breathType = '-';

      Serial.println("Long breath (-)");
    }


    // =================================================
    // Store breath pattern
    // =================================================
    breathPattern[breathCount] = breathType;
    breathCount++;


    // =================================================
    // Show partial pattern on LCD
    // =================================================
    String partialPattern = "";

    for (int i = 0; i < breathCount; i++)
    {
      partialPattern += breathPattern[i];
    }

    updateLCD(partialPattern);


    // =================================================
    // Three breaths completed
    // =================================================
    if (breathCount == 3)
    {
      String word = interpretPattern();

      Serial.print("Recognized: ");
      Serial.println(word);


      // ===============================================
      // Valid command
      // ===============================================
      if (word != "******")
      {
        lastWord = word;

        updateLCD(lastWord);

        lastUpdateTime = millis();

        // Buzzer
        digitalWrite(buzzerPin, HIGH);


        // =============================================
        // TRANSMIT THROUGH HC-05
        // =============================================
        HC05.println(word);

        Serial.print("Bluetooth TX: ");
        Serial.println(word);
      }


      // ===============================================
      // Invalid command
      // ===============================================
      else
      {
        digitalWrite(buzzerPin, LOW);

        updateLCD("******");
      }


      // Reset for next 3-breath pattern
      breathCount = 0;
    }
  }


  // ===================================================
  // Idle timeout
  // ===================================================
  if (millis() - lastUpdateTime > idleTimeout &&
      lastWord != "******")
  {
    lastWord = "******";

    updateLCD(lastWord);

    digitalWrite(buzzerPin, LOW);
  }


  delay(1);
}
