/* SPDX-License-Identifier: MIT
 * Host-only frame, with optional user-supplied Livven artwork.
 * Artwork attribution and export details: skins/README.md (not MIT licensed).
 * The unchanged QEMU framebuffer is a separate, opaque child NSView.
 */
#import <Cocoa/Cocoa.h>
#import <QuartzCore/QuartzCore.h>

static NSSize n00_n9_model_size(NSSize guest)
{
    return guest.width > guest.height ? NSMakeSize(1160, 620)
                                      : NSMakeSize(620, 1160);
}

static NSRect n00_n9_aperture(NSSize guest)
{
    /* Original PSD: Screen (480x854 @2x), (220,546)-(1180,2254).
     * PNG crop: (80,240)-(1320,2560), displayed at half its pixel size. */
    return guest.width > guest.height ? NSMakeRect(153, 70, 854, 480)
                                      : NSMakeRect(70, 153, 480, 854);
}

static NSPoint n00_n9_clamp_touch(NSPoint point, NSSize screen)
{
    /* QEMU absolute axes include both endpoints, unlike NSPointInRect. */
    return NSMakePoint(MIN(screen.width, MAX(0, point.x)),
                       MIN(screen.height, MAX(0, point.y)));
}

@interface N00N9SkinView : NSView
{
    NSView *guestView; /* retained by the subview hierarchy */
    NSImage *caseImage;
    NSSize guestSize;
    BOOL configured;
}
- (id)initWithGuestView:(NSView *)view image:(NSImage *)image;
- (void)resizeWindowForGuestSize:(NSSize)size;
- (void)layoutGuest;
@end

@implementation N00N9SkinView
- (id)initWithGuestView:(NSView *)view image:(NSImage *)image
{
    self = [super initWithFrame:NSMakeRect(0, 0, 465, 870)];
    if (self) {
        guestView = view;
        caseImage = [image retain];
        guestSize = NSMakeSize(480, 864);
        [self setWantsLayer:YES];
        [view setWantsLayer:YES];
        [[view layer] setBackgroundColor:[[NSColor blackColor] CGColor]];
        [self addSubview:view];
        [self layoutGuest];
    }
    return self;
}

- (void)dealloc
{
    [caseImage release];
    [super dealloc];
}

- (BOOL)isOpaque { return NO; }

- (NSView *)hitTest:(NSPoint)point
{
    NSView *hit = [super hitTest:point];
    if (!hit) return nil;
    NSPoint local = [self convertPoint:point fromView:[self superview]];
    NSSize model = n00_n9_model_size(guestSize), bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    if (scale <= 0) return hit;
    local.x = (local.x - (bounds.width - model.width * scale) / 2) / scale;
    local.y = (local.y - (bounds.height - model.height * scale) / 2) / scale;
    if (guestSize.width > guestSize.height) {
        local = NSMakePoint(620 - local.y, local.x);
    }
    /* Original PSD Body/Glass vector mask, in the cropped half-size model.
     * Give AppKit the guest as the initial receiver even outside its frame:
     * it then owns the complete down/drag/up sequence across the screen edge. */
    NSBezierPath *glass = [NSBezierPath bezierPathWithRoundedRect:
        NSMakeRect(36, 49.5, 548, 1061) xRadius:40 yRadius:40];
    return [glass containsPoint:local] ? guestView : hit;
}

- (void)layoutGuest
{
    NSSize model = n00_n9_model_size(guestSize);
    NSSize bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    NSRect aperture = n00_n9_aperture(guestSize);
    /* Keep all guest pixels and their aspect ratio. The 480x864 guest is a
     * little taller than the original N9 screen; the gap stays black. */
    CGFloat fit = MIN(aperture.size.width / guestSize.width,
                      aperture.size.height / guestSize.height);
    NSSize display = NSMakeSize(guestSize.width * fit, guestSize.height * fit);
    NSRect frame = NSMakeRect(
        (bounds.width - model.width * scale) / 2 +
            (aperture.origin.x + (aperture.size.width - display.width) / 2) * scale,
        (bounds.height - model.height * scale) / 2 +
            (aperture.origin.y + (aperture.size.height - display.height) / 2) * scale,
        display.width * scale, display.height * scale);
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    [guestView setFrame:frame];
    [guestView setBoundsSize:guestSize];
    [CATransaction commit];
}

- (void)resizeSubviewsWithOldSize:(NSSize)oldSize
{
    [self layoutGuest];
    [self setNeedsDisplay:YES];
}

- (void)resizeWindowForGuestSize:(NSSize)size
{
    BOOL changed = !NSEqualSizes(size, guestSize);
    guestSize = size;
    NSWindow *window = [self window];
    if (!window) return;
    NSSize model = n00_n9_model_size(size);
    [window setContentAspectRatio:model];
    [window setContentMinSize:NSMakeSize(model.width * .32, model.height * .32)];
    if (!([window styleMask] & NSWindowStyleMaskFullScreen)) {
        NSRect available = [window contentRectForFrameRect:[[window screen] visibleFrame]];
        CGFloat scale = MIN(.75, MIN((available.size.width - 32) / model.width,
                                      (available.size.height - 32) / model.height));
        if (configured && !changed && ([window styleMask] & NSWindowStyleMaskResizable)) {
            scale = MIN([self bounds].size.width / model.width,
                        [self bounds].size.height / model.height);
        }
        [window setContentSize:NSMakeSize(model.width * scale, model.height * scale)];
        if (!configured || changed) [window center];
    }
    configured = YES;
    [self layoutGuest];
    [self setNeedsDisplay:YES];
}

- (void)mouseDown:(NSEvent *)event
{
    /* Only the outer body receives this event; the guest owns all glass. */
    [[self window] performWindowDragWithEvent:event];
}

- (void)drawRect:(NSRect)dirty
{
    [[NSColor clearColor] setFill];
    NSRectFillUsingOperation(dirty, NSCompositingOperationCopy);
    NSSize model = n00_n9_model_size(guestSize), bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    CGContextRef context = [[NSGraphicsContext currentContext] CGContext];
    [NSGraphicsContext saveGraphicsState];
    CGContextTranslateCTM(context, (bounds.width - model.width * scale) / 2,
                          (bounds.height - model.height * scale) / 2);
    CGContextScaleCTM(context, scale, scale);
    if (guestSize.width > guestSize.height) {
        CGContextTranslateCTM(context, 0, 620);
        CGContextRotateCTM(context, -M_PI_2);
    }
    [[NSGraphicsContext currentContext] setImageInterpolation:NSImageInterpolationHigh];
    if (caseImage) {
        [caseImage drawInRect:NSMakeRect(0, 0, 620, 1160)
                    fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1];
    } else {
        /* Original code-drawn fallback; no third-party image or logo. */
        NSBezierPath *body = [NSBezierPath bezierPathWithRoundedRect:
            NSMakeRect(25, 20, 570, 1120) xRadius:78 yRadius:78];
        [[NSColor colorWithCalibratedWhite:.12 alpha:1] setFill];
        [body fill];
        [[NSColor colorWithCalibratedWhite:.25 alpha:1] setStroke];
        [body setLineWidth:2];
        [body stroke];
        [[NSColor colorWithCalibratedWhite:.025 alpha:1] setFill];
        [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(36, 49.5, 548, 1061)
            xRadius:40 yRadius:40] fill];
        [[NSColor colorWithCalibratedWhite:.18 alpha:1] setFill];
        [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(259, 1072, 102, 5)
            xRadius:2.5 yRadius:2.5] fill];
    }
    /* Overlap the opening by two view points, including at fractional zoom.
     * This covers the resampled PNG/child-layer fringe as well as aspect-fit
     * gaps. The framebuffer itself keeps its complete, unscaled bounds. */
    [[NSColor blackColor] setFill];
    if (scale > 0) {
        NSRectFill(NSInsetRect(NSMakeRect(70, 153, 480, 854), -2 / scale, -2 / scale));
    }
    [NSGraphicsContext restoreGraphicsState];
}
@end

static N00N9SkinView *n00_n9_skin;
