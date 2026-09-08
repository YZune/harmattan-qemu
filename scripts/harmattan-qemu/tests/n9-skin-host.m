/* Native NSView layout, hit routing and rendering regression.
 * No OS mouse/keyboard events are synthesized. */
#import "../../../ports/qemu-n00/n00-n9-skin.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

static NSPoint hostPoint(NSPoint portrait, NSSize guest, NSSize container, N00N9Geometry geometry)
{
    NSSize model = n00_n9_model_size(guest, geometry);
    CGFloat scale = MIN(container.width / model.width, container.height / model.height);
    if (guest.width > guest.height) portrait = NSMakePoint(portrait.y, geometry.canvas.width - portrait.x);
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

static void checkMatte(N00N9SkinView *skin, NSSize guest, NSSize container,
                       N00N9Geometry geometry)
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
    NSPoint a = hostPoint(geometry.aperture.origin, guest, container, geometry);
    NSPoint b = hostPoint(NSMakePoint(NSMaxX(geometry.aperture), NSMaxY(geometry.aperture)),
                          guest, container, geometry);
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
    N00N9Geometry geometry = n00_n9_geometry(image != nil);
    if (image) {
        /* Freeze legacy alignment independently of the new default frame. */
        assert(NSEqualSizes(geometry.canvas, NSMakeSize(620, 1160)));
        assert(NSEqualRects(geometry.aperture, NSMakeRect(70, 153, 480, 854)));
        assert(NSEqualRects(geometry.glass, NSMakeRect(36, 49.5, 548, 1061)));
        assert(geometry.glassRadius == 40);
        assert(NSEqualRects(geometry.lockTarget, NSMakeRect(586, 628, 34, 106)));
    } else {
        NSRect body = n00_n9_frame_body();
        assert(fabs(body.size.width / body.size.height - 61.2 / 116.45) < 1e-12);
        assert(NSEqualSizes(geometry.canvas, NSMakeSize(632, 1184.5)));
        assert(fabs(geometry.aperture.size.width - 485.3647066802483) < 1e-7);
        assert(fabs(geometry.aperture.size.height - 863.5447073019418) < 1e-7);
        assert(fabs(hypot(geometry.aperture.size.width, geometry.aperture.size.height)
                    / 10 / 25.4 - 3.9) < 1e-12);
        assert(fabs(NSMidX(geometry.aperture) - NSMidX(body)) < 1e-9);
        assert(fabs(NSMidY(geometry.aperture) - NSMidY(body)) < 1e-9);
        assert(NSContainsRect(geometry.glass, geometry.aperture));
        assert(NSContainsRect(geometry.lockTarget, n00_n9_frame_power_key()));
        assert(!NSIntersectsRect(geometry.glass, geometry.lockTarget));
    }
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
    const NSPoint glass[][6] = {
        {{316,592},{316,1120},{316,70},{42,592},{590,592},{40,1118}},
        {{310,580},{310,1090},{310,80},{50,580},{570,580},{50,1080}}
    };
    const NSPoint body[][5] = {
        {{14,592},{618,592},{316,20},{316,1165},{29,39}},
        {{20,580},{600,580},{310,30},{310,1130},{38,51}}
    };
    unsigned mode = image != nil;
    for (unsigned i = 0; i < sizeof(glass[mode])/sizeof(glass[mode][0]); i++) {
        NSPoint local = hostPoint(glass[mode][i], guest, container, geometry);
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
    for (unsigned i = 0; i < sizeof(body[mode])/sizeof(body[mode][0]); i++) {
        NSPoint point = [skin convertPoint:hostPoint(body[mode][i], guest, container, geometry) toView:parent];
        assert([skin hitTest:point] == skin);
    }
    NSPoint keyPoint = [skin convertPoint:hostPoint(image ? NSMakePoint(603, 681) : NSMakePoint(625, 685),
                                                    guest, container, geometry) toView:parent];
    NSView *key = [skin hitTest:keyPoint];
    assert([key isKindOfClass:[N00LockButton class]]);
    assert([(NSButton *)key target] == skin);
    assert([(NSButton *)key action] == @selector(pressLockButton:));
    assert(!NSIntersectsRect([key frame], [screen frame]));
    assert([[(NSButton *)key accessibilityLabel] isEqualToString:@"Lock screen / show unlock screen"]);
    assert([skin hitTest:[skin convertPoint:NSMakePoint(-1, -1) toView:parent]] == nil);
    assert(CGColorEqualToColor([[screen layer] backgroundColor], [[NSColor blackColor] CGColor]));
    checkMatte(skin, guest, container, geometry);
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
