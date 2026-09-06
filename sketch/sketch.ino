#include <Arduino_RouterBridge.h>
#include <Arduino_LED_Matrix.h>
#include <atomic>

Arduino_LED_Matrix matrix;
// Bridge callbacks and loop may run on different threads.
std::atomic<int> homeState{0};
std::atomic<int> peopleHome{0};
std::atomic<unsigned long> lastUpdate{0};
uint8_t frame[8 * 13] = {0};

void presenceDisplay(int state, int count) {
  homeState.store(state >= 0 && state <= 2 ? state : 0);
  peopleHome.store(count < 0 ? 0 : (count > 13 ? 13 : count));
  lastUpdate.store(millis());
}

void setup() {
  matrix.begin();
  matrix.setGrayscaleBits(3);
  matrix.clear();
  Bridge.begin();
  Bridge.provide("presence_display", presenceDisplay);
}

void loop() {
  const bool fresh = millis() - lastUpdate.load() < 15000;
  const int state = fresh ? homeState.load() : 0;
  memset(frame, 0, sizeof(frame));
  // H = HOME, A = AWAY, ? = UNKNOWN. Each glyph is five columns wide.
  const uint8_t glyphs[3][5] = {
    {14, 1, 6, 0, 4},   // ?
    {14, 17, 31, 17, 17}, // A
    {17, 17, 31, 17, 17}  // H
  };
  for (int row = 0; row < 5; ++row) {
    for (int col = 0; col < 5; ++col) {
      if (glyphs[state][row] & (1 << (4 - col))) frame[row * 13 + col + 4] = 7;
    }
  }
  // Bottom row: one dot per person HOME, up to thirteen.
  const int count = fresh ? peopleHome.load() : 0;
  for (int col = 0; col < count; ++col) frame[7 * 13 + col] = 4;
  matrix.draw(frame);
  delay(100);
}
