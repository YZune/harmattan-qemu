#!/usr/bin/perl
# SPDX-License-Identifier: GPL-2.0-or-later
# Original protocol: mcompositor 1.1.35 doc/src/splash-screens.dox and
# tests/manual-splash/main.cpp. Original compositor owns loading/animation.
use strict;
use warnings;
use FindBin;
use lib $FindBin::Bin;
use N00X11;

sub publish {
    my ($pid, $portrait, $landscape, $endpoint) = @_;
    defined($pid) && $pid =~ /^[1-9][0-9]{0,9}$/ && $pid <= 2147483647
        or die "invalid application PID\n";
    defined($portrait) && length($portrait) or die "portrait image required\n";
    for my $file ($portrait, $landscape) {
        defined($file) && $file !~ /[\x00-\x1f\x7f]/ or die "invalid splash path\n";
        next if $file eq '';
        $file =~ m{^/} && -f $file && -r $file or die "unreadable splash image\n";
    }
    # readSplashProperty() reads at most 1000 32-bit words. Include every NUL.
    my $value = join("\0", $pid, '', $portrait, $landscape, '0', '');
    length($value) <= 4000 or die "oversized splash property\n";
    my $x = N00X11->new($endpoint);
    my $wm = $x->compositor();
    $x->send_request(18, 0, pack('V3CxxxV', $wm, $x->atom('_MEEGO_SPLASH_SCREEN'), 31, 8, length($value)) . $value);
    $x->sync();
    printf "N00_SPLASH_PUBLISHED pid=%u wm=%08x portrait=%s landscape=%s\n",
        $pid, $wm, unpack('H*', $portrait), unpack('H*', $landscape);
    # Publication is not a visual PASS. The host's transition probe separately
    # observes the actual original splash and application frames.
}

unless (caller) {
    alarm 5;
    @ARGV == 3 && $ARGV[0] eq getppid() or die "expected direct invoker parent PID and two image paths\n";
    publish(@ARGV);
}
1;
