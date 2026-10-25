
#include "led_controller.hpp"
#include "rgb.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <thread>

using namespace std::chrono_literals;

// Convert an HSV color into RGB.
// Hue:        0 - 360 degrees
// Saturation: 0 - 1
// Value:      0 - 1 (brightness)
Rgb hsv_to_rgb(double hue, double saturation, double value)
{
    const double c = value * saturation;
    const double h = hue / 60.0;
    const double x = c * (1.0 - std::abs(std::fmod(h, 2.0) - 1.0));
    const double m = value - c;

    double r = 0.0;
    double g = 0.0;
    double b = 0.0;

    if (h < 1.0) {
        r = c; g = x;
    } else if (h < 2.0) {
        r = x; g = c;
    } else if (h < 3.0) {
        g = c; b = x;
    } else if (h < 4.0) {
        g = x; b = c;
    } else if (h < 5.0) {
        r = x; b = c;
    } else {
        r = c; b = x;
    }

    return Rgb{
        static_cast<std::uint8_t>((r + m) * 255.0),
        static_cast<std::uint8_t>((g + m) * 255.0),
        static_cast<std::uint8_t>((b + m) * 255.0)
    };
}

int main()
{
    LedController leds{"/dev/robot_led"};

    constexpr double pi = 3.141592653589793;
    constexpr auto frame_interval = 33ms; // ~30 FPS

    double hue = 0.0;
    double phase = 0.0;

    while (true) {

        // Smooth breathing brightness: 10% to 80%
        const double brightness =
            0.45 + 0.35 * std::sin(phase);

        Rgb color = hsv_to_rgb(hue, 1.0, brightness);

        leds.set(color);

        // Rotate through the color spectrum.
        hue = std::fmod(hue + 1.0, 360.0);

        // One breathing cycle every ~3 seconds.
        phase = std::fmod(
            phase + (2.0 * pi / 90.0),
            2.0 * pi
        );

        std::this_thread::sleep_for(frame_interval);
    }
}
