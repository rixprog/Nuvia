/*
 * RespTalk (BCAI) - OLED edition
 * =======================================================================
 * Three breaths form a Morse-like pattern that resolves to a word, shown on
 * an SSD1306 OLED and sent over Bluetooth.
 *
 * HARDWARE
 *   SSD1306 128x64 I2C   -> A4 (SDA), A5 (SCL), addr 0x3C or 0x3D
 *   Comparator 1 (upper) -> D2   (INT0)
 *   Comparator 2 (lower) -> D3   (INT1)
 *   Buzzer               -> D8
 *   Piezo/LM324 analog   -> A0
 *   HC-05                -> D11 (SoftwareSerial) and/or D1 (hardware TX)
 *
 * LIBRARIES: Adafruit GFX, Adafruit SSD1306 (Library Manager).
 *
 * WIRE FORMAT - unchanged from your version:
 *   ADC:<0-1023>      100 Hz raw analog          (hardware Serial only)
 *   BREATH:.          short breath
 *   BREATH:_          long breath
 *   PATTERN:.._       the completed three-breath pattern
 *   COMMAND:<word>    recognised word, or COMMAND:NILL
 *
 * WHY THE ADC STREAM IS NOT ON SoftwareSerial
 * SoftwareSerial bit-bangs with interrupts disabled: "ADC:512\r\n" is 9 bytes
 * = 9.4 ms blocked, every 10 ms. That starves millis(), which then runs slow,
 * which made the real sample rate 210-417 Hz instead of 100 and corrupted
 * every breath duration. Hardware Serial is interrupt-driven and buffered, so
 * it costs almost nothing. The low-rate BREATH/PATTERN/COMMAND lines still go
 * to both links.
 *
 * If your HC-05 is wired to D11 you will not receive ADC over Bluetooth. Move
 * it to D0/D1 for calibration, or read the ADC stream over USB.
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <SoftwareSerial.h>

// Set to 0 if the HC-05 is on hardware serial (D0/D1); saves ~117 bytes of
// RAM, which matters because the display buffer is another 1024.
#define USE_SOFTSERIAL 1

// ===============================
// Display
// ===============================
#define SCREEN_W 128
#define SCREEN_H 64

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
bool haveDisplay = false;

#if USE_SOFTSERIAL
SoftwareSerial bluetooth(10, 11);
#endif

// ===============================
// Pins
// ===============================
const uint8_t comp1Pin  = 2;
const uint8_t comp2Pin  = 3;
const uint8_t buzzerPin = 8;
const uint8_t adcPin    = A0;

// ===============================
// Tuning
// ===============================
const unsigned long ADC_INTERVAL_MS  = 10;    // 100 Hz raw stream
const unsigned long LONG_BREATH_MS   = 1000;  // >= this is a dash
const unsigned long MIN_BREATH_MS    = 50;    // shorter than this is a glitch
const unsigned long PATTERN_TIMEOUT_MS = 4000;// max gap between breaths
const unsigned long IDLE_TIMEOUT_MS  = 5000;  // how long a word stays up
const unsigned long METER_FULL_MS    = 2000;  // full scale of the live meter
const unsigned long BEEP_MS          = 150;
const unsigned long FRAME_MS         = 50;    // ~20 fps

// ===============================
// State
// ===============================
enum WordId : uint8_t {
  W_NONE = 0, W_FOOD, W_WATER, W_EMERGENCY, W_TOILET, W_MEDICINE, W_YES, W_NO
};

char    breathPattern[3];
uint8_t breathCount = 0;

// Breath timing lives in the ISRs. display.display() pushes 1024 bytes over
// I2C and blocks for ~25 ms; polling the comparators would go blind for that
// whole window. Edge interrupts capture the timestamps regardless.
volatile bool          breathActive = false;
volatile unsigned long breathStart  = 0;
volatile unsigned long breathLen    = 0;
volatile bool          breathReady  = false;

WordId        lastWord       = W_NONE;
bool          showUnknown    = false;
unsigned long lastUpdateTime = 0;
unsigned long lastBreathTime = 0;
unsigned long beepUntil      = 0;
unsigned long lastFrame      = 0;
unsigned long lastAdcTime    = 0;
uint8_t       wavePhase      = 0;
int           lastAdc        = 0;

// One cycle of a sine, +-12 px, for the idle respiration trace.
const int8_t WAVE[32] PROGMEM = {
   0,  2,  5,  7,  8, 10, 11, 12, 12, 12, 11, 10,  8,  7,  5,  2,
   0, -2, -5, -7, -8,-10,-11,-12,-12,-12,-11,-10, -8, -7, -5, -2
};


// =====================================================
// Pattern -> word
// =====================================================
static bool patternIs(const char *p)
{
  return breathPattern[0] == p[0] &&
         breathPattern[1] == p[1] &&
         breathPattern[2] == p[2];
}

WordId interpretPattern()
{
  if (patternIs(".-.")) return W_FOOD;
  if (patternIs(".--")) return W_WATER;
  if (patternIs("---")) return W_EMERGENCY;
  if (patternIs("-.-")) return W_TOILET;
  if (patternIs("--.")) return W_MEDICINE;
  if (patternIs("...")) return W_YES;
  if (patternIs("-..")) return W_NO;
  return W_NONE;
}

const char *wordName(WordId w)
{
  switch (w) {
    case W_FOOD:      return "FOOD";
    case W_WATER:     return "WATER";
    case W_EMERGENCY: return "EMERGENCY";
    case W_TOILET:    return "TOILET";
    case W_MEDICINE:  return "MEDICINE";
    case W_YES:       return "YES";
    case W_NO:        return "NO";
    default:          return "******";
  }
}

// Low-rate messages go to both links; the 100 Hz ADC stream never does.
void sendLine(const char *tag, const char *value)
{
  Serial.print(tag);
  Serial.println(value);
#if USE_SOFTSERIAL
  bluetooth.print(tag);
  bluetooth.println(value);
#endif
}


// =====================================================
// Drawing helpers
// =====================================================
static bool i2cPresent(uint8_t addr)
{
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void centerText(const char *s, int16_t y, uint8_t size)
{
  display.setTextSize(size);
  display.setTextColor(SSD1306_WHITE);
  int16_t w = (int16_t)strlen(s) * 6 * size;
  display.setCursor((SCREEN_W - w) / 2, y);
  display.print(s);
}

// Title bar with three pattern slots, so progress through the sequence is
// always visible.
void drawHeader()
{
  display.fillRect(0, 0, SCREEN_W, 11, SSD1306_WHITE);
  display.setTextSize(1);
  display.setTextColor(SSD1306_BLACK);
  display.setCursor(3, 2);
  display.print(F("RespTalk"));

  for (uint8_t i = 0; i < 3; i++) {
    int16_t sx = 84 + i * 14;
    if (i < breathCount) {
      if (breathPattern[i] == '.') display.fillRect(sx + 4, 3, 4, 5, SSD1306_BLACK);
      else                         display.fillRect(sx, 4, 11, 3, SSD1306_BLACK);
    } else {
      display.drawRect(sx, 3, 11, 5, SSD1306_BLACK);
    }
  }
}

// ---- 28x28 icons, primitives so they cost no RAM ----------------------
void iconFood(int16_t x, int16_t y)
{
  int16_t cx = x + 14;
  display.fillCircle(cx, y + 16, 12, SSD1306_WHITE);
  display.fillRect(x, y, 28, 16, SSD1306_BLACK);
  display.fillRect(cx - 13, y + 14, 26, 3, SSD1306_WHITE);
  for (int8_t i = -1; i < 2; i++)
    display.fillRect(cx + i * 7 - 1, y + 1, 2, 9, SSD1306_WHITE);
}

void iconWater(int16_t x, int16_t y)
{
  int16_t cx = x + 14;
  display.fillTriangle(cx, y + 1, x + 5, y + 18, x + 23, y + 18, SSD1306_WHITE);
  display.fillCircle(cx, y + 18, 9, SSD1306_WHITE);
}

void iconEmergency(int16_t x, int16_t y)
{
  int16_t cx = x + 14;
  display.drawTriangle(cx, y + 1, x + 1, y + 26, x + 27, y + 26, SSD1306_WHITE);
  display.drawTriangle(cx, y + 3, x + 3, y + 25, x + 25, y + 25, SSD1306_WHITE);
  display.fillRect(cx - 1, y + 11, 3, 8, SSD1306_WHITE);
  display.fillRect(cx - 1, y + 21, 3, 3, SSD1306_WHITE);
}

void iconToilet(int16_t x, int16_t y)
{
  display.fillRect(x + 3, y + 3, 6, 12, SSD1306_WHITE);
  display.fillRoundRect(x + 9, y + 8, 16, 10, 4, SSD1306_WHITE);
  display.fillRect(x + 13, y + 18, 7, 6, SSD1306_WHITE);
  display.fillRect(x + 9, y + 24, 15, 3, SSD1306_WHITE);
}

void iconMedicine(int16_t x, int16_t y)
{
  display.fillRoundRect(x + 1, y + 9, 26, 11, 5, SSD1306_WHITE);
  display.fillRect(x + 14, y + 10, 12, 9, SSD1306_BLACK);
  display.drawRoundRect(x + 1, y + 9, 26, 11, 5, SSD1306_WHITE);
  display.drawFastVLine(x + 14, y + 9, 11, SSD1306_WHITE);
}

void iconYes(int16_t x, int16_t y)
{
  for (int8_t t = 0; t < 3; t++) {
    display.drawLine(x + 4,  y + 14 + t, x + 11, y + 21 + t, SSD1306_WHITE);
    display.drawLine(x + 11, y + 21 + t, x + 24, y + 7 + t,  SSD1306_WHITE);
  }
}

void iconNo(int16_t x, int16_t y)
{
  for (int8_t t = 0; t < 3; t++) {
    display.drawLine(x + 5 + t,  y + 7, x + 22 + t, y + 24, SSD1306_WHITE);
    display.drawLine(x + 22 - t, y + 7, x + 5 - t,  y + 24, SSD1306_WHITE);
  }
}

void drawIcon(WordId w, int16_t x, int16_t y)
{
  switch (w) {
    case W_FOOD:      iconFood(x, y);      break;
    case W_WATER:     iconWater(x, y);     break;
    case W_EMERGENCY: iconEmergency(x, y); break;
    case W_TOILET:    iconToilet(x, y);    break;
    case W_MEDICINE:  iconMedicine(x, y);  break;
    case W_YES:       iconYes(x, y);       break;
    case W_NO:        iconNo(x, y);        break;
    default: break;
  }
}

// Integer seconds - avoids linking float printf into a 32 KB part.
void fmtSeconds(unsigned long ms, char *out)
{
  unsigned long tenths = ms / 100;
  unsigned long whole  = tenths / 10;
  char *p = out;
  if (whole >= 10) *p++ = '0' + (char)((whole / 10) % 10);
  *p++ = '0' + (char)(whole % 10);
  *p++ = '.';
  *p++ = '0' + (char)(tenths % 10);
  *p++ = 's';
  *p   = '\0';
}


// =====================================================
// Screens
// =====================================================

// Idle: a scrolling respiration trace, so the device reads as alive. This is
// decorative - the comparators give two digital edges, not a waveform.
void screenIdle()
{
  drawHeader();

  const int16_t mid = 30;
  for (int16_t px = 0; px < SCREEN_W; px++) {
    uint8_t idx = (uint8_t)(((px + wavePhase) >> 1) & 31);
    int8_t v = (int8_t)pgm_read_byte(&WAVE[idx]);
    display.drawPixel(px, mid + v,     SSD1306_WHITE);
    display.drawPixel(px, mid + v + 1, SSD1306_WHITE);
  }

  centerText("breathe to speak", 48, 1);

  // Live A0 level, so a dead sensor is obvious at a glance.
  int16_t w = (int16_t)(((uint32_t)lastAdc * 126UL) / 1023UL);
  display.drawRect(0, 59, 128, 5, SSD1306_WHITE);
  display.fillRect(1, 60, w, 3, SSD1306_WHITE);
}

// Measuring: a live meter with the dot/dash threshold marked, so the symbol
// being produced is visible before the breath ends.
void screenMeasuring(unsigned long elapsed)
{
  drawHeader();

  if (elapsed >= LONG_BREATH_MS) display.fillRect(46, 17, 36, 8, SSD1306_WHITE);
  else                           display.fillCircle(64, 21, 7, SSD1306_WHITE);

  unsigned long shown = elapsed > METER_FULL_MS ? METER_FULL_MS : elapsed;
  int16_t w = (int16_t)(((uint32_t)shown * 124UL) / METER_FULL_MS);

  display.drawRect(1, 38, 126, 10, SSD1306_WHITE);
  display.fillRect(2, 39, w, 8, SSD1306_WHITE);

  int16_t tx = 2 + (int16_t)((124UL * LONG_BREATH_MS) / METER_FULL_MS);
  display.fillTriangle(tx - 3, 32, tx + 3, 32, tx, 37, SSD1306_WHITE);

  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(2, 52);   display.print(F("short"));
  display.setCursor(103, 52); display.print(F("long"));

  char buf[8];
  fmtSeconds(elapsed, buf);
  centerText(buf, 52, 1);
}

// Recognised: icon, word, and a bar draining over the idle timeout.
void screenWord()
{
  drawHeader();
  drawIcon(lastWord, 50, 13);
  centerText(wordName(lastWord), 44, 2);

  unsigned long age = millis() - lastUpdateTime;
  if (age < IDLE_TIMEOUT_MS) {
    unsigned long left = IDLE_TIMEOUT_MS - age;
    int16_t w = (int16_t)(((uint32_t)left * SCREEN_W) / IDLE_TIMEOUT_MS);
    display.fillRect(0, 62, w, 2, SSD1306_WHITE);
  }
}

// Rejected: show the pattern actually entered, as glyphs rather than font
// characters - as text the dots sit on the baseline and read as specks.
void drawBigPattern(int16_t y)
{
  for (uint8_t i = 0; i < 3; i++) {
    int16_t x = 15 + i * 36;
    if (breathPattern[i] == '.') display.fillCircle(x + 13, y + 5, 5, SSD1306_WHITE);
    else                         display.fillRect(x, y + 2, 26, 6, SSD1306_WHITE);
  }
}

void screenUnknown()
{
  drawHeader();
  centerText("?", 14, 3);
  drawBigPattern(44);
}

// Waiting mid-pattern: show how long is left to give the next breath.
void screenWaiting()
{
  drawHeader();
  centerText("listening", 18, 1);
  drawBigPattern(30);

  unsigned long waited = millis() - lastBreathTime;
  if (waited < PATTERN_TIMEOUT_MS) {
    unsigned long left = PATTERN_TIMEOUT_MS - waited;
    int16_t w = (int16_t)(((uint32_t)left * SCREEN_W) / PATTERN_TIMEOUT_MS);
    display.fillRect(0, 61, w, 3, SSD1306_WHITE);
  }
}

void render()
{
  if (!haveDisplay) return;

  display.clearDisplay();

  bool          active;
  unsigned long started;
  noInterrupts();
  active  = breathActive;
  started = breathStart;
  interrupts();

  if (active)                  screenMeasuring(millis() - started);
  else if (showUnknown)        screenUnknown();
  else if (lastWord != W_NONE) screenWord();
  else if (breathCount > 0)    screenWaiting();
  else                         screenIdle();

  display.display();
}


// =====================================================
// Interrupt handlers - keep these tiny
// =====================================================
void onBreathStart()
{
  if (!breathActive) {
    breathActive = true;
    breathStart  = millis();
  }
}

void onBreathEnd()
{
  if (breathActive) {
    breathLen    = millis() - breathStart;
    breathActive = false;
    breathReady  = true;
  }
}


// =====================================================
// Setup
// =====================================================
void setup()
{
  Serial.begin(9600);
#if USE_SOFTSERIAL
  bluetooth.begin(9600);
#endif

  pinMode(comp1Pin, INPUT);
  pinMode(comp2Pin, INPUT);
  pinMode(buzzerPin, OUTPUT);
  digitalWrite(buzzerPin, LOW);

  // D2/D3 are INT0/INT1, the ATmega328P's only external interrupt pins.
  attachInterrupt(digitalPinToInterrupt(comp1Pin), onBreathStart, RISING);
  attachInterrupt(digitalPinToInterrupt(comp2Pin), onBreathEnd,   FALLING);

  Wire.begin();
  Wire.setClock(400000);   // at 100 kHz a full redraw takes ~100 ms

  // begin() reports success even with no panel attached, so probe the bus
  // ourselves - otherwise a module at 0x3D just stays blank with no error.
  uint8_t addr = i2cPresent(0x3C) ? 0x3C : (i2cPresent(0x3D) ? 0x3D : 0);
  haveDisplay = addr && display.begin(SSD1306_SWITCHCAPVCC, addr);

  if (haveDisplay) {
    Serial.print(F("OLED at 0x"));
    Serial.println(addr, HEX);

    display.clearDisplay();
    centerText("RespTalk", 18, 2);
    centerText("BCAI", 42, 1);
    display.display();
    delay(1200);
  } else {
    // A missing screen must not take the device down with it - the buzzer and
    // the Bluetooth link still carry EMERGENCY without a display.
    Serial.println(F("No OLED on 0x3C/0x3D - running headless"));
  }

  Serial.println(F("RespTalk started..."));
#if USE_SOFTSERIAL
  bluetooth.println(F("RespTalk Bluetooth Started"));
#endif
}


// =====================================================
// Main loop
// =====================================================
void loop()
{
  // ---- raw A0 stream, hardware Serial only ----------------------------
  if (millis() - lastAdcTime >= ADC_INTERVAL_MS) {
    lastAdcTime += ADC_INTERVAL_MS;      // fixed cadence, no drift
    lastAdc = analogRead(adcPin);

    Serial.print(F("ADC:"));
    Serial.println(lastAdc);
  }

  // ---- a completed breath ---------------------------------------------
  if (breathReady) {
    noInterrupts();
    unsigned long duration = breathLen;
    breathReady = false;
    interrupts();

    if (duration >= MIN_BREATH_MS) {
      showUnknown = false;
      lastBreathTime = millis();

      char breathType;
      if (duration < LONG_BREATH_MS) {
        breathType = '.';
        Serial.println(F("Short breath (.)"));
        sendLine("BREATH:", ".");
      } else {
        breathType = '-';
        Serial.println(F("Long breath (-)"));
        sendLine("BREATH:", "_");
      }

      Serial.print(F("duration : "));
      Serial.println(duration);

      breathPattern[breathCount] = breathType;
      breathCount++;

      if (breathCount == 3) {
        WordId word = interpretPattern();

        Serial.print(F("Recognized: "));
        Serial.println(wordName(word));

        char sent[4];
        for (uint8_t i = 0; i < 3; i++)
          sent[i] = (breathPattern[i] == '.') ? '.' : '_';
        sent[3] = '\0';
        sendLine("PATTERN:", sent);

        if (word != W_NONE) {
          lastWord       = word;
          showUnknown    = false;
          lastUpdateTime = millis();
          sendLine("COMMAND:", wordName(word));

          digitalWrite(buzzerPin, HIGH);
          beepUntil = millis() + BEEP_MS;
        } else {
          lastWord       = W_NONE;
          showUnknown    = true;
          lastUpdateTime = millis();
          sendLine("COMMAND:", "NILL");
          digitalWrite(buzzerPin, LOW);
        }

        breathCount = 0;
      }
    }
  }

  // ---- a lone breath with no follow-up is not a command ---------------
  if (breathCount > 0 && !breathActive
      && millis() - lastBreathTime > PATTERN_TIMEOUT_MS) {
    Serial.println(F("Pattern timed out, cleared"));
    sendLine("PATTERN:", "TIMEOUT");
    breathCount = 0;
  }

  // ---- short chirp rather than holding the buzzer on -------------------
  if (beepUntil && millis() >= beepUntil) {
    digitalWrite(buzzerPin, LOW);
    beepUntil = 0;
  }

  // ---- idle timeout clears the last word ------------------------------
  if (lastWord != W_NONE && millis() - lastUpdateTime > IDLE_TIMEOUT_MS) {
    lastWord = W_NONE;
    digitalWrite(buzzerPin, LOW);
  }
  if (showUnknown && millis() - lastUpdateTime > IDLE_TIMEOUT_MS) {
    showUnknown = false;
  }

  // ---- render on a fixed cadence --------------------------------------
  if (millis() - lastFrame >= FRAME_MS) {
    lastFrame = millis();
    wavePhase += 2;
    render();
  }
}
