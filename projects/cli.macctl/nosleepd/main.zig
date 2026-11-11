const std = @import("std");
const c = @import("bindings.zig");
const builtin = @import("builtin");
var test_disabled: ?bool = false;
var test_journal: JournalState = .absent;
var test_write_fails = false;

// The installed launchd definition supplies fixed, root-controlled paths and uid.
// The only privileged operations are native power-setting calls.
const journal = "/var/db/macctl-nosleep.d/owned";
const journal_dir = "/var/db/macctl-nosleep.d";
const marker = "macctl-nosleep-v1\n";
const max_clients = 64;
var stopping: bool = false;
fn onSignal(_: c_int) callconv(.c) void {
    stopping = true;
}
fn log(msg: [*:0]const u8) void {
    _ = c.fprintf(c.stderr(), "nosleep.d: %s\n", msg);
}
const Client = struct { fd: c_int = -1, state: enum { empty, pending, ac, battery } = .empty, accepted_at: i64 = 0, len: usize = 0, buf: [16]u8 = undefined };
const Power = enum { ac, battery, unknown };

const CF = ?*const anyopaque;
extern "c" fn CFStringCreateWithCString(CF, [*:0]const u8, u32) CF;
extern "c" fn CFDictionaryGetValue(CF, CF) CF;
extern "c" fn CFGetTypeID(CF) usize;
extern "c" fn CFBooleanGetTypeID() usize;
extern "c" fn CFEqual(CF, CF) u8;
extern "c" fn CFRelease(CF) void;
extern "c" var kCFBooleanTrue: CF;
extern "c" var kCFBooleanFalse: CF;
extern "c" fn IOPSCopyPowerSourcesInfo() CF;
extern "c" fn IOPSGetProvidingPowerSourceType(CF) CF;
extern "c" fn IOPMCopySystemPowerSettings() CF;
extern "c" fn IOPMSetSystemPowerSetting(CF, CF) i32;

fn cfString(value: [*:0]const u8) CF {
    return CFStringCreateWithCString(null, value, 0x08000100);
}
fn power() Power {
    const info = IOPSCopyPowerSourcesInfo() orelse return .unknown;
    defer CFRelease(info);
    const source = IOPSGetProvidingPowerSourceType(info) orelse return .unknown;
    const ac = cfString("AC Power") orelse return .unknown;
    defer CFRelease(ac);
    const battery = cfString("Battery Power") orelse return .unknown;
    defer CFRelease(battery);
    if (CFEqual(source, ac) != 0) return .ac;
    if (CFEqual(source, battery) != 0) return .battery;
    return .unknown;
}
fn disabled() ?bool {
    if (builtin.is_test) return test_disabled;
    const settings = IOPMCopySystemPowerSettings() orelse return null;
    defer CFRelease(settings);
    const key = cfString("SleepDisabled") orelse return null;
    defer CFRelease(key);
    const value = CFDictionaryGetValue(settings, key) orelse return false;
    if (CFGetTypeID(value) != CFBooleanGetTypeID()) return null;
    return CFEqual(value, kCFBooleanTrue) != 0;
}
fn setDisabled(value: bool) bool {
    if (builtin.is_test) {
        if (test_write_fails) return false;
        test_disabled = value;
        return true;
    }
    const key = cfString("SleepDisabled") orelse return false;
    defer CFRelease(key);
    if (IOPMSetSystemPowerSetting(key, if (value) kCFBooleanTrue else kCFBooleanFalse) != 0) return false;
    return (disabled() orelse return false) == value;
}
fn syncDir() bool {
    const fd = c.open(journal_dir, c.O_RDONLY | c.O_DIRECTORY | c.O_NOFOLLOW);
    if (fd < 0) return false;
    defer _ = c.close(fd);
    return c.fsync(fd) == 0;
}
fn safeDir() bool {
    var st: c.struct_stat = undefined;
    if (c.lstat(journal_dir, &st) != 0) return false;
    return (st.st_mode & c.S_IFMT) == c.S_IFDIR and st.st_uid == 0 and (st.st_mode & 0o022) == 0;
}
const JournalState = enum { absent, ours, invalid };
fn journalState() JournalState {
    if (builtin.is_test) return test_journal;
    const fd = c.open(journal, c.O_RDONLY | c.O_NOFOLLOW);
    if (fd < 0) return if (c.__error().* == c.ENOENT) .absent else .invalid;
    defer _ = c.close(fd);
    var st: c.struct_stat = undefined;
    if (c.fstat(fd, &st) != 0 or (st.st_mode & c.S_IFMT) != c.S_IFREG or st.st_uid != 0 or (st.st_mode & 0o077) != 0 or st.st_nlink != 1) return .invalid;
    var buf: [64]u8 = undefined;
    const n = c.read(fd, &buf, buf.len);
    if (n < 0) return .invalid;
    return if (std.mem.eql(u8, buf[0..@intCast(n)], marker)) .ours else .invalid;
}
fn makeJournal() bool {
    if (builtin.is_test) {
        if (test_journal != .absent) return false;
        test_journal = .ours;
        return true;
    }
    const fd = c.open(journal, c.O_WRONLY | c.O_CREAT | c.O_EXCL | c.O_NOFOLLOW, @as(c.mode_t, 0o600));
    if (fd < 0) return false;
    const written = c.write(fd, marker.ptr, marker.len);
    const ok = written == marker.len and c.fsync(fd) == 0;
    _ = c.close(fd);
    // Keep even an invalid marker on I/O failure: do not silently overwrite it.
    return ok and syncDir();
}
fn removeJournal() bool {
    if (builtin.is_test) {
        test_journal = .absent;
        return true;
    }
    return c.unlink(journal) == 0 and syncDir();
}
fn restore() bool {
    const state = journalState();
    if (state == .absent) return true;
    if (state != .ours) return false;
    const current = disabled() orelse return false;
    if (current and !setDisabled(false)) return false;
    return removeJournal();
}
fn send(fd: c_int, message: []const u8) bool {
    return c.write(fd, message.ptr, message.len) == message.len;
}
fn closeClient(client: *Client) void {
    if (client.fd >= 0) _ = c.close(client.fd);
    client.* = .{};
}
fn desired(clients: *const [max_clients]Client, source: Power) bool {
    if (source == .unknown) return false;
    for (clients) |client| {
        if (client.state == .battery or (client.state == .ac and source == .ac)) return true;
    }
    return false;
}
fn apply(clients: *const [max_clients]Client, source: Power) bool {
    if (!desired(clients, source)) return restore();
    switch (journalState()) {
        .invalid => return false,
        .ours => {
            // Do not silently fight an external administrator or tool.
            return disabled() orelse false;
        },
        .absent => {
            if ((disabled() orelse return false)) return false;
            if (!makeJournal()) return false;
            if (!setDisabled(true)) {
                _ = restore();
                return false;
            }
            return true;
        },
    }
}
fn reject(client: *Client, msg: []const u8) void {
    _ = send(client.fd, msg);
    closeClient(client);
}

pub fn main(init: std.process.Init.Minimal) void {
    const argv = init.args.vector;
    const recover_only = argv.len == 2 and std.mem.eql(u8, std.mem.span(argv[1]), "--recover");
    if ((!recover_only and argv.len != 3) or c.geteuid() != 0 or !safeDir()) {
        log("requires root, a protected journal directory, socket path, and allowed uid");
        std.process.exit(1);
    }
    // Lock before recovery: a second daemon must never restore a live lease.
    const lock_fd = c.open("/var/db/macctl-nosleep.d/lock", c.O_RDWR | c.O_CREAT | c.O_NOFOLLOW, @as(c.mode_t, 0o600));
    if (lock_fd < 0) {
        log("cannot open daemon lock");
        std.process.exit(1);
    }
    defer _ = c.close(lock_fd);
    var lock_stat: c.struct_stat = undefined;
    if (c.fstat(lock_fd, &lock_stat) != 0 or (lock_stat.st_mode & c.S_IFMT) != c.S_IFREG or lock_stat.st_uid != 0 or (lock_stat.st_mode & 0o077) != 0 or lock_stat.st_nlink != 1 or c.flock(lock_fd, c.LOCK_EX | c.LOCK_NB) != 0) {
        log("daemon lock unavailable or unsafe");
        std.process.exit(1);
    }
    if (!restore()) {
        log("cannot safely recover previous override");
        std.process.exit(1);
    }
    if (recover_only) return;
    const path = std.mem.span(argv[1]);
    const uid = std.fmt.parseInt(c.uid_t, std.mem.span(argv[2]), 10) catch {
        log("invalid uid");
        std.process.exit(1);
    };
    var addr: c.struct_sockaddr_un = std.mem.zeroes(c.struct_sockaddr_un);
    if (!std.mem.eql(u8, path, "/var/run/macctl-nosleep.d/control.sock") or path.len >= addr.sun_path.len) {
        log("invalid socket path");
        std.process.exit(1);
    }
    if (c.mkdir("/var/run/macctl-nosleep.d", @as(c.mode_t, 0o755)) != 0 and c.__error().* != c.EEXIST) {
        log("cannot create socket directory");
        std.process.exit(1);
    }
    var run_dir: c.struct_stat = undefined;
    if (c.lstat("/var/run/macctl-nosleep.d", &run_dir) != 0 or (run_dir.st_mode & c.S_IFMT) != c.S_IFDIR or run_dir.st_uid != 0 or (run_dir.st_mode & 0o022) != 0) {
        log("unsafe socket directory");
        std.process.exit(1);
    }
    const server = c.socket(c.AF_UNIX, c.SOCK_STREAM, 0);
    if (server < 0) {
        log("socket failed");
        std.process.exit(1);
    }
    defer _ = c.close(server);
    addr.sun_family = c.AF_UNIX;
    @memcpy(addr.sun_path[0..path.len], path);
    addr.sun_len = @intCast(@offsetOf(c.struct_sockaddr_un, "sun_path") + path.len + 1);
    // launchd restarts after crashes, which leave the socket pathname behind.
    // Only remove the exact service path when it is a root-owned socket and
    // connecting to it proves no other daemon is listening.
    var st: c.struct_stat = undefined;
    if (c.lstat(argv[1], &st) == 0) {
        if ((st.st_mode & c.S_IFMT) != c.S_IFSOCK or st.st_uid != 0) {
            log("unsafe socket path");
            std.process.exit(1);
        }
        const probe = c.socket(c.AF_UNIX, c.SOCK_STREAM, 0);
        if (probe < 0) {
            log("socket probe failed");
            std.process.exit(1);
        }
        const connected = c.connect(probe, @ptrCast(&addr), addr.sun_len);
        const err = c.__error().*;
        _ = c.close(probe);
        if (connected == 0 or err != c.ECONNREFUSED or c.unlink(argv[1]) != 0) {
            log("socket in use or cannot remove stale socket");
            std.process.exit(1);
        }
    } else if (c.__error().* != c.ENOENT) {
        log("cannot inspect socket path");
        std.process.exit(1);
    }
    if (c.bind(server, @ptrCast(&addr), addr.sun_len) != 0 or c.chmod(argv[1], 0o666) != 0 or c.listen(server, 16) != 0) {
        log("cannot bind socket (remove stale socket before starting)");
        std.process.exit(1);
    }
    defer _ = c.unlink(argv[1]);
    _ = c.signal(c.SIGTERM, onSignal);
    _ = c.signal(c.SIGINT, onSignal);
    var clients: [max_clients]Client = @splat(.{});
    var source: Power = .unknown;
    var last_check: i64 = 0;
    while (!stopping) {
        const now = c.time(null);
        if (now != last_check) {
            last_check = now;
            source = power();
            if (!apply(&clients, source)) {
                log("cannot reconcile sleep override; closing leases");
                for (&clients) |*client| {
                    if (client.state == .ac or client.state == .battery) reject(client, "ERR lease lost\n");
                }
            }
        }
        var fds: [max_clients + 1]c.struct_pollfd = undefined;
        fds[0] = .{ .fd = server, .events = c.POLLIN, .revents = 0 };
        for (&clients, 0..) |client, i| fds[i + 1] = .{ .fd = client.fd, .events = c.POLLIN, .revents = 0 };
        const n = c.poll(&fds, fds.len, 500);
        if (n < 0) continue;
        if (fds[0].revents & c.POLLIN != 0) {
            const fd = c.accept(server, null, null);
            if (fd >= 0) {
                var one: c_int = 1;
                if (c.setsockopt(fd, c.SOL_SOCKET, c.SO_NOSIGPIPE, &one, @sizeOf(c_int)) != 0) {
                    _ = c.close(fd);
                    continue;
                }
                var peer: c.uid_t = undefined;
                var gid: c.gid_t = undefined;
                const free = for (&clients) |*client| {
                    if (client.fd < 0) break client;
                } else null;
                if (c.getpeereid(fd, &peer, &gid) != 0 or peer != uid or free == null) {
                    _ = c.close(fd);
                } else {
                    free.?.* = .{ .fd = fd, .state = .pending, .accepted_at = now };
                }
            }
        }
        for (&clients, 0..) |*client, i| {
            if (client.fd < 0) continue;
            if (client.state == .pending and now - client.accepted_at > 5) {
                closeClient(client);
                continue;
            }
            const events = fds[i + 1].revents;
            if (events & (c.POLLERR | c.POLLHUP | c.POLLNVAL) != 0) {
                closeClient(client);
                continue;
            }
            if (events & c.POLLIN == 0) continue;
            if (client.state != .pending) {
                closeClient(client);
                continue;
            }
            const got = c.read(client.fd, client.buf[client.len..].ptr, client.buf.len - client.len);
            if (got <= 0) {
                closeClient(client);
                continue;
            }
            client.len += @intCast(got);
            if (std.mem.indexOfScalar(u8, client.buf[0..client.len], '\n') == null and client.len < client.buf.len) continue;
            if (std.mem.eql(u8, client.buf[0..client.len], "AC\n")) client.state = .ac else if (std.mem.eql(u8, client.buf[0..client.len], "BATTERY\n")) client.state = .battery else {
                reject(client, "ERR invalid request\n");
                continue;
            }
            source = power();
            if (source == .unknown or (source == .battery and client.state == .ac)) {
                reject(client, "ERR power source not eligible\n");
                continue;
            }
            if (!apply(&clients, source)) {
                reject(client, "ERR cannot enable sleep override\n");
                continue;
            }
            if (!send(client.fd, "OK\n")) closeClient(client);
        }
        if (!apply(&clients, source)) log("cannot reconcile sleep override; retrying");
    }
    for (&clients) |*client| closeClient(client);
    if (!restore()) {
        log("failed to restore sleep; recovery journal retained");
        std.process.exit(1);
    }
}

test "lease reconciliation and recovery fail closed" {
    var clients: [max_clients]Client = @splat(.{});
    test_journal = .absent;
    test_disabled = false;
    test_write_fails = false;
    clients[0].state = .ac;
    try std.testing.expect(tryApply(&clients, .ac));
    try std.testing.expect(test_disabled.? and test_journal == .ours);
    // Unplugging suspends the AC-only lease and restores sleep.
    try std.testing.expect(tryApply(&clients, .battery));
    try std.testing.expect(!test_disabled.? and test_journal == .absent);
    // A battery lease keeps it active even while the AC-only lease is suspended.
    clients[1].state = .battery;
    try std.testing.expect(tryApply(&clients, .battery));
    try std.testing.expect(test_disabled.? and test_journal == .ours);
    clients[1].state = .empty;
    try std.testing.expect(tryApply(&clients, .unknown));
    try std.testing.expect(!test_disabled.? and test_journal == .absent);
    // Never clear an override found before this daemon owns it.
    test_disabled = true;
    try std.testing.expect(!tryApply(&clients, .ac));
    try std.testing.expect(test_disabled.? and test_journal == .absent);
    // An owned journal survives a failed restore, so startup can retry it.
    test_journal = .ours;
    test_write_fails = true;
    try std.testing.expect(!restore());
    try std.testing.expect(test_journal == .ours and test_disabled.?);
    test_write_fails = false;
    try std.testing.expect(restore());
    try std.testing.expect(test_journal == .absent and !test_disabled.?);
}
fn tryApply(clients: *const [max_clients]Client, source: Power) bool {
    return apply(clients, source);
}
