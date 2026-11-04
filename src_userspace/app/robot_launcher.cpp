#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include <system_error>
#include <iostream>
#include <cstdint>

int main(){
    try{
        std::cerr << "Before any fork: PID = " << getpid() << 
            ", PPID = " << getppid() << '\n' << std::flush;
        
        pid_t pid_1 = fork();

        if(pid_1 == -1){
            throw std::system_error(
                errno,
                std::generic_category(),
                "comms host fork failed"
            );
        }


        if(pid_1 == 0){
            // child
            // run comms process
            std::cerr << "COMMS host forked: PID = " << getpid() << 
                    ", PPID = " << getppid() << '\n' << std::flush;

            char *args[] = {nullptr};

            char *env[] = {
                nullptr
            };

            execve("./bin/robot_comms_host", args, env);

            // Reached only if execve fails
            throw std::system_error(
                errno,
                std::generic_category(),
                "comms host execve failed"
            );
        }
        else{
            // parent
            // for again to run robot controller
            pid_t pid_2 = fork();

            if(pid_2 == -1){
                throw std::system_error(
                    errno,
                    std::generic_category(),
                    "robot fork failed"
                );
            }

            if(pid_2 == 0){
                // child
                std::cerr << "robot forked: PID = " << getpid() << 
                        ", PPID = " << getppid() << '\n' << std::flush;

                char *args[] = {nullptr};

                char *env[] = {
                    nullptr
                };

                execve("./bin/robot", args, env);

                // Reached only if execve fails
                throw std::system_error(
                    errno,
                    std::generic_category(),
                    "robot execve failed"
                );
            }
            else{
                // parent
                int status = 0;
                pid_t result;

                // reap child statuses - they can finish in any order
                for(std::uint8_t i{0}; i < 2; i++){
                    do{
                        result = waitpid(-1, &status, 0); // reap whiever finish first
                    }while(result == -1 && errno == EINTR);
                    
                    if(result == -1){
                        throw std::system_error{
                            errno,
                            std::generic_category(),
                            "waitpid failed"
                        };
                    }
        
                    std::string process_name;

                    if(result == pid_1){
                        process_name = "COMMS_HOST";
                    }
                    else{
                        process_name = "ROBOT";
                    }
                    if(WIFEXITED(status)){
                        std::cerr << process_name << " exited with status: " << 
                            WEXITSTATUS(status) << '\n';
                    }
                    else if(WIFSIGNALED(status)){
                        std::cerr << process_name << " terminated by signal: " << 
                            WTERMSIG(status) << '\n';
                    }
                }

            }
        }

        return 0;
    }
    catch(const std::system_error &e){
        std::cerr << e.what() << '\n';
        return 1;
    }

    return 0;
}