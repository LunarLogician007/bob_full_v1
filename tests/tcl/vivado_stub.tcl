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
proc launch_simulation {args} { stub_log "launch_simulation $args" }
proc run {args} { stub_log "run $args" }
proc close_sim {} {}
