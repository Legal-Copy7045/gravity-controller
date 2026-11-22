CXXFLAGS ?= -std=c++17 -O1 -g -Wall -Wextra -fsanitize=address,undefined
SRC = test_core.cpp ../components/gravity980/protocol.cpp ../components/cook_assistant/predictor.cpp \
      ../components/cook_assistant/history.cpp ../components/cook_assistant/program.cpp \
      ../components/cook_assistant/fuel.cpp

test_core: $(SRC) $(wildcard ../components/*/*.h)
	$(CXX) $(CXXFLAGS) -o $@ $(SRC)

run: test_core
	./test_core

.PHONY: run
.DEFAULT_GOAL := run
