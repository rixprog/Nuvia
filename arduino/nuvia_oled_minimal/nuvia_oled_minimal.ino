#include <Wire.h>

// CHANGED: OLED instead of LiquidCrystal_I2C
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ADDED: Software Serial for HC-05
#include <SoftwareSerial.h>

// CHANGED: SSD1306 128x64 OLED (address auto-detected, 0x3C or 0x3D)
#define SCREEN_W 128
#define SCREEN_H 64
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
bool haveDisplay = false;

// ADDED: HC-05 SoftwareSerial
// Arduino D10 = RX (not connected)
// Arduino D11 = TX -> HC-05 RX
SoftwareSerial bluetooth(10, 11);

// Pin assignments
const int comp1Pin = 2;   // Upper threshold comparator
const int comp2Pin = 3;   // Lower threshold comparator
const int buzzerPin = 8;  // Buzzer pin

// ADDED: Analog input
const int adcPin = A0;

// ADDED: ADC sampling timing
// 10 ms = 100 samples/second
unsigned long lastAdcTime = 0;
const unsigned long adcInterval = 10;

// Timing variables
unsigned long startTime = 0;
unsigned long duration = 0;
bool measuring = false;

// Breath pattern storage
char breathPattern[3];     // stores '.', '-' pattern
int breathCount = 0;       // current breath index
// CHANGED: char* instead of String. Strings allocate on the heap, and the
// OLED framebuffer already takes 1024 of the Uno's 2048 bytes - with String
// the sketch compiles but has ~36 bytes left and corrupts at runtime.
const char *lastWord = "******";

// Idle timeout
unsigned long lastUpdateTime = 0;
const unsigned long idleTimeout = 5000; // 5 seconds

// Interpret Morse-like pattern
static bool patternIs(const char *p) {
  return breathPattern[0] == p[0] &&
         breathPattern[1] == p[1] &&
         breathPattern[2] == p[2];
}

const char *interpretPattern() {
  if (patternIs(".-.")) return "FOOD";
  else if (patternIs(".--")) return "WATER";
  else if (patternIs("---")) return "EMERGENCY";
  else if (patternIs("-.-")) return "TOILET";
  else if (patternIs("--.")) return "MEDICINE";
  else if (patternIs("...")) return "YES";
  else if (patternIs("-..")) return "NO";
  else return "******"; // Unknown
}


// =========================================================
// ADDED: OLED drawing helpers
// =========================================================

void centerText(const char *s, int16_t y, uint8_t size) {
  display.setTextSize(size);
  display.setTextColor(SSD1306_WHITE);
  int16_t w = (int16_t)strlen(s) * 6 * size;
  display.setCursor((SCREEN_W - w) / 2, y);
  display.print(s);
}

// Title bar with three slots showing progress through the 3-breath sequence
void drawHeader() {
  display.fillRect(0, 0, SCREEN_W, 11, SSD1306_WHITE);
  display.setTextSize(1);
  display.setTextColor(SSD1306_BLACK);
  display.setCursor(3, 2);
  display.print(F("Nuvia"));

  for (int i = 0; i < 3; i++) {
    int16_t sx = 84 + i * 14;
    if (i < breathCount) {
      if (breathPattern[i] == '.') display.fillRect(sx + 4, 3, 4, 5, SSD1306_BLACK);
      else                         display.fillRect(sx, 4, 11, 3, SSD1306_BLACK);
    } else {
      display.drawRect(sx, 3, 11, 5, SSD1306_BLACK);
    }
  }
}

// 28x28 icons drawn with primitives, so they use no RAM
void iconFood(int16_t x, int16_t y) {
  int16_t cx = x + 14;
  display.fillCircle(cx, y + 16, 12, SSD1306_WHITE);
  display.fillRect(x, y, 28, 16, SSD1306_BLACK);
  display.fillRect(cx - 13, y + 14, 26, 3, SSD1306_WHITE);
  for (int i = -1; i < 2; i++)
    display.fillRect(cx + i * 7 - 1, y + 1, 2, 9, SSD1306_WHITE);
}

void iconWater(int16_t x, int16_t y) {
  int16_t cx = x + 14;
  display.fillTriangle(cx, y + 1, x + 5, y + 18, x + 23, y + 18, SSD1306_WHITE);
  display.fillCircle(cx, y + 18, 9, SSD1306_WHITE);
}

void iconEmergency(int16_t x, int16_t y) {
  int16_t cx = x + 14;
  display.drawTriangle(cx, y + 1, x + 1, y + 26, x + 27, y + 26, SSD1306_WHITE);
  display.drawTriangle(cx, y + 3, x + 3, y + 25, x + 25, y + 25, SSD1306_WHITE);
  display.fillRect(cx - 1, y + 11, 3, 8, SSD1306_WHITE);
  display.fillRect(cx - 1, y + 21, 3, 3, SSD1306_WHITE);
}

void iconToilet(int16_t x, int16_t y) {
  display.fillRect(x + 3, y + 3, 6, 12, SSD1306_WHITE);
  display.fillRoundRect(x + 9, y + 8, 16, 10, 4, SSD1306_WHITE);
  display.fillRect(x + 13, y + 18, 7, 6, SSD1306_WHITE);
  display.fillRect(x + 9, y + 24, 15, 3, SSD1306_WHITE);
}

void iconMedicine(int16_t x, int16_t y) {
  display.fillRoundRect(x + 1, y + 9, 26, 11, 5, SSD1306_WHITE);
  display.fillRect(x + 14, y + 10, 12, 9, SSD1306_BLACK);
  display.drawRoundRect(x + 1, y + 9, 26, 11, 5, SSD1306_WHITE);
  display.drawFastVLine(x + 14, y + 9, 11, SSD1306_WHITE);
}

void iconYes(int16_t x, int16_t y) {
  for (int t = 0; t < 3; t++) {
    display.drawLine(x + 4,  y + 14 + t, x + 11, y + 21 + t, SSD1306_WHITE);
    display.drawLine(x + 11, y + 21 + t, x + 24, y + 7 + t,  SSD1306_WHITE);
  }
}

void iconNo(int16_t x, int16_t y) {
  for (int t = 0; t < 3; t++) {
    display.drawLine(x + 5 + t,  y + 7, x + 22 + t, y + 24, SSD1306_WHITE);
    display.drawLine(x + 22 - t, y + 7, x + 5 - t,  y + 24, SSD1306_WHITE);
  }
}

void drawIcon(const char *w, int16_t x, int16_t y) {
  if      (!strcmp(w, "FOOD"))      iconFood(x, y);
  else if (!strcmp(w, "WATER"))     iconWater(x, y);
  else if (!strcmp(w, "EMERGENCY")) iconEmergency(x, y);
  else if (!strcmp(w, "TOILET"))    iconToilet(x, y);
  else if (!strcmp(w, "MEDICINE"))  iconMedicine(x, y);
  else if (!strcmp(w, "YES"))       iconYes(x, y);
  else if (!strcmp(w, "NO"))        iconNo(x, y);
}

// Draw a partial pattern as large dot/dash glyphs. As font characters the
// dots sit on the baseline and read as specks.
void drawBigPattern(const char *pattern, int16_t y) {
  for (int i = 0; pattern[i]; i++) {
    int16_t x = 15 + i * 36;
    if (pattern[i] == '.') display.fillCircle(x + 13, y + 5, 5, SSD1306_WHITE);
    else                   display.fillRect(x, y + 2, 26, 6, SSD1306_WHITE);
  }
}

static bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}


// CHANGED: same signature and call sites as updateLCD, but renders one of
// three screens depending on what it is handed - idle, a partial pattern,
// or a recognised word.
void updateLCD(const char *line2) {
  if (!haveDisplay) return;

  display.clearDisplay();
  drawHeader();

  if (!strcmp(line2, "******")) {
    // Idle / unrecognised
    centerText("- - -", 26, 2);
    centerText("breathe to speak", 50, 1);

  } else if (line2[0] == '.' || line2[0] == '-') {
    // A pattern still being entered
    centerText("listening", 18, 1);
    drawBigPattern(line2, 34);

  } else {
    // A recognised word
    drawIcon(line2, 50, 13);
    centerText(line2, 44, 2);
  }

  display.display();
}


void setup() {
  Serial.begin(9600);

  // HC-05
  bluetooth.begin(9600);

  pinMode(comp1Pin, INPUT);
  pinMode(comp2Pin, INPUT);
  pinMode(buzzerPin, OUTPUT);

  digitalWrite(buzzerPin, LOW);

  // CHANGED: OLED init instead of lcd.init()/lcd.backlight().
  // begin() returns true even with no panel attached, so probe the bus first
  // - otherwise a module at 0x3D just stays blank with no error.
  Wire.begin();
  Wire.setClock(400000);
  uint8_t addr = i2cPresent(0x3C) ? 0x3C : (i2cPresent(0x3D) ? 0x3D : 0);
  haveDisplay = addr && display.begin(SSD1306_SWITCHCAPVCC, addr);

  if (haveDisplay) {
    display.clearDisplay();
    centerText("Nuvia", 18, 2);
    centerText("BCAI", 42, 1);
    display.display();
    delay(1200);
  } else {
    // A missing screen must not take the device down with it - the buzzer
    // and Bluetooth still work without a display.
    Serial.println(F("No OLED found on 0x3C or 0x3D"));
  }

  updateLCD(lastWord);

  Serial.println(F("Breath detection started..."));

  bluetooth.println(F("Nuvia Bluetooth Started"));
}

void loop() {

  // =========================================================
  // RAW A0 SAMPLING
  // 100 Hz = one sample every 10 ms
  // =========================================================

  if (millis() - lastAdcTime >= adcInterval) {

    lastAdcTime = millis();

    // Read raw ADC value from A0
    int adcValue = analogRead(A0);

    // Send RAW ADC value through HC-05
    bluetooth.print(F("ADC:"));
    bluetooth.println(adcValue);

    // Also print to USB Serial Monitor
    Serial.print(F("ADC:"));
    Serial.println(adcValue);
  }


  int comp1 = digitalRead(comp1Pin);  // upper threshold
  int comp2 = digitalRead(comp2Pin);  // lower threshold

  // Start measuring when comparator 1 goes HIGH
  if (comp1 == HIGH && !measuring) {
    measuring = true;
    startTime = millis();
  }

  // Stop measuring when comparator 2 goes LOW
  if (measuring && comp2 == LOW) {
    duration = millis() - startTime;
    measuring = false;

    Serial.print(F("duration : "));
    Serial.println(duration);

    char breathType;

    if (duration < 1000) {
      breathType = '.';
      Serial.println(F("Short breath (.)"));

      // Bluetooth short breath
      bluetooth.println(F("BREATH:."));

    } else {
      breathType = '-';
      Serial.println(F("Long breath (-)"));

      // Bluetooth deep/long breath represented as _
      bluetooth.println(F("BREATH:_"));
    }

    // Store pattern
    breathPattern[breathCount] = breathType;
    breathCount++;

    // Build partial pattern string for the display
    char partialPattern[4];
    for (int i = 0; i < breathCount; i++)
      partialPattern[i] = breathPattern[i];
    partialPattern[breathCount] = '\0';

    updateLCD(partialPattern); // show pattern as it builds

    // Once 3 breaths are done, interpret pattern
    if (breathCount == 3) {

      const char *word = interpretPattern();

      Serial.print(F("Recognized: "));
      Serial.println(word);

      lastWord = word;
      updateLCD(lastWord);
      lastUpdateTime = millis();

      // Build Bluetooth breath array
      char bluetoothPattern[4];

      for (int i = 0; i < 3; i++) {
        bluetoothPattern[i] = (breathPattern[i] == '.') ? '.' : '_';
      }
      bluetoothPattern[3] = '\0';

      // Send pattern
      bluetooth.print(F("PATTERN:"));
      bluetooth.println(bluetoothPattern);

      if (strcmp(word, "******") != 0) {

        bluetooth.print(F("COMMAND:"));
        bluetooth.println(word);

      } else {

        bluetooth.println(F("COMMAND:NILL"));
      }

      // Buzzer ON only for valid commands
      if (strcmp(word, "******") != 0)
        digitalWrite(buzzerPin, HIGH);
      else
        digitalWrite(buzzerPin, LOW);

      breathCount = 0;
    }
  }

  // Idle timeout
  if (millis() - lastUpdateTime > idleTimeout && strcmp(lastWord, "******") != 0) {

    lastWord = "******";
    updateLCD(lastWord);
    digitalWrite(buzzerPin, LOW);
  }

  delay(1);
}
