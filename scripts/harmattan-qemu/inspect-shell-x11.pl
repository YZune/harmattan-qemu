# Read-only X11 window/WM evidence, using the guest's existing Perl runtime.
# Protocol layouts: source DVD xcb-proto 1.6, src/xproto.xml.
# SPDX-License-Identifier: GPL-2.0-or-later
use strict;
use warnings;
use Socket;
alarm 15;
socket(my $socket, PF_UNIX, SOCK_STREAM, 0) or die "socket: $!";
connect($socket, sockaddr_un("/tmp/.X11-unix/X9")) or die "connect: $!";
sub send_all {
    my ($data) = @_;
    while (length($data)) {
        my $n = syswrite($socket, $data);
        defined($n) && $n > 0 or die "write: $!";
        substr($data, 0, $n, "");
    }
}
sub receive_exact {
    my ($length) = @_;
    my $data = "";
    while (length($data) < $length) {
        my $n = sysread($socket, my $part, $length - length($data));
        defined($n) && $n > 0 or die "read: $!";
        $data .= $part;
    }
    return $data;
}
send_all(pack("CCvvvvv", 108, 0, 11, 0, 0, 0, 0));
my ($ok, $major, $minor, $length) = unpack("Cxvvv", receive_exact(8));
my $body = receive_exact($length * 4);
$ok == 1 && length($body) >= 32 or die "X11 setup failure";
my ($vendor, $maxrequest, $roots, $formats) = unpack("x16vvCC", $body);
$roots > 0 or die "missing screen";
my $offset = 32 + (($vendor + 3) & ~3) + 8 * $formats;
length($body) >= $offset + 40 or die "truncated screen";
my ($root, $width, $height, $depth) = unpack("Vx16vvx14C", substr($body, $offset, 40));
printf "N00_X11_ROOT id=%08x size=%ux%u depth=%u\n", $root, $width, $height, $depth;
my $sequence = 0;
sub request {
    my ($op, $minor, $payload) = @_;
    $payload .= "\0" x ((4 - length($payload) % 4) % 4);
    send_all(pack("CCv", $op, $minor, 1 + length($payload) / 4) . $payload);
    $sequence++;
    for (;;) {
        my $header = receive_exact(32);
        my ($type, $reply_sequence, $extra) = unpack("CxvV", $header);
        $type != 0 or die "X11 error: " . unpack("H*", $header);
        next if $type != 1;
        $reply_sequence == $sequence && $extra <= 262144 or die "unexpected X11 reply";
        return $header . receive_exact($extra * 4);
    }
}
my %atoms;
sub atom {
    my ($name) = @_;
    if (!exists $atoms{$name}) {
        # only_if_exists: inspection never creates properties or atoms.
        $atoms{$name} = unpack("x8V", request(16, 1, pack("vxx", length($name)) . $name));
    }
    return $atoms{$name};
}
sub property {
    my ($window, $name) = @_;
    my $id = atom($name);
    return (0, "") unless $id;
    my $reply = request(20, 0, pack("V5", $window, $id, 0, 0, 4096));
    my ($format, $type, $after, $items) = unpack("xCx6VVV", $reply);
    $after == 0 && ($format == 0 || $format == 8 || $format == 16 || $format == 32) or die "oversized/unknown property";
    my $bytes = $items * $format / 8;
    length($reply) >= 32 + $bytes or die "truncated property";
    return ($format, substr($reply, 32, $bytes));
}
sub numbers {
    my ($window, $name) = @_;
    my ($format, $value) = property($window, $name);
    return () unless $format == 32;
    return unpack("V*", $value);
}
my @manager = numbers($root, "_NET_SUPPORTING_WM_CHECK");
my @self = @manager ? numbers($manager[0], "_NET_SUPPORTING_WM_CHECK") : ();
printf "N00_X11_WM check=%08x self=%08x\n", $manager[0] || 0, $self[0] || 0;
my $selection = atom("_NET_WM_CM_S0");
my $owner = $selection ? unpack("x8V", request(23, 0, pack("V", $selection))) : 0;
printf "N00_X11_COMPOSITOR owner=%08x\n", $owner;
my @active = numbers($root, "_NET_ACTIVE_WINDOW");
printf "N00_X11_ACTIVE id=%08x\n", $active[0] || 0;
my @sbwindow = numbers($root, "_MEEGOTOUCH_STATUSBAR_PROPERTY_WINDOW");
if (@sbwindow == 1 && $sbwindow[0]) {
    my @pixmap = numbers($sbwindow[0], "_MEEGOTOUCH_STATUSBAR_PIXMAP");
    @pixmap == 1 && $pixmap[0] or die "missing statusbar pixmap";
    my $geometry = request(14, 0, pack("V", $pixmap[0]));
    my ($depth, $w, $h) = unpack("xCx14vv", $geometry);
    printf "N00_X11_STATUSBAR window=%08x pixmap=%08x size=%ux%u depth=%u\n",
        $sbwindow[0], $pixmap[0], $w, $h, $depth;
} else {
    print "N00_X11_STATUSBAR absent\n";
}
my @clients = numbers($root, "_NET_CLIENT_LIST_STACKING");
printf "N00_X11_CLIENTS %s\n", join(",", map { sprintf "%08x", $_ } @clients);
my $tree = request(15, 0, pack("V", $root));
my $children = unpack("x16v", $tree);
$children <= 256 && length($tree) == 32 + $children * 4 or die "unexpected window tree";
my %seen;
for my $window (unpack("V*", substr($tree, 32)), @clients) {
    next if $seen{$window}++;
    my ($format, $class) = property($window, "WM_CLASS");
    my @pid = numbers($window, "_NET_WM_PID");
    my $attrs = request(3, 0, pack("V", $window));
    my $map = unpack("x26C", $attrs);
    my ($x, $y, $w, $h) = unpack("x12ssvv", request(14, 0, pack("V", $window)));
    printf "N00_X11_WINDOW id=%08x map=%u geometry=%dx%d+%d+%d pid=%u class=%s\n",
        $window, $map, $w, $h, $x, $y, $pid[0] || 0, unpack("H*", $class);
    my @angle = numbers($window, "_MEEGOTOUCH_ORIENTATION_ANGLE");
    printf "N00_X11_ORIENTATION id=%08x angle=%s\n", $window,
        @angle == 1 ? $angle[0] : "absent";
}
print "N00_X11_INSPECT_OK\n";
