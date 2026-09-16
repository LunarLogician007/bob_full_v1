# -----------------------------------------------------------------------------
# hw/sources.f - THE synthesisable source list, relative to hw/
#
# Read by all three consumers, so they can never compile different files:
#   hw/scripts/build.tcl   Vivado  (adds new entries, removes dropped ones)
#   sim/run_*.sh           iverilog
#   sim/lint.sh            verilator
#
# One path per line, '#' starts a comment. Packages before their users.
# Both board tops are listed; hw/build.cfg (or -tclargs top=...) picks one.
# -----------------------------------------------------------------------------

# CLB: fracturable LUT6 + carry + FF (AMD UG474), and the routing muxes
src/clb/clb_pkg.sv
src/clb/lut6.sv
src/clb/clb.sv
src/clb/mux_bank.v
src/clb/tile.v

# JTAG TAP and the boundary scan cell
src/core/jtag_tap.v
src/core/bsc_cell.v

# M2: 6-bit AMD TAP and the scan-chain configuration plane (docs/bitstream-format.md)
src/core/jtag_tap6.v
src/core/cfg_tile_sr.v
src/core/cfg_mem.v
src/core/cfg_ctrl.v
src/core/capture_chain.v

# fabrics
src/fabric/fabric.v
src/fabric/fpga4x4.v
src/fabric/mini_fpga.v

# board tops (PYNQ-Z2)
src/top/fpga4x4_top.v
src/top/mini_fpga_top.v
src/top/cfg_test_top.v
