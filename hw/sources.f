# -----------------------------------------------------------------------------
# hw/sources.f - THE synthesisable source list, relative to hw/
#
# Read by all three consumers, so they can never compile different files:
#   hw/scripts/build.tcl   Vivado  (adds new entries, removes dropped ones)
#   sim/run_*.sh           iverilog
#   sim/lint.sh            verilator
#
# One path per line, '#' starts a comment. Packages before their users.
# Every board top is listed; hw/build.cfg (or -tclargs top=...) picks one.
# M7 retired the hand-written 4x4 fabric (fabric.v, tile.v, mux_bank.v,
# fpga4x4*.v, bram_tile.v, dsp_tile.v); they stay frozen in release/hw_M6.
# -----------------------------------------------------------------------------

# CLB: fracturable LUT + carry + FF (AMD UG474)
src/clb/clb_pkg.sv
src/clb/lutk.sv
src/clb/clb.sv

# JTAG TAP and the boundary scan cell
src/core/jtag_tap.v
src/core/bsc_cell.v

# M2: 6-bit AMD TAP and the scan-chain configuration plane (docs/bitstream-format.md)
src/core/jtag_tap6.v
src/core/cfg_tile_sr.v
src/core/cfg_mem.v
src/core/cfg_ctrl.v
src/core/cfg_store.v
src/core/cfg_frames.v
src/core/capture_chain.v

# M4: user clock (sysclk + enable) and its synchronisers
src/core/clock_ctrl.v

# M5: BRAM (AMD UG473 RAMB18E1 behaviour, one inferred RAMB18 per block)
src/tiles/bram_core.v
src/tiles/bram_jtag.v
src/tiles/bram_block.v

# M6: DSP (AMD UG479 DSP48E1 behaviour, trimmed)
src/tiles/dsp_core.v
src/tiles/dsp_jtag.v
src/tiles/dsp_block.v

# M7: the fabric generated from VPR's routing-resource graph (software/bob/device.py)
src/fabric/bob_mux.v
src/generated/bob_fabric.v
src/fabric/bob_fpga.v

# single-CLB bring-up fabric (M0)
src/fabric/mini_fpga.v

# board tops (PYNQ-Z2)
src/top/bob_top.v
src/top/mini_fpga_top.v
src/top/cfg_test_top.v
