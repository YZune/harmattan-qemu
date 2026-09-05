# SPDX-License-Identifier: GPL-2.0-or-later
# Small X11 core-protocol client for snapshot-local launch helpers. Layouts:
# source DVD xcb-proto 1.6, xproto.xml. No replacement display/renderer.
package N00X11;
use strict;
use warnings;
use Socket;

sub new {
    my ($class, $endpoint) = @_;
    if (!defined $endpoint) {
        ($ENV{DISPLAY} || '') =~ /^:([0-9]{1,3})(?:\.0)?$/ or die "local DISPLAY required\n";
        $endpoint = "/tmp/.X11-unix/X$1";
    }
    socket(my $socket, PF_UNIX, SOCK_STREAM, 0) or die "socket: $!\n";
    connect($socket, sockaddr_un($endpoint)) or die "connect: $!\n";
    my $self = bless {socket => $socket, sequence => 0, atoms => {}, events => []}, $class;
    $self->write_all(pack('CCvvvvv', 108, 0, 11, 0, 0, 0, 0));
    my ($ok, $major, $minor, $length) = unpack('Cxvvv', $self->read_exact(8));
    my $body = $self->read_exact($length * 4);
    $ok == 1 && $major == 11 && length($body) >= 32 or die "X11 setup failure\n";
    my ($vendor, $maxrequest, $roots, $formats) = unpack('x16vvCC', $body);
    my $offset = 32 + (($vendor + 3) & ~3) + 8 * $formats;
    $roots > 0 && length($body) >= $offset + 40 or die "missing X11 screen\n";
    $self->{root} = unpack('V', substr($body, $offset, 4));
    $self->{maxrequest} = $maxrequest;
    return $self;
}

sub write_all {
    my ($self, $data) = @_;
    while (length($data)) {
        my $n = syswrite($self->{socket}, $data);
        defined($n) && $n > 0 or die "X11 write: $!\n";
        substr($data, 0, $n, '');
    }
}

sub read_exact {
    my ($self, $length) = @_;
    my $data = '';
    while (length($data) < $length) {
        my $n = sysread($self->{socket}, my $part, $length - length($data));
        defined($n) && $n > 0 or die "X11 read: $!\n";
        $data .= $part;
    }
    return $data;
}

sub send_request {
    my ($self, $opcode, $detail, $body) = @_;
    $body .= "\0" x ((4 - length($body) % 4) % 4);
    my $length = 1 + length($body) / 4;
    $length <= $self->{maxrequest} or die "oversized X11 request\n";
    $self->write_all(pack('CCv', $opcode, $detail, $length) . $body);
    return ++$self->{sequence} % 65536;
}

sub request {
    my ($self, $opcode, $detail, $body) = @_;
    my $sequence = $self->send_request($opcode, $detail, $body);
    for (;;) {
        my $header = $self->read_exact(32);
        my ($type, $reply_sequence, $extra) = unpack('CxvV', $header);
        $type != 0 or die "X11 error: " . unpack('H*', $header) . "\n";
        if ($type != 1) {
            push @{$self->{events}}, $header;
            next;
        }
        $reply_sequence == $sequence && $extra <= 262144 or die "unexpected X11 reply\n";
        return $header . $self->read_exact($extra * 4);
    }
}

sub atom {
    my ($self, $name) = @_;
    if (!exists $self->{atoms}{$name}) {
        # All required atoms already belong to the original running WM.
        my $reply = $self->request(16, 1, pack('vxx', length($name)) . $name);
        $self->{atoms}{$name} = unpack('x8V', $reply);
    }
    $self->{atoms}{$name} or die "missing X11 atom $name\n";
    return $self->{atoms}{$name};
}

sub property {
    my ($self, $window, $name, $expected_type, $expected_format) = @_;
    my $reply = $self->request(20, 0, pack('V5', $window, $self->atom($name), $expected_type, 0, 1000));
    my ($format, $type, $after, $items) = unpack('xCx6VVV', $reply);
    $type == $expected_type && $format == $expected_format && !$after && $items <= 4000
        or die "unexpected X11 property $name\n";
    my $bytes = $items * $format / 8;
    length($reply) == 32 + (($bytes + 3) & ~3) or die "truncated X11 property\n";
    return substr($reply, 32, $bytes);
}

sub compositor {
    my ($self) = @_;
    my $value = $self->property($self->{root}, '_NET_SUPPORTING_WM_CHECK', 33, 32);
    length($value) == 4 or die "missing compositor window\n";
    my $window = unpack('V', $value);
    $window && $self->property($window, '_NET_SUPPORTING_WM_CHECK', 33, 32) eq $value
        or die "compositor self-check failed\n";
    my $reply = $self->request(23, 0, pack('V', $self->atom('_NET_WM_CM_S0')));
    unpack('x8V', $reply) == $window or die "compositor owner mismatch\n";
    return $window;
}

sub sync {
    my ($self) = @_;
    $self->request(43, 0, ''); # GetInputFocus: fence, not rendered-frame proof.
}

1;
