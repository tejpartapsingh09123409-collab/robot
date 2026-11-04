#include <iostream>
#include <unistd.h>
#include <cstdint>
#include "u_socket.hpp"
#include <thread>
#include <iomanip>

constexpr std::uint16_t SocketRcvBufLen = 1000;
static int comms_slave_worker(void);
static int controller_worker(void);

int main(void) {

    try{
        std::thread comms_slave_thread{comms_slave_worker};
        std::thread controller_thread{controller_worker};

        controller_thread.join();
        comms_slave_thread.join();
        
    }
    catch(const std::system_error &e){
        std::cerr <<"Thread error: " << e.what() << '\n';
        return 1;
    }

    return 0;
}


static int comms_slave_worker(void){
    
    try{
        std::cerr << "COMMS slave thread running: PID = "
                << getpid() << '\n';

        const std::string socket_path = "/tmp/robot_controller.sock";
            
        Socket socket{AF_UNIX, socket_path};

        while(1){
            FileDescriptor client_fd = socket.accept_connection();

            
            while (1) {
                std::uint8_t buf[SocketRcvBufLen];

                ssize_t bytes_received = ::recv(client_fd.get(), buf, sizeof(buf), 0);

                if (bytes_received == -1) {
                    throw std::system_error{
                        errno,
                        std::generic_category(),
                        "Receive failed for client fd = " + std::to_string(client_fd.get())
                    };
                }

                if (bytes_received == 0) {
                    std::cerr << "Client disconnected. Client fd = "
                            << client_fd.get() << '\n';
                    break;
                }

                std::cout << "Bytes received (" << bytes_received << "):\n";

                // print ascii
                std::cout << "Hex-\n";
                for (ssize_t i = 0; i < bytes_received; ++i) {
                    std::cout << "0x"
                            << std::hex
                            << std::uppercase
                            << std::setw(2)
                            << std::setfill('0')
                            << static_cast<unsigned int>(buf[i])
                            << ' ';
                }
                std::cout << "\n";

                // print ascii
                std::cout << "Ascii-\n";
                std::cout.write(
                    reinterpret_cast<const char*>(buf),
                    bytes_received
                );

                std::cout << std::dec << '\n';
            }

        }
    }
    catch(const std::exception& e){
        std::cerr << "Comms slave failed: " << e.what() << '\n';
        return 1;
    }
    
    return 0;
}


static int controller_worker(void){
    std::cerr << "Controller thread running: PID = "
            << getpid() << '\n';

    return 0;
}