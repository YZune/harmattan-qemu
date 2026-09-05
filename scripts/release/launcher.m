/* SPDX-License-Identifier: GPL-2.0-or-later */
#import <Cocoa/Cocoa.h>
#include <unistd.h>

static BOOL chinese;
static NSString *text(NSString *en, NSString *zh) { return chinese ? zh : en; }

static NSArray *arguments(NSString *contents, NSArray *command)
{
    return [@[@"-s", @"-B", @"-P", [contents stringByAppendingPathComponent:@"Resources/project/scripts/release/runtime.py"],
              @"--contents", contents] arrayByAddingObjectsFromArray:command];
}

static int execute(NSString *contents, NSArray *command, NSFileHandle *output)
{
    NSTask *task = [[NSTask alloc] init];
    task.executableURL = [NSURL fileURLWithPath:[contents stringByAppendingPathComponent:@"MacOS/python3"]];
    task.arguments = arguments(contents, command);
    task.standardOutput = output;
    task.standardError = output;
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) return 127;
    [task waitUntilExit];
    return task.terminationStatus;
}

static NSString *choose(NSString *message)
{
    NSOpenPanel *panel = [NSOpenPanel openPanel];
    panel.message = message;
    panel.canChooseDirectories = NO;
    panel.allowsMultipleSelection = NO;
    if ([panel runModal] != NSModalResponseOK) return nil;
    return panel.URL.path;
}

static void failure(NSString *log)
{
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = text(@"Harmattan QEMU could not start", @"Harmattan QEMU 未能启动");
    alert.informativeText = [NSString stringWithFormat:text(@"See the diagnostic log:\n%@\n\nRun with --configure to choose another prepared disk. Original inputs remain unchanged.",
        @"请查看诊断日志：\n%@\n\n可使用 --configure 重新选择已准备的磁盘。原始输入文件未修改。"), log];
    [alert addButtonWithTitle:text(@"Show log", @"查看日志")];
    [alert addButtonWithTitle:text(@"Close", @"关闭")];
    if ([alert runModal] == NSAlertFirstButtonReturn)
        [[NSWorkspace sharedWorkspace] activateFileViewerSelectingURLs:@[[NSURL fileURLWithPath:log]]];
}

int main(int argc, const char **argv)
{
    @autoreleasepool {
        NSString *contents = [[NSBundle mainBundle].bundlePath stringByAppendingPathComponent:@"Contents"];
        NSString *pythonHome = [contents stringByAppendingPathComponent:@"Resources/python"];
        unsetenv("PYTHONPATH");
        unsetenv("PYTHONSTARTUP");
        setenv("PYTHONHOME", pythonHome.fileSystemRepresentation, 1);
        setenv("PYTHONNOUSERSITE", "1", 1);
        BOOL configure = argc == 2 && !strcmp(argv[1], "--configure");
        if (argc > 1 && !configure) {
            NSMutableArray *command = [NSMutableArray array];
            for (int i = 1; i < argc; i++) [command addObject:@(argv[i])];
            NSArray *args = arguments(contents, command);
            const char **values = calloc(args.count + 2, sizeof(char *));
            values[0] = [[contents stringByAppendingPathComponent:@"MacOS/python3"] fileSystemRepresentation];
            for (NSUInteger i = 0; i < args.count; i++) values[i + 1] = [args[i] UTF8String];
            execv(values[0], (char *const *)values);
            return 127;
        }
        chinese = [[[NSLocale preferredLanguages] firstObject] hasPrefix:@"zh"];
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
        [NSApp activateIgnoringOtherApps:YES];
        NSString *state = NSProcessInfo.processInfo.environment[@"HARMATTAN_DATA_HOME"];
        if (!state) state = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Application Support/Harmattan QEMU"];
        NSError *error = nil;
        if (![[NSFileManager defaultManager] createDirectoryAtPath:state withIntermediateDirectories:YES
            attributes:@{NSFilePosixPermissions: @0700} error:&error]) return 1;
        NSString *log = [state stringByAppendingPathComponent:@"launcher.log"];
        [[NSFileManager defaultManager] createFileAtPath:log contents:nil attributes:@{NSFilePosixPermissions: @0600}];
        NSFileHandle *output = [NSFileHandle fileHandleForWritingAtPath:log];
        if (configure || execute(contents, @[@"check"], output) != 0) {
            NSAlert *intro = [[NSAlert alloc] init];
            intro.messageText = text(@"Choose your Harmattan system", @"选择 Harmattan 系统资源");
            intro.informativeText = text(@"This preview needs an already prepared PR1.3 raw disk and the matching PR1.0 emulator kernel. It cannot convert retail firmware yet. Select two files; the app creates private APFS copies. Keep the source disk closed while importing. Guest changes are discarded after each session.",
                @"此预览版需要已经准备好的 PR1.3 raw 磁盘和对应的 PR1.0 模拟器内核，暂不支持直接转换零售固件。接下来选择两个文件，应用会创建私有 APFS 副本。导入时请停止对源磁盘的写入。每次退出都会丢弃客体修改。");
            [intro addButtonWithTitle:text(@"Choose files", @"选择文件")];
            [intro addButtonWithTitle:text(@"Cancel", @"取消")];
            if ([intro runModal] != NSAlertFirstButtonReturn) return 0;
            NSString *disk = choose(text(@"Choose the prepared PR1.3 .raw disk", @"选择已准备的 PR1.3 .raw 磁盘"));
            if (!disk) return 0;
            NSString *kernel = choose(text(@"Choose zImage-2.6.32.26-qemu", @"选择 zImage-2.6.32.26-qemu 内核"));
            if (!kernel) return 0;
            if (execute(contents, @[@"import", @"--disk", disk, @"--kernel", kernel, @"--replace"], output) != 0) {
                failure(log);
                return 1;
            }
        }
        int result = execute(contents, @[@"run"], output);
        if (result != 0) failure(log);
        return result;
    }
}
