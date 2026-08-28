#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define WORKER_COUNT 64
#define REGION_SIZE (256u * 1024u * 1024u)
#define MAGIC_VALUE 123456789u

static HANDLE workers[WORKER_COUNT];
static volatile LONG keep_running = 1;
static volatile uint64_t counters[WORKER_COUNT];
static volatile uint32_t *scan_region;
static FILE *log_file;

static void log_line(const char *kind, unsigned long long cycle,
                     unsigned index, DWORD code, unsigned long long elapsed_ms)
{
    SYSTEMTIME now;
    GetLocalTime(&now);
    fprintf(log_file,
            "%02u:%02u:%02u.%03u kind=%s cycle=%llu worker=%u code=%lu elapsed_ms=%llu\n",
            now.wHour, now.wMinute, now.wSecond, now.wMilliseconds,
            kind, cycle, index, (unsigned long)code, elapsed_ms);
    fflush(log_file);
}

static DWORD WINAPI worker_main(LPVOID parameter)
{
    uintptr_t index = (uintptr_t)parameter;
    while (InterlockedCompareExchange(&keep_running, 1, 1)) {
        counters[index]++;
        Sleep(1);
    }
    return 0;
}

static BOOL WINAPI console_handler(DWORD event)
{
    (void)event;
    InterlockedExchange(&keep_running, 0);
    return TRUE;
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "suspend-context-probe.log";
    unsigned long long cycle = 0;
    unsigned i;

    log_file = fopen(path, "w");
    if (!log_file) return 2;
    setvbuf(log_file, NULL, _IOLBF, 0);
    SetConsoleCtrlHandler(console_handler, TRUE);

    scan_region = (volatile uint32_t *)VirtualAlloc(
        NULL, REGION_SIZE, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!scan_region) {
        log_line("virtual_alloc_failed", 0, 0, GetLastError(), 0);
        return 3;
    }
    for (size_t offset = 0; offset < REGION_SIZE / sizeof(uint32_t); offset += 1024)
        scan_region[offset] = MAGIC_VALUE;

    for (i = 0; i < WORKER_COUNT; i++) {
        workers[i] = CreateThread(NULL, 0, worker_main, (LPVOID)(uintptr_t)i, 0, NULL);
        if (!workers[i]) {
            log_line("create_thread_failed", 0, i, GetLastError(), 0);
            return 4;
        }
    }

    fprintf(log_file, "READY pid=%lu workers=%u region=%p size=%u magic=%u\n",
            (unsigned long)GetCurrentProcessId(), WORKER_COUNT,
            (void *)scan_region, REGION_SIZE, MAGIC_VALUE);

    while (InterlockedCompareExchange(&keep_running, 1, 1)) {
        ULONGLONG started = GetTickCount64();
        cycle++;
        for (i = 0; i < WORKER_COUNT; i++) {
            CONTEXT context;
            DWORD suspend_count;
            ZeroMemory(&context, sizeof(context));
            context.ContextFlags = CONTEXT_FULL;

            suspend_count = SuspendThread(workers[i]);
            if (suspend_count == (DWORD)-1) {
                log_line("suspend_failed", cycle, i, GetLastError(),
                         GetTickCount64() - started);
                continue;
            }
            if (!GetThreadContext(workers[i], &context))
                log_line("context_failed", cycle, i, GetLastError(),
                         GetTickCount64() - started);
            if (ResumeThread(workers[i]) == (DWORD)-1)
                log_line("resume_failed", cycle, i, GetLastError(),
                         GetTickCount64() - started);
        }

        if ((cycle % 10) == 0 || GetTickCount64() - started > 1000)
            log_line("cycle", cycle, WORKER_COUNT, 0, GetTickCount64() - started);
        Sleep(100);
    }

    WaitForMultipleObjects(WORKER_COUNT, workers, TRUE, 5000);
    for (i = 0; i < WORKER_COUNT; i++) CloseHandle(workers[i]);
    VirtualFree((LPVOID)scan_region, 0, MEM_RELEASE);
    log_line("stopped", cycle, 0, 0, 0);
    fclose(log_file);
    return 0;
}
