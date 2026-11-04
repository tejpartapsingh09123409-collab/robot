
CXX := g++
CXXFLAGS := -std=c++20 -Wall -Wextra -Wpedantic -MMD -MP
CPPFLAGS := -Imiddleware -Iutility

BUILD_DIR := build
BIN_DIR := bin

TARGETS := $(BIN_DIR)/robot_launcher \
           $(BIN_DIR)/robot \
           $(BIN_DIR)/robot_comms_host

SRCS := app/robot_launcher.cpp \
        app/robot.cpp \
        app/robot_comms_host.cpp

OBJS := $(patsubst app/%.cpp,$(BUILD_DIR)/%.o,$(SRCS))
DEPS := $(OBJS:.o=.d)

.PHONY: all clean

all: $(TARGETS)

$(BIN_DIR)/robot_launcher: $(BUILD_DIR)/robot_launcher.o | $(BIN_DIR)
	$(CXX) $< -o $@

$(BIN_DIR)/robot: $(BUILD_DIR)/robot.o | $(BIN_DIR)
	$(CXX) $< -o $@

$(BIN_DIR)/robot_comms_host: $(BUILD_DIR)/robot_comms_host.o | $(BIN_DIR)
	$(CXX) $< -o $@

$(BUILD_DIR)/%.o: app/%.cpp | $(BUILD_DIR)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(BUILD_DIR) $(BIN_DIR):
	mkdir -p $@

-include $(DEPS)

clean:
	rm -rf $(BUILD_DIR) $(BIN_DIR)
