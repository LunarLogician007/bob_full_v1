# bob_full_v1 - everything that can be checked on the Mac, in one command.
#
#   make check     simulations + lint + pytest   (run before every hw/ handoff)
#   make rrgraph   after changing the architecture in software/bob/device.py: VPR (Docker)
#                  builds the routing-resource graphs, then everything is regenerated
#   make vpr       after changing an example, the synthesis flow or the architecture:
#                  VPR (Docker) packs, places and routes every example -> software/bob/vpr/
#   make hw        refresh generated files inside hw/ and print the handoff steps
#   make hwtest M=M0   hardware test on the PYNQ-Z2 through the Pico (ONLY=check,check to rerun some)

M ?= $(shell sed -n 's/^tag *= *\([A-Za-z0-9]*\).*/\1/p' hw/build.cfg)

.PHONY: check device rrgraph vpr pnr sim lint test mutate hw hwtest clean clean-logs

# M7: arch XML -> VPR rr graph (Docker, committed) -> device.json / bob_params.vh / bob_fabric.v
rrgraph:
	software/bob/device.py --arch-only
	software/bob/vpr_rrgraph.sh
	software/bob/device.py

# M9/M10: examples (+ pin variants) -> yosys -> VPR on the committed rr graph (Docker) -> software/bob/vpr/<name>/ (committed)
vpr:
	for t in gates adder counter blinky ram mult switches fir wide big atspeed fir16; do software/bob/equiv.py work/examples/$$t/$$t.v || exit 1; done
	software/bob/vpr_run.py --repeat
	# M18: the block-design example, a project (its sources are listed in its .bobproj)
	software/bob/cli.py build --project work/examples/bd_demo/bd_demo.bobproj --pnr python -o build/bit/bd_demo_py.bit
	software/bob/vpr_run.py --repeat bd_demo_bd_wrapper
	software/bob/fasm_from_vpr.py --check

# M12a: bob's own Python pack/place/route vs VPR's committed results (no Docker)
pnr:
	software/bob/pnr/compare.py
.DEFAULT_GOAL := check

# every deliberately broken guard must fail its testbench (slow-ish; not in check)
mutate:
	sim/mutate_cfg.sh
	sim/mutate_fabric.sh
	sim/mutate_frames.sh

# device -> vectors -> sims must run in order even under make -j
.NOTPARALLEL:

check: device sim lint test

# regenerate the architectures, software/bob/device.json, bob_params.vh and bob_fabric.v
# (fails with "run make rrgraph" if the architecture changed since the rr graph was built)
device:
	software/bob/device.py
	software/bob/devtable.py --check
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
	sim/run_frames_sim.sh

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
	cd host && ./hwtest.py --milestone $(M) $(if $(ONLY),--only $(ONLY))

clean:
	rm -f sim/*.vvp sim/*.vcd
	rm -rf .pytest_cache tests/__pycache__ software/host/__pycache__

# build/ is scratch (gitignored). A whole-design yosys run logs every wire it sees,
# so one estimate is over a gigabyte and they accumulate: 7.6 GB by M16.
clean-logs:
	@du -sh build 2>/dev/null || true
	@# Only the known giants, and only ones nothing has written for an hour: a glob
	@# over *.log will happily unlink the log a running `make mutate` is writing to.
	@find build -maxdepth 1 \( -name 'est_*.log' -o -name 'est_*.time' \
	     -o -name 'fab_*.log' -o -name 'fab_*.time' \) -mmin +60 -delete 2>/dev/null || true
	@find build -maxdepth 1 -name synthcheck -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
	@echo "kept: bitstreams, VPR and PnR work dirs, cosim, the page checks, and anything recent"
	@du -sh build 2>/dev/null || true
