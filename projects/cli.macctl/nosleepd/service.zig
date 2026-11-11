const std = @import("std");
const c = @import("bindings.zig");
extern "c" fn _NSGetExecutablePath([*]u8, *u32) c_int;
const label = "system/dev.nonlogical.macctl.nosleepd";
const helper = "/Library/PrivilegedHelperTools/macctl-nosleepd";
const plist = "/Library/LaunchDaemons/dev.nonlogical.macctl.nosleepd.plist";
const state_dir = "/var/db/macctl-nosleep.d";
const marker = "/var/db/macctl-nosleep.d/install";
const socket_dir = "/var/run/macctl-nosleep.d";
const socket = "/var/run/macctl-nosleep.d/control.sock";
fn err(msg: [*:0]const u8) noreturn {
    _ = c.fprintf(c.stderr(), "macctl nosleep.d: %s\n", msg);
    std.process.exit(1);
}
fn exec(args: []const ?[*:0]const u8) c_int {
    const pid = c.fork();
    if (pid < 0) return -1;
    if (pid == 0) {
        if (std.mem.eql(u8, std.mem.span(args[1].?), "print")) {
            const sink = c.open("/dev/null", c.O_WRONLY);
            if (sink >= 0) {
                _ = c.dup2(sink, 1);
                _ = c.dup2(sink, 2);
                _ = c.close(sink);
            }
        }
        _ = c.execv(args[0].?, @ptrCast(args.ptr));
        c._exit(127);
    }
    var status: c_int = 0;
    while (c.waitpid(pid, &status, 0) < 0) {
        if (c.__error().* != c.EINTR) return -1;
    }
    return if ((status & 0x7f) == 0) (status >> 8) & 0xff else -1;
}
fn absent(path: [*:0]const u8) bool {
    var st: c.struct_stat = undefined;
    if (c.lstat(path, &st) == 0) return false;
    return c.__error().* == c.ENOENT;
}
fn protectedDir(path: [*:0]const u8) bool {
    var st: c.struct_stat = undefined;
    return c.lstat(path, &st) == 0 and (st.st_mode & c.S_IFMT) == c.S_IFDIR and st.st_uid == 0 and (st.st_mode & 0o022) == 0;
}
fn openSafe(path: [*:0]const u8, require_root: bool) c_int {
    const fd = c.open(path, c.O_RDONLY | c.O_NOFOLLOW);
    if (fd < 0) return -1;
    var st: c.struct_stat = undefined;
    if (c.fstat(fd, &st) != 0 or (st.st_mode & c.S_IFMT) != c.S_IFREG or st.st_nlink != 1 or (require_root and (st.st_uid != 0 or (st.st_mode & 0o022) != 0))) {
        _ = c.close(fd);
        return -1;
    }
    return fd;
}
fn writeAll(fd: c_int, bytes: []const u8) bool {
    var off: usize = 0;
    while (off < bytes.len) {
        const n = c.write(fd, bytes[off..].ptr, bytes.len - off);
        if (n <= 0) return false;
        off += @intCast(n);
    }
    return true;
}
fn newFile(path: [*:0]const u8, mode: c.mode_t, contents: []const u8) bool {
    const fd = c.open(path, c.O_WRONLY | c.O_CREAT | c.O_EXCL | c.O_NOFOLLOW, mode);
    if (fd < 0) return false;
    defer _ = c.close(fd);
    const ok = c.fchmod(fd, mode) == 0 and writeAll(fd, contents) and c.fsync(fd) == 0;
    if (!ok) _ = c.unlink(path);
    return ok;
}
fn copyFile(in: c_int, dst: [*:0]const u8) bool {
    const out = c.open(dst, c.O_WRONLY | c.O_CREAT | c.O_EXCL | c.O_NOFOLLOW, @as(c.mode_t, 0o755));
    if (out < 0) return false;
    defer _ = c.close(out);
    var ok = false;
    defer if (!ok) {
        _ = c.unlink(dst);
    };
    if (c.fchmod(out, 0o755) != 0) return false;
    var buf: [16384]u8 = undefined;
    while (true) {
        const n = c.read(in, &buf, buf.len);
        if (n < 0) return false;
        if (n == 0) break;
        if (!writeAll(out, buf[0..@intCast(n)])) return false;
    }
    ok = c.fsync(out) == 0;
    return ok;
}
fn text(fd: c_int, buf: []u8) ?[]u8 {
    const n = c.read(fd, buf.ptr, buf.len);
    if (n < 0 or n == buf.len) return null;
    return buf[0..@intCast(n)];
}
fn safeStat(path: [*:0]const u8) ?c.struct_stat {
    const fd = openSafe(path, true);
    if (fd < 0) return null;
    defer _ = c.close(fd);
    var st: c.struct_stat = undefined;
    if (c.fstat(fd, &st) != 0) return null;
    return st;
}
fn servicePlist(uid: u32, buf: []u8) ?[]u8 {
    return std.fmt.bufPrint(buf, "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n<plist version=\"1.0\"><dict><key>Label</key><string>dev.nonlogical.macctl.nosleepd</string><key>ProgramArguments</key><array><string>" ++ helper ++ "</string><string>" ++ socket ++ "</string><string>{d}</string></array><key>KeepAlive</key><true/></dict></plist>\n", .{uid}) catch null;
}
fn sibling() ?[:0]u8 {
    var buf: [4096]u8 = undefined;
    var len: u32 = buf.len;
    if (_NSGetExecutablePath(&buf, &len) != 0) return null;
    const path = std.mem.sliceTo(&buf, 0);
    const slash = std.mem.lastIndexOfScalar(u8, path, '/') orelse return null;
    return std.fmt.allocPrintSentinel(std.heap.page_allocator, "{s}/macctl-nosleepd", .{path[0..slash]}, 0) catch null;
}
fn expectedMarker(uid: u32, hs: c.struct_stat, ps: c.struct_stat, buf: []u8) ?[]u8 {
    return std.fmt.bufPrint(buf, "macctl-nosleepd-v1 {d} {d} {d} {d} {d}\n", .{ uid, hs.st_dev, hs.st_ino, ps.st_dev, ps.st_ino }) catch null;
}
fn getuid() ?u32 {
    const raw = c.getenv("SUDO_UID") orelse return null;
    const uid = std.fmt.parseInt(u32, std.mem.span(raw), 10) catch return null;
    return if (uid == 0) null else uid;
}
fn verify() bool {
    if (!protectedDir(state_dir)) return false;
    const mf = openSafe(marker, true);
    if (mf < 0) return false;
    defer _ = c.close(mf);
    var mb: [512]u8 = undefined;
    const m = text(mf, &mb) orelse return false;
    var iter = std.mem.tokenizeAny(u8, m, " \n");
    if (!std.mem.eql(u8, iter.next() orelse return false, "macctl-nosleepd-v1")) return false;
    const uid = std.fmt.parseInt(u32, iter.next() orelse return false, 10) catch return false;
    const hs = safeStat(helper) orelse return false;
    const ps = safeStat(plist) orelse return false;
    var check: [512]u8 = undefined;
    const expected = expectedMarker(uid, hs, ps, &check) orelse return false;
    if (!std.mem.eql(u8, m, expected)) return false;
    const pf = openSafe(plist, true);
    if (pf < 0) return false;
    defer _ = c.close(pf);
    var pb: [4096]u8 = undefined;
    const actual = text(pf, &pb) orelse return false;
    var eb: [4096]u8 = undefined;
    const exp = servicePlist(uid, &eb) orelse return false;
    return std.mem.eql(u8, actual, exp);
}
fn install() void {
    if (c.geteuid() != 0) err("install requires sudo");
    const uid = getuid() orelse err("install must be invoked using sudo by the intended user");
    if (!protectedDir("/Library/PrivilegedHelperTools") or !protectedDir("/Library/LaunchDaemons") or !protectedDir("/var/db")) err("unsafe system directories");
    if (!absent(helper) or !absent(plist) or !absent(state_dir) or !absent(socket_dir)) err("existing service files found; refusing to overwrite");
    const print_args = [_]?[*:0]const u8{ "/bin/launchctl", "print", label, null };
    if (exec(&print_args) != 113) err("service already loaded or launchctl unavailable");
    const source = sibling() orelse err("cannot find sibling macctl-nosleepd");
    const source_fd = openSafe(source, false);
    if (source_fd < 0) err("cannot read sibling macctl-nosleepd");
    defer _ = c.close(source_fd);
    if (c.mkdir(state_dir, @as(c.mode_t, 0o700)) != 0) err("cannot create service state directory");
    if (!copyFile(source_fd, helper)) {
        _ = c.rmdir(state_dir);
        err("cannot install daemon");
    }
    var pb: [4096]u8 = undefined;
    const contents = servicePlist(uid, &pb) orelse err("cannot build service definition");
    if (!newFile(plist, 0o644, contents)) {
        _ = c.unlink(helper);
        _ = c.rmdir(state_dir);
        err("cannot install launchd definition");
    }
    const hs = safeStat(helper) orelse err("cannot verify daemon");
    const ps = safeStat(plist) orelse err("cannot verify launchd definition");
    var mb: [512]u8 = undefined;
    const m = expectedMarker(uid, hs, ps, &mb) orelse err("cannot build installation marker");
    if (!newFile(marker, 0o600, m)) {
        _ = c.unlink(plist);
        _ = c.unlink(helper);
        _ = c.rmdir(state_dir);
        err("cannot record installation");
    }
    const boot = [_]?[*:0]const u8{ "/bin/launchctl", "bootstrap", "system", plist, null };
    if (exec(&boot) != 0) err("bootstrap failed; installed files retained for uninstall or inspection");
    _ = c.printf("Installed nosleep.d for uid %u.\n", uid);
}
fn uninstall() void {
    if (c.geteuid() != 0) err("uninstall requires sudo");
    if (!verify()) err("service files are missing or unrecognized; refusing to remove them");
    const print_args = [_]?[*:0]const u8{ "/bin/launchctl", "print", label, null };
    const status = exec(&print_args);
    if (status == 0) {
        const stop = [_]?[*:0]const u8{ "/bin/launchctl", "bootout", label, null };
        if (exec(&stop) != 0) err("cannot stop daemon; files retained");
    } else if (status != 113) err("cannot determine launchd status; files retained");
    const recover = [_]?[*:0]const u8{ helper, "--recover", null };
    if (exec(&recover) != 0) err("cannot verify sleep restoration; files retained");
    // Hold the daemon lock while removing its resources. Recovery already
    // removed an owned journal; never remove an unknown one.
    const lock_path = state_dir ++ "/lock";
    const lock_fd = c.open(lock_path, c.O_RDONLY | c.O_NOFOLLOW);
    if (lock_fd < 0) err("cannot open daemon lock; files retained");
    defer _ = c.close(lock_fd);
    var ls: c.struct_stat = undefined;
    if (c.fstat(lock_fd, &ls) != 0 or (ls.st_mode & c.S_IFMT) != c.S_IFREG or ls.st_uid != 0 or (ls.st_mode & 0o077) != 0 or ls.st_nlink != 1 or c.flock(lock_fd, c.LOCK_EX | c.LOCK_NB) != 0) err("daemon is running or lock is unsafe; files retained");
    if (!absent(state_dir ++ "/owned") or !verify()) err("service files or recovery state changed; files retained");
    if (!absent(socket_dir)) {
        if (!protectedDir(socket_dir)) err("socket directory is unrecognized; files retained");
        var ss: c.struct_stat = undefined;
        if (c.lstat(socket, &ss) == 0) {
            if ((ss.st_mode & c.S_IFMT) != c.S_IFSOCK or ss.st_uid != 0) err("socket path is unrecognized; files retained");
            if (c.unlink(socket) != 0) err("cannot remove stale socket; files retained");
        } else if (c.__error().* != c.ENOENT) err("cannot inspect socket; files retained");
        if (c.rmdir(socket_dir) != 0) err("socket directory is not empty; files retained");
    }
    if (c.unlink(plist) != 0 or c.unlink(helper) != 0 or c.unlink(marker) != 0 or c.unlink(lock_path) != 0) err("could not remove service files; inspect remaining state");
    if (c.rmdir(state_dir) != 0) err("service removed but state directory is not empty; inspect it before reinstalling");
    _ = c.printf("Uninstalled nosleep.d.\n");
}
pub fn run(args: []const []const u8) noreturn {
    if (args.len != 1) err("usage: macctl nosleep.d install|uninstall|status");
    if (std.mem.eql(u8, args[0], "install")) install() else if (std.mem.eql(u8, args[0], "uninstall")) uninstall() else if (std.mem.eql(u8, args[0], "status")) {
        const argv = [_]?[*:0]const u8{ "/bin/launchctl", "print", label, null };
        const code = exec(&argv);
        if (code == 113) {
            if (absent(helper) and absent(plist)) {
                _ = c.printf("nosleep.d is not installed.\n");
            } else if (!absent(helper) and !absent(plist)) {
                _ = c.printf("nosleep.d is installed but not loaded.\n");
            } else {
                _ = c.printf("nosleep.d installation is incomplete.\n");
            }
        } else if (code == 0) {
            _ = c.printf("nosleep.d is loaded.\n");
        } else err("cannot determine launchd status");
    } else err("usage: macctl nosleep.d install|uninstall|status");
    std.process.exit(0);
}
