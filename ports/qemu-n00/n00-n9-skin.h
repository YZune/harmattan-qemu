/* SPDX-License-Identifier: MIT
 * Host-only frame, with optional user-supplied Livven artwork.
 * Artwork attribution and export details: skins/README.md (not MIT licensed).
 * The unchanged QEMU framebuffer is a separate, opaque child NSView.
 */
#import <Cocoa/Cocoa.h>
#import <QuartzCore/QuartzCore.h>
#include "n00-lockscreen-control.h"
#include "n00-n9-frame.h"

@interface N00LockButton : NSButton
@end
@implementation N00LockButton
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (BOOL)mouseDownCanMoveWindow { return NO; }
- (void)mouseDown:(NSEvent *)event
{
    if (n00_lockscreen_ready()) [super mouseDown:event];
}
@end

static N00N9Geometry n00_n9_geometry(BOOL artwork)
{
    if (!artwork) return n00_n9_frame_geometry();
    /* Optional user-supplied Livven skin only. Preserve its existing mapping:
     * PSD Screen (220,546)-(1180,2254); crop (80,240)-(1320,2560), half size.
     * Glass follows that artwork's Body/Glass mask. */
    N00N9Geometry geometry = {
        NSMakeSize(620, 1160), NSMakeRect(70, 153, 480, 854),
        NSMakeRect(36, 49.5, 548, 1061), 40, NSMakeRect(586, 628, 34, 106)
    };
    return geometry;
}

static NSSize n00_n9_model_size(NSSize guest, N00N9Geometry geometry)
{
    return guest.width > guest.height
        ? NSMakeSize(geometry.canvas.height, geometry.canvas.width) : geometry.canvas;
}

static NSRect n00_n9_oriented_rect(NSRect portrait, NSSize guest, NSSize canvas)
{
    return guest.width > guest.height
        ? NSMakeRect(portrait.origin.y, canvas.width - NSMaxX(portrait),
                     portrait.size.height, portrait.size.width) : portrait;
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
    N00LockButton *lockButton; /* retained by the subview hierarchy */
}
- (id)initWithGuestView:(NSView *)view image:(NSImage *)image;
- (void)resizeWindowForGuestSize:(NSSize)size;
- (void)layoutGuest;
@end

@implementation N00N9SkinView
- (id)initWithGuestView:(NSView *)view image:(NSImage *)image
{
    N00N9Geometry geometry = n00_n9_geometry(image != nil);
    self = [super initWithFrame:NSMakeRect(0, 0, geometry.canvas.width * .75,
                                         geometry.canvas.height * .75)];
    if (self) {
        guestView = view;
        caseImage = [image retain];
        guestSize = NSMakeSize(480, 864);
        [self setWantsLayer:YES];
        [view setWantsLayer:YES];
        [[view layer] setBackgroundColor:[[NSColor blackColor] CGColor]];
        [self addSubview:view];
        lockButton = [[N00LockButton alloc] initWithFrame:NSZeroRect];
        [lockButton setBordered:NO];
        [lockButton setTransparent:YES];
        [lockButton setTitle:@""];
        [lockButton setToolTip:@"Lock screen / show unlock screen"];
        [lockButton setAccessibilityLabel:@"Lock screen / show unlock screen"];
        [lockButton setTarget:self];
        [lockButton setAction:@selector(pressLockButton:)];
        [self addSubview:lockButton];
        [lockButton release];
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

- (void)pressLockButton:(id)sender
{
    if (n00_lockscreen_request() < 0) {
        fprintf(stderr, "N00_LOCKSCREEN_REQUEST_FAILED\n");
        NSBeep();
    }
}

- (NSView *)hitTest:(NSPoint)point
{
    NSView *hit = [super hitTest:point];
    if (!hit) return nil;
    if (hit == lockButton) return hit;
    NSPoint local = [self convertPoint:point fromView:[self superview]];
    N00N9Geometry geometry = n00_n9_geometry(caseImage != nil);
    NSSize model = n00_n9_model_size(guestSize, geometry), bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    if (scale <= 0) return hit;
    local.x = (local.x - (bounds.width - model.width * scale) / 2) / scale;
    local.y = (local.y - (bounds.height - model.height * scale) / 2) / scale;
    if (guestSize.width > guestSize.height) {
        local = NSMakePoint(geometry.canvas.width - local.y, local.x);
    }
    /* Give AppKit the guest as the initial receiver even outside its frame:
     * it then owns the complete down/drag/up sequence across the screen edge. */
    NSBezierPath *glass = [NSBezierPath bezierPathWithRoundedRect:
        geometry.glass xRadius:geometry.glassRadius yRadius:geometry.glassRadius];
    return [glass containsPoint:local] ? guestView : hit;
}

- (void)layoutGuest
{
    N00N9Geometry geometry = n00_n9_geometry(caseImage != nil);
    NSSize model = n00_n9_model_size(guestSize, geometry);
    NSSize bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    NSRect aperture = n00_n9_oriented_rect(geometry.aperture, guestSize, geometry.canvas);
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
    /* The lower side key, below the volume rocker. The hit area stays
     * outside the glass, in artwork/model coordinates, at every zoom. */
    NSRect key = n00_n9_oriented_rect(geometry.lockTarget, guestSize, geometry.canvas);
    [lockButton setFrame:NSMakeRect(
        (bounds.width - model.width * scale) / 2 + key.origin.x * scale,
        (bounds.height - model.height * scale) / 2 + key.origin.y * scale,
        key.size.width * scale, key.size.height * scale)];
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
    N00N9Geometry geometry = n00_n9_geometry(caseImage != nil);
    NSSize model = n00_n9_model_size(size, geometry);
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
    N00N9Geometry geometry = n00_n9_geometry(caseImage != nil);
    NSSize model = n00_n9_model_size(guestSize, geometry), bounds = [self bounds].size;
    CGFloat scale = MIN(bounds.width / model.width, bounds.height / model.height);
    CGContextRef context = [[NSGraphicsContext currentContext] CGContext];
    [NSGraphicsContext saveGraphicsState];
    CGContextTranslateCTM(context, (bounds.width - model.width * scale) / 2,
                          (bounds.height - model.height * scale) / 2);
    CGContextScaleCTM(context, scale, scale);
    if (guestSize.width > guestSize.height) {
        CGContextTranslateCTM(context, 0, geometry.canvas.width);
        CGContextRotateCTM(context, -M_PI_2);
    }
    [[NSGraphicsContext currentContext] setImageInterpolation:NSImageInterpolationHigh];
    if (caseImage) {
        [caseImage drawInRect:NSMakeRect(0, 0, geometry.canvas.width, geometry.canvas.height)
                    fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1];
    } else {
        n00_n9_draw_frame();
    }
    /* Overlap the opening by two view points, including at fractional zoom.
     * This covers the resampled PNG/child-layer fringe as well as aspect-fit
     * gaps. The framebuffer itself keeps its complete, unscaled bounds. */
    [[NSColor blackColor] setFill];
    if (scale > 0) {
        NSRectFill(NSInsetRect(geometry.aperture, -2 / scale, -2 / scale));
    }
    [NSGraphicsContext restoreGraphicsState];
}
@end

static N00N9SkinView *n00_n9_skin;
