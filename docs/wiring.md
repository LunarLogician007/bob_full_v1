# Wiring: Pico (DirtyJTAG) to PYNQ-Z2 PMODA

Five wires. Both sides are 3.3 V CMOS, so no level shifting is needed.

## The connection

| Signal | Pico GPIO | Pico pin | PMODA pin | Zynq pin | Direction |
|--------|-----------|----------|-----------|----------|-----------|
| TCK    | GP18      | 24       | 7         | U18      | Pico → FPGA |
| TMS    | GP19      | 25       | 1         | Y18      | Pico → FPGA |
| TDI    | GP16      | 21       | 2         | Y19      | Pico → FPGA |
| TDO    | GP17      | 22       | 3         | Y16      | FPGA → Pico |
| GND    | GND       | 23       | 5         | —        | — |

**Straight through, no crossover.** JTAG signal names are chain-relative, not
per-device: the probe's `TDI` pin is an *output* that feeds the target's `TDI`
*input*. Wiring TDI↔TDO like a UART is the single most common mistake here and
produces a dead scan chain with no error message.

Pico pin 23 is a ground pin sitting right between GP17 and GP18, so the whole
harness comes off four adjacent positions plus one.

## Power

Power the PYNQ-Z2 and the Pico from **their own USB supplies** and connect
**GND only**.

Do not wire PMODA pin 6 or 12 (3V3) to the Pico's `3V3(OUT)` (pin 36) or `VSYS`
(pin 39). Back-feeding either board's regulator from the other is a good way to
damage one of them.

## PMODA pin numbering

Looking at the 2×6 header on the board, with the notch/silkscreen orientation
matching the reference manual:

```
        +----+----+----+----+----+----+
 top    |  1 |  2 |  3 |  4 |  5 |  6 |   1..4 signal, 5 GND, 6 3V3
        | Y18| Y19| Y16| Y17| GND|3V3 |
        +----+----+----+----+----+----+
 bottom |  7 |  8 |  9 | 10 | 11 | 12 |   7..10 signal, 11 GND, 12 3V3
        | U18| U19| W18| W19| GND|3V3 |
        +----+----+----+----+----+----+
```

## Why TCK is on pin 7 and not pin 4

TCK clocks every flip-flop in the design, so it has to reach a global clock
buffer. `U18` (PMODA pin 7) is `IO_L12P_T1_MRCC_34` — a clock-capable pin with
dedicated routing to a BUFG. The other PMODA pins are ordinary I/O, and placing
TCK on one of them makes Vivado raise a `CLOCK_DEDICATED_ROUTE` DRC error.

If you need to move TCK anyway, uncomment the waiver at the bottom of
`constr/pynq_z2_jtag.xdc`. At 1 MHz the non-dedicated route works fine; the
DRC is protecting against much faster clocks.

## Why PMODA and not PMODB

PMODB is direct-connected while PMODA sits behind 200 Ω series resistors
(it is shared with the Raspberry Pi header). That would argue for PMODB — but
no PMODB pin is clock-capable, and 200 Ω into an FPGA input at ≤6 MHz is
electrically a non-issue. Clean clocking wins.

## Signal integrity

Keep the leads short — under about 15 cm. Use a proper ground return rather
than relying on the USB grounds meeting somewhere upstream. If the link is
flaky, drop the clock before you start rewiring:

```sh
FREQ=100000 ./host/detect.sh
```
