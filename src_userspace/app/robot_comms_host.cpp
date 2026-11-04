#include <iostream>
#include <unistd.h>


int main(){
    std::cerr << "COMMS host running. PID = "
            << getpid() << '\n';

    return 0;
}