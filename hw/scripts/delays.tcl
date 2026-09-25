# -----------------------------------------------------------------------------
# delays.tcl - measure the fabric's per-element delays on the LAST build, without rebuilding
#
# M25: build.tcl no longer does this by default (build.cfg delays = 0): the ~1100 timing
# reports only read timing, need nothing new from the build, and are wanted only when the
# fabric changed. Run it after build.tcl has finished:
#
#   vivado -mode batch -source E:/bob_full_v1/hw/scripts/delays.tcl
#
# or, with the project already open in the GUI, in the Tcl console:
#
#   source E:/bob_full_v1/hw/scripts/delays.tcl
#
# It opens <project>/bob.xpr (build.cfg 'project') unless a project is open, opens the
# routed design (impl_1) unless one is open, and writes <project>/out/<tag>/delay_paths.rpt
# (extract_delays.tcl, with delay_samples.txt from software/bob/delays.py plan). On the Mac:
#   software/bob/delays.py fold docs/reports/<tag>/delay_paths.rpt
# -----------------------------------------------------------------------------

set script_dir [file dirname [file normalize [info script]]]
set hw_dir     [file normalize $script_dir/..]
source [file join $script_dir bob_cfg.tcl]

set cfg      [bob_read_cfg $hw_dir/build.cfg]
set tag      [dict get $cfg tag]
set proj_dir [file normalize [file join $hw_dir [dict get $cfg project]]]
set xpr      $proj_dir/bob.xpr
set out_dir  $proj_dir/out/$tag

if {[catch { current_project }]} {
    if {![file exists $xpr]} { error "delays: no project at $xpr - run build.tcl first" }
    puts "delays: opening $xpr"
    open_project $xpr
}
if {[catch { current_design }]} {
    puts "delays: opening the routed design (impl_1)"
    open_run impl_1
}
file mkdir $out_dir
set t0 [clock seconds]
source [file join $script_dir extract_delays.tcl]
puts "delays: done in [expr {[clock seconds] - $t0}] s - copy $out_dir/delay_paths.rpt to bob_full_v1/docs/reports/$tag/"
