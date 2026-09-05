/* Native lifecycle test using a code-generated movie; no firmware/artwork. */
#import "../../../ports/qemu-n00/n00-boot-animation.h"
#include <assert.h>
#include <stdio.h>

static void pump(double seconds)
{
    NSDate *end = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while ([end timeIntervalSinceNow] > 0) {
        [[NSRunLoop mainRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
    }
}

static void makeMovie(NSString *path)
{
    NSError *error = nil;
    AVAssetWriter *writer = [[AVAssetWriter alloc] initWithURL:[NSURL fileURLWithPath:path]
        fileType:AVFileTypeQuickTimeMovie error:&error];
    assert(writer && !error);
    AVAssetWriterInput *input = [AVAssetWriterInput assetWriterInputWithMediaType:AVMediaTypeVideo
        outputSettings:@{AVVideoCodecKey: AVVideoCodecTypeH264, AVVideoWidthKey:@32, AVVideoHeightKey:@16}];
    AVAssetWriterInputPixelBufferAdaptor *adaptor =
        [AVAssetWriterInputPixelBufferAdaptor assetWriterInputPixelBufferAdaptorWithAssetWriterInput:input
            sourcePixelBufferAttributes:@{(id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_32BGRA),
                (id)kCVPixelBufferWidthKey:@32, (id)kCVPixelBufferHeightKey:@16}];
    [writer addInput:input];
    assert([writer startWriting]);
    [writer startSessionAtSourceTime:kCMTimeZero];
    for (int i = 0; i < 15; i++) {
        NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:3];
        while (!input.readyForMoreMediaData && [limit timeIntervalSinceNow] > 0) pump(.01);
        assert(input.readyForMoreMediaData);
        CVPixelBufferRef buffer;
        assert(CVPixelBufferPoolCreatePixelBuffer(NULL, adaptor.pixelBufferPool, &buffer) == kCVReturnSuccess);
        CVPixelBufferLockBaseAddress(buffer, 0);
        uint8_t *bytes = CVPixelBufferGetBaseAddress(buffer);
        size_t stride = CVPixelBufferGetBytesPerRow(buffer);
        for (int y = 0; y < 16; y++) for (int x = 0; x < 32; x++) {
            uint8_t *pixel = bytes + y * stride + x * 4;
            pixel[0] = 0; pixel[1] = i * 17; pixel[2] = 255 - i * 17; pixel[3] = 255;
        }
        CVPixelBufferUnlockBaseAddress(buffer, 0);
        assert([adaptor appendPixelBuffer:buffer withPresentationTime:CMTimeMake(i, 30)]);
        CVPixelBufferRelease(buffer);
    }
    [input markAsFinished];
    __block BOOL finished = NO;
    [writer finishWritingWithCompletionHandler:^{ finished = YES; }];
    NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5];
    while (!finished && [limit timeIntervalSinceNow] > 0) pump(.01);
    assert(finished && writer.status == AVAssetWriterStatusCompleted);
    [writer release];
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        assert(argc == 2 || argc == 3);
        [NSApplication sharedApplication];
        NSString *directory = [NSString stringWithUTF8String:argv[1]];
        NSString *path = [directory stringByAppendingPathComponent:@"movie.mp4"];
        if (argc == 3) {
            assert([[NSFileManager defaultManager] copyItemAtPath:
                [NSString stringWithUTF8String:argv[2]] toPath:path error:NULL]);
        } else makeMovie(path);
        NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 480, 864)
            styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
        NSView *guest = window.contentView;
        [guest setWantsLayer:YES];
        for (NSInteger degrees = 0; degrees < 360; degrees += 90) {
            N00BootAnimationView *view = [[N00BootAnimationView alloc] initWithFrame:guest.bounds
                directory:directory rotation:degrees];
            assert(view);
            [guest addSubview:view];
            [view layoutMovie];
            CALayer *media = [view valueForKey:@"mediaLayer"];
            CATransform3D transform = media.transform;
            assert(fabs(transform.m11 - cos(degrees * M_PI / 180) * hypot(transform.m11, transform.m12)) < 1e-6);
            assert(fabs(transform.m12 - sin(degrees * M_PI / 180) * hypot(transform.m11, transform.m12)) < 1e-6);
            [view removeFromSuperview];
            [view release];
        }
        N00BootAnimationView *view = [[N00BootAnimationView alloc] initWithFrame:guest.bounds
            directory:directory rotation:270];
        assert(view);
        [guest addSubview:view];
        [guest setFrameSize:NSMakeSize(240, 432)];
        assert(NSEqualRects(view.frame, guest.bounds));
        [guest setBoundsSize:NSMakeSize(640, 480)];
        [view poll:nil];
        [guest setBoundsSize:NSMakeSize(480, 864)];
        [view poll:nil];
        assert(NSEqualRects(view.frame, guest.bounds));
        CALayer *media = [view valueForKey:@"mediaLayer"];
        assert(fabs(media.position.x - view.bounds.size.width / 2) < 1e-6);
        assert(fabs(media.position.y - view.bounds.size.height / 2) < 1e-6);
        NSString *phase = [directory stringByAppendingPathComponent:@"phase"];
        [@"invalid\n" writeToFile:phase atomically:YES encoding:NSUTF8StringEncoding error:NULL];
        pump(.1);
        assert(view.superview == guest);
        [@"play\n" writeToFile:phase atomically:YES encoding:NSUTF8StringEncoding error:NULL];
        AVPlayer *player = [view valueForKey:@"player"];
        NSDate *limit = [NSDate dateWithTimeIntervalSinceNow:5];
        while (CMTimeGetSeconds(player.currentTime) <= .1 && [limit timeIntervalSinceNow] > 0) pump(.02);
        assert(CMTimeGetSeconds(player.currentTime) > .1);
        AVPlayerLayer *movie = [view valueForKey:@"movieLayer"];
        assert(!movie.hidden && player.muted);
        pump(CMTimeGetSeconds(player.currentItem.duration) + .2);
        assert(view.superview == guest); // Movie end alone cannot reveal Home.
        assert(player.rate == 0);
        [@"ready\n" writeToFile:phase atomically:YES encoding:NSUTF8StringEncoding error:NULL];
        pump(.15);
        assert(view.superview == nil);
        assert([[NSFileManager defaultManager] fileExistsAtPath:
            [directory stringByAppendingPathComponent:@"revealed"]]);
        [view release];
        [window release];
        puts("PASS: boot movie playback, rotation, hold and explicit reveal");
    }
    return 0;
}
