#!/usr/bin/perl
# SPDX-License-Identifier: GPL-2.0-or-later
# Discard guest X11 input only during startup verification. This is not a
# Cocoa cursor grab. The original MXT driver remains enabled and unchanged.
use strict;
use warnings;
use FindBin;
use lib $FindBin::Bin;
use N00X11;
use IO::Select;
use Fcntl qw(O_RDWR O_NONBLOCK);

sub hold_input {
    my ($control, $endpoint) = @_;
    -p $control or die "startup control must be a FIFO\n";
    sysopen(my $fifo, $control, O_RDWR | O_NONBLOCK) or die "control: $!\n";
    my $x = N00X11->new($endpoint);
    my $pointer = $x->request(26, 0, pack('VvCCVVV', $x->{root}, 4 | 8 | 64, 1, 1, 0, 0, 0));
    unpack('xC', $pointer) == 0 or die "startup pointer grab failed\n";
    my $keyboard = $x->request(31, 0, pack('VVCCxx', $x->{root}, 0, 1, 1));
    unpack('xC', $keyboard) == 0 or die "startup keyboard grab failed\n";
    $| = 1;
    print "N00_STARTUP_INPUT_HELD pid=$$\n";
    my $select = IO::Select->new($fifo, $x->{socket});
    my ($buffer, $releasing, $buttons, $keys, $motions) = ('', 0, 0, 0, 0);
    for (;;) {
        for my $event (splice @{$x->{events}}) {
            my $type = unpack('C', $event) & 127;
            if ($type == 4 || $type == 5) { $buttons++; }
            elsif ($type == 2 || $type == 3) { $keys++; }
            elsif ($type == 6) { $motions++; }
        }
        if ($releasing) {
            my $reply = $x->request(38, 0, pack('V', $x->{root}));
            my $mask = unpack('x24v', $reply);
            my $keymap = $x->request(44, 0, '');
            # Do not hand a held mouse button/key to the newly unlocked Home.
            if (!($mask & 0x1f00) && substr($keymap, 8, 32) eq "\0" x 32) {
                $x->send_request(27, 0, pack('V', 0));
                $x->send_request(32, 0, pack('V', 0));
                $x->sync();
                print "N00_STARTUP_INPUT_RELEASED pid=$$ buttons=$buttons keys=$keys motions=$motions\n";
                return;
            }
        }
        for my $ready ($select->can_read($releasing ? 0.1 : undef)) {
            if (fileno($ready) == fileno($x->{socket})) {
                my $event = $x->read_exact(32);
                (unpack('C', $event) & 127) >= 2 or die "unexpected startup X11 event\n";
                push @{$x->{events}}, $event;
            } else {
                my $n = sysread($fifo, my $part, 128);
                defined($n) && $n > 0 or die "startup control read failed\n";
                $buffer .= $part;
                length($buffer) <= 128 or die "oversized startup control\n";
                while ($buffer =~ s/^([^\n]*)\n//) {
                    my $command = $1;
                    if ($command eq 'release' && !$releasing) {
                        $releasing = 1;
                        print "N00_STARTUP_INPUT_RELEASE_REQUEST pid=$$\n";
                    } elsif ($command =~ /^check (home|settled|final)$/ && !$releasing) {
                        print "N00_STARTUP_INPUT_CHECK tag=$1 pid=$$ buttons=$buttons keys=$keys motions=$motions\n";
                    } else { die "invalid startup control\n"; }
                }
            }
        }
    }
}

unless (caller) {
    alarm 240;
    @ARGV == 1 or die "expected private startup-control FIFO\n";
    hold_input(@ARGV);
}
1;
