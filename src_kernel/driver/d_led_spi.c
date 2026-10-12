#include <linux/init.h>
#include <linux/module.h>
#include <linux/spi/spi.h>
#include <linux/of.h>


static int led_spi_probe(struct spi_device *spi);
static void led_spi_remove(struct spi_device *spi);


static const struct of_device_id led_spi_of_match[] = {
    {.compatible = "tej,robot-led"},
    {}
};


static struct spi_driver led_spi_driver = {
    .driver = {
        .name = "led_spi",
        .of_match_table = led_spi_of_match
    },

    .probe = led_spi_probe,
    .remove = led_spi_remove
};

static int led_spi_set_all(struct spi_device *spi, bool on);

static int __init led_spi_init(void){
    printk(KERN_INFO "Led Spi driver modprobed\n");

    return spi_register_driver(&led_spi_driver);
}


static int led_spi_probe(struct spi_device *spi)
{
    int ret;

    printk(KERN_INFO "LED SPI device bound to driver\n");

    spi->bits_per_word = 8;
    spi->mode = SPI_MODE_0;

    ret = spi_setup(spi);

    if (ret < 0) {
        printk(KERN_ERR "SPI setup failed: %d\n", ret);
        return ret;
    }

    printk(KERN_INFO "SPI setup successful, max speed = %u Hz\n",
           spi->max_speed_hz);

    ret = led_spi_set_all(spi, true);

    if (ret < 0) {
        printk(KERN_ERR "LED SPI write failed: %d\n", ret);
        return ret;
    }

    printk(KERN_INFO "LEDs turned ON\n");

    return 0;
}


static void led_spi_remove(struct spi_device *spi)
{
    led_spi_set_all(spi, false);

    printk(KERN_INFO "LEDs turned OFF\n");
    printk(KERN_INFO "LED SPI device removed from driver\n");
}

static void __exit led_spi_exit(void){
    printk(KERN_INFO "Led spi driver rmmoded\n");

    spi_unregister_driver(&led_spi_driver);
}

static int led_spi_set_all(struct spi_device *spi, bool on)
{
    u8 tx[96];
    int tx_index = 0;
    int led;
    int color_byte;
    int bit;

    /*
     * 4 LEDs
     * 3 color bytes per LED
     * 8 WS2812 bits per color byte
     * each WS2812 bit becomes 1 SPI byte
     *
     * 4 * 3 * 8 = 96 SPI bytes
     */

    for (led = 0; led < 4; led++) {

        /*
         * Freenove uses GRB ordering.
         *
         * Red:
         * G = 0x00
         * R = 0xFF
         * B = 0x00
         */

        u8 grb[3];

        if (on) {
            grb[0] = 0x00; /* Green */
            grb[1] = 0xFF; /* Red   */
            grb[2] = 0x00; /* Blue  */
        } else {
            grb[0] = 0x00;
            grb[1] = 0x00;
            grb[2] = 0x00;
        }

        for (color_byte = 0; color_byte < 3; color_byte++) {

            for (bit = 7; bit >= 0; bit--) {

                if (grb[color_byte] & (1 << bit))
                    tx[tx_index++] = 0xF8;
                else
                    tx[tx_index++] = 0x80;
            }
        }
    }

    return spi_write(spi, tx, sizeof(tx));
}

module_init(led_spi_init);
module_exit(led_spi_exit);

MODULE_LICENSE("GPL");






