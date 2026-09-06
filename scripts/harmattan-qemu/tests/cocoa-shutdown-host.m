/* Compile the actual Cocoa termination method and completion block from the
 * port patch. Use doubles for QEMU/AppKit termination, never send OS events. */
#import <Cocoa/Cocoa.h>
#include <assert.h>

static bool n00_cocoa_termination_pending;
static NSMutableArray *steps;
static int shutdown_action, requests, exit_status = -1;
enum { SHUTDOWN_ACTION_POWEROFF = 1, SHUTDOWN_CAUSE_HOST_UI = 2 };
#define COCOA_DEBUG(...) ((void)0)

static void with_bql(void (^block)(void)) { block(); }
static void qemu_system_shutdown_request(int cause)
{
    assert(cause == SHUTDOWN_CAUSE_HOST_UI);
    assert(shutdown_action == SHUTDOWN_ACTION_POWEROFF);
    requests++;
    [steps addObject:@"request"];
}
static void n00_interaction_shutdown(void)
{
    assert([NSThread isMainThread]);
    [steps addObject:@"input cleanup"];
}
static void n00_activity_end(void)
{
    assert([NSThread isMainThread]);
    [steps addObject:@"activity cleanup"];
}
static void test_exit(int status)
{
    assert([NSThread isMainThread]);
    exit_status = status;
    [steps addObject:@"exit"];
}

@interface GuestDouble : NSObject
- (void)ungrabMouse;
- (void)raiseAllKeys;
@end
@implementation GuestDouble
- (void)ungrabMouse { [steps addObject:@"release mouse"]; }
- (void)raiseAllKeys { [steps addObject:@"release keys"]; }
@end
static GuestDouble *cocoaView;

@interface ClipboardDouble : NSObject
@end
@implementation ClipboardDouble
- (void)dealloc
{
    assert([NSThread isMainThread]);
    [steps addObject:@"clipboard cleanup"];
    [super dealloc];
}
@end
static ClipboardDouble *cbowner;

@interface ApplicationDouble : NSObject
@property BOOL reply;
@property NSUInteger replyCount;
- (void)replyToApplicationShouldTerminate:(BOOL)reply;
@end
@implementation ApplicationDouble
- (void)replyToApplicationShouldTerminate:(BOOL)reply
{
    self.reply = reply;
    self.replyCount++;
    [steps addObject:@"AppKit reply"];
}
@end
static ApplicationDouble *application;
#undef NSApp
#define NSApp application
#define exit test_exit

@interface ControllerDouble : NSObject
@property BOOL confirm;
@property NSUInteger confirmations;
- (BOOL)verifyQuit;
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender;
@end
@implementation ControllerDouble
- (BOOL)verifyQuit
{
    self.confirmations++;
    return self.confirm;
}
#include "shutdown-request.inc"
@end

static void finish_qemu(int status)
{
#include "shutdown-completion.inc"
}
#undef exit

int main(int argc, const char **argv)
{
    @autoreleasepool {
        assert(argc == 3);
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        int status = atoi(argv[2]);
        steps = [NSMutableArray new];
        cocoaView = [GuestDouble new];
        cbowner = [ClipboardDouble new];
        application = [ApplicationDouble new];
        ControllerDouble *controller = [ControllerDouble new];
        BOOL persistent = [mode isEqualToString:@"persistent"];
        if ([mode isEqualToString:@"cancel"] || [mode isEqualToString:@"storage-fail"]) {
            controller.confirm = [mode isEqualToString:@"storage-fail"];
            assert([controller applicationShouldTerminate:nil] == NSTerminateCancel);
            assert(!n00_cocoa_termination_pending && requests == 0 && steps.count == 0);
            assert(controller.confirmations == 1 && exit_status == -1);
        } else {
            BOOL local = [mode isEqualToString:@"ui"] || persistent;
            if (local) {
                controller.confirm = YES;
                assert([controller applicationShouldTerminate:nil] == NSTerminateLater);
                assert([controller applicationShouldTerminate:nil] == NSTerminateLater);
                assert(n00_cocoa_termination_pending && requests == (persistent ? 0 : 1));
                assert(controller.confirmations == 1 && application.replyCount == 0);
                assert(([steps isEqualToArray:(persistent ? @[@"release mouse", @"release keys"] :
                                                          @[@"release mouse", @"release keys", @"request"])]));
                [steps removeAllObjects];
            }
            /* Completion originates off the main thread, just like QEMU. */
            dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
                finish_qemu(status);
            });
            NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:2];
            while (exit_status == -1 && [deadline timeIntervalSinceNow] > 0) {
                [[NSRunLoop currentRunLoop] runMode:NSDefaultRunLoopMode
                    beforeDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
            }
            assert(exit_status == status);
            assert(application.replyCount == (local ? 1 : 0));
            if (local) assert(application.reply == (status == EXIT_SUCCESS));
            NSMutableArray *expected = [NSMutableArray arrayWithArray:
                @[@"input cleanup", @"activity cleanup", @"clipboard cleanup"]];
            if (local) [expected addObject:@"AppKit reply"];
            [expected addObject:@"exit"];
            assert([steps isEqualToArray:expected]);
        }
        puts("PASS: cancellation, single shutdown request, main-queue cleanup and exit status");
    }
    return 0;
}
