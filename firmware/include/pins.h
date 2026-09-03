// Pin assignment and LED polarity.
//
// Every macro here is guarded, so a -D flag in platformio.ini wins over the
// default without editing this file. Wiring is physical: it changes when a
// soldering iron changes it, not while the program runs. That is why this is
// a build-time choice and not a serial command.

#pragma once

// LEDs are wired through a series resistor. Active high by default: a HIGH
// output lights the LED.
#ifndef PIN_RED
#define PIN_RED 25
#endif

#ifndef PIN_YELLOW
#define PIN_YELLOW 26
#endif

#ifndef PIN_GREEN
#define PIN_GREEN 27
#endif

// Not every board exposes an onboard LED on this pin; set to -1 to disable.
#ifndef PIN_ONBOARD
#define PIN_ONBOARD 2
#endif

// Set to 1 for common-anode modules — the pre-assembled traffic-light boards
// such as the KY-009 family — where a LOW output lights the LED. Without it
// those modules show the exact inverse of the truth, which is worse than
// showing nothing. Applies to the three colour outputs only; the onboard LED
// keeps its own polarity and is switched off with PIN_ONBOARD -1.
#ifndef LED_ACTIVE_LOW
#define LED_ACTIVE_LOW 0
#endif
