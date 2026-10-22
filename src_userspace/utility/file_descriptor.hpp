#pragma once

#include <unistd.h>

class FileDescriptor{
    public:
        explicit FileDescriptor(int fd):
            fd_{fd}{
            
        }

        FileDescriptor(const FileDescriptor&) = delete;
        FileDescriptor& operator=(const FileDescriptor&) = delete;

        ~FileDescriptor() noexcept{
            if(fd_ >= 0){
                ::close(fd_);
            }
        }

        int get() const{
            return fd_;
        }

    private:
        int fd_;

};