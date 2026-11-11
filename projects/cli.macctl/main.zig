const std = @import("std");
const Id = ?*anyopaque;
extern "c" fn dlopen([*:0]const u8, c_int) ?*anyopaque;
extern "c" fn dlsym(?*anyopaque, [*:0]const u8) ?*anyopaque;
extern "c" fn CGGetActiveDisplayList(u32, [*]u32, *u32) i32;
extern "c" fn CGDisplayIsBuiltin(u32) u32;
extern "c" fn objc_getClass([*:0]const u8) Id;
extern "c" fn sel_registerName([*:0]const u8) Id;
extern "c" fn objc_msgSend() void;
extern "c" fn printf([*:0]const u8, ...) c_int;
extern "c" fn fprintf(?*anyopaque, [*:0]const u8, ...) c_int;
extern "c" var __stderrp: ?*anyopaque;

fn send(comptime T: type) T {
    return @ptrCast(&objc_msgSend);
}
fn sel(name: [*:0]const u8) Id {
    return sel_registerName(name);
}
const obj0 = send(*const fn (Id, Id) callconv(.c) Id);
const uint0 = send(*const fn (Id, Id) callconv(.c) u64);
const obj1 = send(*const fn (Id, Id, u64) callconv(.c) Id);
const float1 = send(*const fn (Id, Id, u64) callconv(.c) f32);
const bool1 = send(*const fn (Id, Id, u64) callconv(.c) bool);
const setfloat = send(*const fn (Id, Id, f32, u64) callconv(.c) void);
const setbool = send(*const fn (Id, Id, bool, u64) callconv(.c) void);

fn fail(message: [*:0]const u8) noreturn {
    _ = fprintf(__stderrp, "macctl: %s\n", message);
    std.process.exit(1);
}
fn usage() void {
    _ = printf("Usage: macctl get | set <0..1> | off | max | auto [on|off] | list\n       macctl display get | set <0..1> | off | max\n       macctl nosleep.d install | uninstall | status\n       macctl nosleep [--allow-battery] [--closed-lid] [--timeout SECONDS | --until YYYY-MM-DDTHH:MM:SS | --pid PID | --exec COMMAND [ARGS...]]\n");
}
// Select the built-in panel even when an external display is the main display.
fn display(args: []const []const u8) void {
    var set: ?f32 = null;
    if (args.len == 1 and std.mem.eql(u8, args[0], "get")) {} else if (args.len == 1 and std.mem.eql(u8, args[0], "off")) {
        set = 0;
    } else if (args.len == 1 and std.mem.eql(u8, args[0], "max")) {
        set = 1;
    } else if (args.len == 2 and std.mem.eql(u8, args[0], "set")) {
        const value = std.fmt.parseFloat(f32, args[1]) catch fail("brightness must be a number from 0 to 1");
        if (!std.math.isFinite(value) or value < 0 or value > 1) fail("brightness must be a number from 0 to 1");
        set = value;
    } else {
        usage();
        std.process.exit(1);
    }
    const framework = dlopen("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices", 2) orelse fail("cannot load DisplayServices");
    const get: *const fn (u32, *f32) callconv(.c) c_int = @ptrCast(@alignCast(dlsym(framework, "DisplayServicesGetBrightness") orelse fail("display brightness getter unavailable")));
    const set_brightness: *const fn (u32, f32) callconv(.c) c_int = @ptrCast(@alignCast(dlsym(framework, "DisplayServicesSetBrightness") orelse fail("display brightness setter unavailable")));
    var displays: [32]u32 = undefined;
    var count: u32 = 0;
    if (CGGetActiveDisplayList(displays.len, &displays, &count) != 0) fail("cannot enumerate displays");
    var panel: ?u32 = null;
    for (displays[0..@min(count, displays.len)]) |id| {
        if (CGDisplayIsBuiltin(id) != 0) {
            panel = id;
            break;
        }
    }
    const id = panel orelse fail("no active built-in display found");
    if (set) |value| {
        if (set_brightness(id, value) != 0) fail("cannot set display brightness");
    } else {
        var value: f32 = 0;
        if (get(id, &value) != 0) fail("cannot read display brightness");
        _ = printf("%u %.4f\n", id, @as(f64, value));
    }
}

pub fn main(init: std.process.Init.Minimal) void {
    const raw_args = init.args.vector;
    if (raw_args.len >= 2 and std.mem.eql(u8, std.mem.span(raw_args[1]), "nosleep.d")) {
        const args = std.heap.page_allocator.alloc([]const u8, raw_args.len - 2) catch fail("out of memory");
        for (raw_args[2..], 0..) |arg, i| args[i] = std.mem.span(arg);
        @import("nosleepd/service.zig").run(args);
    }
    if (raw_args.len >= 2 and std.mem.eql(u8, std.mem.span(raw_args[1]), "nosleep")) {
        const allocator = std.heap.page_allocator;
        const args = allocator.alloc([]const u8, raw_args.len - 2) catch fail("out of memory");
        for (raw_args[2..], 0..) |arg, i| args[i] = std.mem.span(arg);
        @import("nosleep.zig").run(args);
    }
    var storage: [4][]const u8 = undefined;
    const raw = init.args.vector;
    if (raw.len > storage.len) {
        usage();
        std.process.exit(1);
    }
    for (raw, 0..) |arg, i| storage[i] = std.mem.span(arg);
    const args = storage[0..raw.len];
    if (args.len == 2 and (std.mem.eql(u8, args[1], "--help") or std.mem.eql(u8, args[1], "help"))) {
        usage();
        return;
    }
    if (args.len < 2) {
        usage();
        std.process.exit(1);
    }
    if (std.mem.eql(u8, args[1], "display")) {
        display(args[2..]);
        return;
    }
    const cmd = args[1];
    var action: enum { get, set, auto_get, auto_set, list } = undefined;
    var level: f32 = 0;
    var enabled = false;
    if (std.mem.eql(u8, cmd, "get") and args.len == 2) {
        action = .get;
    } else if (std.mem.eql(u8, cmd, "list") and args.len == 2) {
        action = .list;
    } else if (std.mem.eql(u8, cmd, "off") and args.len == 2) {
        action = .set;
    } else if (std.mem.eql(u8, cmd, "max") and args.len == 2) {
        action = .set;
        level = 1;
    } else if (std.mem.eql(u8, cmd, "set") and args.len == 3) {
        level = std.fmt.parseFloat(f32, args[2]) catch fail("brightness must be a number from 0 to 1");
        if (!std.math.isFinite(level) or level < 0 or level > 1) fail("brightness must be a number from 0 to 1");
        action = .set;
    } else if (std.mem.eql(u8, cmd, "auto") and args.len == 2) {
        action = .auto_get;
    } else if (std.mem.eql(u8, cmd, "auto") and args.len == 3 and (std.mem.eql(u8, args[2], "on") or std.mem.eql(u8, args[2], "off"))) {
        action = .auto_set;
        enabled = std.mem.eql(u8, args[2], "on");
    } else {
        usage();
        std.process.exit(1);
    }

    if (dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness", 2) == null) fail("cannot load CoreBrightness");
    const cls = objc_getClass("KeyboardBrightnessClient") orelse fail("KeyboardBrightnessClient unavailable");
    const client = obj0(obj0(cls, sel("alloc")), sel("init")) orelse fail("cannot initialize brightness client");
    defer _ = obj0(client, sel("release"));
    const ids = obj0(client, sel("copyKeyboardBacklightIDs")) orelse fail("cannot enumerate keyboards");
    defer _ = obj0(ids, sel("release"));
    const count = uint0(ids, sel("count"));
    if (count == 0) fail("no backlit keyboard found");
    var i: u64 = 0;
    while (i < count) : (i += 1) {
        const num = obj1(ids, sel("objectAtIndex:"), i) orelse fail("invalid keyboard ID");
        const id = uint0(num, sel("unsignedLongLongValue"));
        switch (action) {
            .list => _ = printf("%llu\n", id),
            .get => _ = printf("%llu %.4f\n", id, @as(f64, float1(client, sel("brightnessForKeyboard:"), id))),
            .set => setfloat(client, sel("setBrightness:forKeyboard:"), level, id),
            .auto_get => _ = printf("%llu %d\n", id, @as(c_int, @intFromBool(bool1(client, sel("isAutoBrightnessEnabledForKeyboard:"), id)))),
            .auto_set => setbool(client, sel("enableAutoBrightness:forKeyboard:"), enabled, id),
        }
    }
}
