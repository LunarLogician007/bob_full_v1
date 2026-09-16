# hw/ — the Vivado bundle

This folder is everything Vivado needs. Copy it to the Vivado machine; nothing outside it is read.

```
hw/
  sources.f          ordered source list (Vivado, iverilog and verilator all read it)
  build.cfg          tag, top, IDCODE, part, XDC, sim top, project location
  src/               synthesisable RTL
  tb/                testbenches + generated vectors.vh (XSim)
  constr/            pynq_z2.xdc
  scripts/           build.tcl, drc_waiver.tcl
```

## Every milestone

On the Mac:

```sh
make check          # sims + lint + pytest must be green
make hw             # refreshes hw/tb/vectors.vh, prints these steps
```

On the Vivado machine, with the folder at e.g. `C:\bob\hw`:

1. **Paste the new `hw` over the old one.** Replace the files; the project is not inside it.
2. From any directory, run:
   ```
   vivado -mode batch -source C:/bob/hw/scripts/build.tcl -tclargs all
   ```
   - The first time, it creates the project at `C:\bob\bob_vivado\`.
   - After that it **opens the same project**. It adds files that are new in `sources.f` and removes ones no longer listed. It rebuilds only if a source, the XDC or `build.cfg` actually changed. Line endings are ignored, so a CRLF copy doesn't count as a change.
3. Copy `C:\bob\bob_vivado\out\<tag>\` (bitstream, `timing.rpt`, `util.rpt`, `drc.rpt`, logs, `build_info.txt`) back to `bob_full_v1/docs/reports/<tag>/`.
4. On the Mac with the Pico attached, run `make hwtest`.

## From the Vivado GUI

**Tools → Run Tcl Script → `hw/scripts/build.tcl`** does a plain `build`. The project is created at `bob_vivado/`, next to `hw/`, and stays open when the build finishes so you can look at the reports. The GUI can't pass `-tclargs`, so for any other action type this in the Tcl Console:

```
set bob_args {all}
source C:/bob/bob_full_v1/hw/scripts/build.tcl
```

`bob_args` is used once and then cleared.

## Actions

| `-tclargs` | does |
|---|---|
| *(none)* / `build` | sync the project, build if anything changed |
| `all` | build, then program over the board's USB-JTAG |
| `program` | program `out/<tag>/<top>.bit` only (after a power cycle) |
| `force` | rebuild even if nothing changed |
| `sim` | XSim behavioural run of `sim_top` |
| `status` | print what would be added, removed or rebuilt; changes nothing |

Any `build.cfg` key can be overridden, e.g. `-tclargs all top=mini_fpga_top`.
