/* SPDX-License-Identifier: MIT
 * Host presentation only. The controller extracts and hashes the user's movie.
 * QMP screendumps and guest scanout always retain the real guest framebuffer.
 */
#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#import <QuartzCore/QuartzCore.h>

@interface N00BootAnimationView : NSView
{
    NSString *directory;
    AVPlayer *player;
    AVPlayerLayer *movieLayer;
    CALayer *mediaLayer;
    NSTimer *timer; /* run loop owns it; invalidate before detaching */
    NSInteger rotation;
    BOOL playing;
    BOOL failed;
}
- (id)initWithFrame:(NSRect)frame directory:(NSString *)path rotation:(NSInteger)degrees;
- (void)poll:(NSTimer *)sender;
- (void)layoutMovie;
@end

@implementation N00BootAnimationView
- (void)record:(NSString *)name value:(NSString *)value
{
    [value writeToFile:[directory stringByAppendingPathComponent:name]
           atomically:YES encoding:NSUTF8StringEncoding error:NULL];
}

- (id)initWithFrame:(NSRect)frame directory:(NSString *)path rotation:(NSInteger)degrees
{
    self = [super initWithFrame:frame];
    if (!self) return nil;
    directory = [path copy];
    rotation = degrees;
    [self setAutoresizingMask:NSViewWidthSizable | NSViewHeightSizable];
    [self setWantsLayer:YES];
    self.layer.backgroundColor = NSColor.blackColor.CGColor;
    self.layer.masksToBounds = YES;
    NSURL *url = [NSURL fileURLWithPath:[path stringByAppendingPathComponent:@"movie.mp4"]];
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:url options:nil];
    AVAssetImageGenerator *generator = [AVAssetImageGenerator assetImageGeneratorWithAsset:asset];
    generator.appliesPreferredTrackTransform = YES;
    NSError *error = nil;
    CGImageRef first = [generator copyCGImageAtTime:kCMTimeZero actualTime:NULL error:&error];
    if (!first) {
        [self record:@"failed" value:[NSString stringWithFormat:@"Cannot decode boot movie: %@\n", error]];
        [self release];
        return nil;
    }
    mediaLayer = [CALayer layer];
    mediaLayer.bounds = CGRectMake(0, 0, CGImageGetWidth(first), CGImageGetHeight(first));
    mediaLayer.contents = (id)first;
    CGImageRelease(first);
    [self.layer addSublayer:mediaLayer];
    player = [[AVPlayer alloc] initWithPlayerItem:[AVPlayerItem playerItemWithAsset:asset]];
    player.muted = YES; /* This does not emulate the guest's audio device. */
    player.actionAtItemEnd = AVPlayerActionAtItemEndPause;
    movieLayer = [AVPlayerLayer playerLayerWithPlayer:player];
    movieLayer.frame = mediaLayer.bounds;
    movieLayer.videoGravity = AVLayerVideoGravityResizeAspect;
    movieLayer.hidden = YES;
    [mediaLayer addSublayer:movieLayer];
    [self layoutMovie];
    [self record:@"loaded" value:@"original-movie\n"];
    timer = [NSTimer timerWithTimeInterval:.05 target:self selector:@selector(poll:)
                                  userInfo:nil repeats:YES];
    [[NSRunLoop mainRunLoop] addTimer:timer forMode:NSRunLoopCommonModes];
    return self;
}

- (void)dealloc
{
    [player pause];
    [player release];
    [directory release];
    [super dealloc];
}

- (void)viewWillMoveToWindow:(NSWindow *)window
{
    if (!window) {
        [timer invalidate];
        timer = nil;
        [player pause];
    }
    [super viewWillMoveToWindow:window];
}

- (void)layoutMovie
{
    if (!mediaLayer) return;
    CGSize movie = mediaLayer.bounds.size;
    NSSize area = self.bounds.size;
    BOOL portrait = rotation == 90 || rotation == 270;
    CGFloat scale = MIN(area.width / (portrait ? movie.height : movie.width),
                        area.height / (portrait ? movie.width : movie.height));
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    mediaLayer.position = CGPointMake(area.width / 2, area.height / 2);
    mediaLayer.transform = CATransform3DScale(
        CATransform3DMakeRotation(rotation * M_PI / 180, 0, 0, 1), scale, scale, 1);
    [CATransaction commit];
}

- (void)resizeSubviewsWithOldSize:(NSSize)size
{
    [super resizeSubviewsWithOldSize:size];
    [self layoutMovie];
}

- (void)poll:(NSTimer *)sender
{
    if (failed) return;
    // QEMU changes bounds independently of its zoomed frame on the first
    // scanout/rotation. That need not invoke resizeSubviewsWithOldSize.
    if (self.superview) {
        if (!NSEqualRects(self.frame, self.superview.bounds)) self.frame = self.superview.bounds;
        [self layoutMovie];
    }
    if (player.status == AVPlayerStatusFailed || player.currentItem.status == AVPlayerItemStatusFailed) {
        failed = YES;
        [self record:@"failed" value:@"Native boot movie playback failed\n"];
        return;
    }
    NSString *phase = [NSString stringWithContentsOfFile:
        [directory stringByAppendingPathComponent:@"phase"] encoding:NSUTF8StringEncoding error:NULL];
    if ([phase isEqualToString:@"ready\n"]) {
        // Only the controller's successful validators can request this state.
        // Never infer readiness from elapsed playback time or a window title.
        [self retain];
        [timer invalidate];
        timer = nil;
        [player pause];
        NSView *guest = [self superview];
        [self removeFromSuperview];
        [guest setNeedsDisplay:YES];
        [guest displayIfNeeded];
        [CATransaction flush];
        [self record:@"revealed" value:@"ready\n"];
        [self release];
    } else if ([phase isEqualToString:@"play\n"] && !playing && player.status == AVPlayerStatusReadyToPlay) {
        playing = YES;
        movieLayer.hidden = NO;
        [player play];
        [self record:@"playing" value:@"once\n"];
    }
}

// Early pointer events end here; the existing guest grab also protects keyboard
// input and the skin's glass-edge route until the controller releases it.
- (void)mouseDown:(NSEvent *)event {}
- (void)mouseDragged:(NSEvent *)event {}
- (void)mouseUp:(NSEvent *)event {}
- (void)rightMouseDown:(NSEvent *)event {}
- (void)otherMouseDown:(NSEvent *)event {}
- (void)scrollWheel:(NSEvent *)event {}
@end

static void n00_boot_animation_attach(NSView *guest)
{
    const char *path = getenv("N00_COCOA_BOOT_ANIMATION");
    if (!path || !*path) return;
    const char *value = getenv("N00_COCOA_BOOT_ROTATION");
    if (!value || (strcmp(value, "0") && strcmp(value, "90") &&
                   strcmp(value, "180") && strcmp(value, "270"))) {
        fprintf(stderr, "Invalid native boot animation rotation\n");
        exit(1);
    }
    N00BootAnimationView *view = [[N00BootAnimationView alloc]
        initWithFrame:guest.bounds directory:[NSString stringWithUTF8String:path] rotation:atoi(value)];
    if (!view) {
        fprintf(stderr, "Cannot load original boot animation; inspect boot/failed\n");
        exit(1);
    }
    [guest addSubview:view];
    [view release];
}
