// claude-status-led firmware
//
// A dumb slave: it maps single-character commands arriving over USB serial
// onto three LEDs and knows nothing about Claude Code. Every decision about
// what the light should mean lives on the host, so changing the behaviour
// never requires reflashing this chip.

#include <Arduino.h>

// LEDs are wired active high, each through a series resistor to ground.
#define PIN_RED 25
#define PIN_YELLOW 26
#define PIN_GREEN 27

// Not every board exposes an onboard LED on this pin; set to -1 to disable.
#define PIN_ONBOARD 2

static const unsigned long BOOT_STEP_MS = 200;
static const unsigned long BLINK_MS = 80;

static char currentState = 'O';
static unsigned long blinkStartedAt = 0;
static bool blinkActive = false;

static void showState(char state) {
  digitalWrite(PIN_RED, state == 'R' ? HIGH : LOW);
  digitalWrite(PIN_YELLOW, state == 'Y' ? HIGH : LOW);
  digitalWrite(PIN_GREEN, state == 'G' ? HIGH : LOW);
  currentState = state;
}

// The onboard blink is the verification signal for a board with nothing wired
// to it yet: it proves a command actually arrived.
static void startBlink() {
  if (PIN_ONBOARD < 0) {
    return;
  }
  digitalWrite(PIN_ONBOARD, HIGH);
  blinkStartedAt = millis();
  blinkActive = true;
}

// Ends the blink without blocking the read loop.
static void serviceBlink() {
  if (!blinkActive) {
    return;
  }
  if (millis() - blinkStartedAt < BLINK_MS) {
    return;
  }
  digitalWrite(PIN_ONBOARD, LOW);
  blinkActive = false;
}

static void handleCommand(char command) {
  switch (command) {
    case 'R':
    case 'Y':
    case 'G':
    case 'O':
      showState(command);
      startBlink();
      Serial.print("OK ");
      Serial.println(command);
      break;
    case '?':
      Serial.print("STATE ");
      Serial.println(currentState);
      break;
    default:
      Serial.println("ERR");
      break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  if (PIN_ONBOARD >= 0) {
    pinMode(PIN_ONBOARD, OUTPUT);
  }

  // Boot sweep: proves the board is alive and every LED is wired correctly.
  const char sweep[] = {'R', 'Y', 'G'};
  for (size_t i = 0; i < sizeof(sweep); i++) {
    showState(sweep[i]);
    delay(BOOT_STEP_MS);
  }
  showState('O');

  Serial.println("READY claude-status-led");
}

void loop() {
  serviceBlink();
  while (Serial.available() > 0) {
    int incoming = Serial.read();
    if (incoming < 0) {
      break;
    }
    char command = (char) incoming;
    // Line endings are separators, not commands.
    if (command == '\r' || command == '\n') {
      continue;
    }
    handleCommand(command);
  }
}
