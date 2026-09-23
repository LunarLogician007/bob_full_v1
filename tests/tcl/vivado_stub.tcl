# -----------------------------------------------------------------------------
# vivado_stub.tcl - just enough of Vivado's Tcl API to run hw/scripts/build.tcl
# under plain tclsh on the Mac, so its project-reuse and file-sync logic is
# tested before it ever reaches the Vivado machine.
#
# Project state (file sets, properties, run status) persists in the file named by
# $env(BOB_STUB_STATE) between invocations, the way a real .xpr does.
# Every call that would change the project is logged as "STUB: ..." on stdout.
# -----------------------------------------------------------------------------

set ::stub_state $::env(BOB_STUB_STATE)
array set ::stub_fs {sources_1 {} constrs_1 {} sim_1 {}}
array set ::prop {}
set ::project_open 0
set ::runs_done 0
set ::xpr_path ""
set ::stub_part ""

proc stub_log {msg} { puts "STUB: $msg" }

proc stub_save {} {
    set fh [open $::stub_state w]
    puts $fh [list array set ::stub_fs [array get ::stub_fs]]
    puts $fh [list array set ::prop [array get ::prop]]
    puts $fh [list set ::runs_done $::runs_done]
    puts $fh [list set ::stub_part $::stub_part]
    close $fh
}

proc create_project {name dir args} {
    set ::xpr_path $dir/$name.xpr
    set i [lsearch $args -part]
    if {$i >= 0} { set ::stub_part [lindex $args [expr {$i + 1}]] }
    close [open $::xpr_path w]
    set ::project_open 1
    stub_log "create_project $::xpr_path"
    stub_save
}

proc open_project {xpr} {
    if {[file exists $::stub_state]} { source $::stub_state }
    set ::xpr_path $xpr
    set ::project_open 1
    stub_log "open_project $xpr"
}

proc close_project {} {
    if {!$::project_open} { error "no open project" }
    stub_save
    set ::project_open 0
}

proc current_project {} { return proj }
proc get_filesets {name} { return $name }
proc get_runs {name} { return $name }

proc get_files {args} {
    set i [lsearch $args -of_objects]
    if {$i >= 0} { return $::stub_fs([lindex $args [expr {$i + 1}]]) }
    set pat [lindex $args end]
    set out {}
    foreach k [array names ::stub_fs] {
        foreach f $::stub_fs($k) {
            if {[string match $pat [file tail $f]]} { lappend out $f }
        }
    }
    return $out
}

proc add_files {args} {
    set i [lsearch $args -fileset]
    set fs [lindex $args [expr {$i + 1}]]
    foreach f [lindex $args end] {
        if {![file exists $f]} { error "add_files: no such file $f" }
        lappend ::stub_fs($fs) $f
        stub_log "add_files $fs $f"
    }
}

proc remove_files {args} {
    set i [lsearch $args -fileset]
    set fs [lindex $args [expr {$i + 1}]]
    set f [lindex $args end]
    set j [lsearch -exact $::stub_fs($fs) $f]
    if {$j < 0} { error "remove_files: $f not in $fs" }
    set ::stub_fs($fs) [lreplace $::stub_fs($fs) $j $j]
    stub_log "remove_files $fs $f"
}

proc set_property {args} {
    set ::prop([lindex $args 0],[lindex $args end]) [lindex $args 1]
}

proc get_property {name obj} {
    switch -- $name {
        NAME { return $obj }
        PART {
            if {[info exists ::prop(PART,proj)]} { return $::prop(PART,proj) }
            return $::stub_part
        }
        PROGRESS  { return [expr {$::runs_done ? "100%" : "0%"}] }
        STATUS    { return "stub" }
        DIRECTORY { return [file dirname $::xpr_path]/bob.runs/$obj }
        STATS.WNS { return 1.234 }
        default   { return "" }
    }
}

proc reset_run {run} {
    set ::runs_done 0
    foreach b [glob -nocomplain [get_property DIRECTORY $run]/*.bit] { file delete $b }
    stub_log "reset_run $run"
}

proc launch_runs {run args} {
    set d [get_property DIRECTORY $run]
    file mkdir $d
    set fh [open $d/$::prop(top,sources_1).bit w]
    puts $fh "fake bitstream generic=$::prop(generic,sources_1)"
    close $fh
    set ::runs_done 1
    stub_log "launch_runs $run"
}

proc wait_on_run {args} {}
proc update_compile_order {args} {}
proc open_run {args} {}
proc get_timing_paths {args} { return "" }
proc report_timing_summary {args} { close [open [lindex $args end] w] }
proc report_utilization {args}    { close [open [lindex $args end] w] }
proc report_drc {args}            { close [open [lindex $args end] w] }
# M23: BOB_STUB_RENAME=1 plays a netlist that filed the fabric under another block (as the
# M21/M22 builds did: u_core/u_store/u_fabric/...): exact u_core/u_fabric/ names find
# nothing, and a hierarchical listing returns the renamed objects of delay_samples.txt.
proc stub_renamed {kind} {
    set out {}
    set fh [open $::samples r]
    foreach line [split [read $fh] "\n"] {
        set line [string trim $line]
        if {$line eq "" || [string index $line 0] eq "#"} { continue }
        lassign $line cls a b
        foreach {obj k} [list $a [expr {$cls eq "ffq" ? "cells" : "nets"}] $b [expr {$cls eq "ffd" ? "cells" : "nets"}]] {
            if {$k eq $kind} { lappend out [string map {u_core/u_fabric/ u_core/u_store/u_fabric/} $obj] }
        }
    }
    close $fh
    return [lsort -unique $out]
}
proc stub_rename {} { return [expr {[info exists ::env(BOB_STUB_RENAME)] && $::env(BOB_STUB_RENAME) eq "1"}] }
proc get_cells {args} {
    # the sysclk_1cycle listing asks with -hier -filter: nothing; a named cell: itself
    if {[lsearch -glob $args -hier*] >= 0} {
        if {[stub_rename] && [string match *u_fabric* [lindex $args end]]} { return [stub_renamed cells] }
        return {}
    }
    set n [lindex $args end]
    if {[stub_rename] && [string match u_core/u_fabric/* $n]} { return {} }
    return $n
}
proc get_nets {args} {
    if {[lsearch -glob $args -hier*] >= 0} {
        if {[stub_rename]} { return [stub_renamed nets] }
        return {}
    }
    set n [lindex $args end]
    if {[stub_rename] && [string match u_core/u_fabric/* $n]} { return {} }
    return $n
}
# M20 extract_delays.tcl: a report in Vivado's text layout, with fixed numbers the test
# folds back (a hop of 1.500 ns, clock-to-Q 1.200 ns, input -> D 1.050 ns with setup).
proc report_timing {args} {
    set thr {}; set from ""; set to ""
    for {set i 0} {$i < [llength $args]} {incr i} {
        switch -- [lindex $args $i] {
            -through { incr i; lappend thr [lindex $args $i] }
            -from    { incr i; set from [lindex $args $i] }
            -to      { incr i; set to [lindex $args $i] }
        }
    }
    set r "Slack (MET) :              4000.000ns  (required time - arrival time)\n"
    if {$from ne ""} {
        append r "    SLICE_X1Y1           FDRE (Prop_fdre_C_Q)         0.456     5.456 r  $from/Q\n"
        append r "                         net (fo=1, routed)           0.744     6.200    [lindex $thr 0]\n"
    } elseif {$to ne ""} {
        append r "                         net (fo=1, routed)           0.500     3.000    [lindex $thr 0]\n"
        append r "    SLICE_X1Y1           LUT6 (Prop_lut6_I0_O)        0.124     3.124 r  x/O\n"
        append r "                         net (fo=1, routed)           0.876     4.000    x_n_0\n"
        append r "    SLICE_X1Y1           FDRE (Setup_fdre_C_D)       -0.050     8.000    $to\n"
        append r "                         -------------------------------------------------------------------\n"
        append r "                                                              4.000   arrival time\n"
    } else {
        append r "                         net (fo=1, routed)           0.500    10.000    [lindex $thr 0]\n"
        append r "    SLICE_X1Y1           LUT4 (Prop_lut4_I0_O)        0.124    10.124 r  u_core/u_fabric/i___1_i_2/O\n"
        append r "                         net (fo=1, routed)           1.376    11.500    [lindex $thr 1]\n"
    }
    return $r
}
proc launch_simulation {args} { stub_log "launch_simulation $args" }
proc run {args} { stub_log "run $args" }
proc close_sim {} {}
