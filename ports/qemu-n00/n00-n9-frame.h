/* SPDX-License-Identifier: MIT
 * Project-drawn frame from published device specifications.
 * Facts, derivation and design choices: skins/frame-geometry.md.
 * No artwork coordinates, vector masks or image resources are used here.
 */
#ifndef N00_N9_FRAME_H
#define N00_N9_FRAME_H
#import <Cocoa/Cocoa.h>
#include <math.h>

typedef struct N00N9Geometry {
    NSSize canvas;
    NSRect aperture;
    NSRect glass;
    CGFloat glassRadius;
    NSRect lockTarget;
} N00N9Geometry;

static NSRect n00_n9_frame_body(void)
{
    /* Ten model units per millimetre; one mm of drawing margin per side.
     * Nokia's datasheet gives the body as 61.2 mm wide, 116.45 mm tall. */
    return NSMakeRect(10, 10, 61.2 * 10, 116.45 * 10);
}

static NSRect n00_n9_frame_power_key(void)
{
    NSRect body = n00_n9_frame_body();
    /* Project choices, not measured hardware coordinates. */
    CGFloat height = body.size.height * .065;
    return NSMakeRect(NSMaxX(body) - 1,
        body.origin.y + body.size.height * .58 - height / 2, 7, height);
}

static N00N9Geometry n00_n9_frame_geometry(void)
{
    NSRect body = n00_n9_frame_body();
    N00N9Geometry geometry;
    geometry.canvas = NSMakeSize(NSMaxX(body) + 10, NSMaxY(body) + 10);
    /* Approximate active area from the nominal 3.9-inch diagonal and
     * 480:854 portrait pixel ratio, assuming square pixels. */
    CGFloat diagonal = 3.9 * 25.4 * 10;
    CGFloat pitch = diagonal / hypot(480, 854);
    NSSize screen = NSMakeSize(480 * pitch, 854 * pitch);
    geometry.aperture = NSMakeRect(NSMidX(body) - screen.width / 2,
        NSMidY(body) - screen.height / 2, screen.width, screen.height);
    /* Unspecified by the datasheet: centred screen; 1.8/2.8 mm glass
     * insets; 3.2 mm glass corners. These are our flat illustration. */
    geometry.glass = NSInsetRect(body, 18, 28);
    geometry.glassRadius = 32;
    NSRect key = n00_n9_frame_power_key();
    CGFloat left = NSMaxX(geometry.glass) + 4;
    geometry.lockTarget = NSMakeRect(left, key.origin.y - 12,
        geometry.canvas.width - left, key.size.height + 24);
    return geometry;
}

static void n00_n9_draw_frame(void)
{
    NSRect body = n00_n9_frame_body();
    N00N9Geometry geometry = n00_n9_frame_geometry();
    NSRect volume = NSMakeRect(NSMaxX(body) - 1,
        body.origin.y + body.size.height * .70, 7, body.size.height * .14);
    [[NSColor colorWithCalibratedWhite:.40 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRoundedRect:volume xRadius:2 yRadius:2] fill];
    [[NSBezierPath bezierPathWithRoundedRect:n00_n9_frame_power_key()
        xRadius:2 yRadius:2] fill];
    [[NSColor colorWithCalibratedWhite:.17 alpha:1] setFill];
    NSRectFill(NSMakeRect(volume.origin.x, NSMidY(volume) - 1, volume.size.width, 2));

    NSBezierPath *shell = [NSBezierPath bezierPathWithRoundedRect:body
        xRadius:12 yRadius:12];
    [[NSColor colorWithCalibratedWhite:.18 alpha:1] setFill];
    [shell fill];
    [NSGraphicsContext saveGraphicsState];
    [shell addClip];
    [[NSColor colorWithCalibratedWhite:.13 alpha:1] setFill];
    NSRectFill(NSMakeRect(body.origin.x, body.origin.y, 8, body.size.height));
    NSRectFill(NSMakeRect(NSMaxX(body) - 8, body.origin.y, 8, body.size.height));
    [NSGraphicsContext restoreGraphicsState];
    [[NSColor colorWithCalibratedWhite:.24 alpha:1] setStroke];
    /* Inset the outline so the body keeps the specified outer dimensions. */
    NSBezierPath *outline = [NSBezierPath bezierPathWithRoundedRect:
        NSInsetRect(body, .5, .5) xRadius:11.5 yRadius:11.5];
    [outline setLineWidth:1];
    [outline stroke];

    NSBezierPath *glass = [NSBezierPath bezierPathWithRoundedRect:geometry.glass
        xRadius:geometry.glassRadius yRadius:geometry.glassRadius];
    [[NSColor blackColor] setFill];
    [glass fill];
    [[NSColor colorWithCalibratedWhite:.07 alpha:1] setStroke];
    [glass setLineWidth:1];
    [glass stroke];

    /* The user guide identifies the earpiece, front camera and side keys.
     * Their simplified sizes and placement below are project choices. */
    CGFloat speakerWidth = body.size.width * .085;
    NSRect speaker = NSMakeRect(NSMidX(body) - speakerWidth / 2,
        (NSMaxY(body) + NSMaxY(geometry.glass)) / 2 - 2, speakerWidth, 4);
    [[NSColor colorWithCalibratedWhite:.05 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRoundedRect:speaker xRadius:2 yRadius:2] fill];
    NSPoint camera = NSMakePoint(NSMaxX(geometry.glass) - 28,
        (NSMinY(geometry.glass) + NSMinY(geometry.aperture)) / 2);
    [[NSColor colorWithCalibratedWhite:.09 alpha:1] setFill];
    [[NSBezierPath bezierPathWithOvalInRect:
        NSMakeRect(camera.x - 9, camera.y - 9, 18, 18)] fill];
    [[NSColor colorWithCalibratedWhite:.025 alpha:1] setFill];
    [[NSBezierPath bezierPathWithOvalInRect:
        NSMakeRect(camera.x - 5, camera.y - 5, 10, 10)] fill];
}
#endif
