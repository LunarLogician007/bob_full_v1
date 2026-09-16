# -----------------------------------------------------------------------------
# create_project.tcl - the whole Vivado flow, in one script and one session
#
#   vivado -mode batch -source vivado/create_project.tcl
#       create the project, synthesise, implement, write the bitstream
#
#   vivado -mode batch -source vivado/create_project.tcl -tclargs all
#       ... and then program the board over the built-in USB-JTAG
#
#   vivado -mode batch -source vivado/create_project.tcl -tclargs program
#       just program, using the bitstream that is already built
#
# Add a top module name to build the other design:
#
#   vivado -mode batch -source vivado/create_project.tcl -tclargs build mini_fpga_top
#   vivado -mode batch -source vivado/create_project.tcl -tclargs mini_fpga_top
#
# There are two tops, and the IDCODE version nibble tells them apart on the
# wire, so you always know which one is in the PL:
#
#   fpga4x4_top    the 4x4 CLB fabric,  IDCODE 0x3BEEF093   (default)
#   mini_fpga_top  the single CLB,      IDCODE 0x2BEEF093
#
# Everything runs in one Vivado session on purpose. Splitting create and build
# across two scripts means the second one has to re-open a project the first one
# already opened, which is exactly the "project already opened" error.
# -----------------------------------------------------------------------------

# --- arguments ---------------------------------------------------------------
set action     "build"
set top_module "fpga4x4_top"

if {[info exists argv]} {
    if {[llength $argv] > 0} { set action     [lindex $argv 0] }
    if {[llength $argv] > 1} { set top_module [lindex $argv 1] }
}
# Allow the top to be given on its own, e.g. -tclargs mini_fpga_top
if {[lsearch -exact {build all program} $action] < 0} {
    set top_module $action
    set action     "build"
}

array set TB_OF {fpga4x4_top tb_fpga4x4  mini_fpga_top tb_mini_fpga}
if {![info exists TB_OF($top_module)]} {
    error "unknown top '$top_module' - expected fpga4x4_top or mini_fpga_top"
}

set script_dir [file normalize [file dirname [info script]]]
set origin     [file normalize $script_dir/..]
set proj_dir   $script_dir/proj_$top_module
set xpr        $proj_dir/$top_module.xpr
set part       xc7z020clg400-1
set bitfile    $origin/$top_module.bit

puts ""
puts "action   : $action"
puts "top      : $top_module"
puts "sources  : $origin"
puts "project  : $xpr"
puts "part     : $part"
puts ""

# Anything left open from an earlier source in the same session would collide.
catch { close_project }

# --- programming -------------------------------------------------------------
proc program_board {bitfile} {
    if {![file exists $bitfile]} {
        error "no bitstream at $bitfile - build it first"
    }
    open_hw_manager
    connect_hw_server
    open_hw_target

    # The Zynq chain holds the ARM DAP as well as the FPGA; pick the FPGA.
    set dev ""
    foreach d [get_hw_devices] {
        if {[string match "xc7z020*" $d]} { set dev $d ; break }
    }
    if {$dev eq ""} {
        error "no xc7z020 on the JTAG chain - devices: [get_hw_devices]"
    }
    puts "programming $dev with $bitfile"

    current_hw_device $dev
    refresh_hw_device -update_hw_probes false $dev
    set_property PROGRAM.FILE $bitfile $dev
    program_hw_devices $dev
    refresh_hw_device $dev
    close_hw_manager

    puts ""
    puts "DONE bitstream loaded. Configuration is volatile - re-run with"
    puts "     -tclargs program after every power cycle."
}

if {$action eq "program"} {
    program_board $bitfile
    exit 0
}

# --- create ------------------------------------------------------------------
create_project -force $top_module $proj_dir -part $part

# The PYNQ-Z2 board files are a third-party install (TUL). The design only needs
# the part, so this stays commented out - uncomment if you have them.
# set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]

set_property target_language Verilog [current_project]

add_files -norecurse [concat [glob -nocomplain $origin/rtl/*.v] \
                             [glob -nocomplain $origin/rtl/*.sv]]
add_files -fileset constrs_1 -norecurse $origin/constr/pynq_z2_jtag.xdc
add_files -fileset sim_1 -norecurse [glob -nocomplain $origin/sim/*.v]

# clb_pkg.sv / lut6.sv / clb.sv come from the CLB project unchanged and are
# SystemVerilog; the TAP, the fabric and the boundary are plain Verilog. Vivado
# will mix them happily, but the .sv files must be typed correctly or the
# package will not elaborate.
set svfiles [get_files -quiet *.sv]
if {[llength $svfiles]} {
    set_property file_type SystemVerilog $svfiles
}

set_property top $top_module         [get_filesets sources_1]
set_property top $TB_OF($top_module) [get_filesets sim_1]

# Both tops select a plain wire instead of a BUFG when SIMULATION is defined,
# so the XSim behavioural flow works without the unisims library.
set_property verilog_define {SIMULATION} [get_filesets sim_1]

update_compile_order -fileset sources_1
update_compile_order -fileset sim_1

# The fabric trips LUTLP-1 by construction - see constr/pynq_z2_jtag.xdc. The
# XDC downgrades it, and these hooks re-apply that at the two implementation
# steps where the check actually runs, because a DRC severity is a tool setting
# rather than a design property and does not always persist between steps.
set_property STEPS.OPT_DESIGN.TCL.PRE \
    $script_dir/drc_waiver.tcl [get_runs impl_1]
set_property STEPS.WRITE_BITSTREAM.TCL.PRE \
    $script_dir/drc_waiver.tcl [get_runs impl_1]

puts ""
puts "project created, starting synthesis and implementation ..."
puts ""

# --- build -------------------------------------------------------------------
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1

# launch_runs does NOT raise on failure, so check explicitly. Without this a
# broken build exits 0 and leaves a stale bitstream sitting in place.
foreach run {synth_1 impl_1} {
    set progress [get_property PROGRESS [get_runs $run]]
    set status   [get_property STATUS   [get_runs $run]]
    if {$progress ne "100%"} {
        error "run $run did not complete: $progress / $status"
    }
}

set bit [lindex [glob -nocomplain $proj_dir/$top_module.runs/impl_1/*.bit] 0]
if {$bit eq ""} {
    error "implementation reported success but produced no bitstream"
}
file copy -force $bit $bitfile

open_run impl_1
report_timing_summary -file $origin/timing.rpt
report_utilization    -file $origin/util.rpt

# Worst negative slack. Ask the run for it first - that property is filled in
# by implementation itself. get_timing_paths is the fallback.
#
# Both can come back EMPTY, and an empty value must not be treated as a number:
# Tcl's < falls back to string comparison, where "" sorts before "0" and an
# absent result would read as "timing failed". That is a false alarm, and on a
# design whose loops make static timing analysis inconclusive it is a likely
# one, so check that we actually have a number before comparing.
set wns ""
catch { set wns [get_property STATS.WNS [get_runs impl_1]] }
if {![string is double -strict $wns]} {
    catch { set wns [get_property SLACK [get_timing_paths -delay_type max -max_paths 1]] }
}

puts ""
puts "bitstream : $bitfile"

if {![string is double -strict $wns]} {
    puts "WNS       : not reported"
    puts ""
    puts "Vivado did not return a worst-slack number. On this design that is"
    puts "expected rather than alarming: the fabric's combinational loops are"
    puts "broken arbitrarily for analysis, so there may be no complete path for"
    puts "it to call the worst one. The bitstream above is written and usable."
    puts "Read timing.rpt if you want the detail."
} elseif {$wns < 0} {
    puts "WNS       : $wns ns"
    puts ""
    puts "WARNING: timing is not met."
    puts ""
    puts "The bitstream is still written, because on this design static timing"
    puts "analysis is inconclusive by construction and a hard failure here would"
    puts "throw away a bitstream that very likely works. But do not ignore it:"
    puts "the usual cause is TCK constrained faster than a path through sixteen"
    puts "tiles of muxes and LUT trees can settle. Raise tck_period in"
    puts "constr/pynq_z2_jtag.xdc - the link is driven at 100 kHz to 1 MHz in"
    puts "practice, so there is a lot of headroom to give away before it"
    puts "matters. If it still fails, drive TCK slower and see if it behaves."
} else {
    puts "WNS       : $wns ns"
}

if {$top_module eq "fpga4x4_top"} {
    puts ""
    puts "Note: the fabric contains combinational loops by construction, so"
    puts "Vivado breaks them arbitrarily for static timing analysis and some"
    puts "paths are not analysed. Any WNS above is indicative rather than"
    puts "exhaustive, which is why TCK is constrained well above how the link"
    puts "is actually driven."
}

puts ""
puts "build OK"

if {$action eq "all"} {
    puts ""
    program_board $bitfile
}
