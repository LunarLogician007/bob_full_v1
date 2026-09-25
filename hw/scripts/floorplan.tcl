# -----------------------------------------------------------------------------
# floorplan.tcl - where every part of bob sits on the XC7Z020 (for docs/learn, volume 3)
#
# Read only. On the routed design it walks every SLICE, RAMB36/RAMB18 and DSP48 site of the
# device and writes one line per site that holds something:
#     <site> <x> <y> <clock region> <group> <cells>
# where <group> names the part of bob that owns most of the site's cells:
#     tap, frames (the packet parser: the "brain"), store (frame buffer + shadow), ctrl,
#     loader (CFGLUT5 loader/expander), capture, clk, bram_jtag, dsp_jtag, bsc (pads),
#     clb_x<X>y<Y> (one guest CLB), mux (the routing muxes), bram0/bram1, dsp0/dsp1, other
# The empty sites are counted, not listed. Seconds to a few minutes.
#
#   with the project open (Tcl console):  source E:/bob_full_v1/hw/scripts/floorplan.tcl
#   or: vivado -mode batch -source E:/bob_full_v1/hw/scripts/floorplan.tcl
# It writes floorplan.txt next to delay_paths.rpt (bob_vivado/out/<tag>/): copy that one
# file into bob_full_v1/docs/reports/<tag>/.
# -----------------------------------------------------------------------------
set script_dir [file dirname [file normalize [info script]]]
set hw_dir     [file normalize $script_dir/..]
source [file join $script_dir bob_cfg.tcl]
set cfg [bob_read_cfg $hw_dir/build.cfg]
set tag [dict get $cfg tag]
set proj_dir [file normalize [file join $hw_dir [dict get $cfg project]]]
if {[catch { current_project }]} { open_project $proj_dir/bob.xpr }
if {[catch { current_design }]} { puts "floorplan: opening the routed design (impl_1)"; open_run impl_1 }
set out_dir $proj_dir/out/$tag
file mkdir $out_dir

# the part of bob a cell belongs to, from its hierarchical name
proc bob_group {name} {
    if {[regexp {u_fabric/(u_clb_x\d+y\d+)/} $name -> clb]} { return [string range $clb 2 end] }
    if {[regexp {u_fabric/u_(bram\d|dsp\d)/} $name -> blk]} { return $blk }
    if {[regexp {u_fabric/m\d+/} $name]} { return mux }
    if {[regexp {u_core/u_([a-z_]+)} $name -> part]} {
        switch -glob -- $part {
            tap*       { return tap }
            frames*    { return frames }
            store*     { return store }
            ctrl*      { return ctrl }
            lutld* - loader* - lut_* - expand* { return loader }
            cap*       { return capture }
            clk*       { return clk }
            bram_jtag* { return bram_jtag }
            dsp_jtag*  { return dsp_jtag }
            bsr* - bsc* - pad* { return bsc }
            fabric     { return mux }
            default    { return $part }
        }
    }
    if {[regexp {g_bsr|u_cell|^u_(bsr|bsc|pad)} $name]} { return bsc }
    return other
}

set t0 [clock seconds]
set fh [open $out_dir/floorplan.txt w]
puts $fh "# floorplan.tcl: [get_property PART [current_design]] design=[current_design]"
puts $fh "# site x y clock_region group cells"
set empty 0; set used 0
foreach kind {SLICEL SLICEM RAMB36E1 RAMB18E1 DSP48E1} {
    foreach s [get_sites -quiet -filter "SITE_TYPE == $kind"] {
        set cells [get_cells -quiet -of_objects $s]
        if {![llength $cells]} { incr empty; continue }
        array unset n
        foreach c $cells {
            set g [bob_group [get_property NAME $c]]
            if {[info exists n($g)]} { incr n($g) } else { set n($g) 1 }
        }
        set best ""; set most 0
        foreach g [array names n] { if {$n($g) > $most} { set most $n($g); set best $g } }
        regexp {_X(\d+)Y(\d+)$} $s -> x y
        puts $fh "$s $x $y [get_property -quiet CLOCK_REGION $s] $best [llength $cells]"
        incr used
    }
}
# the device outline: every clock region's site range, and the empty sites per kind
foreach r [get_clock_regions -quiet] {
    puts $fh "# region [get_property NAME $r] [get_property -quiet TOP_LEFT_TILE $r] [get_property -quiet BOTTOM_RIGHT_TILE $r]"
}
puts $fh "# sites used $used, empty $empty"
close $fh
puts "floorplan: $used sites used, $empty empty, in [expr {[clock seconds] - $t0}] s -> $out_dir/floorplan.txt"
