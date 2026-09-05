/* Native NSView layout, hit routing and rendering regression.
 * No OS mouse/keyboard events are synthesized. */
#import "../../../ports/qemu-n00/n00-n9-skin.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static NSPoint hostPoint(NSPoint portrait, NSSize guest, NSSize container)
{
    NSSize model = n00_n9_model_size(guest);
    CGFloat scale = MIN(container.width / model.width, container.height / model.height);
    if (guest.width > guest.height) portrait = NSMakePoint(portrait.y, 620 - portrait.x);
    return NSMakePoint((container.width - model.width * scale) / 2 + portrait.x * scale,
                       (container.height - model.height * scale) / 2 + portrait.y * scale);
}

static void checkBlack(NSBitmapImageRep *bitmap, NSInteger x, NSInteger y)
{
    NSColor *color = [[bitmap colorAtX:x y:[bitmap pixelsHigh] - 1 - y]
                     colorUsingColorSpace:[NSColorSpace genericRGBColorSpace]];
    assert([color alphaComponent] > .999);
    assert([color redComponent] < .001);
    assert([color greenComponent] < .001);
    assert([color blueComponent] < .001);
}

static void checkMatte(N00N9SkinView *skin, NSSize guest, NSSize container)
{
    NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc]
        initWithBitmapDataPlanes:NULL pixelsWide:container.width pixelsHigh:container.height
        bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO
        colorSpaceName:NSCalibratedRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
    [NSGraphicsContext saveGraphicsState];
    [NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithBitmapImageRep:bitmap]];
    [[NSColor magentaColor] setFill];
    NSRectFill([skin bounds]);
    [skin drawRect:[skin bounds]];
    [NSGraphicsContext restoreGraphicsState];
    NSPoint a = hostPoint(NSMakePoint(70, 153), guest, container);
    NSPoint b = hostPoint(NSMakePoint(550, 1007), guest, container);
    NSInteger left = floor(MIN(a.x, b.x)), right = ceil(MAX(a.x, b.x));
    NSInteger bottom = floor(MIN(a.y, b.y)), top = ceil(MAX(a.y, b.y));
    /* Include the first pixel outside all four edges, at fractional scales. */
    for (NSInteger x = left - 1; x <= right; x++) {
        checkBlack(bitmap, x, bottom - 1);
        checkBlack(bitmap, x, top);
    }
    for (NSInteger y = bottom - 1; y <= top; y++) {
        checkBlack(bitmap, left - 1, y);
        checkBlack(bitmap, right, y);
    }
    checkBlack(bitmap, (left + right) / 2, (bottom + top) / 2);
    [bitmap release];
}

static void check(NSSize guest, NSSize container, NSImage *image)
{
    NSView *parent = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 1600, 1600)];
    NSView *screen = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, guest.width, guest.height)];
    N00N9SkinView *skin = [[N00N9SkinView alloc] initWithGuestView:screen image:image];
    [parent addSubview:skin];
    [skin setFrameOrigin:NSMakePoint(17, 23)];
    [skin resizeWindowForGuestSize:guest];
    [skin setFrameSize:container];
    [skin layoutGuest];
    NSRect f = [screen frame];
    assert(f.origin.x >= 0 && f.origin.y >= 0);
    assert(NSMaxX(f) <= container.width && NSMaxY(f) <= container.height);
    assert(fabs(f.size.width / f.size.height - guest.width / guest.height) < 1e-9);
    const double points[][2] = {{0, 0}, {1, 0}, {0, 1}, {1, 1}, {.5, .5}, {.01, .6}, {.99, .2}};
    for (unsigned i = 0; i < sizeof(points)/sizeof(points[0]); i++) {
        NSPoint host = NSMakePoint(f.origin.x + f.size.width * points[i][0],
                                   f.origin.y + f.size.height * points[i][1]);
        NSPoint p = [screen convertPoint:host fromView:skin];
        assert(fabs(p.x - guest.width * points[i][0]) < 1e-7);
        assert(fabs(p.y - guest.height * points[i][1]) < 1e-7);
    }
    const NSPoint glass[] = {{310,580},{310,1090},{310,80},{50,580},{570,580},{50,1080}};
    const NSPoint body[] = {{20,580},{600,580},{310,30},{310,1130},{38,51}};
    for (unsigned i = 0; i < sizeof(glass)/sizeof(glass[0]); i++) {
        NSPoint local = hostPoint(glass[i], guest, container);
        NSPoint point = [skin convertPoint:local toView:parent];
        assert([skin hitTest:point] == screen);
        NSPoint raw = [screen convertPoint:local fromView:skin];
        NSPoint touch = n00_n9_clamp_touch(raw, guest);
        assert(touch.x >= 0 && touch.x <= guest.width);
        assert(touch.y >= 0 && touch.y <= guest.height);
        if (i > 0) { /* Every bezel press reaches an exact guest edge. */
            assert(touch.x == 0 || touch.x == guest.width ||
                   touch.y == 0 || touch.y == guest.height);
        }
        if (NSPointInRect(raw, [screen bounds])) assert(NSEqualPoints(touch, raw));
    }
    for (unsigned i = 0; i < sizeof(body)/sizeof(body[0]); i++) {
        NSPoint point = [skin convertPoint:hostPoint(body[i], guest, container) toView:parent];
        assert([skin hitTest:point] == skin);
    }
    assert([skin hitTest:[skin convertPoint:NSMakePoint(-1, -1) toView:parent]] == nil);
    assert(CGColorEqualToColor([[screen layer] backgroundColor], [[NSColor blackColor] CGColor]));
    checkMatte(skin, guest, container);
    [skin release];
    [screen release];
    [parent release];
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        /* Synthetic transparent geometry fixture, not product artwork.
         * The test covers coordinates and the opaque aperture matte. */
        NSBitmapImageRep *bitmap = [[NSBitmapImageRep alloc]
            initWithBitmapDataPlanes:NULL pixelsWide:1240 pixelsHigh:2320
            bitsPerSample:8 samplesPerPixel:4 hasAlpha:YES isPlanar:NO
            colorSpaceName:NSCalibratedRGBColorSpace bytesPerRow:0 bitsPerPixel:0];
        memset([bitmap bitmapData], 0, [bitmap bytesPerRow] * [bitmap pixelsHigh]);
        NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(1240,2320)];
        [image addRepresentation:bitmap];
        [bitmap release];
        const NSSize surfaces[] = {{480,864},{864,480},{640,480}};
        const NSSize sizes[] = {{465,870},{310,580},{558,1044},{1280,800},{800,1280}};
        for (unsigned i=0; i<3; i++)
            for (unsigned j=0; j<5; j++) {
                check(surfaces[i],sizes[j],image);
                check(surfaces[i],sizes[j],nil);
            }
        [image release];
        puts("PASS: 30 native view layouts; 210 coordinate conversions; 360 hit targets; 180 glass touches; image and code-drawn frames");
    }
}
