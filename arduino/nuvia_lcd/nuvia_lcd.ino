#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// ADDED: Software Serial for HC-05
#include <SoftwareSerial.h>

// Create LCD object. The address is auto-detected in setup() - these modules
// ship as either 0x27 or 0x3F and there is no way to tell by looking.
LiquidCrystal_I2C lcd(0x27, 16, 2);
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
const char *lastWord = "******"; // last displayed word

// Idle timeout
unsigned long lastUpdateTime = 0;
const unsigned long idleTimeout = 5000; // 5 seconds


// =========================================================
// ADDED: custom characters
// A 16x2 has 8 slots of user-definable 5x8 glyphs in CGRAM.
// '.' and '-' as ordinary text sit on the baseline and read as
// specks; these are drawn to be legible at a glance.
// =========================================================
const uint8_t GLYPH_DOT   = 0;
const uint8_t GLYPH_DASH  = 1;
const uint8_t GLYPH_EMPTY = 2;
const uint8_t GLYPH_ALERT = 3;

const uint8_t dotGlyph[8] PROGMEM = {
  0b00000, 0b00000, 0b01110, 0b01110,
  0b01110, 0b00000, 0b00000, 0b00000
};

const uint8_t dashGlyph[8] PROGMEM = {
  0b00000, 0b00000, 0b00000, 0b11111,
  0b11111, 0b00000, 0b00000, 0b00000
};

const uint8_t emptyGlyph[8] PROGMEM = {
  0b00000, 0b00000, 0b00000, 0b00000,
  0b00000, 0b00000, 0b11111, 0b00000
};

const uint8_t alertGlyph[8] PROGMEM = {
  0b00100, 0b01110, 0b01110, 0b01110,
  0b11111, 0b00000, 0b00100, 0b00000
};

void loadGlyph(uint8_t slot, const uint8_t *src) {
  uint8_t buf[8];
  for (uint8_t i = 0; i < 8; i++) buf[i] = pgm_read_byte(&src[i]);
  lcd.createChar(slot, buf);
}


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


static bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

// Row 0 right-hand side: three slots showing progress through the sequence,
// so the user can see how many breaths have registered without counting.
void drawSlots() {
  lcd.setCursor(13, 0);
  for (int i = 0; i < 3; i++) {
    if (i < breathCount)
      lcd.write(breathPattern[i] == '.' ? GLYPH_DOT : GLYPH_DASH);
    else
      lcd.write(GLYPH_EMPTY);
  }
}

// Centre a string on row 1.
void centerRow1(const char *text) {
  int len = strlen(text);
  if (len > 16) len = 16;
  int pad = (16 - len) / 2;
  lcd.setCursor(pad, 1);
  for (int i = 0; i < len; i++) lcd.print(text[i]);
}


// Same name and call sites as before. Renders one of three states depending
// on what it is handed: idle, a partial pattern, or a recognised word.
void updateLCD(const char *line2) {
  if (!haveDisplay) return;

  lcd.clear();

  lcd.setCursor(0, 0);
  lcd.print(F("Nuvia"));
  drawSlots();

  if (!strcmp(line2, "******")) {
    centerRow1("breathe to speak");

  } else if (line2[0] == '.' || line2[0] == '-') {
    // Mid-pattern. The slots already show what has been entered, so row 1
    // just confirms the device is still listening.
    centerRow1("listening...");

  } else if (!strcmp(line2, "EMERGENCY")) {
    // The one word worth making unmistakable.
    lcd.setCursor(1, 1);
    lcd.write(GLYPH_ALERT);
    lcd.print(F(" EMERGENCY "));
    lcd.write(GLYPH_ALERT);

  } else {
    centerRow1(line2);
  }
}


void setup() {
  Serial.begin(9600);

  // HC-05
  bluetooth.begin(9600);

  pinMode(comp1Pin, INPUT);
  pinMode(comp2Pin, INPUT);
  pinMode(buzzerPin, OUTPUT);

  digitalWrite(buzzerPin, LOW);

  // These backpacks ship as 0x27 or 0x3F; probe rather than guess.
  Wire.begin();
  uint8_t addr = i2cPresent(0x27) ? 0x27 : (i2cPresent(0x3F) ? 0x3F : 0);

  if (addr) {
    lcd = LiquidCrystal_I2C(addr, 16, 2);
    lcd.init();
    lcd.backlight();
    haveDisplay = true;

    loadGlyph(GLYPH_DOT,   dotGlyph);
    loadGlyph(GLYPH_DASH,  dashGlyph);
    loadGlyph(GLYPH_EMPTY, emptyGlyph);
    loadGlyph(GLYPH_ALERT, alertGlyph);

    lcd.setCursor(0, 0);
    lcd.print(F("Nuvia-(BCAI)"));
    lcd.setCursor(4, 1);
    lcd.print(F("starting"));
    delay(1000);

    Serial.print(F("LCD at 0x"));
    Serial.println(addr, HEX);
  } else {
    // A missing screen must not take the device down with it - the buzzer
    // and Bluetooth still work without a display.
    Serial.println(F("No LCD on 0x27 or 0x3F - running headless"));
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
