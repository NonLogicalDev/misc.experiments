# macctl

A small macOS command-line tool for keyboard and built-in display brightness. It uses the private CoreBrightness and DisplayServices frameworks, so it may stop working after a macOS update. It has no network access or runtime dependency beyond macOS system libraries. The optional closed-lid service runs in the background.

Build with Zig 0.17 on macOS:

```sh
zig translate-c nosleepd/bindings.h -lc > nosleepd/bindings.zig
zig build-exe main.zig -O ReleaseSafe -lc -lobjc -framework CoreGraphics -framework IOKit -framework CoreFoundation -femit-bin=macctl
zig build-exe nosleepd/main.zig -O ReleaseSafe -lc -framework IOKit -framework CoreFoundation -femit-bin=macctl-nosleepd
```

```sh
./macctl get        # keyboard ID and brightness, one line per keyboard
./macctl set 0.5    # set every backlit keyboard to a level from 0 to 1
./macctl off
./macctl max
./macctl auto        # keyboard ID and automatic-brightness state, 1 or 0
./macctl auto off
./macctl auto on
./macctl list        # keyboard IDs

./macctl display get       # built-in display ID and brightness
./macctl display set 0.5   # set built-in display brightness
./macctl display off       # can make the screen completely dark
./macctl display max
```

Display commands target the active built-in display, not external monitors. Display automatic brightness can change a manually set level.

Keyboard automatic brightness may change a manually set level. Turn it off first if the level should remain fixed. The setters affect all detected backlit keyboards; they do not change the automatic setting implicitly. Invalid inputs fail without changing settings. The private API exposes no confirmed success status, so read the value back to verify changes.

Inspired by the CoreBrightness calls in [macos-keyboard-backlight](https://github.com/noluyorAbi/macos-keyboard-backlight), revision `73eafe7a7be33fdd95f6738d76cfd61a18851f74`. This implementation covers direct brightness and automatic adjustment; it does not implement that project's pulse, sunrise, or scheduling features.

## Prevent idle sleep

`nosleep` runs in the foreground and requests a system-sleep assertion that is effective on AC power until it exits. It uses IOKit directly and does not require the optional daemon. Press Ctrl-C to stop an indefinite session. It does not turn on the display or alter persistent `pmset` settings.

```sh
./macctl nosleep                         # until interrupted
./macctl nosleep --timeout 300           # seconds
./macctl nosleep --until 2026-12-01T18:30:00  # local time
./macctl nosleep --pid 12345             # until that process exits
./macctl nosleep --exec make test        # until the command exits
./macctl nosleep --allow-battery --exec make test  # also prevent idle sleep on battery
./macctl nosleep --closed-lid --timeout 300       # use the optional daemon
```

The modes are mutually exclusive; `--allow-battery` must come before the mode. `--until` uses local time and rejects past or invalid dates. `--exec` returns the wrapped command's exit status. By default, the system-sleep assertion is effective only on AC power. `--allow-battery` additionally prevents idle system sleep on battery; it does not prevent all sleep on battery. For closed-lid operation, `--closed-lid` requests a connection to the optional privileged daemon. The daemon disables system sleep while eligible connections exist and restores it when they end. AC-only connections remain open on battery, but do not keep sleep disabled unless another connection allows battery. Other sleep causes, including lid close, can still apply. Use `pmset -g assertions` to inspect active assertions.

The closed-lid service is optional. It requires administrator access for installation and removal:

```sh
./macctl nosleep.d status
sudo ./macctl nosleep.d install
sudo ./macctl nosleep.d uninstall
```

The daemon keeps a connection open per `--closed-lid` session. It restores its own system-wide sleep override after the last eligible session ends and on restart before accepting new connections. An existing override owned by another program is left alone. Closed-lid sessions on battery require `--allow-battery`. If power is unplugged, AC-only sessions stay connected but no longer keep sleep disabled; they become eligible again when power returns.

The system-wide setting has no ownership token, so another program changing it at the same time can interfere. A crash can leave it set until the service restarts. Clearing it does not necessarily make an already-closed Mac sleep immediately.
