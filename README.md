# TimeMachines Clock Flasher

TimeMachines makes a series of PoE and Wi-Fi-enabled clocks that get their time from NTP. They're pretty neat, and way easier to read than almost any other clock I've found.

They're also some of the least expensive commercial-grade LCD clocks, and you can sometimes find them on sale for a good price on eBay or Marketplace.

But TimeMachines has some pretty ancient software. The [downloads page](https://timemachinescorp.com/downloads/) has a flasher (TM-Flash) that runs on "Windows 10 or later", and the TM-Manager application has a macOS version, but it's a little buggy.

I came into possession of a number of TM WiFi clocks running version 3.0—3.7 was the latest as of 2026. I wanted to update the clocks from my Mac or my Linux PC, so I figured a Python CLI tool would be more universal.

I also figured this would be a nice test of a new AI model that came out today: I threw the TM-Manger .exe file and the 3.7 .bin firmware file into the following prompt, and after a couple small tweaks, had a functional Python version of their application:

```
TimeMachines has a TM-Flash application exe for Windows that you can download - I grabbed "Devices with a serial number that Start with a "C". [Download Version 3.7](https://timemachinescorp.com//wp-content/uploads/WiFiClock_3.7_Update.zip)"
But I'm on a Mac. Can you reverse engineer the upgrading process so I can do it from Mac or Linux too?
```

Opus 5.5 took about 8 minutes and spat out `tmflash.py`.

## Usage

> **NOTE**: I've only tested with TimeMachines WiFi clocks with serial numbers starting with 'C'. I can't guarantee this flasher will work with other clocks.

First, download the latest firmware file (zip) from TimeMachines' website, and expand the archive so you can see the `.bin` file inside (for mine, it was version 3.7 for clocks starting with 'C', so `wificlockMB_3.7_revCHW.bin`). Copy that file into this repository (or specify its full path in the commands later on).

Then:

  1. Plug the clock into wired Ethernet and power-cycle it so it comes up wired.
  1. Double-click the reset button on the back to see its wired IP address.
  1. Make sure Internet Sharing or any other local DHCP or TFTP server is not running.
  1. Perform a dry run: `sudo python3 tmflash.py [IP address] wificlockMB_3.7_revCHW.bin --dry-run`

> If you are using a non-default password (`tmachine`), specify the password with `-p PASSWORD_HERE`. Note that TimeMachines only allowed up to 12 character passwords on their older clocks (not sure about newer ones).

You should see something like:

```
$ sudo python3 tmflash.py 10.0.100.163 wificlockMB_3.7_revCHW.bin --dry-run
[tmflash] firmware 375068 bytes, target tag 'I' (WiFi Type C)
[tmflash] discovered WiFi rev 3, MAC 70:b3:d5:75:65:a8
[tmflash] using host IP 10.0.100.132
[tmflash] challenge '3999120' -> code 1001278090818093101
```

This means everything _should_ succeed when you actually try updating the clock. Now go ahead and run without `--dry-run`:

```
$ sudo python3 tmflash.py 10.0.100.163 wificlockMB_3.7_revCHW.bin
[tmflash] firmware 375068 bytes, target tag 'I' (WiFi Type C)
[tmflash] discovered WiFi rev 3, MAC 70:b3:d5:75:65:a8
[tmflash] using host IP 10.0.100.132
[tmflash] challenge '3485516' -> code 981248486809393101
[tmflash] update_code accepted (connection closed: ConnectionResetError)
[tmflash] magic packet sent; clock should reboot into bootloader
[tmflash] waiting for BOOTP from 70:b3:d5:75:65:a8 (up to 90s)...
[tmflash] BOOTP request seen, reply #1 -> 10.0.100.163:68
[tmflash] TFTP RRQ 'firmware.bin' from 10.0.100.163:13633
[tmflash] sent block 733/733 (100%)
[tmflash] transfer done in 14.0s; clock should reboot into new firmware
```

It's best to have your computer plugged into the same wired network, as TFTP doesn't like having flaky WiFi connections.

At this point, the clock should reboot, and you should see the new version number flash across the digits while it's starting up. If that happens, you're done!

## AI Disclosure

I don't know how to license code that was spit out by AI tools, so 'do what you want with it' is the best I can do. The README is entirely my own work, but the Python script was written by Claude Opus 5.5.
