

int main(){
    LedController leds{"dev/led_node"};



    while(1){
        Rgb rgb_led{.red = 0xFF, 
                    .green = 0xFF,
                    .blue = 0xFF};

        leds.set(rgb_led);
    }

    return 0;
}





// FUTURE: Add WDT