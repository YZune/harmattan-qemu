# SPDX-License-Identifier: GPL-2.0-or-later
# Drive the original sysuid lock UI in the rescue desktop. This is not MCE,
# a device/PIN lock, or emulated display power management.
use strict;
use warnings;
use FindBin;
use lib $FindBin::Bin;
use N00X11;
use Time::HiRes qw(time sleep);

alarm 20;
my $action = shift || '';
($action eq 'inspect' || $action eq 'press') && !@ARGV or die "invalid lock action\n";

sub command {
    open my $pipe, '-|', @_ or die "lock command: $!\n";
    my $text = do { local $/; <$pipe> };
    close $pipe or die "lock command failed\n";
    return $text;
}
my $pid = command('pidof', 'sysuid');
chomp $pid;
$pid =~ /^[1-9][0-9]*$/ or die "sysuid must be unique\n";
for my $input (["/proc/$pid/exe", '6e6ca0153aea0bf3b4556c08d68f934f'],
               ['/usr/lib/meegotouch/applicationextensions/libsysuid-screenlock-nokia.so',
                'd80c0728dae6c55ac53b08170aea63f7']) {
    command('md5sum', $input->[0]) =~ /^\Q$input->[1]\E  / or die "original lock UI hash mismatch\n";
}
my @bus = ('dbus-send', '--system', '--print-reply', '--reply-timeout=5000');
my $owner = command(@bus, '--dest=org.freedesktop.DBus', '/org/freedesktop/DBus',
    'org.freedesktop.DBus.GetConnectionUnixProcessID', 'string:com.nokia.system_ui');
$owner =~ /\n\s+uint32 \Q$pid\E\n$/ or die "original lock bus owner mismatch\n";

sub state {
    my $x = N00X11->new('/tmp/.X11-unix/X9');
    $x->compositor();
    my $clients = $x->property($x->{root}, '_NET_CLIENT_LIST_STACKING', 33, 32);
    length($clients) <= 1024 && length($clients) % 4 == 0 or die "invalid managed window list\n";
    my @locks;
    for my $window (unpack('V*', $clients)) {
        my $class = eval { $x->property($window, 'WM_CLASS', 31, 8) };
        next unless defined($class) && $class eq "sysuid\0Sysuid\0";
        my $name = eval { $x->property($window, 'WM_NAME', 31, 8) };
        next unless defined($name) && $name eq 'Screen Lock';
        my $actual = unpack('V', $x->property($window, '_NET_WM_PID', 6, 32));
        $actual == $pid or die "lock window process mismatch\n";
        my $map = unpack('x26C', $x->request(3, 0, pack('V', $window)));
        # Qt also has hidden helper windows. Only the mapped, managed lock
        # window owns the mode property and actually covers the application.
        next if $map == 0;
        my $reply = $x->request(20, 0, pack('V5', $window, $x->atom('_MEEGO_LOW_POWER_MODE'), 0, 0, 4));
        my ($format, $type, $after, $items) = unpack('xCx6VVV', $reply);
        $type == 6 && $format == 32 && !$after && $items == 1 && length($reply) == 36
            or die "invalid lock mode property: window=$window map=$map type=$type format=$format after=$after items=$items raw=" . unpack('H*', $reply) . "\n";
        my $low = unpack('x32V', $reply);
        $map == 2 && ($low == 0 || $low == 1) or die "invalid lock window state\n";
        push @locks, {window => $window, mapped => $map == 2 ? 1 : 0, low => $low};
    }
    @locks <= 1 or die "ambiguous lock window\n";
    return @locks ? $locks[0] : {window => 0, mapped => 0, low => 0};
}

my $state = state();
if ($action eq 'press') {
    # The original low-power clock is a UI mode, not guest suspend. The next
    # press reveals the original wallpaper/unlock gesture. Never bypass it.
    my $mode = $state->{mapped} && $state->{low} ? 5 : 6;
    # sysuid accepts an empty callback method. Its own unlocked() signal hides
    # the UI; no fake com.nokia.mce owner or successful security response.
    my $reply = command(@bus, '--dest=com.nokia.system_ui', '/com/nokia/system_ui/request',
        'com.nokia.system_ui.request.tklock_open', 'string:org.freedesktop.DBus',
        'string:/org/freedesktop/DBus', 'string:org.freedesktop.DBus', 'string:',
        "uint32:$mode", 'boolean:true', 'boolean:false');
    $reply =~ /\n\s+int32 1\n$/ or die "lock UI rejected request\n";
    my $end = time + 5;
    my $last_error = '';
    while (time < $end) {
        # tklock_open replies before its queued showEvent sets the X11 mode
        # property. Observe readiness; an accepted D-Bus call is not a pass.
        my $observed = eval { state() };
        $last_error = $@;
        $state = $observed if $observed;
        last if !$last_error && $state->{mapped} && $state->{low} == ($mode == 6 ? 1 : 0);
        sleep .05;
    }
    !$last_error && $state->{mapped} && $state->{low} == ($mode == 6 ? 1 : 0)
        or die "lock UI did not reach requested state: $last_error\n";
}
printf "N00_LOCKSCREEN window=%08x pid=%u mapped=%u low_power=%u\n",
    $state->{window}, $pid, $state->{mapped}, $state->{low};
