#pragma once

#include "file_descriptor.hpp"

#include <array>
#include <cerrno>
#include <cstdint>
#include <string>
#include <system_error>
#include <stdexcept>
#include <cstddef>

#include <fcntl.h>
#include <unistd.h>

#include "rgb.hpp"

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

            
            ssize_t bytes_written;

            do {
                bytes_written = ::write(
                    led_driver_fd_.get(),
                    led_data.data(),
                    led_data.size()
                );
            } while (bytes_written < 0 && errno == EINTR);

            if(bytes_written < 0){

                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "Led write failed"
                };
            }

            if(static_cast<std::size_t>(bytes_written) != led_data.size()){
                throw std::runtime_error{
                    "Incomplete LED cmd written"
                };
            }
        }

    private:
        FileDescriptor led_driver_fd_;

        static int open_led_driver(const std::string &dev_node_name){
            const int fd{::open(dev_node_name.c_str(), O_WRONLY)};
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