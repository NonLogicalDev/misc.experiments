const std = @import("std");
extern "c" fn execvp([*:0]const u8, [*:null]const ?[*:0]const u8) c_int;
const CF = ?*const anyopaque;
extern "c" fn CFStringCreateWithCString(CF, [*:0]const u8, u32) CF;
extern "c" fn CFRelease(CF) void;
extern "c" fn IOPMAssertionCreateWithName(CF, u32, CF, *u32) i32;
fn assertion(kind: [*:0]const u8) void {
    const name = CFStringCreateWithCString(null, "macctl nosleep", 0x08000100) orelse fail("cannot create assertion name");
    defer CFRelease(name);
    const typ = CFStringCreateWithCString(null, kind, 0x08000100) orelse fail("cannot create assertion type");
    defer CFRelease(typ);
    var id: u32 = 0;
    if (IOPMAssertionCreateWithName(typ, 255, name, &id) != 0) fail("cannot create sleep assertion");
}
extern "c" fn socket(c_int, c_int, c_int) c_int;
extern "c" fn connect(c_int, *const SockAddr, u32) c_int;
extern "c" fn read(c_int, [*]u8, usize) isize;
extern "c" fn write(c_int, [*]const u8, usize) isize;
extern "c" fn close(c_int) c_int;
extern "c" fn fork() c_int;
extern "c" fn waitpid(c_int, *c_int, c_int) c_int;
extern "c" fn kill(c_int, c_int) c_int;
extern "c" fn signal(c_int, *const fn (c_int) callconv(.c) void) ?*const anyopaque;
extern "c" fn getpeereid(c_int, *u32, *u32) c_int;
extern "c" fn poll([*]PollFd, c_uint, c_int) c_int;
extern "c" fn clock_gettime(c_int, *Timespec) c_int;
const PollFd = extern struct { fd: c_int, events: i16, revents: i16 = 0 };
const Timespec = extern struct { sec: i64, nsec: i64 };
extern "c" fn sleep(c_uint) c_uint;
extern "c" fn _exit(c_int) noreturn;
extern "c" fn kqueue() c_int;
extern "c" fn kevent(c_int, ?[*]const KEvent, c_int, ?[*]KEvent, c_int, ?*const anyopaque) c_int;
const SockAddr = extern struct { len: u8, family: u8, path: [104]u8 };
const KEvent = extern struct { ident: usize, filter: i16, flags: u16, fflags: u32, data: isize, udata: ?*anyopaque };
var child_pid: c_int = 0;
fn interrupted(sig: c_int) callconv(.c) void {
    if (child_pid > 0) _ = kill(child_pid, sig);
    _exit(128 + sig);
}
extern "c" fn time(?*i64) i64;
extern "c" fn strptime([*:0]const u8, [*:0]const u8, *Tm) ?[*:0]u8;
extern "c" fn mktime(*Tm) i64;
extern "c" fn strftime([*]u8, usize, [*:0]const u8, *const Tm) usize;
extern "c" fn fprintf(?*anyopaque, [*:0]const u8, ...) c_int;
extern "c" var __stderrp: ?*anyopaque;
const Tm = extern struct { sec: c_int = 0, min: c_int = 0, hour: c_int = 0, mday: c_int = 0, mon: c_int = 0, year: c_int = 0, wday: c_int = 0, yday: c_int = 0, isdst: c_int = -1, gmtoff: c_long = 0, zone: ?[*:0]const u8 = null };
fn fail(msg: [*:0]const u8) noreturn {
    _ = fprintf(__stderrp, "macctl nosleep: %s\n", msg);
    std.process.exit(1);
}
fn positive(value: []const u8, max: u32) u32 {
    if (value.len == 0) fail("expected a positive integer");
    for (value) |c| if (c < '0' or c > '9') {
        fail("expected a positive integer");
    };
    const n = std.fmt.parseInt(u32, value, 10) catch fail("integer is too large");
    if (n == 0 or n > max) fail("integer is outside the supported range");
    return n;
}
fn deadline(value: []const u8, allocator: std.mem.Allocator) i64 {
    const input = allocator.dupeSentinel(u8, value, 0) catch fail("out of memory");
    var tm: Tm = .{};
    const end = strptime(input, "%Y-%m-%dT%H:%M:%S", &tm) orelse fail("deadline must be local YYYY-MM-DDTHH:MM:SS");
    if (end[0] != 0) fail("deadline must be local YYYY-MM-DDTHH:MM:SS");
    const when = mktime(&tm);
    var canonical: [32]u8 = undefined;
    const len = strftime(&canonical, canonical.len, "%Y-%m-%dT%H:%M:%S", &tm);
    if (len == 0 or !std.mem.eql(u8, canonical[0..len], value)) fail("invalid or nonexistent local deadline");
    const now = time(null);
    if (now == -1 or when <= now) fail("deadline must be in the future");
    return when;
}
pub fn run(args: []const []const u8) noreturn {
    const a = std.heap.page_allocator;
    var i: usize = 0;
    var allow_battery = false;
    var closed_lid = false;
    while (i < args.len) {
        if (std.mem.eql(u8, args[i], "--allow-battery") and !allow_battery) {
            allow_battery = true;
            i += 1;
        } else if (std.mem.eql(u8, args[i], "--closed-lid") and !closed_lid) {
            closed_lid = true;
            i += 1;
        } else break;
    }
    const Mode = enum { indefinite, timed, deadline, pid, exec };
    var mode: Mode = .indefinite;
    var value: u32 = 0;
    var deadline_at: i64 = 0;
    var cmd: []const []const u8 = &.{};
    if (i < args.len) {
        const option = args[i];
        if (std.mem.eql(u8, option, "--exec")) {
            i += 1;
            if (i == args.len) fail("--exec requires a command");
            cmd = args[i..];
            mode = .exec;
        } else {
            if (i + 2 != args.len) fail("expected --timeout SECONDS, --until DEADLINE, --pid PID, or --exec COMMAND [ARGS...]");
            if (std.mem.eql(u8, option, "--timeout")) {
                value = positive(args[i + 1], std.math.maxInt(u32));
                mode = .timed;
            } else if (std.mem.eql(u8, option, "--until")) {
                deadline_at = deadline(args[i + 1], a);
                mode = .deadline;
            } else if (std.mem.eql(u8, option, "--pid")) {
                value = positive(args[i + 1], std.math.maxInt(i32));
                mode = .pid;
            } else fail("unknown option");
        }
    }
    // Register before requesting a lease so an already-exited PID fails closed.
    var queue: c_int = -1;
    if (mode == .pid) {
        queue = kqueue();
        if (queue < 0) fail("cannot create process watcher");
        const change = KEvent{ .ident = value, .filter = -5, .flags = 0x15, .fflags = 0x80000000, .data = 0, .udata = null };
        if (kevent(queue, @ptrCast(&change), 1, null, 0, null) < 0) fail("cannot watch PID; it may have exited");
    }
    var fd: c_int = -1;
    if (closed_lid) {
        fd = socket(1, 1, 0);
        if (fd < 0) fail("cannot create daemon socket");
        const path = "/var/run/macctl-nosleep.d/control.sock";
        var addr = SockAddr{ .len = @intCast(2 + path.len + 1), .family = 1, .path = @splat(0) };
        @memcpy(addr.path[0..path.len], path);
        if (connect(fd, &addr, addr.len) != 0) fail("cannot connect to nosleep.d; install and start the service");
        var uid: u32 = 0;
        var gid: u32 = 0;
        if (getpeereid(fd, &uid, &gid) != 0 or uid != 0) fail("nosleep.d peer is not root");
        const request = if (allow_battery) "BATTERY\n" else "AC\n";
        if (write(fd, request.ptr, request.len) != request.len) fail("cannot request daemon lease");
        var reply: [3]u8 = undefined;
        var received: usize = 0;
        while (received < reply.len) {
            const n = read(fd, reply[received..].ptr, reply.len - received);
            if (n <= 0) fail("nosleep.d refused the lease; inspect its logs");
            received += @intCast(n);
        }
        if (!std.mem.eql(u8, &reply, "OK\n")) fail("nosleep.d refused the lease; inspect its logs");
    } else {
        assertion("PreventSystemSleep");
        if (allow_battery) assertion("PreventUserIdleSystemSleep");
    }
    _ = signal(1, interrupted);
    _ = signal(2, interrupted);
    _ = signal(15, interrupted);
    if (mode == .exec) {
        const argv = a.allocSentinel(?[*:0]const u8, cmd.len, null) catch fail("out of memory");
        for (cmd, 0..) |arg, index| argv[index] = a.dupeSentinel(u8, arg, 0) catch fail("out of memory");
        const pid = fork();
        if (pid < 0) fail("cannot start command");
        if (pid == 0) {
            if (fd >= 0) _ = close(fd);
            _ = execvp(argv[0].?, argv.ptr);
            _exit(127);
        }
        child_pid = pid;
    }
    var start: Timespec = undefined;
    if (mode == .timed and clock_gettime(6, &start) != 0) fail("cannot read monotonic clock");
    var status: c_int = 0;
    while (true) {
        if (mode == .exec) {
            const result = waitpid(child_pid, &status, 1);
            if (result == child_pid) break;
            if (result < 0) fail("cannot wait for command");
        }
        if (mode == .timed) {
            var now: Timespec = undefined;
            if (clock_gettime(6, &now) != 0) fail("cannot read monotonic clock");
            if (now.sec - start.sec > value or (now.sec - start.sec == value and now.nsec >= start.nsec)) break;
        }
        if (mode == .deadline) {
            const now = time(null);
            if (now == -1) fail("cannot read wall clock");
            if (now >= deadline_at) break;
        }
        var fds = [_]PollFd{ .{ .fd = fd, .events = 1 }, .{ .fd = queue, .events = 1 } };
        const count: c_uint = if (mode == .pid) 2 else 1;
        if (poll(&fds, count, 1000) < 0) fail("session monitoring failed");
        if (fds[0].revents != 0) fail("connection to nosleep.d lost; the command may still be running without sleep protection");
        if (mode == .pid and fds[1].revents != 0) {
            var event: KEvent = undefined;
            if (kevent(queue, null, 0, @ptrCast(&event), 1, null) != 1) fail("process watcher failed");
            break;
        }
    }
    if (fd >= 0) _ = close(fd);
    if (mode == .exec) {
        if ((status & 0x7f) == 0) std.process.exit(@intCast((status >> 8) & 0xff));
        std.process.exit(@intCast(128 + (status & 0x7f)));
    }
    std.process.exit(0);
}
