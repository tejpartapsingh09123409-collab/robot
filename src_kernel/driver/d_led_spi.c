#include <linux/init.h>
#include <linux/module.h>
#include <linux/spi/spi.h>
#include <linux/of.h>
#include <linux/fs.h>
#include <linux/cdev.h>

#define LED_SPI_MAX_DEVICES 1

static const struct of_device_id led_spi_of_match[] = {
    {.compatible = "tej,robot-led"},
    {}
};

struct led_spi_device {
    struct spi_device *spi;
    unsigned int id;

    dev_t dev_num;
    struct cdev cdev;
};

static int led_spi_probe(struct spi_device *spi);
static void led_spi_remove(struct spi_device *spi);

static struct spi_driver led_spi_driver = {
    .driver = {
        .name = "led_spi",
        .of_match_table = led_spi_of_match
    },
    
    .probe = led_spi_probe,
    .remove = led_spi_remove
};

static int led_spi_set_all(struct spi_device *spi, const u8 rgb[3]);

static int __init led_spi_init(void){
    printk(KERN_INFO "Led Spi driver modprobed\n");

    return spi_register_driver(&led_spi_driver);
}

static int robot_led_open(struct inode *inode, struct file *filp);
static ssize_t robot_led_write(struct file *filp, 
                                const char __user *buf,
                                size_t count,
                                loff_t *ppos);

static const struct file_operations led_fops = {
    .owner = THIS_MODULE,
    .open = robot_led_open,
    .write = robot_led_write
};

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

    struct led_spi_device *led;           
    led = devm_kzalloc(&spi->dev, sizeof(*led), GFP_KERNEL);
    if(!led){
        return -ENOMEM;
    }

    led->spi = spi;

    spi_set_drvdata(spi, led);

    ret = alloc_chrdev_region(&led->dev_num, 0, 1, "robot_led");

    if(ret < 0){
        dev_err(&spi->dev,
                "Failed to allocate character device number: %d\n", ret);
        return ret;
    }

    pr_info("Major: %u, Minor: %u\n",
        MAJOR(led->dev_num), MINOR(led->dev_num));


    cdev_init(&led->cdev, &led_fops);
    led->cdev.owner = THIS_MODULE;

    ret = cdev_add(&led->cdev, led->dev_num, 1);
    if(ret < 0){
        dev_err(&spi->dev, "cdev_add failed: %d\n", ret);
        unregister_chrdev_region(led->dev_num, 1);
        return ret;
        
    }


    printk(KERN_INFO "LEDs turned ON\n");

    return 0;
}


static void led_spi_remove(struct spi_device *spi)
{
    struct led_spi_device *led = spi_get_drvdata(spi);

    cdev_del(&led->cdev);
    unregister_chrdev_region(led->dev_num, 1);

    pr_info("LED SPI device removed\n");
}

static void __exit led_spi_exit(void){
    printk(KERN_INFO "Led spi driver rmmoded\n");

    spi_unregister_driver(&led_spi_driver);
}

// userspace functions
static int robot_led_open(struct inode *inode, struct file *filp)
{
    struct led_spi_device *led;
    pr_info("robot_led opened!\n");

    // get to led structure from cdev in inode
    led = container_of(inode->i_cdev, struct led_spi_device, cdev);

    filp->private_data = led;

    return 0;
}

static ssize_t robot_led_write(struct file *filp, 
                                const char __user *buf,
                                size_t count,
                                loff_t *ppos)
{
    struct led_spi_device *led = filp->private_data;
    u8 rgb[3];

    if(count != sizeof(rgb)){
        return -EINVAL;
    }

    if(copy_from_user(rgb, buf, sizeof(rgb))){
        return -EFAULT;
    }

    pr_info("RGB received: R=%u, G=%u, B=%u\n",
            rgb[0],
            rgb[1],
            rgb[2]);

            int ret;

    ret = led_spi_set_all(led->spi, rgb);
    if (ret < 0) {
        dev_err(&led->spi->dev,
                "Failed to update LEDs: %d\n", ret);
        return ret;
    }

    return sizeof(rgb);
}



static int led_spi_set_all(struct spi_device *spi, const u8 rgb[3])
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
        
        u8 grb[3] = {
            rgb[1],  /* Green */
            rgb[0],  /* Red   */
            rgb[2]   /* Blue  */
        };

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






