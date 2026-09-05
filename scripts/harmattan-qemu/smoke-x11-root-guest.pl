# Minimal X11 client in the guest, without xprop/xsetroot or Xlib development files.
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
# Little-endian X11 setup, version 11.0, no authorization data.
send_all(pack("CCvvvvv", 108, 0, 11, 0, 0, 0, 0));
my ($ok, $major, $minor, $length) = unpack("Cxvvv", receive_exact(8));
my $body = receive_exact($length * 4);
$ok == 1 or die "X11 setup status $ok: $body";
length($body) >= 32 or die "truncated X11 setup";
my ($vendor, $maxrequest, $roots, $formats) = unpack("x16vvCC", $body);
$roots > 0 or die "no X11 screen";
my $offset = 32 + (($vendor + 3) & ~3) + 8 * $formats;
length($body) >= $offset + 40 or die "truncated X11 screen";
my ($root, $width, $height, $depth) = unpack("Vx16vvx14C", substr($body, $offset, 40));
$major == 11 && $minor == 0 && $width == 864 && $height == 480 && $depth == 24
    or die "unexpected X11 screen";
print "N00_X11_SETUP_OK version=$major.$minor size=${width}x${height} depth=$depth\n";
# ChangeWindowAttributes(CWBackPixel), ClearArea, then GetInputFocus as a fence.
send_all(pack("CCvVVV", 2, 0, 4, $root, 2, 0x3769a8));
send_all(pack("CCvVvvvv", 61, 0, 4, $root, 0, 0, 0, 0));
send_all(pack("CCv", 43, 0, 1));
my $reply = receive_exact(32);
my ($reply_type, $sequence, $extra) = unpack("CxvV", $reply);
$reply_type == 1 && $sequence == 3 && $extra == 0
    or die "X11 draw/fence error: " . unpack("H*", $reply);
print "N00_X11_ROOT_DRAW_OK rgb=3769a8\n";
