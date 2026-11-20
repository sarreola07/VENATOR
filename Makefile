# VENATOR build and test entry points. Run `make` (or `make help`) for the list.
# Works with the GNU Make that ships with macOS (3.81) and on Linux / the Jetson.

PYTHON  ?= python3
VENV    ?= venv
VPY     := $(VENV)/bin/python
NPX     ?= npx

# Firmware: the Heltec ESP32 board package and the "Heltec ESP32 Dev-Boards"
# library (radio/firmware/README.md). 230400 is the upload speed these boards' CP2102 manages.
HELTEC_URL   := https://resource.heltec.cn/download/package_heltec_esp32_index.json
FQBN_STICK   := Heltec-esp32:esp32:heltec_wireless_stick_V3
FQBN_REMOTE  := Heltec-esp32:esp32:heltec_wifi_lora_32_V3
UPLOAD_SPEED := 230400
FW_OUT       := build/firmware

# The test list is read from the CI workflow, so `make test` runs exactly what CI runs.
TESTS := $(shell grep -oE 'python3 tests/test_[a-z0-9_]+\.py' .github/workflows/tests.yml | awk '{print $$2}')

.DEFAULT_GOAL := help
.PHONY: help setup test check gen site-check gcs firmware-setup firmware firmware-stick \
        firmware-remote flash-stick flash-remote flash-pico clean

help: ## List the targets
	@echo "VENATOR: make <target>"
	@grep -E '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-16s %s\n", $$1, $$2}'

setup: $(VENV)/.installed ## Create venv/ and install the Python dependencies from pyproject.toml

$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(VPY) -m pip install -q --upgrade pip
	$(VPY) -m pip install -q .
	@touch $@

test: ## Run every test suite CI runs (standard library only, no setup needed)
	@set -e; for t in $(TESTS); do echo "== $$t"; $(PYTHON) $$t; done

check: test ## The whole CI test job: tests, compile check, generated assets, shell syntax
	$(PYTHON) -m compileall -q radio drone ground tests
	@for g in tools/gen_*.py; do $(PYTHON) $$g >/dev/null || exit 1; done
	git diff --exit-code -- assets/brand
	@for f in $$(git ls-files '*.sh'); do bash -n "$$f" || exit 1; done; echo "shell scripts parse"

gen: ## Regenerate the animated assets in assets/brand from tools/gen_*.py
	@for g in tools/gen_*.py; do echo "== $$g"; $(PYTHON) $$g || exit 1; done

site-check: ## The site's language-switch test and HTML validation (needs Node for npx)
	$(PYTHON) tests/test_site_i18n.py
	$(NPX) --yes html-validate@11 --rule 'doctype-style:off' index.html how-it-works.html timeline.html

gcs: setup ## Build the ground-station app for this OS into dist/VenatorGCS, as CI does
	$(VPY) -m pip install -q ".[gcs]"
	$(VPY) -m PyInstaller --onefile --console --paths . --name VenatorGCS \
	    --distpath dist --workpath build/pyinstaller --specpath build/pyinstaller \
	    ground/gcs_client.py
	@echo "built dist/VenatorGCS (try: dist/VenatorGCS --mock)"

firmware-setup: ## Install the Heltec ESP32 board package and library for arduino-cli
	arduino-cli core update-index --additional-urls $(HELTEC_URL)
	arduino-cli core install Heltec-esp32:esp32 --additional-urls $(HELTEC_URL)
	arduino-cli lib install "Heltec ESP32 Dev-Boards"

firmware: firmware-stick firmware-remote ## Compile both LoRa sketches into build/firmware/

firmware-stick: ## Compile LoRa_Transceiver for the Wireless Stick V3 (both sticks run it)
	arduino-cli compile --fqbn $(FQBN_STICK) --output-dir $(FW_OUT)/LoRa_Transceiver \
	    radio/firmware/LoRa_Transceiver

firmware-remote: ## Compile Venator_Remote for the WiFi LoRa 32 V3
	arduino-cli compile --fqbn $(FQBN_REMOTE) --output-dir $(FW_OUT)/Venator_Remote \
	    radio/firmware/Venator_Remote

flash-stick: firmware-stick ## Build and flash a stick: make flash-stick PORT=/dev/cu.usbserial-XXXX
	@test -n "$(PORT)" || { echo "Set the board's port: make $@ PORT=/dev/cu.usbserial-XXXX"; exit 1; }
	arduino-cli upload --fqbn $(FQBN_STICK) --board-options UploadSpeed=$(UPLOAD_SPEED) \
	    --port $(PORT) --input-dir $(FW_OUT)/LoRa_Transceiver radio/firmware/LoRa_Transceiver

flash-remote: firmware-remote ## Build and flash the remote: make flash-remote PORT=/dev/cu.usbserial-XXXX
	@test -n "$(PORT)" || { echo "Set the board's port: make $@ PORT=/dev/cu.usbserial-XXXX"; exit 1; }
	arduino-cli upload --fqbn $(FQBN_REMOTE) --board-options UploadSpeed=$(UPLOAD_SPEED) \
	    --port $(PORT) --input-dir $(FW_OUT)/Venator_Remote radio/firmware/Venator_Remote

flash-pico: setup ## Copy the Pico gateway's main.py: make flash-pico PORT=/dev/cu.usbmodemXXXX
	@test -n "$(PORT)" || { echo "Set the Pico's port: make $@ PORT=/dev/cu.usbmodemXXXX"; exit 1; }
	$(VPY) -m pip install -q ".[pico]"
	$(VENV)/bin/mpremote connect $(PORT) cp radio/firmware/Pico_Gateway/main.py :main.py

clean: ## Remove build outputs (build/, dist/)
	rm -rf build dist *.egg-info
