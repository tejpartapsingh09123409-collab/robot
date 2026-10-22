#include "led_controller.hpp"

int main(){
    LedController leds{"/dev/robot_led"};

    Rgb rgb_led{.r = 0xFF, 
                .g= 0xFF,
                .b= 0xFF};

    leds.set(rgb_led);

    return 0;
}





// FUTURE: Add WDT