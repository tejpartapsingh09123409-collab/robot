#include <sys/socket.h>
#include <sys/un.h>
#include <cstring>
#include "file_descriptor.hpp"

class SocketBindPath{
    public:
        SocketBindPath(int fd, int domain, const std::string &path){
            if (domain != AF_UNIX) {
                throw std::invalid_argument("Only AF_UNIX is supported");
            }

            sockaddr_un addr{};
            addr.sun_family = domain;

            // MUST: Validate path length to prevent sun_path buffer overflow
            std::strcpy(addr.sun_path, path.c_str());

            int result = bind(
                fd,
                reinterpret_cast<const sockaddr*>(&addr),   // changing ptr type without changing underlying object
                sizeof(addr)
            );

            if(result == -1){
                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "IPC socket bind failed!"
                };
            }
            
            path_ = path;
        }

        ~SocketBindPath(){
            if(unlink(path_.c_str()) == -1){
                std::perror("unlink failed");
            }
        }

    // MUST: Prevent copying/moving to avoid multiple objects owning the same socket pathname
    private:
        std::string path_;

};

class Socket{
    public:
        Socket(const int domain, const std::string &socket_path):
            fd_{open_socket(domain)},
            socket_bind_path_{fd_.get(), domain, socket_path}{
        
            if(::listen(fd_.get(), kSocketBacklog) == -1){
                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "listen failed"
                };
            }
        }
       
        FileDescriptor accept_connection(){
            int fd = ::accept(fd_.get(), nullptr, nullptr);

            if(fd == -1){
                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "accept failed"
                };
            }

            return FileDescriptor{fd};

        }
    private:


        static int open_socket(const int domain){

            int fd = ::socket(domain, SOCK_STREAM, 0);
            if(fd < 0){
                throw std::system_error{
                    errno,
                    std::generic_category(),
                    "socket creation failed"
                };
            }
            return fd;
        }

        static constexpr int kSocketBacklog = 5;

        const FileDescriptor fd_;
        const SocketBindPath socket_bind_path_;
    };