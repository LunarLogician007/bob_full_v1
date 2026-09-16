# bob_full_v1 - everything that can be checked on the Mac, in one command.
#
#   make check     simulations + lint + pytest   (run before every hw/ handoff)
#   make rrgraph   after changing the architecture in tools/bob/device.py: VPR (Docker)
#                  builds the routing-resource graphs, then everything is regenerated
#   make vpr       after changing an example, the synthesis flow or the architecture:
#                  VPR (Docker) packs, places and routes every example -> tools/bob/vpr/
#   make hw        refresh generated files inside hw/ and print the handoff steps
#   make hwtest M=M0   hardware test on the PYNQ-Z2 through the Pico

M ?= $(shell sed -n 's/^tag *= *\([A-Za-z0-9]*\).*/\1/p' hw/build.cfg)

.PHONY: check device rrgraph vpr sim lint test mutate hw hwtest clean

# M7: arch XML -> VPR rr graph (Docker, committed) -> device.json / bob_params.vh / bob_fabric.v
rrgraph:
	tools/bob/device.py --arch-only
	tools/bob/vpr_rrgraph.sh
	tools/bob/device.py

# M9/M10: examples (+ pin variants) -> yosys -> VPR on the committed rr graph (Docker) -> tools/bob/vpr/<name>/ (committed)
vpr:
	for t in gates adder counter blinky ram mult; do tools/bob/equiv.py examples/$$t.v || exit 1; done
	tools/bob/vpr_run.py --repeat
	tools/bob/fasm_from_vpr.py --check
.DEFAULT_GOAL := check

# every deliberately broken guard must fail its testbench (slow-ish; not in check)
mutate:
	sim/mutate_cfg.sh
	sim/mutate_fabric.sh

# device -> vectors -> sims must run in order even under make -j
.NOTPARALLEL:

check: device sim lint test

# regenerate the architectures, tools/bob/device.json, bob_params.vh and bob_fabric.v
# (fails with "run make rrgraph" if the architecture changed since the rr graph was built)
device:
	tools/bob/device.py
	@echo "=== make check: all green ==="

sim:
	sim/run_sim.sh
	sim/run_clb_sim.sh
	sim/run_bram_sim.sh
	sim/run_dsp_sim.sh
	sim/run_fabric_sim.sh
	sim/run_cfg_sim.sh
	sim/run_k4_sim.sh
	sim/run_synth_sim.sh
	sim/run_cosim_sim.sh

lint:
	sim/lint.sh

test:
	python3 -m pytest -q tests

hw:
	sim/gen_vectors.py
	sim/gen_cfg_vectors.py
	sim/gen_clb_vectors.py
	@echo ""
	@echo "hw/ is ready for tag $(M). On the Vivado machine:"
	@echo "  1. paste $(CURDIR)/hw over the old hw folder"
	@echo "  2. vivado -mode batch -source hw/scripts/build.tcl -tclargs all"
	@echo "  3. copy bob_vivado/out/$(M)/ back to docs/reports/$(M)/"
	@echo "  4. make hwtest M=$(M)"

hwtest:
	cd host && ./hwtest.py --milestone $(M)

clean:
	rm -f sim/*.vvp sim/*.vcd
	rm -rf .pytest_cache tests/__pycache__ host/__pycache__
