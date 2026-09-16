# M7, 8x8 core (48 CLBs, 2 BRAMs, 2 DSPs, 32 pads, 9400-bit chain) - frozen 2026-09-15

Built and simulated (tb_bob 852, K=4 722, mutants 25/25, M8 synth flow and tb_synth 486 on this fabric),
but Vivado synthesis was too slow on the build machine. Kept to build later on a faster machine:
paste this hw/ as the Vivado bundle (top bob_top, IDCODE 0x9BEEF093), then run the hardware test from
this folder: cd host && ./hwtest.py --milestone M7  (and M8).
The main tree moved on to the 16-CLB profile (device.py ARCH) the same day.
