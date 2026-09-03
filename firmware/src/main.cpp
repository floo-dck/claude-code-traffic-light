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

// The onboard LED is a single monochrome LED, so it cannot show a colour. It
// carries the same three states through timing instead: red is solid, yellow
// blinks fast, green is a slow heartbeat, off is off.
static const unsigned long ONBOARD_BLOCKED_HALF_MS = 150;
static const unsigned long ONBOARD_IDLE_PULSE_MS = 80;
static const unsigned long ONBOARD_IDLE_PERIOD_MS = 2000;

static char currentState = 'O';
static unsigned long patternStartedAt = 0;

// Drives the onboard LED from the current state and the time since the
// pattern started. Called every loop, never blocks, and unsigned arithmetic
// keeps it correct across the millis() wrap.
static void serviceOnboard() {
  if (PIN_ONBOARD < 0) {
    return;
  }
  const unsigned long elapsed = millis() - patternStartedAt;
  bool on;
  switch (currentState) {
    case 'R':
      on = true;
      break;
    case 'Y':
      on = (elapsed / ONBOARD_BLOCKED_HALF_MS) % 2 == 0;
      break;
    case 'G':
      on = (elapsed % ONBOARD_IDLE_PERIOD_MS) < ONBOARD_IDLE_PULSE_MS;
      break;
    default:
      on = false;
      break;
  }
  digitalWrite(PIN_ONBOARD, on ? HIGH : LOW);
}

static void showState(char state) {
  digitalWrite(PIN_RED, state == 'R' ? HIGH : LOW);
  digitalWrite(PIN_YELLOW, state == 'Y' ? HIGH : LOW);
  digitalWrite(PIN_GREEN, state == 'G' ? HIGH : LOW);
  currentState = state;
  // Restarting the phase on every command makes a repeat of the state the
  // board is already in visible too, which is the verification signal for a
  // board with nothing wired to it yet: it proves a command arrived.
  patternStartedAt = millis();
  serviceOnboard();
}

static void handleCommand(char command) {
  switch (command) {
    case 'R':
    case 'Y':
    case 'G':
    case 'O':
      showState(command);
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
  serviceOnboard();
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
