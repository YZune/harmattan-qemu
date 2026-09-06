# Wait for original X11 ownership and mapped Home, not a fixed boot delay.
# SPDX-License-Identifier: GPL-2.0-or-later
use strict;
use warnings;
use FindBin;
use lib $FindBin::Bin;
use N00X11;
use Time::HiRes qw(time sleep);

my $role = shift || '';
($role eq 'compositor' || $role eq 'home') && !@ARGV or die "role must be compositor or home\n";
my $started = time;
my $attempts = 0;
my $last_error = '';
alarm 35;
while (time - $started < 30) {
    ++$attempts;
    my $ok = eval {
        my $x = N00X11->new('/tmp/.X11-unix/X9');
        my $manager = $x->compositor();
        if ($role eq 'compositor' && ($ENV{N00_UI_ANIMATIONS} || '') eq '1') {
            # WM ownership precedes the initial root resize. The existing
            # animation gate also needs the real restacker event and shaders.
            # Observe their log; do not synthesize a resize or skip that gate.
            open my $log, '<', '/tmp/n00-shell-compositor.log' or die "compositor log: $!\n";
            my $contents = do { local $/; <$log> };
            close $log;
            for my $marker (qw(WORLD_CACHE_ACTIVE PROJECTION_APPLIED ROOT_CONFIGURE_IGNORED)) {
                $contents =~ /^N00_COMPOSITOR_\Q$marker\E$/m
                    or die "compositor initialization incomplete: $marker\n";
            }
        }
        if ($role eq 'home') {
            my $pid = `pidof meegotouchhome`;
            chomp $pid;
            $pid =~ /^[1-9][0-9]*$/ or die "Home process not unique\n";
            my @clients = unpack('V*', $x->property($x->{root}, '_NET_CLIENT_LIST_STACKING', 33, 32));
            my @home;
            for my $window (@clients) {
                my $class = eval { $x->property($window, 'WM_CLASS', 31, 8) };
                next unless defined($class) && $class eq "meegotouchhome\0Meegotouchhome\0";
                my $actual = unpack('V', $x->property($window, '_NET_WM_PID', 6, 32));
                my $attrs = $x->request(3, 0, pack('V', $window));
                my ($px, $py, $width, $height) = unpack('x12ssvv', $x->request(14, 0, pack('V', $window)));
                $actual == $pid && unpack('x26C', $attrs) == 2 &&
                    $px == 0 && $py == 0 && $width == 864 && $height == 480
                    or die "Home not mapped at original geometry\n";
                push @home, $window;
            }
            @home == 1 or die "Home not uniquely managed\n";
        }
        $x->sync();
        1;
    };
    if ($ok) {
        printf "N00_SHELL_READY role=%s attempts=%d seconds=%.3f\n", $role, $attempts, time - $started;
        exit 0;
    }
    $last_error = $@;
    sleep .1;
}
die "Original $role did not become ready: $last_error";
