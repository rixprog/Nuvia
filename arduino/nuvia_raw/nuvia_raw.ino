/*
 * Nuvia - raw A0 capture
 * -----------------------------------------------------------------------
 * Standalone diagnostic sketch. It reads the analog pin and prints it.
 * Nothing else: no OLED, no comparators, no pattern logic, no buzzer.
 *
 * Purpose: the ATmega only ever sees the LM324's two digital comparator
 * outputs, so the actual breath envelope is invisible to both you and the
 * firmware - which makes setting the two thresholds guesswork. Tap the
 * LM324's analog output (before the comparators) into A0 and this prints
 * the real waveform.
 *
 * Wiring: LM324 analog out -> A0, and a shared GND.
 *         The signal must stay within 0-5 V. Anything outside that range
 *         needs a divider or a clamp first, or it damages the pin.
 *
 * Output: one number per line, 0-1023, at a fixed rate. No timestamps -
 * the rate is constant, so sample index * SAMPLE_INTERVAL_MS is the time.
 *
 *   478
 *   482
 *   611
 */

const uint8_t SENSE_PIN = A0;

// 9600 matches the HC-05, so this works over Bluetooth as well as USB.
// For USB-only capture you can raise it to 115200 and sample faster.
const unsigned long BAUD = 9600;

// 100 Hz. A breath envelope is far slower than this, and at 9600 baud a
// 4-digit line costs ~5 ms to send, so this leaves plenty of headroom.
const unsigned long SAMPLE_INTERVAL_MS = 10;

unsigned long nextSample = 0;

void setup()
{
  Serial.begin(BAUD);
  nextSample = millis();
}

void loop()
{
  if ((long)(millis() - nextSample) < 0) {
    return;
  }
  nextSample += SAMPLE_INTERVAL_MS;

  Serial.println(analogRead(SENSE_PIN));
}
