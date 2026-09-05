#!/usr/bin/perl
# Read real ARM32 Linux evdev records. Never synthesize guest input events.
use strict;
use warnings;
$| = 1;
my ($device, $packets) = @ARGV;
die "usage: inspect-input-guest.pl /dev/input/eventN packet-count\n"
    unless defined($device) && $device =~ m{^/dev/input/event[0-9]+$}
        && defined($packets) && ($packets eq 'release' ||
            ($packets =~ /^[1-9][0-9]*$/ && $packets <= 1000));
my $until_release = $packets eq 'release';
$packets = 1000 if $until_release;
open(my $input, '<', $device) or die "open $device: $!\n";
my $name = "\0" x 256;
ioctl($input, 0x81004506, $name) or die "EVIOCGNAME: $!\n";
$name =~ s/\0.*//s;
die "wrong input device: $name\n" unless $name eq 'Atmel mXT Touchscreen';
print "N00_INPUT_DEVICE $device $name\n";
for my $axis (48, 50, 53, 54, 57) {
    my $info = "\0" x 24;
    ioctl($input, 0x80184540 + $axis, $info) or die "EVIOCGABS($axis): $!\n";
    print 'N00_INPUT_ABS ', $axis, ' ', join(',', unpack('l6', $info)), "\n";
}
print "N00_INPUT_READER_READY\n";
$SIG{ALRM} = sub { die "input packet timeout\n"; };
alarm(60);
my $count = 0;
my ($pressed, $released) = (0, 0);
while ($count < $packets) {
    my $record = '';
    my $n = sysread($input, $record, 16);
    die "short ARM32 input_event\n" unless defined($n) && $n == 16;
    my ($sec, $usec, $type, $code, $value) = unpack('llSSl', $record);
    print "N00_INPUT_EVENT $sec.$usec $type $code $value\n";
    if ($type == 1 && $code == 330) {
        $pressed = 1 if $value == 1;
        $released = 1 if $pressed && $value == 0;
    }
    if ($type == 0 && $code == 0) {
        ++$count;
        print "N00_INPUT_PACKET_$count\n";
        if ($released) {
            print "N00_INPUT_RELEASED\n";
            last if $until_release;
        }
    }
}
alarm(0);
close($input) or die "close input: $!\n";
print "N00_INPUT_READ_OK\n";
