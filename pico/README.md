# Raspberry Pi Pico as the JTAG probe

The Pico runs [pico-dirtyJtag](https://github.com/phdussud/pico-dirtyJtag),
a port of Jean Thomas's DirtyJTAG to the RP2040. It presents a vendor-specific
USB interface at **`1209:c0ca`**, which both `openFPGALoader` (cable
`dirtyJtag`) and `urjtag` (cable `DirtyJTAG`) speak natively.

## Flashing

Release **V1.07** ships a prebuilt UF2 for the RP2040, so there is no SDK to
install:

1. Download `dirtyJtag.uf2` from
   <https://github.com/phdussud/pico-dirtyJtag/releases/tag/V1.07>
2. Hold **BOOTSEL** on the Pico while plugging in its USB cable.
3. A volume named `RPI-RP2` appears. Copy `dirtyJtag.uf2` onto it.
4. The Pico reboots and re-enumerates as the JTAG probe.

Confirm it came up:

```sh
openFPGALoader --scan-usb          # expect 1209:c0ca
picotool info                      # optional, identifies the board
```

On a Pico 2 / RP2350 the prebuilt image does **not** apply — that needs a build
from source against the Pico SDK with `PICO_PLATFORM=rp2350`.

## Pinout

These are the firmware defaults from `dirtyJtagConfig.h`:

| Signal | GPIO | Pico pin |
|--------|------|----------|
| TDI    | GP16 | 21 |
| TDO    | GP17 | 22 |
| TCK    | GP18 | 24 |
| TMS    | GP19 | 25 |
| RST    | GP20 | 26 |
| TRST   | GP21 | 27 |

Our TAP has no TRST or system-reset input, so GP20 and GP21 stay unconnected.
See [`../docs/wiring.md`](../docs/wiring.md) for the full harness.

## macOS notes

The vendor interface is claimed through libusb, so no driver or kext is needed.
If a tool reports that it cannot claim the interface, make sure nothing else has
the device open — a previous `openFPGALoader` or `jtag` process that did not
exit cleanly will hold it.

## Speed

Start at 100 kHz on first contact and raise it once the link is proven:

```sh
FREQ=100000 ../host/detect.sh      # first try
FREQ=1000000 ../host/detect.sh     # normal
```

The firmware clocks considerably faster than this (it drives the pins from a
PIO state machine), but the soft TAP is constrained to a 5 MHz ceiling in
`constr/pynq_z2_jtag.xdc` and there is nothing to gain from pushing it.
