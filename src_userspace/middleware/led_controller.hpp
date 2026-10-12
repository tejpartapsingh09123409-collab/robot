#include "file_descriptor.hpp"

class LedController{
    public:
        LedController(const std::string &dev_node_name):
            led_driver_fd_{open_led_driver(dev_node_name)}
        {   

        }

        void set(const Rgb &rgb_led){
            std::array<std::uint8_t, 3> led_data{   rgb_led.r,
                                                    rgb_led.g,
                                                    rgb_led.b};

            std::size_t bytes_to_write{sizeof(led_data)};
            std::size_t total_bytes_written{0};
            
            while(bytes_to_write > 0 ){
                            
                const ssize_t bytes_written{::write(led_driver_fd_.get(),
                                    &(led_data[total_bytes_written]), 
                                    bytes_to_write)};

                if(bytes_written < 0){
                    if(errno == EINTR){
                        // Interrupted by a signal
                        // Retry
                        continue;
                    }


                    throw std::system_error{
                        errno,
                        std::generic_category(),
                        "Led write failed"
                    };
                }
                else if(bytes_written == 0){
                    throw std::runtime_error{
                        "No led data written"
                    };
                }


                bytes_to_write = bytes_to_write - bytes_written;
                total_bytes_written += bytes_written;
            }
        }

    private:
        FileDescriptor led_driver_fd_;

        static int open_led_driver(const std::string &dev_node_name){
            const int fd{::open(dev_node_name.c_str(), O_RDWR);}
            if(fd < 0){
                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "Led device open failed"
                };
            }

            return fd;
        }

};