# -----------------------------------------------------------------------------
# pynq_z2.xdc - PYNQ-Z2 pins and timing for both tops: fpga4x4_top, mini_fpga_top
#
# PLAIN XDC ONLY. Vivado's XDC parser rejects Tcl control flow: 'if', 'catch',
# 'set' variables and 'expr' are "not supported in the xdc constraint file"
# (Designutils 20-1307). They do not stop the build, they are just skipped - and
# the M0 build proved how dangerous that is: the old version of this file chose
# the TCK period with an 'if', so create_clock never ran, TCK had no clock, and
# Vivado analysed nothing while reporting "all constraints met".
# tests/test_layout.py now rejects Tcl commands in this file.
#
# Anything that must depend on the top (the LUTLP-1 downgrade) lives in
# hw/scripts/drc_waiver.tcl, which is real Tcl.
#
# Pin numbers taken from the official PYNQ-Z2 constraints:
#   Xilinx/PYNQ  boards/Pynq-Z2/base/vivado/constraints/base.xdc
#
# PMODA header, physical pin numbering (looking at the board):
#   pin 1  Y18      pin 7  U18
#   pin 2  Y19      pin 8  U19
#   pin 3  Y16      pin 9  W18
#   pin 4  Y17      pin 10 W19
#   pin 5  GND      pin 11 GND
#   pin 6  3V3      pin 12 3V3
#
# TCK is placed on U18 because that pin is IO_L12P_T1_MRCC_34 - clock capable.
# TCK clocks every flip-flop in this design, so it must reach a BUFG over
# dedicated clock routing.  Moving it to any other PMOD pin will trigger a
# CLOCK_DEDICATED_ROUTE DRC error (see the note at the bottom).
# -----------------------------------------------------------------------------

set_property CFGBVS VCCO        [current_design]
set_property CONFIG_VOLTAGE 3.3 [current_design]

# --- JTAG on PMODA -----------------------------------------------------------
set_property -dict {PACKAGE_PIN U18 IOSTANDARD LVCMOS33} [get_ports tck]
set_property -dict {PACKAGE_PIN Y18 IOSTANDARD LVCMOS33} [get_ports tms]
set_property -dict {PACKAGE_PIN Y19 IOSTANDARD LVCMOS33} [get_ports tdi]
set_property -dict {PACKAGE_PIN Y16 IOSTANDARD LVCMOS33} [get_ports tdo]

# Defined levels when the probe is unplugged: TCK parked low, TMS/TDI high.
# TMS high is the safe idle - it walks the TAP to Test-Logic-Reset.
set_property PULLDOWN true [get_ports tck]
set_property PULLUP   true [get_ports tms]
set_property PULLUP   true [get_ports tdi]

# Modest drive on TDO; this is a short point-to-point link, not a bus.
set_property DRIVE 8     [get_ports tdo]
set_property SLEW  SLOW  [get_ports tdo]

# --- Slide switches: pad_i[1:0] ----------------------------------------------
set_property -dict {PACKAGE_PIN M20 IOSTANDARD LVCMOS33} [get_ports {sw[0]}]
set_property -dict {PACKAGE_PIN M19 IOSTANDARD LVCMOS33} [get_ports {sw[1]}]

# --- Push buttons: pad_i[5:2] ------------------------------------------------
set_property -dict {PACKAGE_PIN D19 IOSTANDARD LVCMOS33} [get_ports {btn[0]}]
set_property -dict {PACKAGE_PIN D20 IOSTANDARD LVCMOS33} [get_ports {btn[1]}]
set_property -dict {PACKAGE_PIN L20 IOSTANDARD LVCMOS33} [get_ports {btn[2]}]
set_property -dict {PACKAGE_PIN L19 IOSTANDARD LVCMOS33} [get_ports {btn[3]}]

# --- User LEDs: LD2..LD0 = pad_o, LD3 = configured ---------------------------
set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[3]}]

# --- Board clock: 125 MHz on H16 (M4 user clock) -----------------------------
# H16 / 8 ns as in the community PYNQ-Z2 constraint files (WoodsTechnicalSolutions
# pynq-z2, the TUL pynq-z2_v1.0.xdc copies); confirm against TUL's master XDC.
# fpga4x4_top only: mini_fpga_top has no sysclk port.
set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports sysclk]
create_clock -period 8.000 -name sysclk [get_ports sysclk]

# --- Timing (M13: docs/bitstream-format.md section 11) --------------------------
# TCK clocks the configuration plane, the boundary and the JTAG data registers.
# M7 constrained it at 1 MHz and failed by 657 ns: a real TCK-to-TCK path runs from
# the IR / boundary update cells through the fabric's routing into the DSP JTAG
# capture register (~1650 ns). The probe never runs TCK faster than 100 kHz
# (host/dirtyjtag.py refuses more), so 10 us is the honest period.
create_clock -period 10000.000 -name tck [get_ports tck]

# TMS/TDI are launched by the probe on the falling edge and sampled here on the
# rising edge; TDO is launched here on the falling edge. Loose on purpose.
set_input_delay  -clock tck -max 20.000 [get_ports {tms tdi}]
set_input_delay  -clock tck -min  0.000 [get_ports {tms tdi}]
set_output_delay -clock tck -max 20.000 -clock_fall [get_ports tdo]
set_output_delay -clock tck -min  0.000 -clock_fall [get_ports tdo]

# TCK and sysclk are unrelated. The configuration (TCK domain) changes only while
# GWE = 0 (both the chain and the frame path refuse writes otherwise), and every
# TCK-domain signal the fabric uses as logic passes through clock_ctrl.v's
# ASYNC_REG synchronisers.
set_clock_groups -asynchronous -group [get_clocks tck] -group [get_clocks sysclk]

# M21: TCK -> TCK through the fabric gets the same treatment as sysclk. Configuration
# bits (cfg_reg) and the boundary / IR update cells are TCK registers that drive the
# fabric, and CAPTURE, the boundary capture and the DSP JTAG capture are TCK registers
# fed by it, so Vivado times TCK paths through the UNCONFIGURED mesh too (M7: 1650 ns,
# failed a 1 MHz TCK by 657 ns). On the cluster fabric that loop-cut path passed the
# 10 us period: the second M21 implementation, with sysclk already relaxed, still
# placed at WNS -228 ns, phys_opt working on u_tap/sr_reg, cfg_reg, u_dsp_jtag and
# capture_reg nets. A configured design's pad and capture paths are tens of ns
# (software/bob/timing.py), and a configuration bit never changes while the fabric is
# captured (GWE = 0). So TCK -> TCK gets 16 periods (160 us, past any path through the
# ~4800 fabric muxes). Hold stays at the same edge (-hold 15), so the TAP and shift
# registers' own hold checks are unchanged; their setup paths are a few ns against 10 us
# either way. XDC_TCK_MULTICYCLE in software/bob/device.py, tests/test_layout.py.
set_multicycle_path -setup 16 -from [get_clocks tck] -to [get_clocks tck]
set_multicycle_path -hold  15 -from [get_clocks tck] -to [get_clocks tck]

# Every fabric register (CLB flip-flops, BRAM and DSP state) changes only on a gce
# pulse, and clock_ctrl.v spaces gce pulses in both clock modes (tb_clock_gap.v).
#
# Through M20 this multicycle was that spacing (2**GAP_SHIFT cycles) and had to cover the
# longest path Vivado found through the UNCONFIGURED fabric: every routing mux open, one
# mesh of combinational loops, cut wherever the timer chose. That stopped working at M21.
# The cluster fabric placed at WNS -133 ns against 512 cycles (4096 ns), and at -290 ns
# against 1024 (8192 ns): the path grew with the budget, because the loop cutting, not the
# fabric, decides it. phys_opt then ground on it for hours. (M16: 256 -> 512 was enough;
# M7: 1202 logic levels, 1110 ns.)
#
# From M21 the sign-off is per design, in software: software/bob/timing.py times the
# configured design with delays measured on this build (extract_delays.tcl), and
# timing.contract() refuses to build or load (flow.py, cli.load) any word whose critical
# path x guard band is longer than the gce spacing it runs at - its clk_gap, or the
# default 2**GCE_MIN_GAP_SHIFT. The board's clock-margin check proves the guard band.
# So this multicycle only tells Vivado not to optimise paths that no configuration
# has: 16384 cycles (131 us), past any simple path through the ~4800 fabric muxes.
# It equals XDC_SYSCLK_MULTICYCLE in software/bob/device.py (tests/test_layout.py).
#
# The fabric is flattened (keeping its hierarchy crashed Vivado on the routing
# loops), and M7 showed flattening renames its registers, so the relaxation is by
# clock: every sysclk -> sysclk path gets 16384 cycles. A clock-level set_false_path
# would do the same but override the cell exceptions below (UG903: a false path beats
# any multicycle), so it is a multicycle. The only sysclk logic outside
# the fabric is u_clk (clock_ctrl.v: gce, dividers, synchronisers) and the sysclk
# half of u_bram_jtag (BRAM INIT/readback strobes). Cell-based exceptions take
# precedence over clock-based ones (UG903), so every path starting or ending there
# is held back to one cycle. Their hierarchy is flattened (keep_hierarchy anywhere
# crashed Vivado), so build.tcl writes the cells these filters caught to
# sysclk_1cycle.txt and tests/test_reports.py requires gce and the BRAM strobes in it.
set_multicycle_path -setup 16384 -from [get_clocks sysclk] -to [get_clocks sysclk]
set_multicycle_path -hold  16383 -from [get_clocks sysclk] -to [get_clocks sysclk]
set_multicycle_path -setup 1 -from [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ *u_bram_jtag/* || (NAME =~ *u_clk/* && NAME !~ *u_clk/cin_m_reg*))}]
set_multicycle_path -hold  0 -from [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ *u_bram_jtag/* || (NAME =~ *u_clk/* && NAME !~ *u_clk/cin_m_reg*))}]
set_multicycle_path -setup 1 -to   [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ *u_bram_jtag/* || NAME =~ *u_clk/*)}]
set_multicycle_path -hold  0 -to   [get_cells -hier -filter {IS_SEQUENTIAL && (NAME =~ *u_bram_jtag/* || NAME =~ *u_clk/*)}]
# USER1 cin (u_clk/cin_m_reg) enters the carry chains and changes only by JTAG, so
# its paths into the fabric keep the 16384 cycles.

# The switches, buttons and LEDs are the fabric's pads, asynchronous to TCK.
set_false_path -to   [get_ports {led[*]}]
set_false_path -from [get_ports {sw[*] btn[*]}]

# --- Only needed if TCK is moved off an MRCC pin (e.g. onto PMODB) -----------
# set_property CLOCK_DEDICATED_ROUTE ANY_CMT_COLUMN [get_nets tck_IBUF]
